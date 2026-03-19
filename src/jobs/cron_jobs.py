import asyncio
import logging
import time as time_func
from datetime import timedelta, date, datetime, time
from functools import partial
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from src.clients.google_sheet_client import update_sheet_data
from src.dto.booking_dto import BookingStatus
from src.handlers.user.booking_handler import promote_user_after_cancel
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.services.tech_service import TechService
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.keyboard.confirm_remind_kb import remind_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb, check_bookings_kb
from src.ui.keyboard.week_result_kb import week_summary_kb
from src.ui.messages.booking_remind_mess import build_digest_message_v2
from src.ui.messages.confirm_to_remind_mess import remind_mess
from src.ui.messages.settings_mess import visit_plan_report_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.ui.messages.week_result_mess import week_summary_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.user_use_case import UserUseCase
from src.utils.get_week_range import week_range
from src.utils.tz_day import d_tz, dt_tz
from src.utils.db_exc_wrapper import DBError
from src.utils.sheet_name import month_name
from src.utils.today import effective_datetime_range
from src.utils.tommorow import fmt_date_ru

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
                logger.error(str(e))
                await svc.finish_booking_session(f"{session.user_id}:{session.message_id}")
            except Exception as e:
                logger.exception(f"ERROR: cleanup_booking_session_job | {str(e)}")


# -------------------------------- Дайджест в чате --------------------------------
async def chat_remind_job(container: AsyncContainer, sched: AsyncIOScheduler, postponed: bool = False) -> None:

    logger.info("chat_remind_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    # Для воскресенья переносим уведомление на 2:30ч вперед. Люди отдыхают
    today_weekday = d_tz().weekday()
    if today_weekday == 6 and not postponed:
        logger.info("chat_remind_job | postponed")
        _add_postponed_sunday_chat_remind_job(container, sched)
        return

    async with container() as req:
        bot: Bot = await req.get(Bot)
        booking_svc: BookingService = await req.get(BookingService)
        capacity_svc: OfficeCapacityService = await req.get(OfficeCapacityService)
        sc_svc: TechService = await req.get(TechService)
        cal_date_svc: CalendarDatesService = await req.get(CalendarDatesService)

        tomorrow = d_tz(delta=1)
        weekday = tomorrow.isoweekday()

        try:
            is_workday = await cal_date_svc.is_workday(tomorrow)
            if not is_workday:
                logger.info("chat_remind_job | tomorrow is not workday")
                return

            bookings = await booking_svc.get_bookings_for_remind(tomorrow)
            if bookings:
                bookings = bookings[0]
            capacity = await capacity_svc.get_weekday_capacity(weekday)

            last_message = await sc_svc.last_message()

            message = await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=build_digest_message_v2(bookings, capacity, tomorrow),
                reply_markup=confirm_kb(bookings, capacity, tomorrow),
                disable_web_page_preview=True
            )
            await bot.pin_chat_message(chat_id=settings.TG_CHAT_ID, message_id=message.message_id, disable_notification=True)
            if last_message:
                await _unpin_last_message(bot, last_message.message_id)
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
                logger.error(f"ERROR: check_chat_remind_job | {str(e)}")
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

    # Если перезапустим приложение в воскресенье, то актуализировать нужно еще одну задачу
    # Так как у нас стоит настройка replace_existing=True, то не важно в какое время мы перезапускаем
    # Задача все равно перезапишется и не будет дубля
    if today_date.weekday() == 6:
        _add_postponed_sunday_chat_remind_job(container, sched)


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

            if end_dt < start_dt:
                logger.info("check_chat_remind_reserve_job | removed cause end_dt (%s) < start_dt (%s)"
                            " for cal_date %s", start_dt, end_dt, message.cal_date)
                return


            _add_job_checker(sched, container, start_dt, end_dt)

        except DBError as e:
            logger.exception(f"ERROR: check_chat_remind_reserve_job | {str(e)}")


# -------------------------------- Пятничное/субботнее подведение итогов --------------------------------
async def week_result_job(container: AsyncContainer, sched: AsyncIOScheduler) -> None:

    logger.info("week_result_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: BookingService = await req.get(BookingService)
        cal_date_svc: CalendarDatesService = await req.get(CalendarDatesService)

        today = d_tz()
        start = today - timedelta(days=today.weekday())
        tomorrow = d_tz(delta=1)

        if today.isoweekday() == 5:
            # Проверка для пятницы:
            # 1. суббота рабочий день
            # 2. сегодня не рабочий день
            today_is_workday = await cal_date_svc.is_workday(today)
            tomorrow_is_workday = await cal_date_svc.is_workday(tomorrow)
            if tomorrow_is_workday or not today_is_workday:
                logger.info("week_result_job | skipped | tomorrow_is_workday - %s, today_is_workday - %s",
                            tomorrow_is_workday, today_is_workday)
                return
            end = start + timedelta(days=4)
        else:
            # Проверка для субботы поэтому today (в else тк в расписании fri, sat)
            today_is_workday = await cal_date_svc.is_workday(today)
            if not today_is_workday:
                logger.info("week_result_job | skipped | today_is_workday - %s",today_is_workday)
                return
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

            _add_head_report(sched, container)

            logger.info("week_result_job | finished at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

        except DBError as e:
            logger.exception(f"ERROR: week_result_job | {str(e)}")


# -------------------------------- Обновление Google-таблицы бронирований --------------------------------
async def sheet_update_job(container: AsyncContainer) -> None:
    async with container() as req:
        svc: BookingService = await req.get(BookingService)

        try:
            for offset in range(-1, 3):
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


# -------------------------------- Напоминание о подтверждении брони --------------------------------
async def remind_to_confirm_booking_job(container: AsyncContainer) -> None:

    now = datetime.now(tz=ZoneInfo(settings.MSC_TZ))
    logger.info("remind_to_confirm_booking_job | started at %s", now)

    today_weekday = now.weekday()
    # Если сегодня воскресенье, то первое уведомление в 18:30 не отправляем
    if today_weekday == 6 and now.hour == settings.CONFIRM_REMIND_JOB_HOUR:
        logger.info("remind_to_confirm_booking_job | skipped cause today is sunday")
        return


    async with container() as req:
        bot: Bot = await req.get(Bot)
        svc: BookingService = await req.get(BookingService)

        tomorrow = d_tz(delta=1)
        # print(f"определяем завтрашний день: {tomorrow}")

        reserved_bookings = await svc.get_bookings_by_status(tomorrow, tomorrow, BookingStatus.BOOKED, BookingStatus.RESERVED)
        # print(f"получаем брони со статусом RESERVED: {reserved_bookings}")
        # print()

        if not reserved_bookings:
            logger.info("remind_to_confirm_booking_job | no data for %s", tomorrow)
            return

        reserved_bookings = reserved_bookings[0]
        # print(f"брони есть, извлекаем данные для {tomorrow}: {reserved_bookings}")
        # print()

        if not reserved_bookings.users:
            logger.info("remind_to_confirm_booking_job | no users to confirm for %s", tomorrow)
            return

        current_hour = datetime.now(tz=ZoneInfo(settings.MSC_TZ)).hour
        # print(f"получаем текущий час для определения текста сообщения: {current_hour}")
        if current_hour == settings.CONFIRM_REMIND_JOB_HOUR:
            message_text = remind_mess(escalation=False)
        elif current_hour == settings.CONFIRM_REMIND_REPEAT_JOB_HOUR:
            message_text = remind_mess(escalation=True)
        else:
            logger.info("remind_to_confirm_booking_job | time has not got registartion (input: %s)",
                        current_hour)
            return

        success = fail = 0

        for users in reserved_bookings.users:
            try:
                await bot.send_message(
                    chat_id=users.user_id,
                    text=message_text,
                    reply_markup=remind_kb(tomorrow)
                )
                success += 1
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                logger.error(f"remind_to_confirm_booking_job | Failed to send to user {users.user_id}: {str(e)}")
                fail += 1

        logger.info("remind_to_confirm_booking_job | finished at %s | users count is %s | success %s | fail %s",
                    datetime.now(tz=ZoneInfo(settings.MSC_TZ)), len(reserved_bookings.users), success, fail
                    )


# -------------------------------- Отменить все брони зависшие в очереди --------------------------------
async def cancel_waitlist_bookings_job(container: AsyncContainer) -> None:
    logger.info("cancel_waitlist_bookings_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        svc: BookingService = await req.get(BookingService)
        session: AsyncSession = await req.get(AsyncSession)

        try:
            async with session.begin():
                res = await svc.update_booking_status(
                    d_tz(),
                    BookingStatus.WAITLISTED,           # текущий
                    BookingStatus.WAITLISTED_MANUAL,
                    BookingStatus.CANCELED,             # Новый
                    BookingStatus.CANCELED_NO_SPOTS_WAITLIST
                )
                logger.info("cancel_waitlist_bookings_job | updated_count=%s", res)
        except DBError as e:
            logger.exception(f"ERROR: cancel_waitlist_job | {str(e)}")


# -------------------------------- Отмена не подтвержденных бронирований --------------------------------
async def cancel_not_confirmed_booking_job(container: AsyncContainer) -> None:

    logger.info("cancel_not_confirmed_booking_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        uc: BookingUseCase = await req.get(BookingUseCase)
        bot: Bot = await req.get(Bot)

        tomorrow = d_tz(delta=1)
        # print(f"определяем завтрашний день: {tomorrow}")

        reserved = await uc.bookings_by_status(
            tomorrow,
            tomorrow,
            BookingStatus.BOOKED,
            BookingStatus.RESERVED
        )
        # print(f"получаем брони со статусом RESERVED: {reserved}")
        # print()

        if not reserved:
            logger.info("cancel_not_confirmed_booking_job | no data for %s", tomorrow)
            return

        reserved = reserved[0]
        # print(f"брони есть, извлекаем данные для {tomorrow}: {reserved}")
        # print()

        if not reserved.users:
            logger.info("cancel_not_confirmed_booking_job | no users to confirm for %s", tomorrow)
            return

        for user in reserved.users:
            await promote_user_after_cancel(
                call=None,
                uc=uc,
                cal_date=tomorrow,
                bot=bot,
                user_id=user.user_id,
                cancel_sub_status=BookingStatus.CANCELED_NOT_CONFIRMED
            )
            await _send_cancel_message(
                bot=bot,
                user_id=user.user_id,
                cal_date=tomorrow
            )

        logger.info("cancel_not_confirmed_booking_job | total_count=%s", len(reserved.users))


# -------------------------------- Рассылка статистики лиду --------------------------------
async def head_report_job(container: AsyncContainer) -> None:

    logger.info("head_report_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        uc: UserUseCase = await req.get(UserUseCase)
        bot: Bot = await req.get(Bot)

        try:
            success = fail = 0
            lead_list = await uc.get_users(100, 0, None, True)
            monday, sunday, _ = week_range(0, False)

            for lead in lead_list:
                try:
                    employee_list = await uc.visit_plan_report(monday, sunday, lead.profession_id)
                    await bot.send_message(
                        chat_id=lead.user_id,
                        text=visit_plan_report_mess(employee_list, monday, sunday, False)
                    )
                    success += 1
                except (TelegramForbiddenError, TelegramBadRequest, DBError) as e:
                    logger.error(f"head_report_job | Failed to send to user {lead.user_id}: {str(e)}")
                    fail += 1

            logger.info("head_report_job | finished at %s | success %s | fail %s",
                        datetime.now(tz=ZoneInfo(settings.MSC_TZ)), success, fail)
        except DBError as e:
            logger.info("head_report_job | finished at %s | fail all cause %s",
                        datetime.now(tz=ZoneInfo(settings.MSC_TZ)), str(e))


# -------------------------------- Поздравление с днем рождения --------------------------------
async def birthday_job(container: AsyncContainer) -> None:

    logger.info("birthday_job | started at %s", datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

    async with container() as req:
        uc: UserUseCase = await req.get(UserUseCase)
        bot: Bot = await req.get(Bot)

        try:
            today = d_tz(delta=0)
            employee_list = await uc.get_users(100, 0, None, None, today)

            if not employee_list:
                logger.info("birthday_job | no data for %s", today)
                return

            mentions = [
                f'<a href="tg://user?id={u.user_id}">{u.full_name}</a>'
                for u in employee_list
            ]
            names_str = ", ".join(mentions)

            await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=f"<b>{names_str}, С днем рождения! 🎁</b>"
            )

            logger.info("birthday_job | finished at %s",
                        datetime.now(tz=ZoneInfo(settings.MSC_TZ)))

        except (TelegramForbiddenError, TelegramBadRequest, DBError) as e:
            logger.info("birthday_job | finished at %s | fail all cause %s",
                        datetime.now(tz=ZoneInfo(settings.MSC_TZ)), str(e))


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


async def _send_cancel_message(bot: Bot, user_id: int, cal_date: date) -> None:

    str_date = fmt_date_ru(cal_date)

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"<b>❗️ {str_date} → Бронь отменена</b>\n\n"
                 f"<blockquote>К сожалению, мы так и не получили подтверждение о завтрашней записи.\n"
                 f"Поэтому она была автоматически отменена. "
                 f"Если места еще остались, ты можешь попробовать занять.\nНовую запись подтверждать не придется</blockquote>",
            reply_markup=check_bookings_kb()
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e_tg:
        logger.error(f"Не удалось отправить сообщение {user_id} | {str(e_tg)}")


async def _unpin_last_message(bot: Bot, last_message_id: int) -> None:
    try:
        await bot.unpin_chat_message(chat_id=settings.TG_CHAT_ID, message_id=last_message_id)
    except TelegramBadRequest:
        return


def _add_postponed_sunday_chat_remind_job(
        container: AsyncContainer,
        sched: AsyncIOScheduler
) -> None:
    run_dt = (datetime.now(ZoneInfo(settings.MSC_TZ)).replace(
        hour=settings.REMIND_JOB_HOUR,
        minute=settings.REMIND_JOB_MINUTES,
        second=0,
        microsecond=0
    ) + timedelta(hours=2, minutes=31))

    now = datetime.now(tz=ZoneInfo(settings.MSC_TZ))

    # Если время планируемого запуска меньше текущего,
    # то задачу ставить не нужно, так как она скорее всего уже выполнилась
    # Например: сегодня воскресенье, я перезапускаю апп после 16:00 (задачу ставим)
    # Я перезапускаю до 12:00 (задачу ставим). Я перезапускаю после 19:00 (НЕ ставим)
    # - так как время запуска должно быть 18:30
    if run_dt < now:
        logger.info("chat_remind_job | will not run cause run_dt (%s) < now (%s)", run_dt, now)
        return

    sched.add_job(
        partial(chat_remind_job, container, sched, True),
        trigger='date',
        id="chat_remind_sunday_job",
        run_date=run_dt,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True
    )
    logger.info("chat_remind_job | will run at %s", run_dt)


def _add_head_report(
        sched: AsyncIOScheduler,
        container: AsyncContainer
) -> None:

    run_dt = dt_tz() + timedelta(minutes=1)

    sched.add_job(
        partial(head_report_job, container),
        trigger='date',
        id="head_report_job",
        run_date=run_dt,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True
    )
    logger.info("head_report_job | will run at %s", run_dt)
