import asyncio
import logging
import time as time_func
from datetime import timedelta, date, datetime, time
from functools import partial
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dishka import AsyncContainer

from config import settings
from src.clients.google_sheet_client import update_sheet_data
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.services.tech_service import TechService
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.week_result_kb import week_summary_kb
from src.ui.messages.booking_remind_mess import build_digest_message_v2
from src.ui.messages.start_mess import bot_menu_mess
from src.ui.messages.week_result_mess import week_summary_mess
from src.utils.db_exc_wrapper import DBError
from src.utils.sheet_name import month_name
from src.utils.today import effective_datetime_range

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
async def chat_remind_job(container: AsyncContainer, sched: AsyncIOScheduler) -> None:

    logger.info("chat_remind_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        bot: Bot = await req.get(Bot)
        booking_svc: BookingService = await req.get(BookingService)
        capacity_svc: OfficeCapacityService = await req.get(OfficeCapacityService)
        sc_svc: TechService = await req.get(TechService)
        cal_date_svc: CalendarDatesService = await req.get(CalendarDatesService)

        tomorrow = date.today() + timedelta(days=1)
        weekday = tomorrow.isoweekday()

        try:
            is_workday = await cal_date_svc.is_workday(tomorrow)
            if not is_workday:
                # print("hui")
                return

            bookings = await booking_svc.get_bookings_for_remind(tomorrow)
            if bookings:
                bookings = bookings[0]
            capacity = await capacity_svc.get_weekday_capacity(weekday)

            message = await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=build_digest_message_v2(bookings, capacity, tomorrow),
                reply_markup=confirm_kb(bookings, capacity, tomorrow),
                disable_web_page_preview=True
            )
            # print(message.message_id)
            await sc_svc.upsert_chat_message_id(cal_date=tomorrow, message_id=message.message_id)

            logger.info("chat_remind_job | finished at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

            # print("Регистрируем задачу для апдейтов каждую минуту")
            start, end = effective_datetime_range()
            # print(f"Период пинга: от {start} до {end} каждую минуту")
            _add_job_checker(sched, container, start, end)

        except DBError as e:
            logger.exception(f"ERROR: chat_remind_job | {str(e)}")


# -------------------------------- Проверка актуальность сообщения в чате --------------------------------
async def check_chat_remind_job(container: AsyncContainer) -> None:

    # logger.info("check_chat_remind_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        bot: Bot = await req.get(Bot)
        booking_svc: BookingService = await req.get(BookingService)
        capacity_svc: OfficeCapacityService = await req.get(OfficeCapacityService)
        sc_svc: TechService = await req.get(TechService)

        now = datetime.now(tz=ZoneInfo(settings.MSC_TZ))

        # Смысл: если щас от 16-23 значит чекать надо данные для завтрашнего дня. Если 0-12 то сегодняшнего
        if time(settings.REMIND_JOB_HOUR, settings.REMIND_JOB_MINUTES) <= now.time() <= time(23, 59, 59):
            target_date = (now + timedelta(days=1)).date()
            # print(f'Выбран завтрашний день: {target_date}')
        else:
            target_date = now.date()
            # print(f'Выбран сегодняшний день: {target_date}')

        try:
            updates = await booking_svc.get_booking_changes_for_day(target_date)
            # print(f'Наличие изменений: {check_updates}')

            if not updates:
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

            message_id = await sc_svc.get_chat_message_id(cal_date=target_date)
            # print(f'Получаем id сообщения в чате для {target_date}: {message_id}')

            if not message_id:
                # print('Сообщения нет. Создаем его в чате и сохраняем id в базе')
                message = await bot.send_message(
                    chat_id=settings.TG_CHAT_ID,
                    text=build_digest_message_v2(bookings, capacity, target_date),
                    reply_markup=confirm_kb(bookings, capacity, target_date),
                    disable_web_page_preview=True
                )
                await sc_svc.upsert_chat_message_id(cal_date=target_date, message_id=message.message_id)
                return

            try:
                # print('Сообщение есть, пытаемся исправить его')
                await bot.edit_message_text(
                    chat_id=settings.TG_CHAT_ID,
                    message_id=message_id,
                    text=build_digest_message_v2(bookings, capacity, target_date),
                    reply_markup=confirm_kb(bookings, capacity, target_date),
                    disable_web_page_preview=True
                )
                return
            except TelegramBadRequest as e:
                # print('Сообщение в базе есть, но не удалось его отредактировать')
                logger.exception(f"ERROR: check_chat_remind_job | {str(e)}")
                if "message to edit not found" in e.message:
                    # print('Сообщение в базе есть, но админ удалил его. Поэтому создаем новое')
                    message = await bot.send_message(
                        chat_id=settings.TG_CHAT_ID,
                        text=build_digest_message_v2(bookings, capacity, target_date),
                        reply_markup=confirm_kb(bookings, capacity, target_date),
                        disable_web_page_preview=True
                    )
                    await sc_svc.upsert_chat_message_id(cal_date=target_date, message_id=message.message_id)
                    return
                else:
                    # print('Сообщение в базе есть, но с предыдущего раза оно не обновлялось')
                    return

        except DBError as e:
            # print('Ошибка базы данных')
            logger.exception(f"ERROR: check_chat_remind_job | {str(e)}")
            return


# -------------------------------- Job health чекер --------------------------------
async def check_chat_remind_reserve_job(container: AsyncContainer, sched: AsyncIOScheduler) -> None:

    now = datetime.now(tz=ZoneInfo(settings.MSC_TZ))
    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)
    if settings.WORK_END_HOUR <= now.hour < settings.REMIND_JOB_HOUR:
        logger.info("check_chat_remind_reserve_job | removed cause not in work hour")
        return

    async with container() as req:
        sc_svc: TechService = await req.get(TechService)

        try:
            message = await sc_svc.last_message()
            if not message:
                logger.info("check_chat_remind_reserve_job | removed cause where are no message data")
                return

            start_dt = now + timedelta(minutes=1)

            if message.cal_date == today_date:
                end_dt = datetime.combine(
                    date=today_date,
                    time=time(settings.WORK_END_HOUR, 0),
                    tzinfo=ZoneInfo(settings.MSC_TZ)
                )
            elif message.cal_date == tomorrow_date:
                end_dt = datetime.combine(
                    date=tomorrow_date,
                    time=time(settings.WORK_END_HOUR, 0),
                    tzinfo=ZoneInfo(settings.MSC_TZ)
                )
            else:
                logger.info("check_chat_remind_reserve_job | removed cause now %s and message cal_date %s",
                            now, message.cal_date)
                return

            _add_job_checker(sched, container, start_dt, end_dt)

        except DBError as e:
            logger.exception(f"ERROR: check_chat_remind_reserve_job | {str(e)}")


# -------------------------------- Пятничное/субботнее подведение итогов --------------------------------
async def week_result_job(container: AsyncContainer) -> None:

    logger.info("week_result_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: BookingService = await req.get(BookingService)
        cal_date_svc: CalendarDatesService = await req.get(CalendarDatesService)

        # если суббота рабочий день (джоб чекает если завтра рабочий день, то не запускается)
        tomorrow = date.today() + timedelta(days=1)
        is_workday = await cal_date_svc.is_workday(tomorrow)
        if is_workday:
            # print("hui")
            return

        today = date.today()
        start = today - timedelta(days=today.weekday())

        # Если последний рабочий день пт, то плюсуем 4 иначе 5
        if today.isoweekday() == 5:
            end = start + timedelta(days=4)
        else:
            end = start + timedelta(days=5)

        try:
            res = await svc.week_visits(start, end)
            max_visitors = await svc.week_max(start, end)
            await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=week_summary_mess(res, max_visitors),
                reply_markup=week_summary_kb(),
                disable_web_page_preview=True
            )
        except DBError as e:
            logger.exception(f"ERROR: week_result_job | {str(e)}")


# -------------------------------- Обновление Google-таблицы бронирований --------------------------------
async def sheet_update_job(container: AsyncContainer) -> None:
    async with container() as req:
        svc: BookingService = await req.get(BookingService)

        try:
            for offset in range(3):
                has_changes = await svc.get_booking_changes(offset)
                # print(f"Наличие изменений: {has_changes}")
                if has_changes:
                    # print()
                    booking_data = await svc.get_users_month_bookings(offset)
                    # print(f"Данные: {booking_data}")
                    # print("---------")
                    sheet_name = month_name(offset)
                    # print(f"Месяц: {sheet_name}")
                    # print()
                    await update_sheet_data(sheet_name, booking_data)
                    await asyncio.sleep(1.5)

            return
        except DBError as e:
            logger.exception(f"ERROR: sheet_update_job | {str(e)}")


# -------------------------------- helpers --------------------------------
def _add_job_checker(
        sched: AsyncIOScheduler,
        container: AsyncContainer,
        start: datetime,
        end: datetime
) -> None:

    sched.add_job(
        partial(check_chat_remind_job, container),
        trigger=CronTrigger(
            minute="*",
            start_date=start,
            end_date=end,
            timezone=sched.timezone
        ),
        id="check_chat_remind_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True
    )

    logger.info("register job: check_chat_remind_job | start: %s, end: %s", start, end)


# TODO
#     JOBS
#             1. Напоминание о бронировании в 18:30, 21:00
#             2. Отмена всех не подтвержденных броней





