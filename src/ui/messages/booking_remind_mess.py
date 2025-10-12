from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from config import settings as s
from src.dto.booking_dto import BookingStatus, DateBookingsDTO
from src.utils.tommorow import fmt_date_ru


def build_digest_message(bookings: DateBookingsDTO, capacity: int, cal_date: date) -> str:

    # --- HEADER ---
    header = f"<b>🗓️ На завтра ({fmt_date_ru(cal_date)})</b>\n\n"

    # --- BODY ---
    lines = []
    has_reserved = False

    if bookings:
        users_sorted = sorted(bookings.users, key=lambda u: 0 if u.sub_status == BookingStatus.CONFIRMED else 1)

        for idx, u in enumerate(users_sorted, start=1):

            if u.sub_status == BookingStatus.CONFIRMED:
                line = f"<b>{idx}. {u.full_name} ✅</b>"
            else:
                line = f'<b>{idx}. <a href="tg://user?id={u.user_id}">{u.full_name}</a></b>'
                has_reserved = True

            lines.append(line)

        filled = len(bookings.users)
        if filled < capacity:
            start = filled + 1
            end = capacity
            if end == start:
                lines.append(f"<b>{start}. <i>Свободно…</i></b>")
            else:
                lines.append(f"<b>{start}-{end}. <i>Свободно…</i></b>")

    else:
        lines.append(f"<b>1-{capacity}. <i>Все места свободны…</i></b>")

    body = "\n".join(lines)

    # --- FOOTER ---
    contacts = f'<a href="https://t.me/{s.BOT_USERNAME}?start=">🤖 БОТ</a>'
    google_sheet = f'<a href="{s.GOOGLE_SHEET_USER_URL}">📗 ТАБЛИЦА ПОСЕЩЕНИЙ</a>'
    additional_info = f"<b>{contacts} | {google_sheet}</b>"
    if has_reserved:
        footer = (
            "<blockquote>Для подтверждения брони — жми\n"
            "<b>ПОДТВЕРДИТЬ до 21:30</b>. Иначе отменится.\n"
            "Для брони свободного слота — жми\n"
            "<b>ЗАНЯТЬ МЕСТО</b>"
            "</blockquote>"
        ) + additional_info
    else:
        footer = additional_info

    return header + body + "\n\n" + footer


def build_digest_message_v2(bookings: DateBookingsDTO, capacity: int, cal_date: date) -> str:

    # --- HEADER ---
    header = f"<b>🗓️ На завтра ({fmt_date_ru(cal_date)})</b>\n"

    # --- BODY ---
    confirmed_title_default = "<blockquote><b>✅ Подтвердили присутствие</b></blockquote>"
    reserved_title  = f"<blockquote><b>🕒 Ожидаем подтверждение до {s.CANCEL_BOOKING_JOB_HOUR}:{s.CANCEL_BOOKING_JOB_MINUTES}</b></blockquote>"

    confirmed_lines: list[str] = []
    reserved_lines: list[str] = []

    users = getattr(bookings, "users", None) or []

    users_sorted = sorted(
        users,
        key=lambda u: (u.sub_status != BookingStatus.CONFIRMED, escape(u.full_name or "").lower())
    )

    for idx, u in enumerate(users_sorted, start=1):
        full_name_safe = escape(u.full_name or "—")
        if u.sub_status == BookingStatus.CONFIRMED:
            confirmed_lines.append(f"{idx}. {full_name_safe}")
        else:
            reserved_lines.append(f'{idx}. <a href="tg://user?id={u.user_id}">{full_name_safe}</a>')

    # --- Блок подтвержденных ---
    confirmed_block = ""
    if confirmed_lines:
        if len(confirmed_lines) == capacity:
            confirmed_title = "<blockquote><b>✅ Все подтвердили присутствие</b></blockquote>"
        else:
            confirmed_title = confirmed_title_default
        confirmed_block = f"{confirmed_title}\n" + "\n".join(confirmed_lines)

    # --- Блок ожидающих подтверждение ---
    reserved_block  = f"{reserved_title}\n"  + "\n".join(reserved_lines)  if reserved_lines  else ""

    # --- Свободные места ---
    filled = len(users_sorted)
    free_block: str
    if capacity <= 0:
        free_block = "<i>Емкость не задана.</i>"
    elif filled >= capacity:
        free_block = "<i>Свободных мест нет.</i>"
    else:
        start = filled + 1
        end = capacity
        if start == end:
            free_block = f"{start}. <i>Свободно…</i>"
        else:
            free_block = f"{start}-{end}. <i>Свободно…</i>"

    if not users_sorted and capacity > 0:
        free_block = f"1-{capacity}. <i>Все места свободны…</i>"


    # --- FOOTER ---
    contacts = f'<a href="https://t.me/{s.BOT_USERNAME}?start=">🤖 Бот ›</a>'
    google_sheet = f'<a href="{s.GOOGLE_SHEET_USER_URL}">📗 Таблица ›</a>'
    last_update = _get_updated_text()
    additional_info = f"<blockquote><b>{last_update} | {google_sheet} | {contacts}</b></blockquote>"

    parts = [header]
    if confirmed_block:
        parts += [confirmed_block, ""]
    if reserved_block:
        parts += [reserved_block, ""]
    parts += [free_block, "", additional_info]

    message = "\n".join(part for part in parts if part is not None)
    return message.strip()


# ----------------------------------------------helpers----------------------------------------------
def _get_updated_text() -> str:
    current_time = datetime.now(tz=ZoneInfo(s.MSC_TZ))
    formatted_time = current_time.strftime("%H:%M")
    return f"🔄 {formatted_time}"

