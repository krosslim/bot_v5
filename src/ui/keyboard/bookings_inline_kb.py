from datetime import date
from typing import Dict, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.booking_dto import DateBookingsDTO, WeekAttendanceDTO
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.utils.idk import gen_idk

def get_booking_kb(
    days: List[DateBookingsDTO],
    capacities: List[OfficeCapacityDTO],
    calendar: List[CalendarDatesDTO],
    week_info: WeekAttendanceDTO,
    week_offset: int
) -> InlineKeyboardMarkup:

    # --- справочники -------------------------------------------------------
    cap_by_wd: Dict[int, OfficeCapacityDTO] = {c.weekday: c for c in capacities}
    holiday_map: Dict[date, bool] = {
        c.cal_date: (c.is_weekend or c.is_holiday) for c in calendar
    }
    bookings_map: Dict[date, DateBookingsDTO] = {d.cal_date: d for d in days}

    user_booked_dates = {b.cal_date for b in week_info.bookings}
    user_wait_dates = {w.cal_date for w in week_info.waitlist}

    today = date.today()
    weekday = today.weekday()

    # --- клавиатура --------------------------------------------------------
    kb = InlineKeyboardBuilder()

    if week_offset >= 0:

        for cal in sorted(calendar, key=lambda x: x.cal_date):
            day = cal.cal_date
            wd = day.isoweekday()  # 1 = Пн

            cap = cap_by_wd.get(wd)
            if cap is None or holiday_map.get(day, False):
                continue

            dto = bookings_map.get(day)
            booked_cnt = len(dto.users) if dto else 0
            free_seats = cap.capacity - booked_cnt

            if day >= today:

                btn = _build_day_button(
                    day=day,
                    short=cap.short_name,
                    free=free_seats,
                    user_has_booking=day in user_booked_dates,
                    user_in_waitlist=day in user_wait_dates,
                )
                kb.add(btn)

        kb.adjust(5)

    kb.attach(
        _paginator_row(
            week_offset,
            week_info.week_start,
            week_info.week_end,
        )
    )
    kb.attach(_bottom_row(week_offset, weekday))

    return kb.as_markup()


def _build_day_button(
    *,
    day: date,
    short: str,
    free: int,
    user_has_booking: bool,
    user_in_waitlist: bool,
) -> InlineKeyboardButton:
    iso = day.isoformat()

    if user_has_booking:
        text = f"✓ {short}"
        cb = BookingCB(step=BookingStep.UNBOOK,
                       extra=iso,
                       idk=gen_idk())

    elif user_in_waitlist:
        text = f"🚪 {short}"
        cb = BookingCB(step=BookingStep.LEAVEQ,
                       extra=iso,
                       idk=gen_idk())
    elif free == 0:
        text = f"⌛ {short}"
        cb = BookingCB(step=BookingStep.JOINQ,
                       extra=iso,
                       idk=gen_idk())
    else:
        text = short
        cb = BookingCB(step=BookingStep.BOOK,
                       extra=iso,
                       idk=gen_idk())

    return InlineKeyboardButton(text=text, callback_data=cb.pack())


def _paginator_row(
    offset: int,
    week_start: date,
    week_end: date,
) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()

    row.row(
        InlineKeyboardButton(text="←", callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=offset-1,
            idk=gen_idk(),
        ).pack()
                             ),
        InlineKeyboardButton(
            text=f"{week_start:%d.%m} - {week_end:%d.%m}",
            callback_data="#",
        ),
        InlineKeyboardButton(text="→", callback_data=BookingCB(
            step=BookingStep.PAGE,
            extra=offset+1,
            idk=gen_idk()
        ).pack()
                             ),
    )

    return row


def _bottom_row(week_offset: int, weekday: int) -> InlineKeyboardBuilder:
    row = InlineKeyboardBuilder()
    row.add(
        InlineKeyboardButton(
            text="« Выйти",
            callback_data=BookingCB(step=BookingStep.GET_BACK_MENU,
                                    idk=gen_idk()).pack(),
        ))
    if weekday >= 5 and week_offset == 0:
        week_offset = -1
    if week_offset >= 0:
        row.add(
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data=BookingCB(
            step=BookingStep.INFO,
            idk=gen_idk()
        ).pack(),
        ))
        row.adjust(2)

    return row