from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional

from src.dto.booking_dto import BookingStatus


def confirm_kb(date_bookings, link) -> Optional[InlineKeyboardMarkup]:
    kb = InlineKeyboardBuilder()
    for i in date_bookings.users:
        if i.sub_status == BookingStatus.RESERVED:
            return kb.row(
                InlineKeyboardButton(
                    text="Подтвердить",
                    url=link
                )
            ).as_markup()
    return None