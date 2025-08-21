from datetime import date, datetime
from enum import auto
from typing import List

from pydantic import BaseModel, ConfigDict
from strenum import StrEnum


class UserBookingDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    user_id: int
    full_name: str
    status: str
    created_at: datetime


class DateBookingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    cal_date: date
    users: List[UserBookingDTO]


class CancelBookingFifoDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    canceled_user_id: int | None
    promoted_user_id: int | None


class OwnBookingDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    booking_id: int
    user_id: int
    cal_date: date
    status: str
    sub_status: str

class WaitlistPositionDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    cal_date: date
    position: int

class BookingStatus(StrEnum):
    # Основные статусы
    BOOKED = auto()
    CANCELED = auto()
    WAITLISTED = auto()

    # Подстатусы для BOOKED
    CONFIRMED = auto()
    RESERVED = auto()

    # Подстатусы для CANCELED
    CANCELED_ILL = auto()
    CANCELED_FAMILY = auto()
    CANCELED_CHANGED_MIND = auto()
    CANCELED_OTHER = auto()
    CANCELED_NO_SPOTS_WAITLIST = auto()
    CANCELED_NOT_CONFIRMED = auto()
    CANCELED_ADMIN = auto()

    # Подстатусы для WAITLISTED
    WAITLISTED_MANUAL = auto()
    WAITLISTED_NO_SPOTS_AUTO = auto()



