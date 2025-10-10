from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message
from dishka import FromDishka

from src.fsm.states import CreateUserState
from src.services.exceptions import UserWarn
from src.ui.keyboard.form_data_kb import get_dict_kb, get_confirmation_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.start_mess import (start_db_exc_mess, bot_init_mess,
                                        bot_menu_mess, finish_start_reg_mess, incorrect_full_name_mess, form_data_mess)
from src.use_cases.user_use_case import UserUseCase
from src.utils.db_exc_wrapper import DBError

router = Router()


@router.message(CommandStart())
async def handle_start(msg: Message, uc: FromDishka[UserUseCase], state: FSMContext):

    if await state.get_state():
        await state.clear()

    try:
        user = await uc.check_exists(msg.from_user.id)
        if user is None:
            bot_msg = await msg.answer(text=bot_init_mess(""))
            await state.set_state(CreateUserState.full_name)
            await state.update_data(bot_msg_id=bot_msg.message_id)
            return
        await msg.answer(text=bot_init_mess(user.full_name), reply_markup=get_menu_kb())

    except DBError:
        await msg.answer(text=start_db_exc_mess())


@router.message(F.text == "/menu")
async def handle_back_menu_command(msg: Message, uc: FromDishka[UserUseCase],  state: FSMContext):

    if await state.get_state():
        await state.clear()

    try:

        user = await uc.check_exists(msg.from_user.id)
        if user is None:
            await msg.answer(text=bot_init_mess(""))
            await state.set_state(CreateUserState.full_name)
            return
        await msg.answer(text=bot_menu_mess(), reply_markup=get_menu_kb())

    except DBError:
        await msg.answer(text=start_db_exc_mess())


@router.message(CreateUserState.full_name)
async def handle_full_name(msg: Message, uc: FromDishka[UserUseCase], state: FSMContext):

    try:
        if uc.check_full_name(msg.text):
            professions_list = await uc.get_professions()

            await state.set_state(CreateUserState.profession)
            await state.update_data(full_name=msg.text)
            await msg.answer(text=form_data_mess(msg.text, None, None),
                             reply_markup=get_dict_kb(professions_list))

    except UserWarn:
        bot_msg_id = await state.get_value(key="bot_msg_id")
        await msg.bot.delete_message(chat_id=msg.from_user.id, message_id=msg.message_id)
        await msg.bot.edit_message_text(chat_id=msg.from_user.id, message_id=bot_msg_id, text=incorrect_full_name_mess())
    except DBError:
        bot_msg_id = await state.get_value(key="bot_msg_id")
        await msg.bot.delete_message(chat_id=msg.from_user.id, message_id=msg.message_id)
        await state.clear()
        await msg.bot.edit_message_text(chat_id=msg.from_user.id, message_id=bot_msg_id,
                                        text=start_db_exc_mess())


@router.callback_query(CreateUserState.profession)
async def handle_profession(call: CallbackQuery, uc: FromDishka[UserUseCase], state: FSMContext):
    try:
        products_list = await uc.get_products()

        data = call.data or ""
        if "#" in data:
            profession_id, profession_name = data.split("#", 1)
        else:
            profession_id, profession_name = "1", "Веб КЦ (общее)"

        await state.set_state(CreateUserState.product)
        await state.update_data(profession_id=profession_id, profession_name=profession_name)


        full_name = await state.get_value(key="full_name")
        await call.message.edit_text(
            text=form_data_mess(full_name, profession_name, None),
            reply_markup=get_dict_kb(products_list)
        )

    except DBError:
        bot_msg_id = await state.get_value(key="bot_msg_id")
        await call.bot.delete_message(chat_id=call.from_user.id, message_id=call.message_id)
        await state.clear()
        await call.bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=bot_msg_id,
            text=start_db_exc_mess()
        )

@router.callback_query(CreateUserState.product)
async def handle_product(call: CallbackQuery, state: FSMContext):
    data = call.data or ""

    if "#" in data:
        product_id, product_name = data.split("#", 1)
    else:
        product_id, product_name = "1", "Веб КЦ (общее)"

    await state.set_state(CreateUserState.confirmation)
    await state.update_data(product_id=product_id, product_name=product_name)

    state_data = await state.get_data()
    full_name = state_data.get("full_name")
    profession_name = state_data.get("profession_name")

    await call.message.edit_text(
        text=form_data_mess(full_name, profession_name, product_name),
        reply_markup=get_confirmation_kb()
    )

@router.callback_query(CreateUserState.confirmation)
async def handle_confirmation(call: CallbackQuery, uc: FromDishka[UserUseCase], state: FSMContext):
    try:
        state_data = await state.get_data()
        full_name = state_data.get("full_name")
        profession_id = int(state_data.get("profession_id"))
        product_id = int(state_data.get("product_id"))

        if call.data == "SAVE":

            await uc.create_user(user_id=call.from_user.id, full_name=full_name,
                                 profession_id=profession_id, product_id=product_id)

            await call.message.edit_text(text= finish_start_reg_mess(), reply_markup=get_menu_kb())
            await state.clear()

        else:

            await call.message.edit_text(text=bot_init_mess(""))
            await state.clear()
            await state.set_state(CreateUserState.full_name)

    except DBError:
        bot_msg_id = await state.get_value(key="bot_msg_id")
        await call.bot.delete_message(chat_id=call.from_user.id, message_id=call.message_id)
        await state.clear()
        await call.bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=bot_msg_id,
            text=start_db_exc_mess()
        )






