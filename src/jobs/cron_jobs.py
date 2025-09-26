import logging
import time
from datetime import timedelta, date

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.utils.deep_linking import create_start_link

from config import settings
from src.clients.google_sheet_client import update_sheet_data
from src.services.booking_service import BookingService
from src.services.tech_service import TechService
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.booking_remind_mess import build_digest_message
from src.ui.messages.start_mess import bot_menu_mess
from src.utils.db_exc_wrapper import DBError
from src.utils.sheet_name import month_name

logger = logging.getLogger(__name__)


# -------------------------------- Очистка сессий окна бронирования --------------------------------
async def cleanup_booking_session_job(container: AsyncContainer) -> None:
    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: TechService = await req.get(TechService)
        session_limit = int(time.time() - settings.BOOKING_SESSION_SEC)
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


# -------------------------------- Дайджест в чате --------------------------------
async def chat_remind_job(container: AsyncContainer) -> None:
    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: BookingService = await req.get(BookingService)
        session: AsyncSession = await req.get(AsyncSession)

        tomorrow = date.today() + timedelta(days=1)

        try:
            async with session.begin():
                bookings = await svc.get_bookings_for_remind(tomorrow)
                bookings = bookings[0]

                link = await create_start_link(bot, "confirm_today")

                message = await bot.send_message(
                    chat_id=settings.TG_CHAT_ID,
                    text=build_digest_message(bookings),
                    reply_markup=confirm_kb(bookings, link)
                )
                print(message.message_id)

        except DBError as e:
            logger.exception(f"ERROR: chat_remind_job | {str(e)}")


# -------------------------------- Обновление Google-таблицы бронирований --------------------------------
async def sheet_update_job(container: AsyncContainer) -> None:
    async with container() as req:
        svc: BookingService = await req.get(BookingService)

        try:
            for offset in range(3):
                has_changes = await svc.get_booking_changes(offset)
                if has_changes:
                    booking_data = await svc.get_users_month_bookings(offset)
                    as_dict = [u.model_dump() for u in booking_data]
                    sheet_name = month_name(offset)
                    await update_sheet_data(sheet_name, as_dict)

            return
        except DBError as e:
            logger.exception(f"ERROR: sheet_update_job | {str(e)}")










# Уведомление о "завтра", в ПН, ВТ, СР, ЧТ, ВС
    # Джоб, который до конца дня держит список актуальным (запускается и умирает после рассылки в чат)
# Подведение итогов в ПТ
# Уведомление о "завтра" + кол-во свободных мест на неделю в ВС
    # Джоб, который до конца дня держит список актуальным (запускается и умирает после рассылки в чат)
# Джоб для автобронирования




