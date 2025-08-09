from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query()
async def handle_unknown_callback(call: CallbackQuery):

    await call.answer(text="Сессия устарела или сценарий больше не активен!\nВведите команду\n/start",
                      show_alert=True)