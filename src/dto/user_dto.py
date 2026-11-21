from datetime import datetime, date

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
    birth_date: date | None
    created_at: datetime


class UserStatisticsDTO(UserDTO):
    visit_count: int


class UserBookingSessionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    message_id: int


class BookingWidgetPointerDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: int
    target_id: int | None = None   # бронь админом за сотрудника
    rich: bool = False             # окно Rich-календаря (иначе виджет)
    view: str | None = None        # что сейчас в Rich-окне: m2026-11-01 календарь месяца, d2026-11-23 экран дня


class DictDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    name: str
