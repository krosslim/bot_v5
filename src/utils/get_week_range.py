from datetime import date, timedelta
from typing import Tuple

LIMIT_WEEKS = 4

def week_range(offset_weeks: int | None = None) -> Tuple[date, date, int]:

    today = date.today()
    this_monday = today - timedelta(days=today.weekday())

    if offset_weeks is None:
        week_offset = 1 if today.weekday() >= 5 else 0
    else:
        week_offset = offset_weeks

    if week_offset > LIMIT_WEEKS or week_offset < -LIMIT_WEEKS:
        week_offset = 1 if today.weekday() >= 5 else 0

    monday = this_monday + timedelta(weeks=week_offset)
    friday = monday + timedelta(days=4)

    return monday, friday, week_offset

