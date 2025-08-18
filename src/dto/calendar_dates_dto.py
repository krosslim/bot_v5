from datetime import date

from pydantic import BaseModel, ConfigDict


class CalendarDatesDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)
    cal_date: date
    is_weekend: bool
    is_holiday: bool

