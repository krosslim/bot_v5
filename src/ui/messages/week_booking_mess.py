from datetime import date
from typing import List

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.utils.tz_day import d_tz, dt_tz

from config import settings as s


def _plural_ru(n: int, form1: str, form2: str, form5: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return form5
    n %= 10
    if n == 1:
        return form1
    if 2 <= n <= 4:
        return form2
    return form5


def render_booking_week_mess(
        dates: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        user_id: int,
) -> str:
    cap_by_weekday = {c.weekday: c for c in capacities}
    bookings_by_date = {d.cal_date: d for d in dates}

    lines: List[str] = []
    today_dt = dt_tz()
    today = today_dt.date()
    today_weekday = today.weekday()

    for c_day in sorted(calendar, key=lambda x: x.cal_date):
        day = c_day.cal_date
        wd = day.isoweekday()
        day_str = f"{day:%d.%m}"
        c_info = cap_by_weekday.get(wd)

        if c_info is None:
            header = f"<b>{day_str}</b> <i>(нет данных)</i>"
            lines.append(f"{header}\n<blockquote expandable><i>Недоступно</i></blockquote>")
            continue

        if c_day.is_holiday and not c_day.is_weekend:
            header = f"<b>🌴 {c_info.short_name} {day_str}</b>"
            lines.append(f"{header}\n<blockquote expandable><i>Нерабочий день</i></blockquote>")
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

        base_header = f"{c_info.short_name} {day_str}"
        if day < today:
            p_was = _plural_ru(booked_count, "был", "было", "было")
            p_people = _plural_ru(booked_count, "человек", "человека", "человек")
            header = f"<b>{base_header}</b> <i>({p_was} {booked_count} {p_people})</i>"
        elif day == today and today_dt.hour >= s.WORK_END_HOUR:
            p_people = _plural_ru(booked_count, "человек", "человека", "человек")
            header = f"<b>{base_header}</b> <i>({booked_count} {p_people})</i>"
        else:
            base_header += _day_delta_str(day, today_weekday)
            if user_is_booked:
                header = f"<b>🟢 {base_header}</b>"
            elif free_seats > 0:
                p_seats = _plural_ru(free_seats, "место", "места", "мест")
                header = f"<b>⚪️ {base_header} • {free_seats} {p_seats}</b>"
            elif user_waitlist_pos:
                header = f"<b>🟡 {base_header} • №{user_waitlist_pos} в очереди</b>"
            else:
                header = f"<b>🔴 {base_header} • Нет мест</b>"

        if booked_list:
            users_block = "\n".join(f"{i}. {u.full_name}" for i, u in enumerate(booked_list, 1))
        else:
            users_block = "<i>Все места были свободны</i>" if day < today else "<i>Все места свободны</i>"

        lines.append(f"{header}\n<blockquote expandable>{users_block}</blockquote>")

    return "\n\n".join(lines)


def _day_delta_str(d: date, today_weekday: int) -> str:

    if d == d_tz(delta=1):
        return " (завтра)"
    elif today_weekday == 5 and d == d_tz(delta=2):
        return " (послезавтра)"
    elif today_weekday == 4 and d == d_tz(delta=3):
        return " (через 3 дня)"
    else:
        return ""
