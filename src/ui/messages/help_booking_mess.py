from typing import List

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.utils.today import effective_today


def render_help_booking_mess(has_holiday: bool, has_available: bool) -> str:

    message = ("⚪️ — Места еще есть\n\n"
               "🟢 — Ты уже забронировал\n")

    if not has_available:
        message +=("───────────\n"
                "🔴 — Мест нет\nВстать в очередь: жми кнопку c ⏳\n\n"
                "🟡️ — Ты в очереди\nВыйти из очереди: жми кнопку с 🚪\n")
    if has_holiday:
        message +=("───────────\n"
                  "🌴 — Праздничный день")

    return message


def render_help_booking_mess2(
    dates: List[DateBookingsDTO],
    capacities: List[OfficeCapacityDTO],
    calendar: List[CalendarDatesDTO],
    user_id: int,
) -> str:
    free, user_booked, no_seat, user_waitlisted, holiday = _helper(dates, capacities, calendar, user_id)
    msg = ""
    if free:
        msg += "⚪️ — Есть свободное место\n\n"
    if user_booked:
        msg += "🟢 — У тебя есть бронь\n\n"
    if no_seat:
        msg += "🔴 — Мест нет\nВстать в очередь: жми кнопку c ⏳\n\n"
    if user_waitlisted:
        msg += "🟡️ — Ты в очереди\nВыйти из очереди: жми кнопку с 🚪\n\n"
    if holiday:
        msg += "🌴 — Праздничный день"

    return msg


def render_help_booking_mess3(
        dates: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        user_id: int,
) -> str:
    cap_by_weekday = {c.weekday: c for c in capacities}
    bookings_by_date = {d.cal_date: d for d in dates}

    lines: List[str] = []
    today = effective_today()

    for c_day in sorted(calendar, key=lambda x: x.cal_date):
        day = c_day.cal_date
        wd = day.isoweekday()
        day_str = f"{day:%d.%m}"
        c_info = cap_by_weekday.get(wd)

        if c_info is None:
            header = f"<b>{day_str}</b> <i>(нет данных)</i>"
            lines.append(f"{header}\n<blockquote><i>Недоступно</i></blockquote>")
            continue

        if c_day.is_holiday and not c_day.is_weekend:
            header = f"<b>🌴 {c_info.short_name} {day_str}</b>"
            lines.append(f"{header}\n<blockquote><i>Нерабочий день</i></blockquote>")
            continue

        if c_day.is_weekend and not c_day.is_workday:
            continue

        day_bookings = bookings_by_date.get(day)
        users = day_bookings.users if day_bookings else []

        booked_raw, waitlist_raw = [], []
        user_is_booked = False
        user_waitlist_pos = None

        for u in users:
            if u.status == BookingStatus.BOOKED:
                booked_raw.append(u)
                if u.user_id == user_id:
                    user_is_booked = True
            elif u.status == BookingStatus.WAITLISTED:
                waitlist_raw.append(u)

        wait_list = sorted(waitlist_raw, key=lambda u: u.updated_at)
        for idx, u in enumerate(wait_list, 1):
            if u.user_id == user_id:
                user_waitlist_pos = idx
                break

        booked_list = sorted(booked_raw, key=lambda u: (u.user_id != user_id, u.full_name))

        booked_count = len(booked_list)
        free_seats = max(c_info.capacity - booked_count, 0)

        if day < today:
            header = f"<b>{c_info.short_name} {day_str}</b>"
            info = "День прошел.\nЗапись недоступна"
        else:
            if user_is_booked:
                header = f"<b>🟢 {c_info.short_name} {day_str}</b>"
                info = f"У тебя есть бронь.\nДля отмены: жми <b>✓ {c_info.short_name}</b>"
            elif free_seats > 0:
                header = f"<b>⚪️ {c_info.short_name} {day_str}</b>"
                info = f"Есть свободные места.\nДля записи: жми <b>{c_info.short_name}</b>"
            elif user_waitlist_pos:
                header = f"<b>🟡 {c_info.short_name} {day_str}</b>"
                info = f"Ты в очереди.\nДля выхода: жми <b>🚪{c_info.short_name}</b>"
            else:
                header = f"<b>🔴 {c_info.short_name} {day_str}</b>"
                info = f"Мест нет.\nДля записи в очередь: жми <b>⏳{c_info.short_name}</b>"


        lines.append(f"{header}\n<blockquote>{info}</blockquote>")

    return "\n\n".join(lines)



# ---------------------------------------------- helpers ----------------------------------------------
def _helper(
        dates: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        user_id: int,
) -> tuple[bool, bool, bool, bool, bool]:
    free = user_booked = no_seat = user_waitlisted = holiday = False

    bookings_by_date = {d.cal_date: d for d in dates}
    # print(f"\n\nbookings_by_date:\n--------------\n{bookings_by_date}\n--------------\n")

    today = effective_today()
    # print(f"today:\n--------------\n{today}\n--------------\n")

    capacity_by_weekday = {c.weekday: c.capacity for c in capacities}
    # print(f"capacity_by_weekday:\n--------------\n{capacity_by_weekday}\n--------------\n")

    for c_day in sorted(calendar, key=lambda x: x.cal_date):

        # print(f"- c_day:{c_day.cal_date}")

        if c_day.is_holiday and not c_day.is_weekend:
            # print(f"  -- is_holiday:{c_day.is_holiday}")
            # print(f"  -- is_weekend:{c_day.is_weekend}")
            holiday = True

        if c_day.is_weekend or c_day.is_holiday:
            continue

        day_booking = bookings_by_date.get(c_day.cal_date)
        weekday = c_day.cal_date.isoweekday()
        # print(f"  -- weekday:{weekday}")
        office_capacity = capacity_by_weekday.get(weekday, 0)
        # print(f"  -- office_capacity:{office_capacity}")

        if day_booking:
            total_booked = len(day_booking.users)
            # print(f"  -- total_booked:{total_booked}")

            user_booking = next((u for u in day_booking.users if u.user_id == user_id), None)

            if user_booking:
                if c_day.cal_date >= today:
                    if user_booking.status == BookingStatus.BOOKED:
                        user_booked = True
                    elif user_booking.status == BookingStatus.WAITLISTED:
                        user_waitlisted = True

            else:
                if total_booked >= office_capacity:
                    no_seat = True
                else:
                    free = True

        else:
            if office_capacity > 0:
                free = True

    return free, user_booked, no_seat, user_waitlisted, holiday
