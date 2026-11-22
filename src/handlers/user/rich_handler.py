"""Нажатия в Rich-календаре (RichCB, src/ui/rich/booking.py). Только личные сообщения с ботом.

Нажатие правит то же сообщение (editMessageText с rich_message, без reply_markup: все кнопки в самом
сообщении). Исключение: дата в календаре открывает экран дня новым сообщением без звука, прежнее окно
удаляется. Клиент Telegram запоминает, какие блоки <details> человек раскрыл, для сообщения по порядку блоков,
и правка это не сбрасывает (даже через календарь без блоков): в другом дне остался бы раскрытым не тот стол.
В новом сообщении раскрыт стол, который выбрал бот (src/ui/rich/booking.py, desks). Действия внутри дня
(занять, отменить, очередь) правят сообщение: раскрытое человеком остаётся.
«Настройки» в нижнем ряду календаря обрабатывает экран настроек (SettingsCB).
Результат действия («Место забронировано», «Бронь отменена», ошибка) приходит только тостом answerCallbackQuery,
в сообщении текущее состояние. Действия идут через те же методы, что у виджета (private_action), тексты те же.

Коды дней пересчитываются на сервере при нажатии: старая кнопка в уже закрытом дне бронировать не даёт.
Бронь админом за сотрудника: user_id сотрудника в callback_data (target), права проверяются на каждое нажатие,
способ бронирования определяется по тому, кто бронирует.
"""
import logging
from datetime import date
from typing import Optional, Tuple

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.callback_answer import CallbackAnswer
from dishka import FromDishka

from src.handlers.user.booking_handler import render_booking_page
from src.handlers.user.home_screen import show_home
from src.handlers.widget.widget_query_handler import (DAY_CLOSED_TEXT, DB_ERROR_TEXT, REGISTER_TEXT, SEAT_FREE_TEXT,
                                                      UNKNOWN_TEXT, PrivateRequest, private_action, widget_error_text)
from src.services.exceptions import BookingError
from src.services.feature_flags import BookingUi, FeatureFlags
from src.ui.keyboard.actions import RichCB
from src.ui.rich.booking import DAY_OFF_TEXT, NOT_OPEN_TEXT, OPEN_CODES, READONLY_CODES, TODAY_TEXT
from src.ui.widgets.layout import BOSS_SEAT
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.widget_use_case import RichFailed, WidgetUseCase, touch_rich
from src.utils.db_exc_wrapper import DBError

router = Router()
logger = logging.getLogger(__name__)

# Команда кнопки → команда личного виджета (parse_private): занять или пересесть, отменить, очередь
ACTIONS = {"seat": "b", "cancel": "c", "queue": "q", "leave": "lq"}
NO_RIGHTS_TEXT = "Нет прав бронировать за других"


def _seat(raw: Optional[str]) -> Optional[int | str]:
    if raw == BOSS_SEAT:
        return BOSS_SEAT
    return int(raw) if raw and raw.isdigit() else None


@router.callback_query(RichCB.filter(), F.message.chat.type == "private")
async def handle_rich(
        call: CallbackQuery,
        callback_data: RichCB,
        callback_answer: CallbackAnswer,
        uc: FromDishka[BookingUseCase],
        widgets: FromDishka[WidgetUseCase],
        flags: FromDishka[FeatureFlags],
        state: FSMContext,
):
    callback_answer.disabled = True   # отвечаем сами: тост без «Ок», и до обновления чужих окон
    actor = call.from_user.id
    touch_rich(actor)                 # фоновое обновление окна подождёт, пока человек нажимает
    message_id = call.message.message_id

    if await flags.booking_ui_for(actor) != BookingUi.RICH:
        # Rich этому пользователю выключили из админки, пока календарь висел в чате:
        # любое нажатие заменяет окно главным экраном, как у виджетов
        await widgets.forget_rich_window(actor, message_id)
        await show_home(call, flags, widgets)
        await call.answer()
        return

    try:
        cal_date = date.fromisoformat(callback_data.day)
    except ValueError:
        await call.answer(UNKNOWN_TEXT, show_alert=True)
        return

    target = callback_data.target if callback_data.target and callback_data.target != actor else None
    subject = target or actor
    toast: Optional[str] = None
    alert = False
    if target and not await uc.can_act_for(actor, target):
        logger.warning("rich | %s пытается действовать за %s без прав", actor, target)
        subject, target, toast, alert = actor, None, NO_RIGHTS_TEXT, True

    changed, promoted = False, None
    view: Optional[Tuple[str, str]] = None
    fresh = False   # экран дня из календаря: новым сообщением, см. описание модуля
    try:
        user = await uc.user_or_none(subject)
        name = user.full_name if user else ""
        target_name = name if target else None
        self_view = subject == actor

        async def day_view() -> Tuple[str, str]:
            return await widgets.rich_day(cal_date, subject, name, self_view, target, target_name)

        cmd = callback_data.cmd
        if cmd == "month":
            view = await widgets.rich_calendar(subject, cal_date, target, target_name)
        elif cmd == "today":
            # «Сегодня» в нижнем ряду: текущий месяц на момент нажатия, не на момент отрисовки кнопки
            view = await widgets.rich_calendar(subject, None, target, target_name)
            toast = toast or TODAY_TEXT
        elif cmd == "day":
            code = await widgets.rich_day_code(subject, cal_date)
            if code in OPEN_CODES or code in READONLY_CODES:
                view = await day_view()
                fresh = True
            elif code == "x":
                toast = toast or NOT_OPEN_TEXT
            else:
                toast = toast or DAY_OFF_TEXT
        elif cmd == "name":
            seat = _seat(callback_data.seat)
            full_name = await widgets.seat_holder_name(cal_date, seat) if seat else None
            if full_name:
                toast = toast or full_name
            else:
                # Место успели освободить: тост и свежая схема
                toast = toast or SEAT_FREE_TEXT
                view = await day_view()
        elif cmd in ACTIONS:
            if alert:
                pass                                  # нет прав: показываем свой день без действия
            elif user is None:
                toast, alert = REGISTER_TEXT, True
            elif not await widgets.is_bookable(cal_date):
                toast, alert = DAY_CLOSED_TEXT, True   # старая кнопка в уже закрытом дне
            else:
                req = PrivateRequest(cmd=ACTIONS[cmd], cal_date=cal_date, seat=_seat(callback_data.seat),
                                     target=target)
                try:
                    toast, promoted = await private_action(req, subject, self_view, name, uc, call.bot)
                    changed = True
                except BookingError as e:
                    toast, alert = widget_error_text(e), True
                except DBError:
                    toast, alert = DB_ERROR_TEXT, True
            view = await day_view()
        else:
            toast, alert = UNKNOWN_TEXT, True
    except DBError as e:
        logger.warning("rich | user=%s data=%s | %s", actor, call.data, e)
        toast, alert, view = DB_ERROR_TEXT, True, None

    if view:
        html, view_key = view
        try:
            if fresh:
                await widgets.show_rich(actor, html, view_key, target, None, silent=True, tapped=message_id)
            else:
                await widgets.show_rich(actor, html, view_key, target, message_id)
        except RichFailed as e:
            if fresh and e.message_id:
                await widgets.remove_message(actor, e.message_id, widget=False)   # ушло с заглушками эмодзи
            if toast == TODAY_TEXT:
                toast = None                          # календарь не обновился: не обещаем обратного
            if e.retry:
                toast, alert = toast or DB_ERROR_TEXT, True
            elif e.gone:
                # Сообщение удалено или больше не правится: календарь новым сообщением
                if not await widgets.open_rich_calendar(actor, actor, None, target, target_name):
                    toast, alert = toast or DB_ERROR_TEXT, True
            else:
                # Telegram отказал или заменил эмодзи заглушками (алерт уже ушёл): базовый сценарий
                await widgets.forget_rich_window(actor, message_id)
                if target:
                    await state.update_data(user_id=target)
                await render_booking_page(call, 0, uc, state, None, subject)

    try:
        await call.answer(toast, show_alert=alert)
    except TelegramBadRequest as e:   # базовый экран при ошибке БД уже ответил своим текстом
        logger.info("rich | answerCallbackQuery | %s", e)

    if changed:
        if subject != actor:
            await widgets.refresh_user_widget(subject)
        if promoted:
            await widgets.refresh_user_widget(promoted)
        await widgets.refresh_digest(cal_date)
