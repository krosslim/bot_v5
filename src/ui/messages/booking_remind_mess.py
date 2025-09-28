from datetime import date

from config import settings
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
    contacts = f'<a href="https://t.me/{settings.BOT_USERNAME}?start=">@{settings.BOT_USERNAME}</a>'
    contact_info = f"<b>🤖→ {contacts}</b>"
    if has_reserved:
        footer = (
            "<blockquote>Для подтверждения брони — жми\n"
            "<b>ПОДТВЕРДИТЬ до 21:30</b>. Иначе отменится.\n"
            "Для брони свободного слота — жми\n"
            "<b>ЗАНЯТЬ МЕСТО</b>"
            "</blockquote>"
        ) + contact_info
    else:
        footer = contact_info

    return header + body + "\n\n" + footer
