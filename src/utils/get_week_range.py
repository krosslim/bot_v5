from datetime import date, timedelta
from typing import Tuple

from config import settings
from src.utils.today import effective_today


def week_range(offset_weeks: int | None = None) -> Tuple[date, date, int]:

    today = effective_today()
    this_monday = today - timedelta(days=today.weekday())

    if offset_weeks is None:
        week_offset = 1 if today.weekday() >= 5 else 0
    else:
        week_offset = offset_weeks

    if week_offset > settings.PAGINATION_LIMIT_WEEKS or week_offset < -settings.PAGINATION_LIMIT_WEEKS:
        week_offset = 1 if today.weekday() >= 5 else 0

    monday = this_monday + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)

    return monday, sunday, week_offset
