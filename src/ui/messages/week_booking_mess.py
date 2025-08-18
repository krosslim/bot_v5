from datetime import date
from typing import List

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO


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
    # Словари для быстрого доступа O(1)
    cap_by_weekday = {c.weekday: c for c in capacities}
    bookings_by_date = {d.cal_date: d for d in dates}
    holiday_map = {c.cal_date: (c.is_weekend or c.is_holiday) for c in calendar}

    lines: List[str] = []
    today = date.today()

    # Основной и единственный цикл по дням
    for c_day in sorted(calendar, key=lambda x: x.cal_date):
        day, wd = c_day.cal_date, c_day.cal_date.isoweekday()
        c_info = cap_by_weekday.get(wd)

        # Обработка дней без данных или праздников
        if c_info is None:
            header = f"<b>{day:%d.%m}</b> <i>(нет данных)</i>"
            lines.append(f"{header}\n<blockquote expandable><i>Недоступно</i></blockquote>")
            continue
        if holiday_map.get(day, False):
            header = f"<b>🌴 {c_info.short_name} {day:%d.%m}</b>"
            lines.append(f"{header}\n<blockquote expandable><i>ПРАЗДНИЧНЫЙ ДЕНЬ</i></blockquote>")
            continue

        # Получаем брони на этот день, или пустой объект, если их нет
        day_bookings = bookings_by_date.get(day, DateBookingsDTO(cal_date=day, users=[]))

        # Фильтруем и сортируем списки прямо здесь
        booked_list = sorted([u for u in day_bookings.users if u.status == BookingStatus.BOOKED],
                             key=lambda u: u.created_at)
        wait_list = sorted([u for u in day_bookings.users if u.status == BookingStatus.WAITLISTED],
                           key=lambda u: u.created_at)

        # Вычисляем статус текущего пользователя "на лету"
        user_is_booked = any(u.user_id == user_id for u in booked_list)
        user_waitlist_pos = next((idx for idx, u in enumerate(wait_list, 1) if u.user_id == user_id), None)

        booked_count = len(booked_list)
        free_seats = max(c_info.capacity - booked_count, 0)

        # --- Генерация заголовка ---
        base_header = f"<b>{c_info.short_name} {day:%d.%m}</b>"
        if day < today:
            p_was = _plural_ru(booked_count, "был", "было", "было")
            p_people = _plural_ru(booked_count, "человек", "человека", "человек")
            header = f"{base_header} <i>({p_was} {booked_count} {p_people})</i>"
        else:
            if user_is_booked:
                header = f"<b>🟢 {c_info.short_name} {day:%d.%m}</b>"
            elif free_seats > 0:
                p_seats = _plural_ru(free_seats, "место", "места", "мест")
                header = f"<b>⚪️ {c_info.short_name} {day:%d.%m} → {free_seats} {p_seats}</b>"
            elif user_waitlist_pos:
                header = f"<b>🟡 {c_info.short_name} {day:%d.%m} → Ты №{user_waitlist_pos} в очереди</b>"
            else:
                header = f"<b>🔴 {c_info.short_name} {day:%d.%m} → Нет мест</b>"

        # --- Генерация блока с пользователями ---
        if booked_list:
            users_block = "\n".join(u.full_name for u in booked_list)
        else:
            users_block = "<i>Все места были свободны</i>" if day < today else "<i>Все места свободны</i>"

        lines.append(f"{header}\n<blockquote expandable>{users_block}</blockquote>")

    return "\n\n".join(lines)
