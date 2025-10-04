from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CalendarDatesDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)
    cal_date: date
    is_holiday: bool
    is_weekend: bool
    is_workday: bool


class DigestScheduleDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    message_id: int
    created_at: datetime
