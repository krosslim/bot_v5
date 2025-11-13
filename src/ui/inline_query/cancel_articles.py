from dataclasses import dataclass
from datetime import date
from typing import Iterable, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

from config import settings as s
from src.dto.booking_dto import BookingStatus, OwnBookingDTO
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.utils.tz_day import d_tz
from src.utils.idk import gen_idk

WEEKDAY_ACCUSATIVE_WITH_PREP = {
    0: "в понедельник",
    1: "во вторник",
    2: "в среду",
    3: "в четверг",
    4: "в пятницу",
    5: "в субботу",
    6: "в воскресенье",
}

def _weekday_phrase(target: date) -> str:
    return WEEKDAY_ACCUSATIVE_WITH_PREP[target.weekday()]

def human_phrase_one(target: date) -> str:
    today = d_tz()
    delta = (target - today).days

    if delta == 0:
        return "Коллеги, <b>сегодня</b> не смогу прийти в офис."
    if delta == 1:
        return "Коллеги, <b>завтра</b> не смогу прийти в офис."
    if 2 <= delta <= 6:
        return f"Коллеги, <b>{_weekday_phrase(target)} ({target.strftime('%d.%m')})</b> не смогу прийти в офис."
    return f"Коллеги, <b>{target.strftime('%d.%m')}</b> не смогу прийти в офис."


@dataclass(frozen=True)
class Reason:
    title: str
    status: BookingStatus
    description: str
    reason_text: str

DEFAULT_REASONS: tuple[Reason, ...] = (
    Reason("😷 Заболел",
           BookingStatus.CANCELED_ILL,
           "Нажмите, чтобы подтвердить",
           "Заболел 😷"),
    Reason("👨‍👩‍👧 Семейные обстоятельства",
           BookingStatus.CANCELED_FAMILY,
           "Нажмите, чтобы подтвердить",
           "Семейные обстоятельства 👨‍👩‍👧"),
    Reason("🌴 Отпуск",
           BookingStatus.CANCELED_VACATION,
           "Нажмите, чтобы подтвердить",
           "Буду в отпуске 🌴"),
    Reason("🤐 Без причины",
           BookingStatus.CANCELED_OTHER,
           "Нажмите, чтобы подтвердить. Сообщение отправится без причины отмены",
           ""),
)

def _make_article_single_date(
    *,
    title: str,
    status: BookingStatus,
    cal_date: date,
    cache_key: str,
    description: str,
    reason_text: str
) -> InlineQueryResultArticle:
    phrase = human_phrase_one(cal_date)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Занять слот",
                callback_data=ChatBookingCB(
                    step=ChatBookingStep.ADD_BOOKING_INLINE_CANCEL,
                    extra=f"{cal_date}",
                    idk=gen_idk()
                ).pack()
            )
        ]]
    )

    article_id = f"{cache_key}|{getattr(status, 'value', str(status))}"
    msg = f"{phrase} {getattr(reason_text, 'value', str(reason_text))}\nЗапись в боте отмена."
    return InlineQueryResultArticle(
        id=article_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text=msg),
        reply_markup=kb
    )

def _make_article_multi_date(
    *,
    title: str,
    status: BookingStatus,
    cache_key: str,
    description: str,
    reason_text: str,
    date_range_str: str
) -> InlineQueryResultArticle:
    phrase = f"Коллеги, <b>{date_range_str}</b> не смогу прийти в офис."

    article_id = f"{cache_key}|{getattr(status, 'value', str(status))}"
    contacts = f'<blockquote><b><a href="https://t.me/{s.BOT_USERNAME}?start=">Занять места ›</a></b></blockquote>'
    msg = (f"{phrase} {getattr(reason_text, 'value', str(reason_text))}\n"
           f"Все мои записи на этот период отмены.\n{contacts}")
    return InlineQueryResultArticle(
        id=article_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text=msg, disable_web_page_preview=True),
        reply_markup=None
    )


def build_cancel_reasons(
        bookings: List[OwnBookingDTO],
        cache_key: str,
        date_range: str = None,
        reasons: Iterable[Reason] = DEFAULT_REASONS,
) -> List[InlineQueryResultArticle]:

    if not bookings:
        return []

    dates = [getattr(b, "cal_date", None) for b in bookings]
    dates = [d for d in dates if isinstance(d, date)]
    if not dates:
        return []

    unique_dates = sorted(set(dates))
    is_single = len(unique_dates) == 1

    if is_single:
        cal_date = unique_dates[0]
        return [
            _make_article_single_date(
                title=r.title,
                status=r.status,
                cal_date=cal_date,
                cache_key=cache_key,
                description=r.description,
                reason_text=r.reason_text,
            ) for r in reasons
        ]
    else:
        return [
            _make_article_multi_date(
                title=r.title,
                status=r.status,
                cache_key=cache_key,
                description=r.description,
                reason_text=r.reason_text,
                date_range_str=date_range,
            ) for r in reasons
        ]