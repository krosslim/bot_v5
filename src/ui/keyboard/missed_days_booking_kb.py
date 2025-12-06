from datetime import date
from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.utils.idk import gen_idk


def render_missed_booking_kb(
        cal_dates: List[CalendarDatesDTO],
        choosen_dates: List[date]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for cal_date_obj in cal_dates:
        cal_date = cal_date_obj.cal_date

        if cal_date in choosen_dates:
            text = f"✓ {cal_date.strftime('%d.%m')}"
            step = BookingStep.MISSED_CHOOSEN
        else:
            text = cal_date.strftime("%d.%m")
            step = BookingStep.MISSED_NOT_CHOOSEN

        callback_data = BookingCB(
            step=step,
            extra=str(cal_date),
            idk=gen_idk()
        ).pack()

        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        builder.add(button)

    builder.adjust(5)

    exit_button = InlineKeyboardButton(
        text="« Выйти",
        callback_data=BookingCB(step=BookingStep.GET_BACK_MENU, idk=gen_idk()).pack()
    )
    confirm_button = InlineKeyboardButton(
        text="Подтвердить",
        callback_data=BookingCB(step=BookingStep.MISSED_CONFIRM, idk=gen_idk()).pack()
    )

    if len(choosen_dates) > 0:
        builder.row(exit_button, confirm_button)
    else:
        builder.row(exit_button)

    return builder.as_markup()