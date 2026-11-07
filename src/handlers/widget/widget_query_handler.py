"""Запросы из виджетов (апдейт widget_query).

Личный виджет:  d|b|c|q|lq:<дата>[:<место>][@<user_id сотрудника>]  → ответ — состояние дня (JSON)
                x[@<user_id>]                                          → «Выйти»: виджет заменяется меню
                o[@<user_id>]                                          → «Открыть заново»: новый виджет вместо устаревшего
Дайджест:       s:<дата>:<место>                                       → ответ — {"m": текст, "e": ошибка, "b": кнопка бота}
"""
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

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
                                     SeatNotFound, UserIsAlreadyInWaitingList, UserIsAlreadyLeaveQueue)
from src.ui.widgets.layout import SEATS
from src.ui.widgets.render import WidgetTooLarge
from src.ui.widgets.state import MAX_DATA_BYTES, data_size, dumps, short_name
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.widget_use_case import WidgetUseCase
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.start_mess import bot_menu_mess
from src.utils.db_exc_wrapper import DBError

logger = logging.getLogger(__name__)

PRIVATE_RE = re.compile(r"^(d|b|c|q|lq):(\d{4}-\d{2}-\d{2})(?::(\d{1,3}))?(?:@(\d{1,20}))?$")
GROUP_RE = re.compile(r"^s:(\d{4}-\d{2}-\d{2}):(\d{1,3})$")

EXIT_CMD = "x"     # кнопка «Выйти» в календаре
REOPEN_CMD = "o"   # кнопка «Открыть заново» в устаревшем или закрытом окне
DB_ERROR_TEXT = "Не удалось выполнить действие, попробуйте ещё раз"
REGISTER_TEXT = "Чтобы бронировать, зарегистрируйтесь в боте"


@dataclass(frozen=True)
class PrivateRequest:
    cmd: str
    cal_date: date
    seat: Optional[int]
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
        seat=int(m.group(3)) if m.group(3) else None,
        target=int(m.group(4)) if m.group(4) else None,
    )


def parse_group(data: str) -> Optional[Tuple[date, int]]:
    m = GROUP_RE.match(data or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1)), int(m.group(2))
    except ValueError:
        return None


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
            answer = dumps(await _handle_group(query, bot, container))
        else:
            logger.info("widget_query из чужого чата %s", query.chat.id)
    except Exception:
        logger.exception("widget_query failed | user=%s data=%s", query.from_user.id, query.data)
        if is_group:
            answer = dumps({"m": DB_ERROR_TEXT, "e": 1})
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

    if er is None and req.cmd != "d":
        if user is None:
            er = REGISTER_TEXT
        elif not await widgets.is_bookable(req.cal_date):
            er = "Бронирование на этот день закрыто"
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
    """«Открыть заново». Ответ нужен только при ошибке: при успехе нажатое окно удаляется"""
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
            return "Пересадили на новое место", None
        await uc.book_place(subject, d, seat_no=req.seat)
        return ("Место забронировано" if self_view else f"{who}: место забронировано"), None

    if req.cmd == "c":
        sub_status = BookingStatus.CANCELED_CHANGED_MIND if self_view else BookingStatus.CANCELED_ADMIN
        promoted = await promote_user_after_cancel(None, uc, d, bot, subject, sub_status)
        return ("Бронь отменена, место ушло первому в очереди" if promoted else "Бронь отменена"), promoted

    if req.cmd == "q":
        try:
            await uc.waitlist_place(subject, d)
        except FreePlaceIsAvailable:
            return "Место освободилось, бронь оформлена", None
        return ("Вы в очереди" if self_view else f"{who} в очереди"), None

    # lq
    await uc.cancel_waitlist_place(subject, d)
    return ("Вы вышли из очереди" if self_view else "Удалено из очереди"), None


# ---------------------------------------------------------------------------#
#  Дайджест в группе: виджет у всех одинаковый, смысл тапа определяется по from.id
# ---------------------------------------------------------------------------#
async def _handle_group(query: WidgetQuery, bot: Bot, container: AsyncContainer) -> dict:
    parsed = parse_group(query.data)
    if parsed is None:
        return {"m": "Неизвестное действие", "e": 1}
    d, seat = parsed

    uc: BookingUseCase = await container.get(BookingUseCase)
    widgets: WidgetUseCase = await container.get(WidgetUseCase)

    user_id = query.from_user.id
    if await uc.user_or_none(user_id) is None:
        return {"m": REGISTER_TEXT, "e": 1, "b": 1}
    if await uc.digest_message_id(d) != query.message_id:
        return {"m": "Этот дайджест уже неактуален", "e": 1}
    if not await widgets.is_bookable(d):
        return {"m": "Бронирование на этот день закрыто", "e": 1}
    if seat not in SEATS:
        return {"m": "Такого места нет", "e": 1}

    day, _ = await uc.widget_day(d)
    at_seat = day.by_seat().get(seat)
    mine = day.holder(user_id)
    promoted: Optional[int] = None

    try:
        if at_seat and at_seat.user_id == user_id:
            if not at_seat.confirmed:
                await uc.confirm_booking(user_id, d)
                text = "Бронь подтверждена, ждём в офисе"
            else:
                promoted = await promote_user_after_cancel(
                    None, uc, d, bot, user_id, BookingStatus.CANCELED_CHANGED_MIND
                )
                text = "Бронь отменена, место ушло первому в очереди" if promoted else "Бронь отменена"
        elif at_seat:
            if not mine and not day.free_seats(SEATS):
                return {"m": "Свободных мест нет. Встать в очередь можно в боте", "b": 1}
            return {"m": f"Место занято: {short_name(at_seat.full_name)}", "e": 1}
        elif mine:
            await uc.move_seat(user_id, d, seat)
            if not mine.confirmed:
                await uc.confirm_booking(user_id, d)
            text = "Пересадили на новое место"
        else:
            await uc.book_place(user_id, d, auto_confirm=True, seat_no=seat)
            text = "Место забронировано"
    except FreePlaceIsNotFound:
        return {"m": "Свободных мест нет. Встать в очередь можно в боте", "b": 1}
    except BookingError as e:
        return {"m": widget_error_text(e), "e": 1}
    except DBError:
        return {"m": DB_ERROR_TEXT, "e": 1}

    await widgets.refresh_digest(d)
    await widgets.refresh_user_widget(user_id)
    if promoted:
        await widgets.refresh_user_widget(promoted)
    return {"m": text}
