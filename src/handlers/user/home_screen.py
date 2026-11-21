"""Главный экран в личке. В Rich это календарь (Rich Message, src/ui/rich/booking.py), иначе меню get_menu_kb.
Если календарь не открылся (Telegram отказал или заменил эмодзи заглушками, причина уже в логе и алерте),
показывается меню базового сценария."""
from typing import Optional

from aiogram import Bot
from aiogram.types import CallbackQuery

from src.services.feature_flags import BookingUi, FeatureFlags
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.widget_use_case import WidgetUseCase


async def show_home(call: CallbackQuery, flags: FeatureFlags, widgets: WidgetUseCase,
                    text: Optional[str] = None) -> None:
    """Главный экран вместо сообщения с нажатой кнопкой. text: текст меню, если показывается меню"""
    user_id = call.from_user.id
    ui = await flags.booking_ui_for(user_id)
    if ui == BookingUi.RICH:
        if await widgets.open_rich_calendar(user_id, user_id, call.message.message_id):
            return
        ui = BookingUi.BASIC
    await call.message.edit_text(text=text or bot_menu_mess(), reply_markup=get_menu_kb(ui))


async def send_home(bot: Bot, user_id: int, flags: FeatureFlags, widgets: WidgetUseCase,
                    text: Optional[str] = None) -> None:
    """Главный экран новым сообщением. text: текст меню, если показывается меню"""
    ui = await flags.booking_ui_for(user_id)
    if ui == BookingUi.RICH:
        if await widgets.open_rich_calendar(user_id, user_id):
            return
        ui = BookingUi.BASIC
    await bot.send_message(chat_id=user_id, text=text or bot_menu_mess(), reply_markup=get_menu_kb(ui))
