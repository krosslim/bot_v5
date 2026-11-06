"""Производственный календарь: флаги дней из isdayoff.ru или библиотеки holidays. Чистые функции без БД и сети.

Смысл флагов совпадает с данными, которые раньше вносились в calendar_dates вручную:
    is_workday — рабочий день по производственному календарю (с переносами и рабочими субботами)
    is_holiday — любой нерабочий день, в том числе обычные суббота и воскресенье (= not is_workday)
    is_weekend — суббота или воскресенье по дню недели
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List

import holidays

from src.dto.calendar_dates_dto import CalendarSource


class CalendarDataError(ValueError):
    """Данные календаря не похожи на настоящие — записывать их нельзя"""


@dataclass(frozen=True)
class DayFlags:
    cal_date: date
    is_weekend: bool
    is_holiday: bool
    is_workday: bool
    source: CalendarSource

    def same_flags(self, other: "DayFlags") -> bool:
        return (self.is_weekend, self.is_holiday, self.is_workday) == (other.is_weekend, other.is_holiday,
                                                                       other.is_workday)


def day_flags(cal_date: date, day_off: bool, source: CalendarSource) -> DayFlags:
    return DayFlags(cal_date=cal_date, is_weekend=cal_date.weekday() >= 5, is_holiday=day_off,
                    is_workday=not day_off, source=source)


def year_days(year: int) -> List[date]:
    start = date(year, 1, 1)
    return [start + timedelta(days=i) for i in range(366 if calendar.isleap(year) else 365)]


def weekends_count(year: int) -> int:
    return sum(d.weekday() >= 5 for d in year_days(year))


def parse_isdayoff_year(year: int, body: str) -> List[DayFlags]:
    """Ответ isdayoff.ru на /api/getdata?year=YYYY: по символу на день, 1 — нерабочий, 0 — рабочий.

    Проверки защищают таблицу от мусора: длина равна числу дней в году, только 0/1,
    а нерабочих дней не меньше суббот и воскресений за вычетом пары рабочих суббот
    и не больше, чем бывает с новогодними каникулами и переносами."""
    days = year_days(year)
    body = (body or "").strip()
    if len(body) != len(days):
        raise CalendarDataError(f"isdayoff.ru {year}: {len(body)} символов вместо {len(days)}: {body[:20]!r}")
    if set(body) - {"0", "1"}:
        raise CalendarDataError(f"isdayoff.ru {year}: неожиданные символы {sorted(set(body) - {'0', '1'})}")
    days_off, weekends = body.count("1"), weekends_count(year)
    if not weekends - 5 <= days_off <= weekends + 30:
        raise CalendarDataError(f"isdayoff.ru {year}: {days_off} нерабочих дней при {weekends} выходных")
    return [day_flags(d, flag == "1", CalendarSource.ISDAYOFF) for d, flag in zip(days, body)]


def holidays_year(year: int) -> List[DayFlags]:
    """Запасной расчёт: суббота, воскресенье и праздники РФ с переносами из библиотеки holidays.
    Рабочих суббот библиотека не знает — они придут из isdayoff.ru, когда сервис станет доступен"""
    ru = holidays.country_holidays("RU", years=year)
    return [day_flags(d, d.weekday() >= 5 or d in ru, CalendarSource.HOLIDAYS) for d in year_days(year)]


@dataclass(frozen=True)
class CalendarChange:
    old: DayFlags
    new: DayFlags

    @property
    def workday_changed(self) -> bool:
        return self.old.is_workday != self.new.is_workday


@dataclass
class CalendarPlan:
    inserts: List[DayFlags] = field(default_factory=list)
    updates: List[CalendarChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.inserts and not self.updates

    @property
    def workday_changes(self) -> List[CalendarChange]:
        """Дни, которые стали рабочими или нерабочими (смена только источника сюда не попадает)"""
        return [c for c in self.updates if c.workday_changed]


def plan_sync(desired: Iterable[DayFlags], existing: Dict[date, DayFlags], today: date) -> CalendarPlan:
    """Что записать в calendar_dates.

    - Дня нет в таблице — добавить (в том числе прошлого: нужен для истории в календаре виджета).
    - Прошлые дни и сегодня не меняются: по ним уже были брони и рассылки.
    - Будущий день обновляется, если изменились флаги или источник.
    - Данные holidays не перезаписывают данные isdayoff.ru: запасной источник только заполняет пробелы
      и обновляет то, что сам когда-то записал.
    visit_count здесь не участвует и при синхронизации не меняется."""
    plan = CalendarPlan()
    for new in desired:
        old = existing.get(new.cal_date)
        if old is None:
            plan.inserts.append(new)
            continue
        if new.cal_date <= today:
            continue
        if new.source == CalendarSource.HOLIDAYS and old.source == CalendarSource.ISDAYOFF:
            continue
        if not new.same_flags(old) or new.source != old.source:
            plan.updates.append(CalendarChange(old=old, new=new))
    return plan
