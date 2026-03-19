from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.user_dto import UserDTO, DictDTO
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.utils.idk import gen_idk


def render_settings_menu_kb(user: UserDTO = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="🤖 Автоподтверждение брони",
            callback_data=SettingsCB(step=SettingsStep.AUTO_CONFIRM,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="👤 Мой профиль",
            callback_data=SettingsCB(step=SettingsStep.MY_PROFILE, idk=gen_idk()).pack()
        )
    )
    if user is not None and user.is_lead:
        kb.row(
        InlineKeyboardButton(
            text="🔓 Меню лида",
            callback_data=SettingsCB(step=SettingsStep.LEAD_BLOCK,
                                     extra=user.profession_id,
                                     idk=gen_idk()).pack()
            )
        )
    if user is not None and user.is_admin:
        kb.row(
        InlineKeyboardButton(
            text="🔓 Меню админа",
            callback_data=SettingsCB(step=SettingsStep.ADMIN_BLOCK,
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


def render_profile_settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Должность",
            callback_data=SettingsCB(step=SettingsStep.UPDATE_PROFESSION,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="Команда",
            callback_data=SettingsCB(step=SettingsStep.UPDATE_PRODUCT,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="Дата рождения",
            callback_data=SettingsCB(step=SettingsStep.UPDATE_BIRTHDATE,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(text="« Меню настроек",
                             callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS, idk=gen_idk()).pack()
                             )
    )

    return kb.as_markup()


def render_lead_admin_menu_kb(profession_id: int = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="👤 Управление записями",
            callback_data=SettingsCB(step=SettingsStep.EMPLOYEE_LIST,
                                     extra=profession_id,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="📝 Управление посещениями",
            callback_data=SettingsCB(step=SettingsStep.VISITS_PLAN,
                                     extra=profession_id,
                                     idk=gen_idk()).pack()
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="📊 Статистика по посещениям",
            callback_data=SettingsCB(step=SettingsStep.EMPLOYEE_STATISTICS,
                                     extra=profession_id,
                                     idk=gen_idk()).pack()
        )
    )

    kb.row(
        InlineKeyboardButton(text="« Меню настроек",
                             callback_data=SettingsCB(step=SettingsStep.INIT_SETTINGS, idk=gen_idk()).pack()
                             )
    )

    return kb.as_markup()


def render_week_visits_count_kb(profession_id: int = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    step = SettingsStep.VISIT_GROUP
    back_step = SettingsStep.LEAD_BLOCK if profession_id else SettingsStep.ADMIN_BLOCK

    adjust_num = 0
    for i in range(1, 6):
        adjust_num += 1
        kb.row(InlineKeyboardButton(text=f"{i}", callback_data=SettingsCB(step=step, extra=i, idk=gen_idk()).pack()))

    kb.adjust(adjust_num)

    kb.row(InlineKeyboardButton(text="« Назад",
                                callback_data=SettingsCB(step=back_step, idk=gen_idk()).pack()))
    return kb.as_markup()


def get_dict_with_back_kb(dict_data: List[DictDTO], dict_type: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    match dict_type:
        case "profession":
            step = SettingsStep.UPDATE_PROFESSION_CHOOSE
        case "product":
            step = SettingsStep.UPDATE_PRODUCT_CHOOSE
        case _:
            kb.button(
                text="« Назад",
                callback_data=SettingsCB(step=SettingsStep.MY_PROFILE, idk=gen_idk()).pack()
            )
            return kb.as_markup()

    for item in dict_data:
        kb.button(
            text=item.name,
            callback_data=SettingsCB(step=step, extra=item.id, idk=gen_idk()).pack()
        )

    kb.button(
        text="« Назад",
        callback_data=SettingsCB(step=SettingsStep.MY_PROFILE, idk=gen_idk()).pack()
    )

    kb.adjust(1)

    return kb.as_markup()