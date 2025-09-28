import asyncio
import logging
import time as time_func
from datetime import timedelta, date, datetime, time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from dishka import AsyncContainer

from config import settings
from src.clients.google_sheet_client import update_sheet_data
from src.services.booking_service import BookingService
from src.services.office_capacity_service import OfficeCapacityService
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
        session_limit = int(time_func.time() - settings.BOOKING_SESSION_SEC)
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
        booking_svc: BookingService = await req.get(BookingService)
        capacity_svc: OfficeCapacityService = await req.get(OfficeCapacityService)
        sc_svc: TechService = await req.get(TechService)

        tomorrow = date.today() + timedelta(days=1)
        weekday = tomorrow.isoweekday()

        try:
            bookings = await booking_svc.get_bookings_for_remind(tomorrow)
            if bookings:
                bookings = bookings[0]
            capacity = await capacity_svc.get_weekday_capacity(weekday)

            message = await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=build_digest_message(bookings, capacity, tomorrow),
                reply_markup=confirm_kb(bookings, capacity, tomorrow)
            )
            # print(message.message_id)
            await sc_svc.upsert_chat_message_id(message.message_id)

        except DBError as e:
            logger.exception(f"ERROR: chat_remind_job | {str(e)}")


# -------------------------------- Проверка актуальность сообщения в чате --------------------------------
async def check_chat_remind_job(container: AsyncContainer) -> None:
    async with container() as req:
        bot: Bot = await req.get(Bot)
        booking_svc: BookingService = await req.get(BookingService)
        capacity_svc: OfficeCapacityService = await req.get(OfficeCapacityService)
        sc_svc: TechService = await req.get(TechService)

        now = datetime.now()

        # Смысл: если щас от 16-23 значит чекать надо данные для завтрашнего дня. Если 0-12 то сегодняшнего
        if time(16, 0) <= now.time() <= time(23, 59, 59):
            target_date = (now + timedelta(days=1)).date()
            # print(f'Выбран завтрашний день: {target_date}')
        else:
            target_date = now.date()
            # print(f'Выбран сегодняшний день: {target_date}')

        try:
            check_updates = await booking_svc.get_booking_changes_for_day(target_date)
            # print(f'Наличие изменений: {check_updates}')

            if not check_updates:
                # print('Изменений нет. Останавливаемся')
                return

            weekday = target_date.isoweekday()
            # print(f'День недели (число): {weekday}')

            bookings = await booking_svc.get_bookings_for_remind(target_date)
            # print(f'Получаем бронирования: {bookings}')
            if bookings:
                # print(f'Бронирования есть. Извлекаем их из массива: {bookings}')
                bookings = bookings[0]
            capacity = await capacity_svc.get_weekday_capacity(weekday)
            # print(f'Получаем вместительность для {target_date}: {capacity}')

            message_id = await sc_svc.get_chat_message_id()
            # print(f'Получаем id сообщения в чате для {target_date}: {message_id}')

            if not message_id:
                # print('Сообщения нет. Создаем его в чате и сохраняем id в базе')
                message = await bot.send_message(
                    chat_id=settings.TG_CHAT_ID,
                    text=build_digest_message(bookings, capacity, target_date),
                    reply_markup=confirm_kb(bookings, capacity, target_date)
                )
                await sc_svc.upsert_chat_message_id(message.message_id)
                return

            try:
                # print('Сообщение есть, пытаемся исправить его')
                await bot.edit_message_text(
                    chat_id=settings.TG_CHAT_ID,
                    message_id=message_id,
                    text=build_digest_message(bookings, capacity, target_date),
                    reply_markup=confirm_kb(bookings, capacity, target_date)
                )
                return
            except TelegramBadRequest as e:
                # print('Сообщение в базе есть, но не удалось его отредактировать')
                logger.exception(f"ERROR: check_chat_remind_job | {str(e)}")
                if "message to edit not found" in e.message:
                    # print('Сообщение в базе есть, но админ удалил его. Поэтому создаем новое')
                    message = await bot.send_message(
                        chat_id=settings.TG_CHAT_ID,
                        text=build_digest_message(bookings, capacity, target_date),
                        reply_markup=confirm_kb(bookings, capacity, target_date)
                    )
                    await sc_svc.upsert_chat_message_id(message.message_id)
                    return
                else:
                    # print('Сообщение в базе есть, но с предыдущего раза оно не обновлялось')
                    return

        except DBError as e:
            # print('Ошибка базы данных')
            logger.exception(f"ERROR: check_chat_remind_job | {str(e)}")
            return


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
                    await asyncio.sleep(3)

            return
        except DBError as e:
            logger.exception(f"ERROR: sheet_update_job | {str(e)}")



# Подведение итогов в ПТ
# Джоб для автобронирования




