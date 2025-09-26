from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.ui.keyboard.actions import SettingsCB, SettingsStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.settings_inline_kb import render_settings_menu_kb, render_settings_auto_confirm_kb
from src.ui.messages.settings_mess import render_auto_confirm_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.user_use_case import UserUseCase
from src.utils.db_exc_wrapper import DBError

router = Router()

# меню настроек
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.INIT_SETTINGS})))
async def handle_settings_page(call: CallbackQuery):
    await call.message.edit_text(
        text="<b>Доступные пункт меню настроек ⤵︎</b>",
        reply_markup=render_settings_menu_kb()
    )

# выйти в меню
@router.callback_query(SettingsCB.filter(F.step.in_({SettingsStep.GET_BACK_MENU})))
async def handle_get_back_menu(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())

# меню автоподтверждения
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