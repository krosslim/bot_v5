from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from src.ui.keyboard.actions import MyBookingCB, MyBookingStep, BookingCB, BookingStep, SettingsStep, SettingsCB


def get_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="🆕 Забронировать место",
            callback_data=BookingCB(step=BookingStep.INIT_BOOKING, idk="-").pack()
        ),
        width=1
    )
    kb.row(
        InlineKeyboardButton(
            text="📋 Мои брони",
            callback_data=MyBookingCB(step=MyBookingStep.INIT_MY_BOOKING).pack()
        ),
        width=1
    )
    kb.row(
        InlineKeyboardButton(
            text="📗 Таблица",
            url=settings.GOOGLE_SHEET_USER_URL
        ),
        InlineKeyboardButton(
            text="⚙️ Настройки",
            callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS).pack()
        ),
        width=2
    )
    return kb.as_markup()


def own_booking_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Управлять бронированием",
            callback_data=MyBookingCB(step=MyBookingStep.INIT_MY_BOOKING).pack()
        ),
        width=1
    )
    return kb.as_markup()
