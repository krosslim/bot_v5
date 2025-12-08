from datetime import date
from typing import List

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.user_dto import UserDTO
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.ui.keyboard.bookings_inline_kb import paginator_nums
from src.utils.idk import gen_idk


def render_employees_keyboard(
        user_list: List[UserDTO],
        offset: int,
        profession_id: int = None,
        pagination_step: SettingsStep = SettingsStep.EMPLOYEES_PAGINATION,
        on_click_step: SettingsStep = SettingsStep.EMPLOYEE,
        group_id: int = None
) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру со списком сотрудников и пагинацией.

    Args:
        user_list: список объектов UserDTO
        offset: текущее смещение для пагинации (номер страницы)
        profession_id: ID профессии (чтобы отличать - лид или админ)
        pagination_step: Название callback-step для пагинации
        on_click_step: Название callback-step при нажатии на пользователя
        group_id: ID группы (week_visit_plan). Нужен для определения корректного on_click_step

    Returns:
        InlineKeyboardMarkup с кнопками сотрудников и навигацией
    """
    builder = InlineKeyboardBuilder()

    if on_click_step != SettingsStep.EMPLOYEE:
        back_step = SettingsStep.VISITS_PLAN
    else:
        back_step = SettingsStep.LEAD_BLOCK if profession_id else SettingsStep.ADMIN_BLOCK

    default_on_click_step = on_click_step

    per_page = 6

    if offset > 0:
        builder.button(
            text="...",
            callback_data=SettingsCB(
                step=pagination_step,
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

        # Если пользователь относится к группе, нужно галочкой отметить его имя
        # И указать корректный step на нажатие (При нажатии - удаляется из группы)
        if user.week_visit_plan == group_id and on_click_step != SettingsStep.EMPLOYEE:
            action_step = SettingsStep.DEL_EMPLOYEE_FROM_GROUP
            display_name = f"✓ {display_name}"
        else:
            action_step = default_on_click_step

        builder.button(
            text=display_name,
            callback_data=SettingsCB(
                step=action_step,
                extra=user.user_id,
                idk=gen_idk()
            ).pack()
        )

    builder.adjust(2)

    if end_idx < len(user_list):
        builder.button(
            text="...",
            callback_data=SettingsCB(
                step=pagination_step,
                extra=offset + 1,
                idk=gen_idk()
            ).pack()
        )
        builder.adjust(*[2] * (len(page_users) // 2 + len(page_users) % 2), 1)

    builder.button(
        text="« Назад",
        callback_data=SettingsCB(
            step=back_step,
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


def visit_plan_report_kb(
        offset: int,
        week_start: date,
        week_end: date,
        profession_id: int = None
) -> InlineKeyboardMarkup:

    kb = InlineKeyboardBuilder()

    back_step = SettingsStep.LEAD_BLOCK if profession_id else SettingsStep.ADMIN_BLOCK

    date_text = f"{week_start:%d.%m} - {week_end:%d.%m}"
    left, right = paginator_nums(offset)

    kb.row(
        InlineKeyboardButton(text=left, callback_data=SettingsCB(
            step=SettingsStep.EMPLOYEE_STATISTICS_PAGE,
            extra=str(offset - 1),
            idk=gen_idk(),
        ).pack()),
        InlineKeyboardButton(
            text=date_text,
            callback_data=SettingsCB(
                step=SettingsStep.EMPLOYEE_STATISTICS_INFO,
                extra=date_text,
                idk=gen_idk(),
            ).pack(),
        ),
        InlineKeyboardButton(text=right, callback_data=SettingsCB(
            step=SettingsStep.EMPLOYEE_STATISTICS_PAGE,
            extra=str(offset + 1),
            idk=gen_idk()
        ).pack()),
    )
    kb.row(
        InlineKeyboardButton(text="« Назад", callback_data=SettingsCB(
            step=back_step,
            idk=gen_idk()
        ).pack())
    )


    return kb.as_markup()
