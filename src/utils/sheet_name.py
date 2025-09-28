from datetime import date

from dateutil.relativedelta import relativedelta

MONTHS_RU = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}

def month_name(offset: int = 0) -> str:
    """Вернёт строку вида 'сентябрь 2025' для текущего месяца + offset."""
    today = date.today()
    target = today + relativedelta(months=offset)
    return f"{MONTHS_RU[target.month]} {target.year}"
