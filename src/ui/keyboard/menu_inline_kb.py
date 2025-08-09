from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.ui.keyboard.actions import MenuCB, MenuStep, BookingCB, BookingStep


def get_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    return kb.row(
        InlineKeyboardButton(
            text="🆕 Забронировать место",
            callback_data=BookingCB(step=BookingStep.INIT_BOOKING,
                                 idk="-").pack()
        ),
        InlineKeyboardButton(
            text="📋 Мои брони",
            callback_data=MenuCB(step=MenuStep.MY_BOOKING).pack()
        ),
        InlineKeyboardButton(
            text="⚙️ Настройки",
            callback_data=MenuCB(step=MenuStep.SETTINGS).pack()
        ),
        width=1
    ).as_markup()

