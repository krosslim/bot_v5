from datetime import date, timedelta
from typing import Tuple

from config import settings
from src.utils.today import effective_today
from src.utils.tz_day import d_tz


def week_range(
        offset_weeks: int | None = None,
        is_effective_today: bool = True,
) -> Tuple[date, date, int]:

    if is_effective_today:
        today = effective_today()
    else:
        today = d_tz()

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
