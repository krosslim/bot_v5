from datetime import date, datetime
from enum import IntEnum

from pydantic import BaseModel, ConfigDict


class CalendarSource(IntEnum):
    """Откуда взяты флаги дня (calendar_dates.source, smallint)"""
    ISDAYOFF = 0    # производственный календарь isdayoff.ru (основной источник, им же заполнены старые строки)
    HOLIDAYS = 1    # библиотека holidays — запасной вариант, пока isdayoff.ru недоступен или не знает год


class CalendarDatesDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)
    cal_date: date
    is_holiday: bool
    is_weekend: bool
    is_workday: bool
    visit_count: int
    source: CalendarSource = CalendarSource.ISDAYOFF
    updated_at: datetime


class DigestScheduleDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    message_id: int
    created_at: datetime


class DayBookingDTO(BaseModel):
    """Бронь или место в очереди на дату — для уведомлений о смене календаря"""
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    user_id: int
    full_name: str
    status: str
