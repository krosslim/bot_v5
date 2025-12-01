from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings as s


def d_tz(delta: int = 0) -> date:
    return datetime.now(tz=ZoneInfo(s.MSC_TZ)).date() + timedelta(days=delta)

def dt_tz(delta: int = 0) -> datetime:
    return datetime.now(tz=ZoneInfo(s.MSC_TZ)) + timedelta(days=delta)
