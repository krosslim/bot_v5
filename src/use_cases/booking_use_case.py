from datetime import date
from typing import Optional, List, Tuple, Union

from sqlalchemy.ext.asyncio import AsyncSession
from src.dto.booking_dto import (
    OwnBookingDTO,
    BookingStatus,
    WaitlistPositionDTO,
    DateBookingsDTO,
)
from src.dto.user_dto import UserDTO
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.exceptions import FreePlaceIsAvailable, NoActiveBooking
from src.services.exceptions import UserWarn
from src.services.office_capacity_service import OfficeCapacityService
from src.services.tech_service import TechService
from src.services.user_service import UserService
from src.utils.is_autoconfirm import is_in_autoconfirm_period


class BookingUseCase:
    def __init__(
        self,
        session: AsyncSession,
        booking: BookingService,
        office_capacity: OfficeCapacityService,
        calendar_dates: CalendarDatesService,
        user: UserService,
        tech: TechService,
    ):
        self.session = session
        self.booking = booking
        self.office_capacity = office_capacity
        self.calendar_dates = calendar_dates
        self.user = user
        self.tech = tech

    async def booking_page_data(self, start: date, end: date) -> tuple:
        async with self.session.begin():
            # import time
            # st = time.time()
            active = await self.booking.get_active_bookings_by_range(start, end)
            capacity = await self.office_capacity.get_office_capacity()
            calendar = await self.calendar_dates.get_calendar_dates_by_range(start, end)
            # print(f"Время use case: {(time.time()-st)*1000:.2f} мс")
            # print()
            return active, capacity, calendar

    async def book_place(
        self, user_id: int, cal_date: date, auto_confirm: bool | None = None
    ) -> None:
        async with self.session.begin():
            if auto_confirm is None:
                if not is_in_autoconfirm_period(cal_date):
                    auto_confirm = await self.user.get_user_auto_confirm(user_id)
                else:
                    auto_confirm = True
            capacity = await self.office_capacity.get_weekday_capacity(
                cal_date.isoweekday()
            )
            await self.booking.pre_check_booking(user_id, cal_date, capacity)
            await self.booking.create_booking(user_id, cal_date, auto_confirm)

    async def cancel_book_place(
        self, user_id: int, cal_date: date, cancel_sub_status: str | None
    ) -> Optional[int]:
        async with self.session.begin():
            promote_user_id = await self.booking.cancel_booking(
                user_id, cal_date, cancel_sub_status
            )
            return promote_user_id

    async def waitlist_place(self, user_id: int, cal_date: date) -> None:
        async with self.session.begin():
            auto_confirm = await self.user.get_user_auto_confirm(user_id)
            capacity = await self.office_capacity.get_weekday_capacity(
                cal_date.isoweekday()
            )
            is_join = await self.booking.join_queue(
                user_id, cal_date, auto_confirm, capacity
            )

        if not is_join:
            raise FreePlaceIsAvailable("✅ Место освободилось — ты записан!")

    async def cancel_waitlist_place(self, user_id: int, cal_date: date) -> None:
        async with self.session.begin():
            await self.booking.leave_from_queue(user_id, cal_date)

    async def week_state(self, start: date, end: date) -> tuple:
        async with self.session.begin():
            data = await self.office_capacity.availability_by_range(start, end)

            has_holiday = False
            has_available = True

            for i in data:
                if i.is_holiday and not i.is_weekend:
                    has_holiday = True
                elif (not i.is_holiday) and (not i.is_available):
                    has_available = False
            return has_holiday, has_available

    async def own_active_bookings(
        self, user_id: int, today: date
    ) -> Tuple[List[OwnBookingDTO], List[WaitlistPositionDTO]]:
        async with self.session.begin():
            bookings = await self.booking.get_own_active_bookings(user_id, today)

            if not bookings:
                raise NoActiveBooking(
                    "❗️Активных записей нет\n\n"
                    "↓ Для бронирования жми ↓\n\n🆕 Забронировать место"
                )

            date_list = []
            wait_list_position = []

            for i in bookings:
                if i.status == BookingStatus.WAITLISTED:
                    date_list.append(i.cal_date)

            if date_list:
                wait_list_position = await self.booking.get_waitlist_position(
                    user_id, date_list
                )
                # Если есть данные по листу ожидания, то чистим bookings от WAITLISTED
                bookings = [
                    b
                    for b in bookings
                    if getattr(b, "status", None) == BookingStatus.BOOKED
                ]

            return bookings, wait_list_position

    async def my_bookings(
        self, user_id: int, cal_date: Union[date, Tuple[date, date], List[date]]
    ) -> List[OwnBookingDTO]:
        async with self.session.begin():
            return await self.booking.get_own_active_bookings(user_id, cal_date)

    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        async with self.session.begin():
            return await self.booking.confirm_booking(user_id, cal_date)

    async def chat_booking_data(self, cal_date: date) -> Tuple[DateBookingsDTO, int]:
        weekday = cal_date.isoweekday()
        bookings = await self.booking.get_bookings_for_remind(cal_date)
        if bookings:
            bookings = bookings[0]
        capacity = await self.office_capacity.get_weekday_capacity(weekday)
        return bookings, capacity

    async def get_user_for_chat_booking(self, user_id: int) -> Optional[UserDTO]:
        async with self.session.begin():
            try:
                user = await self.user.get_user(user_id)
                return user
            except UserWarn:
                return None

    async def user_booking_for_date(
        self, user_id: int, cal_date: date
    ) -> Optional[OwnBookingDTO]:
        return await self.booking.get_user_booking_for_day(user_id, cal_date)

    async def bookings_by_status(
        self,
        start: date,
        end: date,
        status_list: Union[str, List[str]],
        sub_status_list: Optional[Union[str, List[str]]] = None,
    ) -> List[DateBookingsDTO]:
        async with self.session.begin():
            return await self.booking.get_bookings_by_status(
                start, end, status_list, sub_status_list
            )

    async def update_by_status(
        self,
        cal_date: date,
        current_status: BookingStatus,
        current_sub_status: BookingStatus,
        status: BookingStatus,
        sub_status: BookingStatus,
    ) -> int:
        async with self.session.begin():
            return await self.booking.update_booking_status(
                cal_date, current_status, current_sub_status, status, sub_status
            )

    async def cache_key(self, bookings: List[OwnBookingDTO]) -> str:
        date_list = [d.cal_date.isoformat() for d in bookings]
        key = await self.tech.cache_cal_dates(date_list)
        return key

    async def dates_by_cache_key(self, key: str) -> List[date]:
        return await self.tech.dates_by_cache_key(key)
