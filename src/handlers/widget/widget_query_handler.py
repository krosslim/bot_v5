"""Запросы из виджетов (апдейт widget_query).

Личный виджет:  d|b|c|q|lq:<дата>[:<место>][@<user_id сотрудника>]  → ответ — состояние дня (JSON)
                n:<дата>:<место|b>[@<user_id>]                         → ответ — {"n": полное имя на месте}
                x[@<user_id>]                                          → «Выйти»: виджет заменяется меню
                o[@<user_id>]                                          → «Обновить»: новый виджет вместо устаревшего
Дайджест:       gn:<дата>:<место|b>     полное имя на месте или у руководителя
                gu:<дата>:<user_id>     полное имя человека из очереди
                gb:<дата>:<место>       занять (нет брони) или пересесть (подтверждённая бронь)
                gc:<дата>  подтвердить   gx:<дата>  отменить бронь   gq:<дата>  встать в очередь   gl:<дата>  выйти из очереди
                → ответ — {"ok": успех} | {"er": ошибка[, "u": 1 — не зарегистрирован]} | {"n": полное имя}.
                Новое состояние приходит в chat_data (refresh_digest), ответ его не несёт.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from dishka import AsyncContainer

from config import settings
from src.dto.booking_dto import BookingStatus
from src.handlers.user.booking_handler import promote_user_after_cancel
from src.infrastructure.telegram.widgets import AnswerWidgetQuery, WidgetQuery
from src.services.feature_flags import FeatureFlags
from src.services.exceptions import (BookingError, BookingIsAlreadyExist, CancelIsAlreadyExist,
                                     FreePlaceIsAvailable, FreePlaceIsNotFound, NoCapacityInfo,
                                     SeatIsTaken, SeatNotFound, UserIsAlreadyInWaitingList, UserIsAlreadyLeaveQueue)
from src.ui.widgets.layout import BOSS_SEAT, SEATS
from src.ui.widgets.render import WidgetTooLarge
from src.ui.widgets.state import MAX_DATA_BYTES, DaySeats, data_size, dumps, short_name
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.widget_use_case import WidgetUseCase
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.start_mess import bot_menu_mess
from src.utils.db_exc_wrapper import DBError
from src.utils.today import confirm_deadline

logger = logging.getLogger(__name__)

PRIVATE_RE = re.compile(r"^(d|b|c|q|lq|n):(\d{4}-\d{2}-\d{2})(?::(\d{1,3}|b))?(?:@(\d{1,20}))?$")
DIGEST_RE = re.compile(r"^g([nubcxql]):(\d{4}-\d{2}-\d{2})(?::(b|\d{1,20}))?$")
DIGEST_ARG = {"n": r"b|\d{1,3}", "b": r"\d{1,3}", "u": r"\d{1,20}"}   # у остальных команд аргумента нет

EXIT_CMD = "x"     # кнопка «Выйти» в календаре
REOPEN_CMD = "o"   # кнопка «Обновить» в устаревшем или закрытом окне
# Тексты результатов: общие для личного виджета и дайджеста
DB_ERROR_TEXT = "Не удалось выполнить действие, попробуйте ещё раз"
BOOKED_TEXT = "Место забронировано"
MOVED_TEXT = "Пересадили на новое место"
CANCELED_TEXT = "Бронь отменена"
CANCELED_PROMOTED_TEXT = "Бронь отменена, место ушло первому в очереди"
QUEUED_TEXT = "Вы в очереди"
QUEUE_BOOKED_TEXT = "Место освободилось, бронь оформлена"
LEFT_QUEUE_TEXT = "Вы вышли из очереди"
DAY_CLOSED_TEXT = "Бронирование на этот день закрыто"
SEAT_FREE_TEXT = "Место уже свободно"
# Только дайджест
CONFIRMED_TEXT = "Бронь подтверждена"
CONFIRM_LATE_TEXT = "Время подтверждения прошло"
CONFIRM_FIRST_TEXT = "Сначала подтвердите бронь"
NOT_REGISTERED_TEXT = "Вы не зарегистрированы"
STALE_DIGEST_TEXT = "Этот дайджест устарел"
NOT_IN_QUEUE_TEXT = "Уже не в очереди"
UNKNOWN_TEXT = "Неизвестное действие"
REGISTER_TEXT = "Чтобы бронировать, зарегистрируйтесь в боте"


@dataclass(frozen=True)
class PrivateRequest:
    cmd: str
    cal_date: date
    seat: Optional[int | str]   # номер места или BOSS_SEAT
    target: Optional[int]


def parse_private(data: str) -> Optional[PrivateRequest]:
    m = PRIVATE_RE.match(data or "")
    if not m:
        return None
    try:
        cal_date = date.fromisoformat(m.group(2))
    except ValueError:
        return None
    return PrivateRequest(
        cmd=m.group(1),
        cal_date=cal_date,
        seat=_seat(m.group(3)) if m.group(3) else None,
        target=int(m.group(4)) if m.group(4) else None,
    )


@dataclass(frozen=True)
class DigestRequest:
    cmd: str                            # n u b c x q l
    cal_date: date
    seat: Optional[int | str] = None    # gn, gb: номер места или BOSS_SEAT
    user_id: Optional[int] = None       # gu: человек из очереди


def parse_digest(data: str) -> Optional[DigestRequest]:
    m = DIGEST_RE.fullmatch(data or "")   # не match: $ пропустил бы перевод строки в конце
    if not m:
        return None
    cmd, raw_date, arg = m.groups()
    pattern = DIGEST_ARG.get(cmd)
    if (arg is None) != (pattern is None) or (arg is not None and not re.fullmatch(pattern, arg)):
        return None
    try:
        cal_date = date.fromisoformat(raw_date)
    except ValueError:
        return None
    if cmd == "u":
        return DigestRequest(cmd, cal_date, user_id=int(arg))
    return DigestRequest(cmd, cal_date, seat=_seat(arg) if arg else None)


def _seat(raw: str) -> int | str:
    return BOSS_SEAT if raw == BOSS_SEAT else int(raw)


def widget_error_text(e: BookingError) -> str:
    """Короткие тексты для виджета вместо длинных алертов текстового интерфейса"""
    mapping = {
        FreePlaceIsNotFound: "Свободных мест нет",
        BookingIsAlreadyExist: "У вас уже есть бронь на этот день",
        CancelIsAlreadyExist: "Брони на этот день уже нет",
        UserIsAlreadyInWaitingList: "Вы уже в очереди",
        UserIsAlreadyLeaveQueue: "Вы уже вышли из очереди",
        NoCapacityInfo: "Нет данных о лимитах на этот день",
    }
    for cls, text in mapping.items():
        if isinstance(e, cls):
            return text
    return str(e).lstrip("✅⏳ℹ️⚠️❗️ \n") or DB_ERROR_TEXT


async def process_widget_query(query: WidgetQuery, bot: Bot, container: AsyncContainer) -> None:
    answer: Optional[str] = None
    is_group = query.chat is not None and query.chat.type != "private"
    try:
        if query.chat is None or query.message_id is None:
            logger.info("widget_query без сообщения (пересылка или inline): %s", query.data)
        elif not is_group:
            answer = await _handle_private(query, bot, container)
        elif query.chat.id == settings.TG_CHAT_ID:
            answer = dumps(await _handle_digest(query, bot, container))
        else:
            logger.info("widget_query из чужого чата %s", query.chat.id)
    except Exception:
        logger.exception("widget_query failed | user=%s data=%s", query.from_user.id, query.data)
        if is_group:
            answer = dumps({"er": DB_ERROR_TEXT})
    finally:
        if answer is not None and data_size(answer) > MAX_DATA_BYTES:
            logger.error("widget_query | ответ %s Б больше лимита: %s", data_size(answer), answer[:200])
            answer = None
        try:
            await bot(AnswerWidgetQuery(widget_query_id=query.id, data=answer))
        except Exception as e:
            logger.warning("answerWidgetQuery failed | %s", e)


# ---------------------------------------------------------------------------#
#  Личный виджет
# ---------------------------------------------------------------------------#
async def _handle_private(query: WidgetQuery, bot: Bot, container: AsyncContainer) -> Optional[str]:
    cmd, _, raw_target = (query.data or "").partition("@")
    flags: FeatureFlags = await container.get(FeatureFlags)
    enabled = await flags.widgets_for(query.from_user.id)
    if cmd == EXIT_CMD or not enabled:
        # «Выйти» или виджеты этому пользователю выключили из админки, пока окно висело в чате:
        # любое нажатие заменяет окно меню
        await _exit_to_menu(query, bot, container, widgets=enabled)
        return None
    if cmd == REOPEN_CMD:
        return await _reopen(query, bot, container, int(raw_target) if raw_target.isdigit() else None)

    req = parse_private(query.data)
    if req is None:
        return None

    uc: BookingUseCase = await container.get(BookingUseCase)
    widgets: WidgetUseCase = await container.get(WidgetUseCase)

    actor = query.from_user.id
    subject = req.target or actor
    ok = er = None
    promoted: Optional[int] = None
    changed = False

    if subject != actor and not await uc.can_act_for(actor, subject):
        logger.warning("widget_query | %s пытается действовать за %s без прав", actor, subject)
        subject, er = actor, "Нет прав бронировать за других"

    self_view = subject == actor
    user = await uc.user_or_none(subject)
    name = user.full_name if user else ""

    if req.cmd == "n":
        # Нажатие на место с именем: полное имя серым под датой. Место успели освободить — свежая схема
        full_name = await widgets.seat_holder_name(req.cal_date, req.seat) if req.seat else None
        if full_name:
            return dumps({"n": full_name})
        er = er or SEAT_FREE_TEXT
    elif er is None and req.cmd != "d":
        if user is None:
            er = REGISTER_TEXT
        elif not await widgets.is_bookable(req.cal_date):
            er = DAY_CLOSED_TEXT
        else:
            try:
                ok, promoted = await _private_action(req, subject, self_view, name, uc, bot)
                changed = True
            except BookingError as e:
                er = widget_error_text(e)
            except DBError:
                er = DB_ERROR_TEXT

    state = await widgets.day_state(req.cal_date, subject, name, self_view, ok, er)

    if changed:
        await widgets.refresh_booking_message(query.chat.id, query.message_id, subject)
        if subject != actor:
            await widgets.refresh_user_widget(subject)
        if promoted:
            await widgets.refresh_user_widget(promoted)
        await widgets.refresh_digest(req.cal_date)
    return state


async def _exit_to_menu(query: WidgetQuery, bot: Bot, container: AsyncContainer, widgets: bool) -> None:
    """Виджет заменяется меню (сначала меню, потом удаление — чтобы чат не остался пустым)"""
    uc: WidgetUseCase = await container.get(WidgetUseCase)
    await bot.send_message(chat_id=query.chat.id, text=bot_menu_mess(), reply_markup=get_menu_kb(widgets))
    await uc.close_booking_widget(query.chat.id, query.message_id)


async def _reopen(query: WidgetQuery, bot: Bot, container: AsyncContainer, target: Optional[int]) -> Optional[str]:
    """«Обновить». Ответ нужен только при ошибке: при успехе нажатое окно удаляется"""
    uc: BookingUseCase = await container.get(BookingUseCase)
    widgets: WidgetUseCase = await container.get(WidgetUseCase)
    actor = query.from_user.id
    name: Optional[str] = None
    if target and target != actor:
        user = await uc.user_or_none(target) if await uc.can_act_for(actor, target) else None
        if user is None:                      # права отозвали или сотрудника удалили: открываем своё окно
            target = None
        else:
            name = user.full_name
    else:
        target = None

    try:
        await widgets.reopen_booking_widget(query.chat.id, actor, query.message_id, target, name)
    except (TelegramAPIError, WidgetTooLarge, DBError) as e:
        logger.error("widget reopen | user=%s target=%s | %s", actor, target, e)
        return dumps({"er": "Не удалось открыть окно, попробуйте ещё раз"})
    return None


async def _private_action(
        req: PrivateRequest, subject: int, self_view: bool, name: str, uc: BookingUseCase, bot: Bot,
) -> Tuple[str, Optional[int]]:
    who = short_name(name)
    d = req.cal_date

    if req.cmd == "b":
        if req.seat not in SEATS:
            raise SeatNotFound("Такого места нет")
        if await uc.user_booking_for_date(subject, d):
            await uc.move_seat(subject, d, req.seat)
            return MOVED_TEXT, None
        await uc.book_place(subject, d, seat_no=req.seat)
        return (BOOKED_TEXT if self_view else f"{who}: место забронировано"), None

    if req.cmd == "c":
        sub_status = BookingStatus.CANCELED_CHANGED_MIND if self_view else BookingStatus.CANCELED_ADMIN
        promoted = await promote_user_after_cancel(None, uc, d, bot, subject, sub_status)
        return (CANCELED_PROMOTED_TEXT if promoted else CANCELED_TEXT), promoted

    if req.cmd == "q":
        try:
            await uc.waitlist_place(subject, d)
        except FreePlaceIsAvailable:
            return QUEUE_BOOKED_TEXT, None
        return (QUEUED_TEXT if self_view else f"{who} в очереди"), None

    # lq
    await uc.cancel_waitlist_place(subject, d)
    return (LEFT_QUEUE_TEXT if self_view else "Удалено из очереди"), None


# ---------------------------------------------------------------------------#
#  Дайджест в группе: виджет знает зрителя и шлёт явную команду, сервер проверяет её и действует за from.id
# ---------------------------------------------------------------------------#
class _Refusal(Exception):
    """Отказ с готовым текстом для виджета, когда подходящего BookingError нет"""


async def _handle_digest(query: WidgetQuery, bot: Bot, container: AsyncContainer) -> dict:
    req = parse_digest(query.data)
    if req is None:
        return {"er": UNKNOWN_TEXT}

    uc: BookingUseCase = await container.get(BookingUseCase)
    widgets: WidgetUseCase = await container.get(WidgetUseCase)
    d = req.cal_date

    if await uc.digest_message_id(d) != query.message_id:
        # На эту дату отправили дайджест новее (/digest_now): нажатия принимает только он
        return {"er": STALE_DIGEST_TEXT}
    if req.cmd == "n":
        # Имена — всем, в том числе в закрытом дне и без регистрации
        name = await widgets.seat_holder_name(d, req.seat)
        return {"n": name} if name else {"er": SEAT_FREE_TEXT}

    day, _ = await uc.widget_day(d)
    if req.cmd == "u":
        # Имя только тех, кто сейчас в очереди на эту дату: по чужому id имя не раскрываем
        entry = next((e for e in day.queue if e.user_id == req.user_id), None)
        return {"n": entry.full_name} if entry else {"er": NOT_IN_QUEUE_TEXT}

    actor = query.from_user.id   # действовать можно только за себя
    if await uc.user_or_none(actor) is None:
        return {"er": NOT_REGISTERED_TEXT, "u": 1}
    if not await widgets.is_bookable(d):
        return {"er": DAY_CLOSED_TEXT}
    try:
        ok, promoted = await _digest_action(req, actor, day, uc, bot)
    except _Refusal as e:
        return {"er": str(e)}
    except BookingError as e:
        return {"er": widget_error_text(e)}
    except DBError:
        return {"er": DB_ERROR_TEXT}

    await widgets.refresh_digest(d)
    await widgets.refresh_user_widget(actor)
    if promoted:
        await widgets.refresh_user_widget(promoted)
    return {"ok": ok}


async def _digest_action(
        req: DigestRequest, actor: int, day: DaySeats, uc: BookingUseCase, bot: Bot,
) -> Tuple[str, Optional[int]]:
    """Действие из дайджеста. day — схема до действия: по ней отказываем сразу, а гонки с другими бронями
    ловят сами методы BookingUseCase (блокировка дня)"""
    d = req.cal_date
    mine = day.holder(actor)

    if req.cmd == "b":
        if req.seat not in SEATS:
            raise SeatNotFound("Такого места нет")
        if mine and not mine.confirmed:
            raise _Refusal(CONFIRM_FIRST_TEXT)   # виджет такого не шлёт: в W свободные места не нажимаются
        if req.seat in day.by_seat():
            raise SeatIsTaken("Это место только что заняли")
        if req.seat not in day.free_seats(SEATS):
            raise FreePlaceIsNotFound("")        # лимит дня выбран: стулья сверх него недоступны и для пересадки
        if mine:
            await uc.move_seat(actor, d, req.seat)
            return MOVED_TEXT, None
        await uc.book_place(actor, d, seat_no=req.seat)   # автоподтверждение по общему правилу
        return BOOKED_TEXT, None

    if req.cmd == "c":
        if mine is None:
            raise CancelIsAlreadyExist("")
        if mine.confirmed:
            return CONFIRMED_TEXT, None          # данные в виджете могли не успеть обновиться
        if datetime.now(ZoneInfo(settings.MSC_TZ)) >= confirm_deadline(d):
            raise _Refusal(CONFIRM_LATE_TEXT)
        if not await uc.confirm_booking(actor, d):
            raise CancelIsAlreadyExist("")       # бронь сняли между чтением схемы и подтверждением
        return CONFIRMED_TEXT, None

    if req.cmd == "x":
        if mine is None:
            raise CancelIsAlreadyExist("")
        promoted = await promote_user_after_cancel(None, uc, d, bot, actor, BookingStatus.CANCELED_CHANGED_MIND)
        return (CANCELED_PROMOTED_TEXT if promoted else CANCELED_TEXT), promoted

    if req.cmd == "q":
        if mine:
            raise BookingIsAlreadyExist("")
        try:
            await uc.waitlist_place(actor, d)
        except FreePlaceIsAvailable:
            return QUEUE_BOOKED_TEXT, None       # место было свободно — waitlist_place сразу забронировал
        return QUEUED_TEXT, None

    # l
    await uc.cancel_waitlist_place(actor, d)
    return LEFT_QUEUE_TEXT, None
