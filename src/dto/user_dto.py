from datetime import datetime

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
    is_lead: bool
    profession_id: int
    product_id: int
    week_visit_plan: int | None
    created_at: datetime


class UserStatisticsDTO(UserDTO):
    visit_count: int


class UserBookingSessionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    message_id: int


class DictDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    name: str
