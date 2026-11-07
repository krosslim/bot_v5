"""Виджеты бронирования: отправка, сборка состояния, обновление chat_data."""
import asyncio
import calendar
import logging
import time
from datetime import date
from typing import Dict, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

from config import Config
from src.infrastructure.telegram.widgets import EditMessageWidgetData, SendWidget
from src.services.feature_flags import FeatureFlags, WidgetsMode
from src.services.tech_service import TechService
from src.dto.user_dto import UserDTO
from src.ui.widgets.layout import BOSS_SEAT, SEATS
from src.ui.widgets.render import render_booking_widget, render_digest_widget
from src.ui.widgets.state import (build_calendar_data, build_day_state, build_digest_data,
                                  build_expired_data, calendar_last_month, shift_month, short_name)
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.get_week_range import week_range
from src.utils.today import effective_today, widget_data_expiry
from src.utils.tz_day import d_tz

logger = logging.getLogger(__name__)

EDIT_INTERVAL_SEC = 1.05   # Telegram: не чаще одной правки chat_data в секунду на сообщение

_pending: Dict[Tuple[int, int], str] = {}
_tasks: Dict[Tuple[int, int], asyncio.Task] = {}
_last_edit: Dict[Tuple[int, int], float] = {}


def _is_not_modified(e: TelegramBadRequest) -> bool:
    return "not modified" in (e.message or "").lower()


async def edit_widget_data(bot: Bot, chat_id: int, message_id: int, chat_data: str) -> None:
    """Немедленная правка. Ошибки, кроме «not modified», пробрасываются."""
    key = (chat_id, message_id)
    wait = _last_edit.get(key, 0) + EDIT_INTERVAL_SEC - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        await bot(EditMessageWidgetData(chat_id=chat_id, message_id=message_id, chat_data=chat_data))
    except TelegramBadRequest as e:
        if not _is_not_modified(e):
            raise
    finally:
        _last_edit[key] = time.monotonic()


def schedule_widget_edit(bot: Bot, chat_id: int, message_id: int, chat_data: str) -> None:
    """Отложенная правка: несколько изменений подряд схлопываются в одну правку с последним состоянием."""
    key = (chat_id, message_id)
    _pending[key] = chat_data
    task = _tasks.get(key)
    if task is None or task.done():
        _tasks[key] = asyncio.create_task(_edit_loop(bot, key))


async def _edit_loop(bot: Bot, key: Tuple[int, int]) -> None:
    try:
        while key in _pending:
            wait = _last_edit.get(key, 0) + EDIT_INTERVAL_SEC - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            data = _pending.pop(key, None)
            if data is None:
                break
            try:
                await edit_widget_data(bot, key[0], key[1], data)
            except TelegramRetryAfter as e:
                _pending.setdefault(key, data)
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                logger.warning("editMessageWidgetData %s | %s", key, e.message)
            except Exception:
                logger.exception("editMessageWidgetData %s failed", key)
    finally:
        _tasks.pop(key, None)
        if len(_last_edit) > 2000:
            border = time.monotonic() - 60
            for k in [k for k, t in _last_edit.items() if t < border]:
                _last_edit.pop(k, None)


class WidgetUseCase:
    def __init__(self, bot: Bot, uc: BookingUseCase, tech: TechService, cfg: Config, flags: FeatureFlags):
        self.bot = bot
        self.uc = uc
        self.tech = tech
        self.cfg = cfg
        self.flags = flags

    # ---------------------------------------------------------------------------#
    #  Окно бронирования
    # ---------------------------------------------------------------------------#
    @staticmethod
    def first_bookable() -> date:
        """Сегодня до WORK_END_HOUR, иначе завтра"""
        return effective_today()

    def horizon(self) -> date:
        """Последний день, на который можно бронировать (как в недельном экране: PAGINATION_LIMIT_WEEKS)"""
        _, sunday, _ = week_range(self.cfg.PAGINATION_LIMIT_WEEKS)
        return sunday

    def in_window(self, cal_date: date) -> bool:
        return self.first_bookable() <= cal_date <= self.horizon()

    async def is_bookable(self, cal_date: date) -> bool:
        """В окне бронирования и рабочий день (выходные и праздники закрыты даже для запроса в обход календаря)"""
        return self.in_window(cal_date) and await self.uc.is_workday(cal_date)

    # ---------------------------------------------------------------------------#
    #  Состояние
    # ---------------------------------------------------------------------------#
    async def calendar_data(self, user_id: int) -> str:
        """Календарь от history_months месяцев назад до future_months месяцев вперёд (настройки виджетов в админке; не короче горизонта
        бронирования). Прошлые дни — только просмотр, дни после горизонта серые: бронь на них ещё не открыта"""
        today, horizon = d_tz(), self.horizon()
        history = self.flags.widgets.history_months
        future = self.flags.widgets.future_months
        start = shift_month(today, -history)
        last = calendar_last_month(today, horizon, future)
        end = date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
        days = await self.uc.widget_calendar(user_id, start, end)
        return build_calendar_data(days, today, self.first_bookable(), horizon, history, widget_data_expiry(), future)

    async def day_state(
            self, cal_date: date, subject_id: int, subject_name: str, self_view: bool,
            ok: Optional[str] = None, er: Optional[str] = None,
    ) -> str:
        day, is_workday = await self.uc.widget_day(cal_date)
        readonly = not (is_workday and self.in_window(cal_date))
        return build_day_state(day, SEATS, subject_id, subject_name, self_view, readonly, ok, er, today=d_tz())

    # ---------------------------------------------------------------------------#
    #  Руководитель на схеме и полные имена по нажатию на место
    # ---------------------------------------------------------------------------#
    async def boss(self) -> Optional[UserDTO]:
        """Сотрудник, выбранный в «Меню админа → Виджеты». Удалённый или неактивный — как не выбран"""
        boss_id = self.flags.widgets.boss_id
        user = await self.uc.user_or_none(boss_id) if boss_id else None
        return user if user and user.is_active else None

    async def boss_label(self) -> str:
        """Подпись на месте руководителя, вшивается в HTML при отправке виджета"""
        boss = await self.boss()
        return short_name(boss.full_name) if boss else ""

    async def seat_holder_name(self, cal_date: date, seat: int | str) -> Optional[str]:
        """Полное имя на месте: руководитель или тот, кто забронировал. None — место свободно"""
        if seat == BOSS_SEAT:
            boss = await self.boss()
            return boss.full_name if boss else None
        day, _ = await self.uc.widget_day(cal_date)
        holder = day.by_seat().get(seat)
        return holder.full_name if holder else None

    async def digest_data(self, cal_date: date) -> str:
        day, _ = await self.uc.widget_day(cal_date)
        return build_digest_data(day, SEATS, closed=cal_date < self.first_bookable())

    # ---------------------------------------------------------------------------#
    #  Личный виджет
    # ---------------------------------------------------------------------------#
    async def send_booking_widget(
            self, chat_id: int, owner_id: int, target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> Message:
        """Отправить календарь. target_* — бронь админом за сотрудника. Старый виджет в чате удаляется."""
        old = await self.tech.get_booking_widget(chat_id)
        message = await self.bot(SendWidget(
            chat_id=chat_id,
            html=render_booking_widget(target_id, target_name, await self.boss_label()),
            allow_queries=True,
            chat_data=await self.calendar_data(target_id or owner_id),
        ))
        await self.tech.set_booking_widget(chat_id, message.message_id, target_id)
        if old and old.message_id != message.message_id:
            await self.remove_message(chat_id, old.message_id)
        return message

    async def reopen_booking_widget(
            self, chat_id: int, owner_id: int, tapped_id: int,
            target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> None:
        """«Открыть заново» в устаревшем окне: свежий виджет новым сообщением.
        send_booking_widget удаляет окно из указателя; нажатое окно удаляем отдельно, если это не оно"""
        old = await self.tech.get_booking_widget(chat_id)
        message = await self.send_booking_widget(chat_id, owner_id, target_id, target_name)
        if tapped_id not in (message.message_id, old.message_id if old else None):
            await self.remove_message(chat_id, tapped_id)

    async def remove_message(self, chat_id: int, message_id: int) -> None:
        """Удалить сообщение; если Telegram не дал (например, старше 48 часов) — пометить виджет устаревшим"""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError as e:
            logger.info("remove_message %s/%s | %s", chat_id, message_id, e)
            schedule_widget_edit(self.bot, chat_id, message_id, build_expired_data())

    async def close_booking_widget(self, chat_id: int, message_id: int) -> None:
        """Кнопка «Выйти»: виджет удаляется, бот его больше не обновляет"""
        await self.remove_message(chat_id, message_id)
        pointer = await self.tech.get_booking_widget(chat_id)
        if pointer and pointer.message_id == message_id:
            await self.tech.clear_booking_widget(chat_id)

    async def refresh_booking_message(self, chat_id: int, message_id: int, subject_id: int) -> None:
        schedule_widget_edit(self.bot, chat_id, message_id, await self.calendar_data(subject_id))

    async def refresh_user_widget(self, user_id: int) -> None:
        """Обновить открытый виджет пользователя в его личном чате (бронь изменилась вне виджета)"""
        if self.flags.widgets_mode == WidgetsMode.OFF:
            return
        pointer = await self.tech.get_booking_widget(user_id)
        if pointer and (pointer.target_id or user_id) == user_id:
            await self.refresh_booking_message(user_id, pointer.message_id, user_id)

    # ---------------------------------------------------------------------------#
    #  Дайджест
    # ---------------------------------------------------------------------------#
    async def send_digest(self, cal_date: date) -> Message:
        return await self.bot(SendWidget(
            chat_id=self.cfg.TG_CHAT_ID,
            html=render_digest_widget(await self.boss_label()),
            allow_queries=True,
            chat_data=await self.digest_data(cal_date),
        ))

    async def refresh_digest(self, cal_date: date) -> None:
        if not self.flags.digest_widget:
            return
        message_id = await self.uc.digest_message_id(cal_date)
        if message_id:
            schedule_widget_edit(self.bot, self.cfg.TG_CHAT_ID, message_id, await self.digest_data(cal_date))

    async def edit_digest_now(self, cal_date: date, message_id: int) -> None:
        """Для задач по расписанию: «сообщение удалено» и прочие ошибки пробрасываются вызывающему"""
        await edit_widget_data(self.bot, self.cfg.TG_CHAT_ID, message_id, await self.digest_data(cal_date))
