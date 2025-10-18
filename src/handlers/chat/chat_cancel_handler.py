import logging
from typing import Tuple, Optional

from aiogram import Router, F, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineQuery,
    ChosenInlineResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from dishka import FromDishka

from config import settings as s
from src.dto.booking_dto import BookingStatus
from src.handlers.user.booking_handler import promote_user_after_cancel
from src.services.exceptions import CacheCalDate, BookingError
from src.ui.inline_query.cancel_articles import build_cancel_reasons
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.input_validator import (
    validate_and_parse_dates,
    InlineInputError,
    ActionType,
)

router = Router()

logger = logging.getLogger(__name__)


@router.inline_query(F.chat_type.in_({"group", "supergroup"}))
async def handle_cancel_query(q: InlineQuery, bot: Bot, uc: FromDishka[BookingUseCase]):
    user_id = q.from_user.id
    input_data = q.query
    error_title = "⚠️ Ошибка"
    if not input_data:
        error_title = "❓Как отменить запись"
    error_response = (
        f"<b>Как работает inline-mode?</b>\n"
        f"<blockquote>1. Введите: @{s.BOT_USERNAME}\n   (или жми <b>Попробовать</b>)\n"
        f"2. Затем:\n"
        f"  • Для отмены брони на день: ДД.ММ\n"
        f"  • Отмена нескольких дней: ДД.ММ-ДД.ММ</blockquote>"
        # f"  • Для обмена: ДД.ММ ДД.ММ (через пробел)</blockquote>"
    )

    try:
        action, dates, normalized_input = validate_and_parse_dates(input_data)

        if not await _member_validate(user_id, bot):
            return

        if action == ActionType.CHANGE:
            return await _fallback_answer(
                q, error_title, error_response, "Функция обмена временно не доступна."
            )

        bookings = await uc.my_bookings(user_id, dates)
        bookings_count = len(bookings)
        if bookings_count == 0:
            return await _fallback_answer(
                q, error_title, error_response, "У вас нет активных записей для отмены."
            )

        key = await uc.cache_key(bookings)
        articles = build_cancel_reasons(bookings, key, normalized_input)
        return await q.answer(
            results=articles,
            cache_time=0,
            is_personal=True,
            switch_pm_parameter="cancel",
            switch_pm_text=f"Кол-во бронирований: {bookings_count}",
        )

    except (DBError, InlineInputError, CacheCalDate) as e:
        return await _fallback_answer(q, error_title, error_response, e)


@router.chosen_inline_result()
async def handle_cancel_reason(
    res: ChosenInlineResult, bot: Bot, uc: FromDishka[BookingUseCase]
):
    result = res.result_id
    user_id = res.from_user.id
    inline_mess_id = res.inline_message_id
    cache_key, cancel_sub_status = _article_id(result)
    error_text = (
        "<b>⚠️ Не удалось отменить бронирования</b>\nПопробуйте сделать это вручную"
    )

    if cancel_sub_status is None:
        await _send_message(bot, user_id, error_text)
        logger.exception("Не известные данные в article_id %s", result)
        return

    cancel_dates = await uc.dates_by_cache_key(cache_key)
    cancel_dates_count = len(cancel_dates)

    if cancel_dates_count == 0:
        await _send_message(bot, user_id, error_text)
        return

    bookings = await uc.my_bookings(user_id, cancel_dates)

    if not bookings:
        await _send_message(bot, user_id, error_text)
        return

    is_promoted = False
    has_waitlist = False
    error_count = 0

    for i in bookings:
        try:
            if i.status == BookingStatus.BOOKED:
                promote_user_id = await promote_user_after_cancel(
                    call=None,
                    uc=uc,
                    cal_date=i.cal_date,
                    bot=bot,
                    user_id=user_id,
                    cancel_sub_status=cancel_sub_status,
                )
                if promote_user_id:
                    is_promoted = True
            elif i.status == BookingStatus.WAITLISTED:
                has_waitlist = True
                await uc.update_by_status(
                    i.cal_date,
                    BookingStatus.WAITLISTED,  # текущий
                    BookingStatus.WAITLISTED_MANUAL,
                    BookingStatus.CANCELED,  # Новый
                    cancel_sub_status
                )
            else:
                error_count += 1
        except (BookingError, DBError) as e:
            error_count += 1
            await _send_message(
                bot,
                user_id,
                f"<b>⚠️ Ошибка: {i.cal_date}</b>\n{str(e)}\n"
                f"На всякий случай проверь, пожалуйста, календарь",
            )
            continue

    real_cancel_count = cancel_dates_count - error_count

    if real_cancel_count == 0:
        return

    if cancel_dates_count == 1:
        if is_promoted or has_waitlist:
            await bot.edit_message_reply_markup(
                inline_message_id=inline_mess_id, reply_markup=None
            )

    action_mess = f"<b> ✅ Количество отменных записей: {real_cancel_count} из {cancel_dates_count}</b>"
    await _send_message(bot, user_id, action_mess)


# ---------------------------------------------- helpers ----------------------------------------------
async def _member_validate(user_id: int, bot: Bot) -> bool:
    member = await bot.get_chat_member(s.TG_CHAT_ID, user_id)
    if member.status not in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }:
        return False
    return True


def _article_id(data: str) -> Tuple[Optional[str], Optional[BookingStatus]]:
    try:
        cache_key, cancel_status = data.split("|")
        return cache_key, cancel_status
    except ValueError:
        return None, None


async def _fallback_answer(
    q: InlineQuery, error_title: str, error_response: str, error: str
):
    return await q.answer(
        results=[
            InlineQueryResultArticle(
                id="fallback",
                title=error_title,
                description=str(error),
                input_message_content=InputTextMessageContent(
                    message_text=error_response
                ),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Попробовать", switch_inline_query_current_chat=""
                            )
                        ]
                    ]
                ),
            )
        ],
        cache_time=0,
        is_personal=True,
    )


async def _send_message(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.exception("Не удалось отправить сообщение пользователю %s", user_id)
        return


"""
Отмена дня:
    - Бронь должна быть активна
Отмена диапазона:
    - Все брони должны быть активны
Обмен:
    - Бронь должна существовать (Если нет -> У вас нет брони на ДД.ММ для обмена)
    - Все места на желаемый день должны быть заняты (Если нет -> На ДД.ММ места есть. Отмените и забронируйте самостоятельно)
    - Не должно быть такого, что другой день хотите поменять на этот же 

"""
