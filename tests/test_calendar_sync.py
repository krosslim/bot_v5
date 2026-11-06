"""CalendarSyncUseCase без БД, сети и Telegram: python -m unittest discover -s tests -t ."""
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from config import settings
from src.clients.isdayoff_client import IsDayOffError
from src.dto.calendar_dates_dto import CalendarDatesDTO, CalendarSource, DayBookingDTO
from src.use_cases import calendar_sync_use_case as module
from src.use_cases.calendar_sync_use_case import FAIL_SINCE_KEY, CalendarSyncUseCase
from src.utils.work_calendar import day_flags, holidays_year, year_days
from tests.test_work_calendar import ISDAYOFF_2026


def as_isdayoff(days) -> str:
    return "".join("0" if d.is_workday else "1" for d in days)


class FakeSession:
    @asynccontextmanager
    async def begin(self):
        yield


class FakeCalendar:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.saved = None
        self.cache_reset = False

    async def days_by_range(self, start, end):
        return [CalendarDatesDTO(cal_date=d.cal_date, is_holiday=d.is_holiday, is_weekend=d.is_weekend,
                                 is_workday=d.is_workday, visit_count=0, source=d.source,
                                 updated_at=datetime(2026, 1, 1))
                for d in self.rows.values() if start <= d.cal_date <= end]

    async def save_days(self, plan):
        self.saved = plan

    async def reset_cache(self):
        self.cache_reset = True


class FakeBooking:
    def __init__(self, bookings=()):
        self.bookings = list(bookings)
        self.asked = None

    async def active_bookings_on(self, cal_dates):
        self.asked = list(cal_dates)
        return [b for b in self.bookings if b.cal_date in cal_dates]


class FakeClient:
    def __init__(self, answers):
        self.answers = answers        # год → строка | None (101) | исключение

    async def fetch_year(self, year, timeout=10, attempts=3):
        answer = self.answers[year]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeAlerts:
    def __init__(self):
        self.sent = []

    async def notify(self, alert):
        self.sent.append(alert)
        return 1


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get_value(self, key):
        return self.values.get(key)

    async def set_value(self, key, value, ttl=None):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


def flags_2027_string() -> str:
    """Год 2027 в формате ответа isdayoff.ru (расчёт holidays): для тестов достаточно правдоподобной строки"""
    return as_isdayoff(holidays_year(2027))


class CalendarSyncTest(unittest.IsolatedAsyncioTestCase):
    def make(self, answers, rows=None, bookings=(), store=None, today=date(2026, 11, 7)):
        self.calendar, self.booking = FakeCalendar(rows), FakeBooking(bookings)
        self.alerts, self.store = FakeAlerts(), store or FakeStore()
        uc = CalendarSyncUseCase(FakeSession(), self.calendar, self.booking, FakeClient(answers), self.alerts,
                                 self.store)
        patcher = patch.object(module, "d_tz", return_value=today)
        patcher.start()
        self.addCleanup(patcher.stop)
        return uc

    async def test_empty_db_is_filled_from_isdayoff(self):
        uc = self.make({2026: ISDAYOFF_2026, 2027: flags_2027_string()},
                       store=FakeStore({FAIL_SINCE_KEY: "2026-11-01T00:00:00+03:00"}))
        plan = await uc.sync()
        self.assertEqual(len(plan.inserts), 365 * 2)
        self.assertTrue(all(d.source == CalendarSource.ISDAYOFF for d in plan.inserts))
        self.assertTrue(self.calendar.cache_reset)
        self.assertEqual(self.alerts.sent, [])
        self.assertNotIn(FAIL_SINCE_KEY, self.store.values)     # сервис ответил — счётчик сбоя сброшен

    async def test_isdayoff_down_falls_back_to_holidays_and_alerts_after_three_days(self):
        down = IsDayOffError("timeout")
        uc = self.make({2026: down, 2027: down})
        plan = await uc.sync()
        self.assertTrue(all(d.source == CalendarSource.HOLIDAYS for d in plan.inserts))
        self.assertIn(FAIL_SINCE_KEY, self.store.values)        # первый сбой запомнили
        self.assertEqual(self.alerts.sent, [])                  # но ещё рано тревожить

        long_ago = (datetime.now(ZoneInfo(settings.MSC_TZ)) - timedelta(days=4)).isoformat()
        uc = self.make({2026: down, 2027: down}, store=FakeStore({FAIL_SINCE_KEY: long_ago}))
        await uc.sync()
        self.assertEqual([a.key for a in self.alerts.sent], ["calendar:isdayoff:down"])

    async def test_garbage_from_isdayoff_is_not_written(self):
        uc = self.make({2026: "0" * 365, 2027: None})
        with self.assertLogs(module.logger, level="ERROR"):
            plan = await uc.sync()
        self.assertTrue(all(d.source == CalendarSource.HOLIDAYS for d in plan.inserts))

    async def test_current_year_unknown_is_a_failure(self):
        uc = self.make({2026: None, 2027: None})
        await uc.sync()
        self.assertIn(FAIL_SINCE_KEY, self.store.values)

    async def test_next_year_missing_alerts_only_in_december(self):
        uc = self.make({2026: ISDAYOFF_2026, 2027: None})
        plan = await uc.sync()
        self.assertTrue(all(d.source == CalendarSource.HOLIDAYS for d in plan.inserts if d.cal_date.year == 2027))
        self.assertEqual(self.alerts.sent, [])

        uc = self.make({2026: ISDAYOFF_2026, 2027: None}, today=date(2026, 12, 5))
        await uc.sync()
        self.assertEqual([a.key for a in self.alerts.sent], ["calendar:isdayoff:no_year:2027"])

    async def test_day_becoming_day_off_reports_change_and_bookings(self):
        target = date(2026, 12, 30)                              # среда, рабочий день в ответе isdayoff 2026
        rows = {d: day_flags(d, ISDAYOFF_2026[i] == "1", CalendarSource.ISDAYOFF)
                for i, d in enumerate(year_days(2026))}
        api = list(ISDAYOFF_2026)
        api[(target - date(2026, 1, 1)).days] = "1"              # вышло постановление: 30.12 стал выходным
        bookings = [DayBookingDTO(cal_date=target, user_id=1, full_name="Иванов Иван", status="BOOKED"),
                    DayBookingDTO(cal_date=target, user_id=2, full_name="Петров Пётр", status="WAITLISTED")]
        uc = self.make({2026: "".join(api), 2027: flags_2027_string()}, rows=rows, bookings=bookings)

        plan = await uc.sync()
        self.assertEqual([c.new.cal_date for c in plan.workday_changes], [target])
        self.assertEqual(self.booking.asked, [target])
        titles = [a.title for a in self.alerts.sent]
        self.assertEqual(titles, ["Производственный календарь изменился", "Брони на день, который стал нерабочим"])
        self.assertIn("30.12.2026 (ср): рабочий → выходной", self.alerts.sent[0].text)
        self.assertIn("Иванов Иван, Петров Пётр (очередь)", self.alerts.sent[1].text)


if __name__ == "__main__":
    unittest.main()
