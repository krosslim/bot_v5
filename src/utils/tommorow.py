from datetime import date, datetime

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

