"""Синхронизация calendar_dates с производственным календарём.

Источник — isdayoff.ru. Если сервис недоступен или ещё не знает год (нет постановления о переносах),
дни считаются по библиотеке holidays и перезаписываются данными isdayoff.ru, когда они появятся.
Запускается при старте бота и ночным заданием (calendar_sync_job).
"""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from src.clients.isdayoff_client import IsDayOffClient, IsDayOffError
from src.dto.booking_dto import BookingStatus
from src.dto.calendar_dates_dto import DayBookingDTO
from src.services.alert_service import Alert, AlertService
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.storage.redis.store import RedisStore
from src.utils.tz_day import d_tz
from src.utils.work_calendar import (CalendarChange, CalendarDataError, CalendarPlan, DayFlags,
                                     holidays_year, parse_isdayoff_year, plan_sync)

logger = logging.getLogger(__name__)

FAIL_SINCE_KEY = "calendar:isdayoff:fail_since"   # когда isdayoff.ru перестал отвечать (ISO-время)
DOWN_ALERT_AFTER = timedelta(days=3)               # через сколько сообщать в чат алертов, что сервис недоступен
DOWN_ALERT_EVERY = 24 * 3600                       # и как часто повторять
NO_NEXT_YEAR_ALERT_MONTH = 12                      # с какого месяца ждать данных на следующий год
NO_NEXT_YEAR_ALERT_EVERY = 7 * 24 * 3600
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass(frozen=True)
class YearData:
    year: int
    days: List[DayFlags]
    error: Optional[str] = None    # isdayoff.ru не ответил или прислал мусор — дни посчитаны по holidays
    missing: bool = False          # isdayoff.ru ещё не знает год (код 101) — дни посчитаны по holidays


def fmt_day(d: date) -> str:
    return f"{d:%d.%m.%Y} ({WEEKDAYS[d.weekday()]})"


class CalendarSyncUseCase:
    def __init__(
            self,
            session: AsyncSession,
            calendar: CalendarDatesService,
            booking: BookingService,
            client: IsDayOffClient,
            alerts: AlertService,
            store: RedisStore,
    ):
        self.session = session
        self.calendar = calendar
        self.booking = booking
        self.client = client
        self.alerts = alerts
        self.store = store

    async def sync(self, quick: bool = False) -> CalendarPlan:
        """Текущий и следующий год. quick — при старте бота: короткий таймаут без повторов,
        чтобы недоступный сервис не задерживал запуск (пробелы закроет holidays, данные поправит ночной запуск)"""
        today = d_tz()
        years = await asyncio.gather(self._load_year(today.year, quick, current=True),
                                     self._load_year(today.year + 1, quick, current=False))

        async with self.session.begin():
            rows = await self.calendar.days_by_range(date(today.year, 1, 1), date(today.year + 1, 12, 31))
            existing = {r.cal_date: DayFlags(cal_date=r.cal_date, is_weekend=r.is_weekend, is_holiday=r.is_holiday,
                                             is_workday=r.is_workday, source=r.source) for r in rows}
            plan = plan_sync([d for y in years for d in y.days], existing, today)
            await self.calendar.save_days(plan)
            became_off = [c.new.cal_date for c in plan.workday_changes if not c.new.is_workday]
            bookings = await self.booking.active_bookings_on(became_off) if became_off else []

        if not plan.is_empty:
            await self.calendar.reset_cache()
        logger.info("calendar_sync | added=%s updated=%s workday_changes=%s | %s", len(plan.inserts),
                    len(plan.updates), len(plan.workday_changes),
                    ", ".join(f"{y.year}: {'holidays' if y.error or y.missing else 'isdayoff'}" for y in years))

        await self._alert_changes(plan.workday_changes)
        await self._alert_bookings(bookings)
        await self._check_source(years, today)
        return plan

    async def _load_year(self, year: int, quick: bool, current: bool) -> YearData:
        try:
            body = await self.client.fetch_year(year, timeout=5 if quick else 10, attempts=1 if quick else 3)
        except IsDayOffError as e:
            logger.warning("calendar_sync | %s | isdayoff.ru недоступен, считаем по holidays | %s", year, e)
            return YearData(year, holidays_year(year), error=str(e))

        if body is None:
            if current:
                # Текущий год сервис знать обязан: это сбой, а не «ещё нет постановления»
                return YearData(year, holidays_year(year), error=f"isdayoff.ru не знает текущий {year} год")
            return YearData(year, holidays_year(year), missing=True)

        try:
            return YearData(year, parse_isdayoff_year(year, body))
        except CalendarDataError as e:
            logger.error("calendar_sync | %s | ответ isdayoff.ru не прошёл проверку, считаем по holidays | %s",
                         year, e)
            return YearData(year, holidays_year(year), error=str(e))

    # ---------------------------------------------------------------------------#
    #  Алерты
    # ---------------------------------------------------------------------------#
    async def _alert_changes(self, changes: Sequence[CalendarChange]) -> None:
        if not changes:
            return
        lines = [
            f"• {fmt_day(c.new.cal_date)}: {'рабочий → выходной' if not c.new.is_workday else 'выходной → рабочий'}"
            f" ({c.new.source.name.lower()})"
            for c in sorted(changes, key=lambda c: c.new.cal_date)
        ]
        await self.alerts.notify(Alert("Производственный календарь изменился", "\n".join(lines),
                                       level=logging.INFO))

    async def _alert_bookings(self, bookings: Sequence[DayBookingDTO]) -> None:
        if not bookings:
            return
        by_day: Dict[date, List[str]] = defaultdict(list)
        for b in bookings:
            by_day[b.cal_date].append(b.full_name + (" (очередь)" if b.status == BookingStatus.WAITLISTED else ""))
        lines = [f"• {fmt_day(d)}: {', '.join(names)}" for d, names in sorted(by_day.items())]
        await self.alerts.notify(Alert(
            "Брони на день, который стал нерабочим",
            "\n".join(lines) + "\n\nБрони не отменены: предупредите сотрудников или отмените их вручную.",
            level=logging.WARNING,
        ))

    async def _check_source(self, years: Sequence[YearData], today: date) -> None:
        """isdayoff.ru не отвечает дольше DOWN_ALERT_AFTER или к декабрю не знает следующий год"""
        try:
            failed = [y for y in years if y.error]
            if failed:
                since = await self._fail_since()
                if datetime.now(ZoneInfo(settings.MSC_TZ)) - since >= DOWN_ALERT_AFTER:
                    await self.alerts.notify(Alert(
                        "isdayoff.ru недоступен",
                        f"Производственный календарь ({', '.join(str(y.year) for y in failed)}) не обновляется "
                        f"с {since:%d.%m.%Y %H:%M}. Уже загруженные дни не меняются, недостающие добавляются "
                        f"по библиотеке holidays (рабочих суббот она не знает).\n"
                        f"Последняя ошибка: {failed[-1].error}",
                        level=logging.ERROR, key="calendar:isdayoff:down", dedup_ttl=DOWN_ALERT_EVERY,
                    ))
            else:
                await self.store.delete(FAIL_SINCE_KEY)

            next_year = years[-1]
            if next_year.missing and today.month >= NO_NEXT_YEAR_ALERT_MONTH:
                await self.alerts.notify(Alert(
                    f"Нет производственного календаря на {next_year.year} год",
                    f"isdayoff.ru пока не знает {next_year.year} год: видимо, постановление о переносах ещё "
                    f"не вышло. До его появления дни считаются по библиотеке holidays — праздники и переносы, "
                    f"которые она уже знает. Данные обновятся сами, когда появятся на isdayoff.ru.",
                    level=logging.WARNING, key=f"calendar:isdayoff:no_year:{next_year.year}",
                    dedup_ttl=NO_NEXT_YEAR_ALERT_EVERY,
                ))
        except Exception as e:
            logger.warning("calendar_sync | проверка источника не удалась | %s", e)

    async def _fail_since(self) -> datetime:
        raw = await self.store.get_value(FAIL_SINCE_KEY)
        if raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
        now = datetime.now(ZoneInfo(settings.MSC_TZ))
        await self.store.set_value(FAIL_SINCE_KEY, now.isoformat())
        return now
