from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import settings as s


router = Router()

@router.message(F.pinned_message, F.chat.id == s.TG_CHAT_ID)
async def handle_pinned_system_message(msg: Message):
    try:
        if not msg.from_user.is_bot:
            return
        await msg.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
    except (TelegramForbiddenError, TelegramBadRequest):
        return