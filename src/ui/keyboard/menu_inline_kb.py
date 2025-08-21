from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.ui.keyboard.actions import MyBookingCB, MyBookingStep, BookingCB, BookingStep, SettingsStep, SettingsCB


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
            callback_data=MyBookingCB(step=MyBookingStep.INIT_MY_BOOKING).pack()
        ),
        InlineKeyboardButton(
            text="⚙️ Настройки",
            callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS).pack()
        ),
        width=1
    ).as_markup()

