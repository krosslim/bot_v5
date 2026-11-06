from datetime import date, datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings as s
from src.utils.tz_day import d_tz


def work_end_time() -> time:
    """Время закрытия бронирования на текущий день: WORK_END_HOUR:WORK_END_MINUTES"""
    return time(s.WORK_END_HOUR, s.WORK_END_MINUTES)


def is_after_work_end(now: datetime) -> bool:
    return now.time() >= work_end_time()


def widget_data_expiry(now: Optional[datetime] = None) -> int:
    """Когда календарь виджета устаревает (unix-время): сегодня в WORK_END — закрывается текущий день,
    после него — в полночь, когда сдвигается «сегодня»"""
    now = now or datetime.now(ZoneInfo(s.MSC_TZ))
    end = datetime.combine(now.date(), work_end_time(), tzinfo=now.tzinfo)
    if now >= end:
        end = datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=now.tzinfo)
    return int(end.timestamp())


def effective_today() -> date:
    now_utc3 = datetime.now(tz=ZoneInfo(s.MSC_TZ))
    if is_after_work_end(now_utc3):
        today = now_utc3.date() + timedelta(days=1)
    else:
        today = now_utc3.date()
    return today


def effective_datetime_range() -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo(s.MSC_TZ))
    today = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    tomorrow = datetime.combine(date=d_tz(delta=1), time=work_end_time(), tzinfo=ZoneInfo(s.MSC_TZ))

    return today, tomorrow
