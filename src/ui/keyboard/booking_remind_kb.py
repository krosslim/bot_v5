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

    buttons = []
    if has_unconfirmed:
        buttons.append(InlineKeyboardButton(
            text="Подтвердить",
            callback_data=ChatBookingCB(
                step=ChatBookingStep.CONFIRM_BOOKING,
                extra=f"{cal_date}",
                idk=gen_idk()).pack()
        ))
    if has_free:
        buttons.append(InlineKeyboardButton(
            text="Занять место",
            callback_data=ChatBookingCB(
                step=ChatBookingStep.ADD_BOOKING,
                extra=f"{cal_date}",
                idk=gen_idk()).pack()
        ))
    if not buttons:
        return None

    kb = InlineKeyboardBuilder()
    kb.row(*buttons, width=2)
    return kb.as_markup()
