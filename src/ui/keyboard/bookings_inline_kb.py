# from datetime import date, timedelta
from datetime import date
from typing import Dict, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.utils.idk import gen_idk
from src.utils.today import effective_today

PAGINATION_NUMS = {0: "₀", 1: "₁", 2: "₂", 3: "₃", 4: "₄", 5: "₅", 6: "₆", 7: "₇", 8: "₈", 9: "₉", ".": "․"}
# PAGINATION_NUMS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
# PAGINATION_NUMS = "₀₁₂₃₄₅₆₇₈₉"

def render_booking_week_kb(
        days: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        user_id: int,
        week_offset: int,
        help_page: Optional[int] = None
) -> InlineKeyboardMarkup:
    cap_by_wd: Dict[int, OfficeCapacityDTO] = {c.weekday: c for c in capacities}
    bookings_map: Dict[date, DateBookingsDTO] = {d.cal_date: d for d in days}

    today = effective_today()
    kb = InlineKeyboardBuilder()

    sorted_calendar = sorted(calendar, key=lambda x: x.cal_date)

    if week_offset >= 0:
        day_buttons = []
        for cal in sorted_calendar:
            day, wd = cal.cal_date, cal.cal_date.isoweekday()

            cap = cap_by_wd.get(wd)
            if cap is None:
                continue
            if day < today:
                continue
            if cal.is_holiday:
                continue
            if cal.is_weekend and not cal.is_workday:
                continue

            booked_cnt = 0
            user_has_booking = False
            user_in_waitlist = False

            day_bookings = bookings_map.get(day)
            if day_bookings:
                for u in day_bookings.users:
                    if u.status == BookingStatus.BOOKED:
                        booked_cnt += 1
                        if u.user_id == user_id:
                            user_has_booking = True
                    elif u.status == BookingStatus.WAITLISTED and u.user_id == user_id:
                        user_in_waitlist = True

            free_seats = cap.capacity - booked_cnt

            btn = _build_day_button(
                day=day,
                short=cap.short_name,
                free=free_seats,
                user_has_booking=user_has_booking,
                user_in_waitlist=user_in_waitlist,
            )
            day_buttons.append(btn)

        if day_buttons:
            kb.row(*day_buttons, width=7)

    week_start = week_end = None

    work_days = [day.cal_date for day in sorted_calendar if day.is_workday]
    if len(work_days) > 1:
        week_start, week_end = work_days[0], work_days[-1]
    else:
        week_start, week_end = sorted_calendar[0].cal_date, sorted_calendar[-1].cal_date
    kb.attach(_paginator_row(week_offset, week_start, week_end, help_page))

    kb.attach(_bottom_row(week_start, week_end))

    return kb.as_markup()


def _build_day_button(
        *,
        day: date,
        short: str,
        free: int,
        user_has_booking: bool,
        user_in_waitlist: bool,
) -> InlineKeyboardButton:
    if user_has_booking:
        text, step = f"✓ {short}", BookingStep.UNBOOK
    elif user_in_waitlist:
        text, step = f"🚪 {short}", BookingStep.LEAVEQ
    elif free <= 0:
        text, step = f"⌛ {short}", BookingStep.JOINQ
    else:
        text, step = short, BookingStep.BOOK

    callback_data = BookingCB(
        step=step,
        extra=day.isoformat(),
        idk=gen_idk()
    ).pack()

    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _paginator_row(
        offset: int,
        week_start: date,
        week_end: date,
        help_page: Optional[int] = None
) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()
    left, right = paginator_nums(offset)
    date_text = f"{week_start:%d.%m} - {week_end:%d.%m}"
    if help_page:
        date_text = f"• {week_start:%d.%m}-{week_end:%d.%m} •"
    row.row(
        InlineKeyboardButton(text=left, callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=str(offset - 1),
            idk=gen_idk(),
        ).pack()),
        InlineKeyboardButton(
            text=date_text,
            callback_data=BookingCB(
            step=BookingStep.WEEK_INFO,
            extra=f"{week_start:%d.%m} - {week_end:%d.%m}",
            idk=gen_idk(),
        ).pack(),
        ),
        InlineKeyboardButton(text=right, callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=str(offset + 1),
            idk=gen_idk()
        ).pack()),
    )
    return row

# Используется еще в settings_employee_kb.py
def paginator_nums(offset: int) -> tuple[str, str]:
    if offset == 0:
        return "←", "→"
    elif offset > 0:
        return "←", f"→ ₊{_convert_number(offset)}"
    else:
        return f"₋{_convert_number(offset)} ←", "→"

def _convert_number(num: int) -> str:
    if num == 0:
        return ""
    return "".join(PAGINATION_NUMS[int(digit)] for digit in str(abs(num)))

# def _paginator_nums(offset: int, today: date) -> tuple[str, str]:
#     current_monday = today - timedelta(days=today.weekday())
#     anchor_monday = current_monday + timedelta(days=offset * 7)
#
#     prev_monday = anchor_monday - timedelta(days=7)
#     next_monday = anchor_monday + timedelta(days=7)
#
#     def to_subscript(d: date) -> str:
#         text = f"{d.day:02d}.{d.month:02d}"
#         return text.translate(str.maketrans("0123456789", PAGINATION_NUMS))
#
#     return f"{to_subscript(prev_monday)} ←", f"→ {to_subscript(next_monday)}"


def _bottom_row(
        week_start: date,
        week_end: date
) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()

    row.row(
        InlineKeyboardButton(
            text="« Выйти",
            callback_data=BookingCB(step=BookingStep.GET_BACK_MENU, idk=gen_idk()).pack(),
        ),
        InlineKeyboardButton(text="ℹ️ Инструкция", callback_data=BookingCB(
            step=BookingStep.INFO,
            extra=f"{week_start:%d.%m} - {week_end:%d.%m}",
            idk=gen_idk()
        ).pack())
    )

    return row
