"""Производственный календарь без БД и сети: python -m unittest discover -s tests -t ."""
import unittest
from datetime import date, timedelta

from src.dto.calendar_dates_dto import CalendarSource
from src.utils.work_calendar import (CalendarDataError, DayFlags, day_flags, holidays_year, parse_isdayoff_year,
                                     plan_sync)

# Ответы isdayoff.ru /api/getdata?year=YYYY (2025 совпадает со строкой из сида init_dicts_config)
ISDAYOFF_2025 = (
    "11111111001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110"
    "00001100000110001111000111100000110000011000001100000110001111000001100000110000011000001100000110000011"
    "00000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000001110001"
    "10000011000001100000110000011000001100000110000011001"
)
ISDAYOFF_2026 = (
    "11111111111000001100000110000011000001100000110000011100001100000111000011000001100000110000011000001100"
    "00011000001100001110000011100001100000110000011000001100001110000011000001100000110000011000001100000110"
    "00001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110010011"
    "00000110000011000001100000110000011000001100000110001"
)


def flags(year: int, body: str):
    return {d.cal_date: d for d in parse_isdayoff_year(year, body)}


class IsDayOffParsingTest(unittest.TestCase):
    def test_fixtures_are_full_years(self):
        self.assertEqual(len(ISDAYOFF_2025), 365)
        self.assertEqual(len(ISDAYOFF_2026), 365)

    def test_flags_meaning_matches_existing_data(self):
        days = flags(2025, ISDAYOFF_2025)
        jan1, jan9, nov1 = days[date(2025, 1, 1)], days[date(2025, 1, 9)], days[date(2025, 11, 1)]
        self.assertEqual((jan1.is_workday, jan1.is_holiday, jan1.is_weekend), (False, True, False))
        self.assertEqual((jan9.is_workday, jan9.is_holiday), (True, False))
        # Рабочая суббота: выходной по дню недели, но рабочий по производственному календарю
        self.assertEqual((nov1.is_workday, nov1.is_holiday, nov1.is_weekend), (True, False, True))
        self.assertTrue(all(d.is_holiday == (not d.is_workday) for d in days.values()))
        self.assertTrue(all(d.source == CalendarSource.ISDAYOFF for d in days.values()))

    def test_garbage_is_rejected(self):
        for body in (ISDAYOFF_2025[:-1], ISDAYOFF_2025 + "0", "2" + ISDAYOFF_2025[1:], "0" * 365, "1" * 365,
                     "101", ""):
            with self.subTest(body=body[:10]), self.assertRaises(CalendarDataError):
                parse_isdayoff_year(2025, body)

    def test_leap_year_needs_366_days(self):
        with self.assertRaises(CalendarDataError):
            parse_isdayoff_year(2028, ISDAYOFF_2025)


class HolidaysFallbackTest(unittest.TestCase):
    def test_matches_production_calendar_2026(self):
        api, lib = flags(2026, ISDAYOFF_2026), {d.cal_date: d for d in holidays_year(2026)}
        diff = [d for d in api if api[d].is_workday != lib[d].is_workday]
        self.assertEqual(diff, [])
        self.assertTrue(all(d.source == CalendarSource.HOLIDAYS for d in lib.values()))

    def test_only_working_saturday_differs_in_2025(self):
        api, lib = flags(2025, ISDAYOFF_2025), {d.cal_date: d for d in holidays_year(2025)}
        self.assertEqual([d for d in api if api[d].is_workday != lib[d].is_workday], [date(2025, 11, 1)])


class PlanSyncTest(unittest.TestCase):
    TODAY = date(2026, 11, 7)

    @staticmethod
    def day(d: date, off: bool, source=CalendarSource.ISDAYOFF) -> DayFlags:
        return day_flags(d, off, source)

    def test_missing_days_are_inserted_even_in_the_past(self):
        past, future = self.TODAY - timedelta(days=30), self.TODAY + timedelta(days=3)
        plan = plan_sync([self.day(past, False), self.day(future, False)], {}, self.TODAY)
        self.assertEqual([d.cal_date for d in plan.inserts], [past, future])
        self.assertEqual(plan.updates, [])

    def test_past_and_today_are_never_changed(self):
        days = [self.TODAY - timedelta(days=1), self.TODAY]
        existing = {d: self.day(d, False) for d in days}
        plan = plan_sync([self.day(d, True) for d in days], existing, self.TODAY)
        self.assertTrue(plan.is_empty)

    def test_future_change_is_updated_and_reported(self):
        d = self.TODAY + timedelta(days=10)
        plan = plan_sync([self.day(d, True)], {d: self.day(d, False)}, self.TODAY)
        self.assertEqual(len(plan.updates), 1)
        self.assertEqual([c.new.cal_date for c in plan.workday_changes], [d])

    def test_unchanged_day_is_skipped(self):
        d = self.TODAY + timedelta(days=10)
        self.assertTrue(plan_sync([self.day(d, False)], {d: self.day(d, False)}, self.TODAY).is_empty)

    def test_isdayoff_replaces_holidays_without_workday_change_alert(self):
        d = self.TODAY + timedelta(days=60)
        plan = plan_sync([self.day(d, True)], {d: self.day(d, True, CalendarSource.HOLIDAYS)}, self.TODAY)
        self.assertEqual(len(plan.updates), 1)
        self.assertEqual(plan.updates[0].new.source, CalendarSource.ISDAYOFF)
        self.assertEqual(plan.workday_changes, [])

    def test_holidays_never_overwrite_isdayoff(self):
        d = self.TODAY + timedelta(days=60)
        plan = plan_sync([self.day(d, True, CalendarSource.HOLIDAYS)], {d: self.day(d, False)}, self.TODAY)
        self.assertTrue(plan.is_empty)

    def test_holidays_refresh_their_own_days(self):
        d = self.TODAY + timedelta(days=60)
        existing = {d: self.day(d, False, CalendarSource.HOLIDAYS)}
        plan = plan_sync([self.day(d, True, CalendarSource.HOLIDAYS)], existing, self.TODAY)
        self.assertEqual([c.new.cal_date for c in plan.workday_changes], [d])


if __name__ == "__main__":
    unittest.main()
