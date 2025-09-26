from config import settings
from src.dto.booking_dto import BookingStatus


def build_digest_message(date_bookings) -> str:

    header = "<b>📅 Бронирования на завтра</b>"

    contacts = f'<a href="https://t.me/{settings.BOT_USERNAME}?start=">@{settings.BOT_USERNAME}</a>'

    footer = (
        "<blockquote>У кого бронирование ожидает подтверждения — не забудьте "
        "подтвердить своё присутствие до <b>21:30 сегодня</b>.\n"
        "После этого места перейдут тем, кто в лист ожидания.\n"
        f"Для записи: {contacts}</blockquote>"
    )

    contacts_footer = f"Для записи: {contacts}"


    lines = []
    has_reserved = False

    for idx, u in enumerate(date_bookings.users, start=1):
        link = f'<a href="tg://user?id={u.user_id}">{u.full_name}</a>'

        sub = (u.sub_status or "").upper()
        if sub == BookingStatus.CONFIRMED:
            status_text = " — подтверждено ✅"
        else:
            status_text = ""
            has_reserved = True

        lines.append(f"{idx}. {link}{status_text}")

    body = "\n".join(lines) if lines else f"Пока никто не записался."

    if has_reserved:
        return f"{header}\n\n{body}\n\n{footer}"
    else:
        return f"{header}\n\n{body}\n\n{contacts_footer}"