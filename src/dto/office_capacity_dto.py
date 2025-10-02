from pydantic import BaseModel, ConfigDict
from datetime import date

class OfficeCapacityDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)

    weekday: int
    short_name: str
    capacity: int

class AvailabilityDTO(BaseModel):
    cal_date: date
    is_holiday: bool
    is_available: bool
    is_weekend: bool


