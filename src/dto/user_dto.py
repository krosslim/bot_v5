from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)

    user_id: int
    full_name: str
    is_active: bool
    created_at: datetime


class UserCheckDTO(BaseModel):
    is_new: bool = False
    is_completed: bool = False
    user: UserDTO | None = None


class UserBookingSessionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    message_id: int




