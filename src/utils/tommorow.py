from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings as s

WEEKDAYS_RU = [
    "Понедельник", "Вторник", "Среда",
    "Четверг", "Пятница", "Суббота", "Воскресенье"
]

def _weekday_ru(d: date) -> str:
    return WEEKDAYS_RU[d.weekday()]

def fmt_date_ru(d: date) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.strftime('%d.%m')}, {_weekday_ru(d)}"


def is_tomorrow(d: date) -> bool:
    today = datetime.now(tz=ZoneInfo(s.MSC_TZ)).date()
    if d == today + timedelta(days=1):
        return True
    return False