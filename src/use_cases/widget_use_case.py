"""Окно бронирования в личке (виджет или Rich-календарь) и дайджест-виджет: отправка, сборка состояния,
обновление при изменении брони вне окна."""
import asyncio
import calendar
import json
import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound, TelegramRetryAfter
from aiogram.methods import EditMessageText, SendRichMessage
from aiogram.types import InputRichMessage, Message

from config import Config
from src.dto.user_dto import BookingWidgetPointerDTO, UserDTO
from src.infrastructure.telegram.rich import emoji_ids, missing_emoji
from src.infrastructure.telegram.widgets import EditMessageWidgetData, SendWidget
from src.services.feature_flags import BookingUi, FeatureFlags
from src.services.tech_service import TechService
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.start_mess import bot_menu_mess
from src.ui.rich.booking import Person, render_calendar, render_day
from src.ui.widgets.layout import BOSS_SEAT, SEATS
from src.ui.widgets.render import render_booking_widget, render_digest_widget
from src.ui.widgets.state import (build_calendar_data, build_day_state, build_digest_data,
                                  build_expired_data, calendar_last_month, day_code, shift_month, short_name)
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.get_week_range import week_range
from src.utils.today import confirm_deadline, effective_today, widget_data_expiry
from src.utils.tz_day import d_tz

logger = logging.getLogger(__name__)

EDIT_INTERVAL_SEC = 1.05   # Telegram: не чаще одной правки chat_data в секунду на сообщение

_pending: Dict[Tuple[int, int], str] = {}
_tasks: Dict[Tuple[int, int], asyncio.Task] = {}
_last_edit: Dict[Tuple[int, int], float] = {}

# Rich-окна, которые бот обновляет сам: в 00:00 и WORK_END (refresh_all_rich_windows) и когда меняется то, что
# в окне видно (watch_rich_windows, раз в RICH_WATCH_SECONDS)
RICH_PACE_SEC = 0.1    # пауза между правками разных окон: 120 окон за ~12 с при лимите Telegram ~30 сообщений в с
RICH_QUIET_SEC = 5.0   # в окне нажимали недавно: фоновая правка подождёт, иначе могла бы вернуть прошлый экран
_rich_touched: Dict[int, float] = {}   # чат → когда в его Rich-окне нажимали или бот его показывал
_rich_marks: Dict[str, object] = {}    # вид окна ("m2026-11-01", "d2026-11-26") → отпечаток при прошлом обходе
_rich_stale: Set[int] = set()          # чаты, чьё окно надо обновить, но в нём как раз нажимали


def touch_rich(chat_id: int) -> None:
    """В Rich-окне нажали или бот его показал: фоновое обновление этого окна подождёт RICH_QUIET_SEC"""
    _rich_touched[chat_id] = time.monotonic()


def rich_busy(chat_id: int) -> bool:
    return time.monotonic() - _rich_touched.get(chat_id, float("-inf")) < RICH_QUIET_SEC


def _is_not_modified(e: TelegramBadRequest) -> bool:
    return "not modified" in (e.message or "").lower()


def _is_gone(e: TelegramBadRequest) -> bool:
    """Сообщение удалили или его больше нельзя править (старше 48 часов)"""
    text = (e.message or "").lower()
    return "message to edit not found" in text or "can't be edited" in text


class RichFailed(Exception):
    """Rich-окно не показалось. Причина уже в логе: logger.error (алерт) у отказа Telegram и пропавших эмодзи,
    warning у удалённого сообщения и просьбы подождать.
    message_id: отправленное сообщение с заглушками вместо эмодзи (его нужно убрать или заменить);
    gone: сообщение удалено или устарело; retry: Telegram просит подождать (правок слишком много)"""

    def __init__(self, reason: str, message_id: Optional[int] = None, gone: bool = False, retry: bool = False):
        super().__init__(reason)
        self.message_id = message_id
        self.gone = gone
        self.retry = retry


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
        return build_digest_data(day, SEATS, closed=cal_date < self.first_bookable(),
                                 deadline=int(confirm_deadline(cal_date).timestamp()))

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
            await self.remove_message(chat_id, old.message_id, widget=not old.rich)
        return message

    async def reopen_booking_widget(
            self, chat_id: int, owner_id: int, tapped_id: int,
            target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> None:
        """«Обновить» в устаревшем окне: свежий виджет новым сообщением.
        send_booking_widget удаляет окно из указателя; нажатое окно удаляем отдельно, если это не оно"""
        old = await self.tech.get_booking_widget(chat_id)
        message = await self.send_booking_widget(chat_id, owner_id, target_id, target_name)
        if tapped_id not in (message.message_id, old.message_id if old else None):
            await self.remove_message(chat_id, tapped_id)

    async def remove_message(self, chat_id: int, message_id: int, widget: bool = True) -> None:
        """Удалить сообщение; если Telegram не дал (например, старше 48 часов), виджет пометить устаревшим.
        Rich-окно так не пометить: его кнопки и так пересчитывают всё на сервере при нажатии"""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError as e:
            logger.info("remove_message %s/%s | %s", chat_id, message_id, e)
            if widget:
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
        """Обновить открытое окно бронирования пользователя в его личном чате (бронь изменилась вне окна):
        виджет, если у него сейчас виджеты, Rich-календарь, если Rich. Окно другого способа (способ сменили
        в админке) не трогаем: нажатие в нём само заменит его новым экраном"""
        if not self.flags.any_widgets:
            return
        pointer = await self.tech.get_booking_widget(user_id)
        if not pointer or (pointer.target_id or user_id) != user_id:
            return
        ui = await self.flags.booking_ui_for(user_id)
        if pointer.rich and ui == BookingUi.RICH:
            await self.refresh_rich_window(user_id, pointer)
        elif not pointer.rich and ui == BookingUi.WIDGETS:
            await self.refresh_booking_message(user_id, pointer.message_id, user_id)

    # ---------------------------------------------------------------------------#
    #  Rich-календарь: Rich Message в личке вместо главного меню (src/ui/rich/booking.py)
    # ---------------------------------------------------------------------------#
    def rich_month_range(self) -> Tuple[date, date]:
        """Первые числа первого и последнего месяца, которые можно листать: как у виджета, от history_months назад
        до calendar_last_month (месяц горизонта бронирования или future_months вперёд, что дальше)"""
        today = d_tz()
        w = self.flags.widgets
        return shift_month(today, -w.history_months), calendar_last_month(today, self.horizon(), w.future_months)

    async def rich_codes(self, subject_id: int, start: date, end: date) -> Dict[date, str]:
        """Код каждого дня (day_code) по данным календаря; дня нет в БД → x, как у виджета"""
        first_bookable, horizon = self.first_bookable(), self.horizon()
        days = await self.uc.widget_calendar(subject_id, start, end)
        codes = {d.cal_date: day_code(d, first_bookable, horizon) for d in days}
        return {start + timedelta(days=i): codes.get(start + timedelta(days=i), "x")
                for i in range((end - start).days + 1)}

    async def rich_day_code(self, subject_id: int, cal_date: date) -> str:
        """Код дня на момент нажатия: старая кнопка в уже закрытом дне не должна давать бронировать"""
        return (await self.rich_codes(subject_id, cal_date, cal_date))[cal_date]

    async def rich_calendar(
            self, subject_id: int, month: Optional[date] = None,
            target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> Tuple[str, str]:
        """(HTML, view) календаря месяца month (по умолчанию текущего), месяц за пределами диапазона прижимается
        к его краю. target_*: бронь админом за сотрудника"""
        start, last = self.rich_month_range()
        month = min(max((month or d_tz()).replace(day=1), start), last)
        end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        codes = await self.rich_codes(subject_id, month, end)
        prev_m, next_m = shift_month(month, -1), shift_month(month, 1)
        html = render_calendar(month, "".join(codes.values()), d_tz(), prev_m if prev_m >= start else None,
                               next_m if next_m <= last else None, target_id, target_name)
        return html, f"m{month.isoformat()}"

    async def rich_day(
            self, cal_date: date, subject_id: int, subject_name: str, self_view: bool,
            target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> Tuple[str, str]:
        """(HTML, view) экрана дня. Тексты состояния из build_day_state, как у виджета, но место руководителя
        (если выбран) считается занятым: «Свободно 3 из 11». Имена и user_id занявших берутся полными из тех же
        данных дня (DaySeats), а не из урезанного под лимит виджета состояния"""
        day, is_workday = await self.uc.widget_day(cal_date)
        readonly = not (is_workday and self.in_window(cal_date))
        boss = await self.boss()
        state = json.loads(build_day_state(day, SEATS, subject_id, subject_name, self_view, readonly, today=d_tz(),
                                           extra_taken=1 if boss else 0))
        person = Person(boss.user_id, boss.full_name) if boss else None
        return render_day(cal_date, state, day, person, target_id, target_name), f"d{cal_date.isoformat()}"

    async def show_rich(
            self, chat_id: int, html: str, view: str, target_id: Optional[int] = None,
            message_id: Optional[int] = None, silent: bool = False, tapped: Optional[int] = None,
    ) -> Optional[Message]:
        """Отправить Rich-окно (message_id None) или поправить сообщение message_id на месте. Без reply_markup:
        «Сегодня», «Настройки» и листание в самом календаре, а inline-клавиатура старого окна при правке снимается.
        «message is not modified» не ошибка.
        После отправки и правки сверяет кастомные эмодзи в ответе Telegram с отправленными (missing_emoji).
        Запоминает окно в указателе, прежнее Rich-окно в этом чате удаляет. RichFailed: окно не показалось.
        silent: новое сообщение без звука уведомления (окно в ответ на нажатие); tapped: окно, в котором нажали,
        удаляется вместе с прежним, если новое отправлено вместо него, а в указателе было другое окно"""
        rich = InputRichMessage(html=html)
        where = f"chat={chat_id} message={message_id} view={view}"
        result = None
        try:
            if message_id is None:
                result = await self.bot(SendRichMessage(chat_id=chat_id, rich_message=rich,
                                                        disable_notification=silent or None))
            else:
                result = await self.bot(EditMessageText(chat_id=chat_id, message_id=message_id, rich_message=rich))
        except TelegramRetryAfter as e:
            logger.warning("rich | %s | Telegram просит подождать %s с", where, e.retry_after)
            raise RichFailed(str(e), retry=True) from e
        except TelegramBadRequest as e:
            if message_id is not None and _is_not_modified(e):
                result = None
            elif message_id is not None and _is_gone(e):
                logger.warning("rich | %s | %s", where, e.message)
                raise RichFailed(e.message, gone=True) from e
            else:
                logger.error("rich | %s | Telegram отказал: %s. Пользователь уходит в базовый сценарий", where, e)
                raise RichFailed(str(e)) from e
        except TelegramNotFound as e:
            logger.error("rich | Bot API %s не знает Rich Messages, нужен TG_API_BASE беты | %s",
                         self.cfg.TG_API_BASE, e)
            raise RichFailed(str(e)) from e
        except TelegramAPIError as e:
            logger.error("rich | %s | %s. Пользователь уходит в базовый сценарий", where, e)
            raise RichFailed(str(e)) from e
        finally:
            if message_id is not None:
                _last_edit[(chat_id, message_id)] = time.monotonic()

        new_id = result.message_id if isinstance(result, Message) else message_id
        missing = missing_emoji(result, html)
        if missing:
            logger.error("rich | %s | Telegram заменил кастомные эмодзи заглушками (%s из %s, например %s): "
                         "удалён набор или у владельца бота нет Telegram Premium. Пользователь уходит "
                         "в базовый сценарий", where, len(missing), len(emoji_ids(html)), sorted(missing)[0])
            raise RichFailed("custom emoji replaced", message_id=new_id)

        touch_rich(chat_id)
        old = await self.tech.get_booking_widget(chat_id)
        await self.tech.set_booking_widget(chat_id, new_id, target_id, rich_view=view)
        if old and old.rich and old.message_id != new_id:
            await self.remove_message(chat_id, old.message_id, widget=False)
        if tapped and tapped != new_id and not (old and old.message_id == tapped):
            await self.remove_message(chat_id, tapped, widget=False)
        return result if isinstance(result, Message) else None

    async def open_rich_calendar(
            self, chat_id: int, owner_id: int, message_id: Optional[int] = None,
            target_id: Optional[int] = None, target_name: Optional[str] = None,
    ) -> bool:
        """Календарь текущего месяца новым сообщением (message_id None) или вместо сообщения message_id.
        False: не вышло, причина в логе, вызывающий показывает базовый экран. Отправленное с заглушками
        сообщение удаляется; поправленное заменит базовым экраном вызывающий"""
        try:
            html, view = await self.rich_calendar(target_id or owner_id, None, target_id, target_name)
            await self.show_rich(chat_id, html, view, target_id, message_id)
        except DBError as e:
            logger.error("rich | календарь не собран | user=%s target=%s | %s", owner_id, target_id, e)
            return False
        except RichFailed as e:
            if message_id is None and e.message_id:
                await self.remove_message(chat_id, e.message_id, widget=False)
            return False
        return True

    async def forget_rich_window(self, chat_id: int, message_id: int) -> None:
        """Сообщение ушло из Rich-окна (настройки, базовый экран): больше его не обновлять"""
        pointer = await self.tech.get_booking_widget(chat_id)
        if pointer and pointer.rich and pointer.message_id == message_id:
            await self.tech.clear_booking_widget(chat_id)

    async def refresh_rich_window(self, user_id: int, pointer: BookingWidgetPointerDTO, roll_month: bool = False,
                                  background: bool = False) -> bool:
        """Перерисовать открытое Rich-окно пользователя тем же экраном (месяц или день) по свежим данным.
        Окно брони за сотрудника (pointer.target_id) рисуется от его имени, кнопки несут target, как при нажатии.
        roll_month: 1-го числа календарь прошлого месяца становится текущим (вместе с подсветкой «сегодня»).
        background: правка по расписанию или по изменению у других. Перед правкой указатель перечитывается: если
        человек за это время ушёл на другой экран или нажимает прямо сейчас, окно не трогаем (False).
        Не чаще правки в EDIT_INTERVAL_SEC на сообщение. Если окно не показалось, бот перестаёт его обновлять;
        окно с заглушками вместо эмодзи заменяется меню базового сценария"""
        view = pointer.view or ""
        target = pointer.target_id
        subject = target or user_id
        try:
            target_user = await self.uc.user_or_none(target) if target else None
            target_name = (target_user.full_name if target_user else "") if target else None
            if view.startswith("d"):
                user = target_user if target else await self.uc.user_or_none(user_id)
                html, view = await self.rich_day(date.fromisoformat(view[1:]), subject, user.full_name if user else "",
                                                 subject == user_id, target, target_name)
            else:
                month = date.fromisoformat(view[1:]) if view else None
                if roll_month and month == shift_month(d_tz(), -1):
                    month = None
                html, view = await self.rich_calendar(subject, month, target, target_name)
        except (DBError, ValueError) as e:
            logger.warning("rich refresh | user=%s view=%s | %s", user_id, pointer.view, e)
            return True
        key = (user_id, pointer.message_id)
        wait = _last_edit.get(key, 0) + EDIT_INTERVAL_SEC - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        if background and (rich_busy(user_id) or await self.tech.get_booking_widget(user_id) != pointer):
            return False
        try:
            await self.show_rich(user_id, html, view, target, pointer.message_id)
        except RichFailed as e:
            if e.retry:
                return False                 # Telegram просит подождать: обход повторит на следующем круге
            await self.tech.clear_booking_widget(user_id)
            if e.message_id:
                try:
                    await self.bot.edit_message_text(chat_id=user_id, message_id=pointer.message_id,
                                                     text=bot_menu_mess(), reply_markup=get_menu_kb(BookingUi.BASIC))
                except TelegramAPIError as err:
                    logger.warning("rich refresh | меню вместо окна не встало | user=%s | %s", user_id, err)
        return True

    async def rich_windows(self) -> List[Tuple[int, BookingWidgetPointerDTO]]:
        """Открытые Rich-окна, которые бот обновляет сам. Чат без окна или со способом бронирования не Rich
        выпадает из списка: нажатие в таком окне само заменит его нужным экраном"""
        out = []
        for chat_id in await self.tech.rich_window_chats():
            pointer = await self.tech.get_booking_widget(chat_id)
            if not pointer or not pointer.rich or await self.flags.booking_ui_for(chat_id) != BookingUi.RICH:
                await self.tech.forget_rich_chat(chat_id)
                continue
            out.append((chat_id, pointer))
        return out

    async def refresh_all_rich_windows(self, roll_month: bool = False) -> int:
        """Перерисовать все открытые Rich-окна: по расписанию в 00:00 (подсветка «сегодня», 1-го числа новый месяц)
        и в WORK_END (бронь на сегодня закрывается, в воскресенье открывается новая неделя). Окна, в которых сейчас
        нажимают, пропускаются: человек и так видит свежий экран. Возвращает число перерисованных"""
        done = 0
        for chat_id, pointer in await self.rich_windows():
            if rich_busy(chat_id):
                continue
            if await self.refresh_rich_window(chat_id, pointer, roll_month=roll_month, background=True):
                done += 1
            await asyncio.sleep(RICH_PACE_SEC)
        return done

    async def _month_mark(self, month: date) -> str:
        """Отпечаток календаря месяца: коды дней для того, у кого в нём нет броней. Меняется, когда день другого
        человека переходит между «есть места» и «мест нет», закрывается или открывается для брони. Своя бронь
        отпечаток не меняет: её окно перерисовывает тот, кто бронировал (refresh_user_widget)"""
        end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        first_bookable, horizon = self.first_bookable(), self.horizon()
        return "".join(day_code(d, first_bookable, horizon) for d in await self.uc.widget_calendar(0, month, end))

    async def _day_mark(self, cal_date: date) -> tuple:
        """Отпечаток экрана дня: кто на каком месте, очередь, лимит, руководитель на схеме, закрыт ли день"""
        day, is_workday = await self.uc.widget_day(cal_date)
        return (tuple(sorted((h.seat_no or 0, h.user_id, h.full_name) for h in day.holders)), tuple(day.queue_ids()),
                day.capacity, self.flags.widgets.boss_id, is_workday and self.in_window(cal_date))

    async def watch_rich_windows(self) -> int:
        """Обход раз в RICH_WATCH_SECONDS: перерисовать окна, в которых изменилось видимое, откуда бы ни пришло
        изменение (Rich, виджет, текстовый сценарий, чат, задачи по расписанию). Для каждого открытого вида
        (месяц или день) снимается отпечаток и сравнивается с прошлым обходом; вид, увиденный впервые, только
        запоминается. Окно, в котором как раз нажимают, обновится на следующем обходе. Возвращает число
        перерисованных"""
        windows = await self.rich_windows()
        marks: Dict[str, object] = {}
        for view in {p.view for _, p in windows if p.view}:
            if view.startswith("m"):
                marks[view] = await self._month_mark(date.fromisoformat(view[1:]))
            elif view.startswith("d"):
                marks[view] = await self._day_mark(date.fromisoformat(view[1:]))
        changed = {v for v, mark in marks.items() if v in _rich_marks and _rich_marks[v] != mark}
        _rich_marks.clear()
        _rich_marks.update(marks)
        done = 0
        for chat_id, pointer in windows:
            if pointer.view not in changed and chat_id not in _rich_stale:
                continue
            if rich_busy(chat_id) or not await self.refresh_rich_window(chat_id, pointer, background=True):
                _rich_stale.add(chat_id)
                continue
            _rich_stale.discard(chat_id)
            done += 1
            await asyncio.sleep(RICH_PACE_SEC)
        return done

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
