from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import settings


def is_in_autoconfirm_period(cal_date: date) -> bool:

    tz = ZoneInfo(settings.MSC_TZ)
    now = datetime.now(tz)
    today = now.date()

    if cal_date == today:
        return True

    if cal_date == today + timedelta(days=1):
        return now.time() >= time(16, 0)

    return False
