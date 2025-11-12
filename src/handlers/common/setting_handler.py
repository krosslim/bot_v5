from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.handlers.user.booking_handler import render_booking_page
from src.services.exceptions import UserWarn
from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.settings_employee_kb import render_employees_keyboard
from src.ui.keyboard.settings_inline_kb import render_settings_menu_kb, render_settings_auto_confirm_kb
from src.ui.messages.settings_mess import render_auto_confirm_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.user_use_case import UserUseCase
from src.utils.db_exc_wrapper import DBError

router = Router()

# меню настроек
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.INIT_SETTINGS})))
async def handle_settings_page(call: CallbackQuery, uc: FromDishka[UserUseCase], state: FSMContext):

    try:
        user = await uc.check_exists(call.from_user.id)

        # Чтобы profession_id сбрасывался при возврате в меню
        await state.clear()

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
        SettingsStep.MY_EMPLOYEES,
        SettingsStep.EMPLOYEES_PAGINATION,
        SettingsStep.ALL_EMPLOYEES
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
        if not profession_id:
            if callback_data.step not in (SettingsStep.ALL_EMPLOYEES, SettingsStep.EMPLOYEES_PAGINATION):
                profession_id = int(callback_data.extra)
                await state.update_data(profession_id=profession_id)
        page = int(callback_data.extra) if callback_data.step == SettingsStep.EMPLOYEES_PAGINATION else 0
        employees = await uc.get_users(100, 0, profession_id)

        await call.message.edit_text(
            text="<b>Выберите доступного сотрудника ⤵︎</b>\n\n"
                 "<blockquote>При нажатии на имя сотрудника вы будете "
                 "авторизованы под его именем в окне бронирования.\n"
                 "У вас будет возможность управлять его записями</blockquote>",
            reply_markup=render_employees_keyboard(employees, page)
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
