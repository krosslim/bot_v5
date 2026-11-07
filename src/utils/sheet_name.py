from datetime import date

from dateutil.relativedelta import relativedelta

from src.utils.tz_day import d_tz

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

def month_title(d: date) -> str:
    """Название листа месяца в Google-таблице: 'сентябрь 2025'. Одно и то же для данных бота и шаблона листа"""
    return f"{MONTHS_RU[d.month]} {d.year}"


def month_name(offset: int = 0) -> str:
    """Вернёт строку вида 'сентябрь 2025' для текущего месяца + offset"""
    return month_title(d_tz() + relativedelta(months=offset))
