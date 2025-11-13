from datetime import date, datetime

from src.dto.booking_dto import BookingStatus
from src.utils.tz_day import d_tz

_WEEKDAYS_RU = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')

def _fmt_day(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d} ({_WEEKDAYS_RU[d.weekday()]})"

def _ordinal_masc(n: int) -> str:
    return f"{n}-й"

def render_my_booking_mess(data) -> str:
    booked, waitlist = data

    if not booked and not waitlist:
        return "<b>В настоящий момент у вас нет активных записей</b>"

    today = d_tz()
    tomorrow = d_tz(delta=1)
    after_tomorrow = d_tz(delta=2)

    parts = []
    blocks_count = 0

    # --- Блок 1: Твои бронирования ---
    if booked:
        parts.append("🗓️ <b>Твои бронирования</b>\n")
        booked_sorted = sorted(booked, key=lambda x: x.cal_date)

        lines = []
        for b in booked_sorted:
            d = b.cal_date
            prefix = ""
            if d == today:
                prefix = "Сегодня, "
            elif d == tomorrow:
                prefix = "Завтра, "
            elif d == after_tomorrow:
                prefix = "Послезавтра, "
            line = f"• {prefix}<b>{_fmt_day(d)}</b>"
            if getattr(b, "sub_status", "") == "CONFIRMED":
                line += " ✅"
            lines.append(line + "\n")

        if len(booked_sorted) > 3:
            parts.append("<blockquote expandable>")
        else:
            parts.append("<blockquote>")
        parts.append("".join(lines))
        parts.append("</blockquote>\n")
        blocks_count += 1

    # --- Блок 2: Лист ожидания ---
    if waitlist:
        parts.append("⏳ <b>Лист ожидания</b>\n")

        wl_sorted = sorted(waitlist, key=lambda x: x.cal_date)
        if len(wl_sorted) > 3:
            parts.append("<blockquote expandable>")
        else:
            parts.append("<blockquote>")

        for w in wl_sorted:
            d = w.cal_date
            pos = getattr(w, "position", None)
            parts.append(f"• {_fmt_day(d)} — ты <b>{_ordinal_masc(pos)}</b>\n")

        parts.append("</blockquote>\n")
        blocks_count += 1

    # --- Нижний блок ---
    if blocks_count == 2:
        parts.append("Выбери, что хочешь изменить ⤵︎")
    else:
        parts.append("Выбери дату для редактирования ⤵︎")

    return "".join(parts)

def render_book_day_mess(date_str: str, sub_status: str) -> str:

    date_data = _fmt_day(datetime.strptime(date_str, "%Y-%m-%d").date())

    header = f"<b>📅 {date_data}</b>\n"

    if sub_status == BookingStatus.CONFIRMED:
        status = "Статус: <b>подтверждено</b> ✅\n\n"
    elif sub_status == BookingStatus.RESERVED:
        status = "Статус: <b>ожидает подтверждения</b>\n\n"
    else:
        status = f"Статус: <b>{sub_status}</b>\n\n"

    footer = "Выбери действие ⤵︎"

    return header + status + footer
