from datetime import date
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from typing import Tuple

def month_first_last(offset: int) -> Tuple[date, date]:
    first = date.today().replace(day=1) + relativedelta(months=offset)
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return first, last
