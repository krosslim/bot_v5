from datetime import date
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class UserBookingDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    full_name: str
    status_id: int


class DateBookingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    users: List[UserBookingDTO]


class UserOwnBookingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    status_id: int
    status_name: str = Field(alias="description")


class UserWaitlistDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    position: int


class WeekAttendanceDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    week_start: date
    week_end: date
    bookings: List[UserOwnBookingsDTO]
    waitlist: List[UserWaitlistDTO]


class CancelBookingDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    cal_date: date
    waiter_user_id: int = None



