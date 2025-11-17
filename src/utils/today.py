from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo

from config import settings as s
from src.utils.tz_day import d_tz


def effective_today() -> date:
    now_utc3 = datetime.now(tz=ZoneInfo(s.MSC_TZ))
    if now_utc3.hour >= s.WORK_END_HOUR:
        today = now_utc3.date() + timedelta(days=1)
    else:
        today = now_utc3.date()
    return today


def effective_datetime_range() -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo(s.MSC_TZ))
    today = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    tomorrow = datetime.combine(date=d_tz(delta=1), time=time(s.WORK_END_HOUR, 0), tzinfo=ZoneInfo(s.MSC_TZ))

    return today, tomorrow
