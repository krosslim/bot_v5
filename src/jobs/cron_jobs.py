import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from dishka import AsyncContainer

from src.services.tech_service import TechService
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.text.start_mess import bot_menu_mess

logger = logging.getLogger(__name__)


async def cleanup_booking_session_job(
        container: AsyncContainer,
) -> None:
    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: TechService = await req.get(TechService)

        session_limit = int(time.time() - 60)  # время сессии 5 мин

        users = await svc.get_booking_session(session_limit)

        if not users:
            return

        for session in users:
            try:
                await bot.edit_message_text(
                    text=bot_menu_mess(),
                    chat_id=session.user_id,
                    message_id=session.message_id,
                    reply_markup=get_menu_kb()
                )
                await svc.finish_booking_session(f"{session.user_id}:{session.message_id}")
            except TelegramBadRequest as e:
                logger.exception(str(e))
                await svc.finish_booking_session(f"{session.user_id}:{session.message_id}")
            except Exception as e:
                logger.exception(f"ERROR: cleanup_booking_session_job | {str(e)}")




