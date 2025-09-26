from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)

    user_id: int
    full_name: str
    is_active: bool
    auto_confirm: bool
    auto_join_queue: bool
    is_admin: bool
    created_at: datetime


class UserBookingSessionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    message_id: int

class DictDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    name: str


class UserBookingDaysDTO(BaseModel):
    team: str
    position: str
    name: str
    days: List[str]

class UsersBookingDaysDTO(BaseModel):
    users: List[UserBookingDaysDTO]


