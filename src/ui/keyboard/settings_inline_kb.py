from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.user_dto import UserDTO
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.utils.idk import gen_idk


def render_settings_menu_kb(user: UserDTO = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="🤖✅ Автоподтверждение брони",
            callback_data=SettingsCB(step=SettingsStep.AUTO_CONFIRM,
                                     idk=gen_idk()).pack()
        )
    )
    if user is not None and user.is_lead:
        kb.row(
        InlineKeyboardButton(
            text="👤 Мои сотрудники",
            callback_data=SettingsCB(step=SettingsStep.MY_EMPLOYEES,
                                     extra=user.profession_id,
                                     idk=gen_idk()).pack()
            )
        )
    kb.row(
        InlineKeyboardButton(
            text="« Выйти",
            callback_data=SettingsCB(step=SettingsStep.GET_BACK_MENU,
                                     idk=gen_idk()).pack()
        )
    )

    return kb.as_markup()

def render_settings_auto_confirm_kb(auto_confirm: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if not auto_confirm:
        off = "🔘 Выключено"
        off_cb = SettingsCB(step=SettingsStep.AUTO_CONFIRM_OFF,extra=f"{auto_confirm}", idk=gen_idk()).pack()
        on = "⚪️ Включено"
        on_cb = SettingsCB(step=SettingsStep.AUTO_CONFIRM_ON, idk=gen_idk()).pack()
    else:
        off = "⚪️ Выключено"
        off_cb = SettingsCB(step=SettingsStep.AUTO_CONFIRM_OFF, idk=gen_idk()).pack()
        on = "🔘️ Включено"
        on_cb = SettingsCB(step=SettingsStep.AUTO_CONFIRM_ON, extra=f"{auto_confirm}", idk=gen_idk()).pack()

    kb.row(
        InlineKeyboardButton(text=off, callback_data=off_cb),
        InlineKeyboardButton(text=on, callback_data=on_cb)
    )

    kb.row(
        InlineKeyboardButton(text="« Меню настроек",
                             callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS, idk=gen_idk()).pack()
                             )
    )


    return kb.as_markup()

