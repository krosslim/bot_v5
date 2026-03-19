from datetime import date
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.booking_dto import BookingStatus, DateBookingsDTO
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.utils.idk import gen_idk


def confirm_kb(bookings: DateBookingsDTO, capacity: int, cal_date: date) -> Optional[InlineKeyboardMarkup]:

    if bookings:
        booked_cnt = canceled_cnt = 0
        for i in bookings.users:
            if i.status == BookingStatus.BOOKED:
                booked_cnt += 1
            elif i.status == BookingStatus.CANCELED:
                canceled_cnt += 1

        free_left = max(0, capacity - booked_cnt)
        has_free = free_left > 0

        has_unconfirmed = any(
            u.sub_status == BookingStatus.RESERVED
            for u in bookings.users
        )
    else:
        has_free = True
        has_unconfirmed = False


    if has_free and has_unconfirmed:
        button_text = "Забронировать / Подтвердить"
    elif has_free and not has_unconfirmed:
        button_text = "Забронировать"
    elif not has_free and has_unconfirmed:
        button_text = "Подтвердить"
    else: 
        return None


    kb = InlineKeyboardBuilder()
    kb.add(
        InlineKeyboardButton(
            text=button_text,
            stype="success",
            callback_data=ChatBookingCB(
                step=ChatBookingStep.ADD_OR_CONFIRM_BOOKING,
                extra=f"{cal_date}",
                idk=gen_idk()).pack()
        )
    )
    return kb.as_markup()
