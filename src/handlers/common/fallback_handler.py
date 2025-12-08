import logging

from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()

logger = logging.getLogger(__name__)

@router.callback_query()
async def handle_unknown_callback(call: CallbackQuery):

    logger.warning("Неизвестный callback: %s", call.data)

    await call.answer(text="Сессия устарела или сценарий больше не активен!\nВведите команду\n/start",
                      show_alert=True)
