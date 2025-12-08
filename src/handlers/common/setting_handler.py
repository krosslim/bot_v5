from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.handlers.user.booking_handler import render_booking_page
from src.services.exceptions import UserWarn
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.settings_employee_kb import render_employees_keyboard, visit_plan_report_kb
from src.ui.keyboard.settings_inline_kb import (render_settings_menu_kb,
                                                render_settings_auto_confirm_kb,
                                                render_lead_admin_menu_kb,
                                                render_week_visits_count_kb)
from src.ui.messages.settings_mess import render_auto_confirm_mess, render_employee_group_mess, visit_plan_report_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.user_use_case import UserUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.get_week_range import week_range

router = Router()

# меню настроек
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.INIT_SETTINGS})))
async def handle_settings_page(call: CallbackQuery, uc: FromDishka[UserUseCase], state: FSMContext):

    try:

        # Чтобы profession_id сбрасывался при возврате в меню (актуально если юзер и админ и лид)
        await state.clear()

        user = await uc.check_exists(call.from_user.id)

        # Для корректной инициализации меню админа или лида
        # Логика такая: если profession_id = None то мы работаем с админом, иначе лид
        profession_id = None
        if user.is_lead:
            profession_id = user.profession_id
        if user.is_admin or user.is_lead:
            await state.update_data(profession_id=profession_id)

    except (DBError, UserWarn):
        user = None

    await call.message.edit_text(
        text="<b>Доступные пункт меню настроек ⤵︎</b>",
        reply_markup=render_settings_menu_kb(user)
    )

# выйти в меню
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.GET_BACK_MENU})))
async def handle_get_back_menu(call: CallbackQuery, state: FSMContext):
    if await state.get_data():
        await state.clear()
    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())

# меню авто подтверждения
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.AUTO_CONFIRM})))
async def handle_settings_auto_confirm(call: CallbackQuery, uc: FromDishka[UserUseCase]):

    try:
        auto_confirm = await uc.user_auto_confirm(call.from_user.id)
        await call.message.edit_text(
            text=render_auto_confirm_mess(),
            reply_markup=render_settings_auto_confirm_kb(auto_confirm)
        )
    except DBError:
        await call.answer(text="❌ Не удалось получить настройки.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )

@router.callback_query(SettingsCB.filter(F.step.in_(SettingsStep.AUTO_CONFIRM_ON)))
async def handle_settings_auto_confirm_on(call: CallbackQuery,
                                          callback_data: SettingsCB,
                                          uc: FromDishka[UserUseCase]
                                          ):
    # Если текущее состояние - не изменяем
    if callback_data.extra:
        return

    try:
        await uc.update_auto_confirm(call.from_user.id, True)
        await call.message.edit_text(
            text=render_auto_confirm_mess(),
            reply_markup=render_settings_auto_confirm_kb(True)
        )
    except DBError:
        await call.answer(text="❌ Не удалось изменить настройки.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )


@router.callback_query(SettingsCB.filter(F.step.in_(SettingsStep.AUTO_CONFIRM_OFF)))
async def handle_settings_auto_confirm_on(call: CallbackQuery,
                                          callback_data: SettingsCB,
                                          uc: FromDishka[UserUseCase]
                                          ):
    # Если текущее состояние - не изменяем
    if callback_data.extra:
        return

    try:
        await uc.update_auto_confirm(call.from_user.id, False)
        await call.message.edit_text(
            text=render_auto_confirm_mess(),
            reply_markup=render_settings_auto_confirm_kb(False)
        )
    except DBError:
        await call.answer(text="❌ Не удалось изменить настройки.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )


@router.callback_query(SettingsCB.filter(F.step.in_({
    SettingsStep.LEAD_BLOCK,
    SettingsStep.ADMIN_BLOCK
    })))
async def handle_settings_head_block(
        call: CallbackQuery,
        callback_data: SettingsCB,
        state: FSMContext
):
    state_data = await state.get_data()
    profession_id = state_data.get("profession_id", None)

    # Для корректного разделения админок (на случай если юзер админ и лид)
    if callback_data.step == SettingsStep.ADMIN_BLOCK:
        await state.update_data(profession_id=None)

    await call.message.edit_text(
        text="<b>Выберите доступное действие ⤵︎</b>\n\n"
             "<blockquote expandable><b>• Управление записями</b> - изменение статуса записей подчиненных\n"
             "<b>• Управление посещениями</b> - установка плана по кол-ву визитов в неделю\n"
             "<b>• Статистика по посещениям</b> - отчет по выполнению плана посещений по неделям</blockquote>",
        reply_markup=render_lead_admin_menu_kb(profession_id)
    )


@router.callback_query(SettingsCB.filter(F.step.in_({
        SettingsStep.EMPLOYEE_LIST,
        SettingsStep.EMPLOYEES_PAGINATION
    })))
async def handle_settings_my_employees(
        call: CallbackQuery,
        callback_data: SettingsCB,
        uc: FromDishka[UserUseCase],
        state: FSMContext
):
    try:
        state_data = await state.get_data()
        profession_id = state_data.get("profession_id", None)

        page = int(callback_data.extra) if callback_data.step == SettingsStep.EMPLOYEES_PAGINATION else 0
        employees = await uc.get_users(200, 0, profession_id)

        await call.message.edit_text(
            text="<b>Выберите доступного сотрудника ⤵︎</b>\n\n"
                 "<blockquote>При нажатии на имя сотрудника вы будете "
                 "авторизованы под его именем в окне бронирования.\n"
                 "У вас будет возможность управлять его записями</blockquote>",
            reply_markup=render_employees_keyboard(employees, page, profession_id)
        )
    except DBError:
        await call.answer(text="❌ Не удалось получить сотрудников.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )


@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.EMPLOYEE})))
async def handle_settings_employee(
        call: CallbackQuery,
        callback_data: SettingsCB,
        u_uc: FromDishka[UserUseCase],
        b_uc: FromDishka[BookingUseCase],
        state: FSMContext
):
    try:
        employee_id = int(callback_data.extra)
        employee = await u_uc.check_exists(employee_id)

        await state.update_data(user_id=employee_id)

        await call.answer(
            text="❗️Вы авторизовались как:\n"
                 f"{employee.full_name}\n\n"
                 "Для выхода:\n"
                 "- Кнопка « Выйти\n"
                 "- команда /start\n"
                 "- команда /menu",
            show_alert=True
        )
        await render_booking_page(call, 0, b_uc, state, None, employee_id)
    except DBError:
        await call.answer(text="❌ Не удалось получить сотрудника.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )


@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.VISITS_PLAN})))
async def handle_settings_visits_plan(
        call: CallbackQuery,
        state: FSMContext
):

    # profession_id получать ТОЛЬКО из state, так как есть сценарии, где мы не можем брать его из callback_data.extra
    # например, при нажатии кнопки "Назад" в шаге VISIT_GROUP
    state_data = await state.get_data()
    profession_id = state_data.get("profession_id", None)

    await call.message.edit_text(
        text="<b>Укажите кол-во визитов в неделю, которое хотите назначить сотрудникам ⤵︎</b>\n\n"
             "<blockquote>Каждую пятницу вы будете получать отчет по таким сотрудникам</blockquote>",
        reply_markup=render_week_visits_count_kb(profession_id)
    )


@router.callback_query(SettingsCB.filter(F.step.in_({
    SettingsStep.VISIT_GROUP,
    SettingsStep.EMPLOYEES_PAGINATION_FOR_GROUP
})))
async def handle_settings_visit_group(
        call: CallbackQuery,
        callback_data: SettingsCB,
        uc: FromDishka[UserUseCase],
        state: FSMContext
):
    state_data = await state.get_data()

    if callback_data.step == SettingsStep.VISIT_GROUP:
        group_id = int(callback_data.extra)
        await state.update_data(group_id=group_id)
    else:
        group_id = state_data.get('group_id', None)

    profession_id = state_data.get('profession_id', None)

    page = 0
    if callback_data.step == SettingsStep.EMPLOYEES_PAGINATION_FOR_GROUP:
        page = int(callback_data.extra)

    await state.update_data(page=page)

    await _render_settings_visit_group_page(call, uc, group_id, profession_id, page)


@router.callback_query(SettingsCB.filter(F.step.in_({
    SettingsStep.ADD_EMPLOYEE_TO_GROUP,
    SettingsStep.DEL_EMPLOYEE_FROM_GROUP
})))
async def handle_settings_change_employee_group(
        call: CallbackQuery,
        callback_data: SettingsCB,
        uc: FromDishka[UserUseCase],
        state: FSMContext
):

    state_data = await state.get_data()
    group_id = state_data.get('group_id')
    profession_id = state_data.get('profession_id', None)
    page = state_data.get('page', 0)
    employee_id = int(callback_data.extra)

    try:

        if not group_id:
            await call.answer(text="Не удалось получить группу\nВыйдите из админки и зайдите заново",
                              show_alert=True)
            return

        if callback_data.step == SettingsStep.DEL_EMPLOYEE_FROM_GROUP:
            await uc.set_visit_plan(employee_id, None)
        else:
            await uc.set_visit_plan(employee_id, group_id)

    except DBError:
        await call.answer(text="❌ Не удалось назначить группу.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )

    await _render_settings_visit_group_page(call, uc, group_id, profession_id, page)


# ---------------------------------------------- helpers ----------------------------------------------
async def _render_settings_visit_group_page(
        call: CallbackQuery,
        uc: UserUseCase,
        group_id: int,
        profession_id: int | None,
        page: int
) -> None:
    try:

        pagination_step = SettingsStep.EMPLOYEES_PAGINATION_FOR_GROUP
        on_click_step = SettingsStep.ADD_EMPLOYEE_TO_GROUP

        employees = await uc.get_users(200, 0, profession_id)

        await call.message.edit_text(
            text=render_employee_group_mess(employees, group_id),
            reply_markup=render_employees_keyboard(
                employees, page, profession_id, pagination_step, on_click_step, group_id
            )
        )

    except DBError:
        await call.answer(text="❌ Не удалось получить сотрудника.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )


@router.callback_query(SettingsCB.filter(F.step.in_({
    SettingsStep.EMPLOYEE_STATISTICS,
    SettingsStep.EMPLOYEE_STATISTICS_INFO,
    SettingsStep.EMPLOYEE_STATISTICS_PAGE
})))
async def handle_settings_employee_statistics(
        call: CallbackQuery,
        callback_data: SettingsCB,
        uc: FromDishka[UserUseCase],
        state: FSMContext
):
    if callback_data.step == SettingsStep.EMPLOYEE_STATISTICS_INFO:
        return await call.answer(
            text=f"Статистика за {callback_data.extra}",
            show_alert=True
        )

    try:

        state_data = await state.get_data()
        profession_id = state_data.get('profession_id', None)

        start, end, week_offset = week_range(
            int(callback_data.extra) if callback_data.step == SettingsStep.EMPLOYEE_STATISTICS_PAGE else None
        )

        data = await uc.visit_plan_report(start, end, profession_id)

        await call.message.edit_text(
            text=visit_plan_report_mess(data, start, end),
            reply_markup=visit_plan_report_kb(week_offset, start, end, profession_id)
        )

    except DBError:
        await call.answer(text="❌ Не удалось получить данные.\nПопробуйте ещё раз позже.",
                          show_alert=True
                          )
