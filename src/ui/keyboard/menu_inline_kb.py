from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from src.ui.keyboard.actions import MyBookingCB, MyBookingStep, BookingCB, BookingStep, SettingsStep, SettingsCB
from src.utils.idk import gen_idk


def get_menu_kb(widgets: bool = False) -> InlineKeyboardMarkup:
    """widgets — пользователю включены виджеты (FeatureFlags.widgets_for): тогда «Мои брони» не нужна.
    По умолчанию кнопка есть: лишняя кнопка ничего не ломает, пропавшая — оставит без экрана броней"""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Забронировать место",
            style="success",
            # icon_custom_emoji_id="6039758482524081695",
            callback_data=BookingCB(step=BookingStep.INIT_BOOKING, idk=gen_idk()).pack()
        ),
        width=1
    )
    # С виджетами брони видны и отменяются в календаре, отдельный экран не нужен
    if not widgets:
        kb.row(
            InlineKeyboardButton(
                text="Мои брони",
                style="primary",
                # icon_custom_emoji_id="5972158252790582632",
                callback_data=MyBookingCB(step=MyBookingStep.INIT_MY_BOOKING, idk=gen_idk()).pack()
            ),
            width=1
        )
    kb.row(
        InlineKeyboardButton(
            text="Таблица",
            style="primary",
            # icon_custom_emoji_id="5974308936189218317",
            url=settings.GOOGLE_SHEET_USER_URL
        ),
        InlineKeyboardButton(
            text="Настройки",
            style="primary",
            # icon_custom_emoji_id="5974104203688152439",
            callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS, idk=gen_idk()).pack()
        ),
        width=2
    )
    return kb.as_markup()


def own_booking_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Управлять бронированием",
            callback_data=MyBookingCB(step=MyBookingStep.INIT_MY_BOOKING, idk=gen_idk()).pack()
        ),
        width=1
    )
    return kb.as_markup()


def check_bookings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Проверить наличие мест",
            callback_data=BookingCB(step=BookingStep.INIT_BOOKING, idk=gen_idk()).pack()
        ),
        width=1
    )
    return kb.as_markup()
