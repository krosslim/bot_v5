from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.utils.idk import gen_idk


def remind_kb(cal_date: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="Отменить",
            callback_data=ChatBookingCB(
                step=ChatBookingStep.CANCEL_BOOKING_IN_REMINDER,
                extra=f"{cal_date}",
                idk=gen_idk()).pack()
        ),
        InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=ChatBookingCB(
                step=ChatBookingStep.CONFIRM_BOOKING_IN_REMINDER,
                extra=f"{cal_date}",
                idk=gen_idk()).pack()
        ),
        width=2
    )
    return kb.as_markup()