from typing import List

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.user_dto import UserDTO
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.utils.idk import gen_idk


def render_employees_keyboard(user_list: List[UserDTO], offset: int) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру со списком сотрудников и пагинацией.

    Args:
        user_list: список объектов UserDTO
        offset: текущее смещение для пагинации (номер страницы)

    Returns:
        InlineKeyboardMarkup с кнопками сотрудников и навигацией
    """
    builder = InlineKeyboardBuilder()

    per_page = 6

    if offset > 0:
        builder.button(
            text="...",
            callback_data=SettingsCB(
                step=SettingsStep.EMPLOYEES_PAGINATION,
                extra=offset - 1,
                idk=gen_idk()
            ).pack()
        )
        builder.adjust(1)

    start_idx = offset * per_page
    end_idx = start_idx + per_page
    page_users = user_list[start_idx:end_idx]

    for user in page_users:
        name_parts = user.full_name.split()
        if len(name_parts) >= 2:
            display_name = f"{name_parts[0]} {name_parts[1][0]}."
        else:
            display_name = user.full_name

        builder.button(
            text=display_name,
            callback_data=SettingsCB(
                step=SettingsStep.EMPLOYEE,
                extra=user.user_id,
                idk=gen_idk()
            ).pack()
        )

    builder.adjust(2)

    if end_idx < len(user_list):
        builder.button(
            text="...",
            callback_data=SettingsCB(
                step=SettingsStep.EMPLOYEES_PAGINATION,
                extra=offset + 1,
                idk=gen_idk()
            ).pack()
        )
        builder.adjust(*[2] * (len(page_users) // 2 + len(page_users) % 2), 1)

    builder.button(
        text="« Меню настроек",
        callback_data=SettingsCB(
            step=SettingsStep.INIT_SETTINGS,
            idk=gen_idk()
        ).pack()
    )

    if offset > 0:
        rows = [1]
        rows.extend([2] * (len(page_users) // 2))
        if len(page_users) % 2 == 1:
            rows.append(1)
        if end_idx < len(user_list):
            rows.append(1)
        rows.append(1)
        builder.adjust(*rows)
    else:
        rows = [2] * (len(page_users) // 2)
        if len(page_users) % 2 == 1:
            rows.append(1)
        if end_idx < len(user_list):
            rows.append(1)
        rows.append(1)
        builder.adjust(*rows)

    return builder.as_markup()