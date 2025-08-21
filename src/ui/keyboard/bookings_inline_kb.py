from datetime import date
from typing import Dict, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.utils.idk import gen_idk
from src.utils.today import effective_today


def render_booking_week_kb(
        days: List[DateBookingsDTO],
        capacities: List[OfficeCapacityDTO],
        calendar: List[CalendarDatesDTO],
        user_id: int,
        week_offset: int
) -> InlineKeyboardMarkup:
    cap_by_wd: Dict[int, OfficeCapacityDTO] = {c.weekday: c for c in capacities}
    holiday_map: Dict[date, bool] = {c.cal_date: (c.is_weekend or c.is_holiday) for c in calendar}
    bookings_map: Dict[date, DateBookingsDTO] = {d.cal_date: d for d in days}

    today = effective_today()
    kb = InlineKeyboardBuilder()

    sorted_calendar = sorted(calendar, key=lambda x: x.cal_date)

    if week_offset >= 0:
        day_buttons = []
        for cal in sorted_calendar:
            day, wd = cal.cal_date, cal.cal_date.isoweekday()

            cap = cap_by_wd.get(wd)
            if cap is None or holiday_map.get(day, False) or day < today:
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
            kb.row(*day_buttons, width=5)

    if sorted_calendar:
        week_start = sorted_calendar[0].cal_date
        week_end = sorted_calendar[-1].cal_date
        kb.attach(_paginator_row(week_offset, week_start, week_end))

    kb.attach(_bottom_row(week_offset, today.weekday()))

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
) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()
    row.row(
        InlineKeyboardButton(text="←", callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=str(offset - 1),
            idk=gen_idk(),
        ).pack()),
        InlineKeyboardButton(
            text=f"{week_start:%d.%m} - {week_end:%d.%m}",
            callback_data="#",
        ),
        InlineKeyboardButton(text="→", callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=str(offset + 1),
            idk=gen_idk()
        ).pack()),
    )
    return row


def _bottom_row(week_offset: int, weekday: int) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()
    row.add(
        InlineKeyboardButton(
            text="« Выйти",
            callback_data=BookingCB(step=BookingStep.GET_BACK_MENU, idk=gen_idk()).pack(),
        )
    )
    # if weekday >= 4 and week_offset == 0:
    #     week_offset = -1
    #
    if week_offset > -1:
        row.add(
            InlineKeyboardButton(text="ℹ️ Инструкция", callback_data=BookingCB(
                step=BookingStep.INFO,
                idk=gen_idk()
            ).pack()),
        )
    row.adjust(2 if week_offset > -1 else 1)
    return row
