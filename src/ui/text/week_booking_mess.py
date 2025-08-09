from datetime import date
from typing import Dict, List

from src.dto.booking_dto import DateBookingsDTO, WeekAttendanceDTO
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO


def render_week(
        dates: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        my_bookings: WeekAttendanceDTO,
) -> str:

    cap_by_weekday: Dict[int, OfficeCapacityDTO] = {
        c.weekday: c for c in capacities
    }
    bookings_by_date: Dict[date, DateBookingsDTO] = {d.cal_date: d for d in dates}
    holiday_map: Dict[date, bool] = {
        c.cal_date: (c.is_weekend or c.is_holiday) for c in calendar
    }
    my_bookings_map: Dict[date, int] = {w.cal_date: w.position for w in my_bookings.waitlist}
    user_booked_dates = {b.cal_date for b in my_bookings.bookings}


    lines: List[str] = []

    for c_day in sorted(calendar, key=lambda x: x.cal_date):
        day = c_day.cal_date
        today = date.today()
        wd = day.isoweekday()
        c_info = cap_by_weekday.get(wd)

        if c_info is None:
            continue

        if holiday_map.get(day, False):
            header = f"<b>🌴 {c_info.short_name} {day:%d.%m}</b>"
            users_block = "<i>ПРАЗДНИЧНЫЙ ДЕНЬ</i>"
            lines.append(f"{header}\n<blockquote expandable>{users_block}</blockquote>")
            continue

        dto = bookings_by_date.get(day)
        booked_count = len(dto.users) if dto else 0
        free_seats = c_info.capacity - booked_count
        users_block = ""

        if day < today:
            pre_plural = _plural_ru(booked_count, "был", "было", "было")
            plural = _plural_ru(booked_count, "человек", "человека", "человек")
            header = f"<b>{c_info.short_name} {day:%d.%m}</b> <i>({pre_plural} {booked_count} {plural})</i>"
        else:
            if free_seats > 0:
                plural = _plural_ru(free_seats, "место", "места", "мест")
                if day in user_booked_dates:
                    header = f"<b>🟢 {c_info.short_name} {day:%d.%m}</b>"
                else:
                    header = f"<b>⚪️ {c_info.short_name} {day:%d.%m} → {free_seats} {plural}</b>"
            else:
                pos = my_bookings_map.get(day)
                if pos:
                    header = (f"<b>🟡 {c_info.short_name} {day:%d.%m} → "
                              f"Ты №{pos} в очереди</b>")
                    # users_block = f"👉 🚪 {c_info.short_name}  <i>для выхода из очереди</i>\n"
                else:
                    if day in user_booked_dates:
                        header = f"<b>🟢 {c_info.short_name} {day:%d.%m}</b>"
                    else:
                        header = f"<b>🔴 {c_info.short_name} {day:%d.%m} → Нет мест</b>"
                        # users_block = f"👉 ⏳ {c_info.short_name}  <i>для записи в очередь</i>\n"

        if booked_count:
            users_block += "\n".join(u.full_name for u in dto.users)
        else:
            if day < today:
                users_block += "<i>Все места были свободны</i>"
            else:
                users_block += "<i>Все места свободны</i>"

        lines.append(f"{header}\n<blockquote expandable>{users_block}</blockquote>")

    return "\n\n".join(lines)


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