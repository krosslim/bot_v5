from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings


def effective_today() -> date:
    now_utc3 = datetime.now(tz=ZoneInfo(settings.MSC_TZ))
    if now_utc3.hour >= settings.WORK_END_HOUR:
        today = now_utc3.date() + timedelta(days=1)
    else:
        today = now_utc3.date()
    return today