from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from dishka import FromDishka

from src.fsm.states import CreateUserState
from src.services.user_service import UserService
from src.ui.keyboard.actions import MenuCB, MenuStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.text.start_mess import (start_db_exc_mess, bot_init_mess,
                                    bot_menu_mess, finish_start_reg_mess)
from src.utils.db_exc_wrapper import DBError

router = Router()


@router.message(CommandStart())
async def handle_start(msg: Message, svc: FromDishka[UserService], state: FSMContext) -> None:

    if state:
        await state.clear()

    try:

        user = await svc.get_user(msg.from_user.id)
        if user is None:
            await msg.answer(text=bot_init_mess(""))
            await state.set_state(CreateUserState.full_name)
            return

        await msg.answer(text=bot_init_mess(user.full_name), reply_markup=get_menu_kb())

    except DBError:
        await msg.answer(text=start_db_exc_mess())


@router.message(CreateUserState.full_name)
async def handle_full_name(msg: Message, svc: FromDishka[UserService], state: FSMContext) -> None:

    try:

        await svc.create_user(tg_id=msg.from_user.id, full_name=msg.text)
        await msg.answer(text= finish_start_reg_mess(), reply_markup=get_menu_kb())
        await state.clear()

    except DBError:
        await msg.answer(text=start_db_exc_mess())


@router.message(F.text == "/menu")
async def handle_back_menu_command(msg: Message, state: FSMContext) -> None:

    if state:
        await state.clear()

    await msg.answer(text=bot_menu_mess(), reply_markup=get_menu_kb())





