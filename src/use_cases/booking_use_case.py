from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.exceptions import FreePlaceIsAvailable
from src.services.office_capacity_service import OfficeCapacityService
from src.services.user_service import UserService


class BookingUseCase:

    def __init__(self,
                 session: AsyncSession,
                 booking: BookingService,
                 office_capacity: OfficeCapacityService,
                 calendar_dates: CalendarDatesService,
                 user: UserService):

        self.session = session
        self.booking = booking
        self.office_capacity = office_capacity
        self.calendar_dates = calendar_dates
        self.user = user

    async def booking_page_data(self, monday: date, friday: date) -> tuple:
        async with self.session.begin():
            active = await self.booking.get_active_bookings_by_range(monday, friday)
            capacity = await self.office_capacity.get_office_capacity()
            calendar = await self.calendar_dates.get_calendar_dates_by_range(monday, friday)
            return active, capacity, calendar

    async def book_place(self, user_id: int, cal_date: date) -> None:
        async with self.session.begin():
            auto_confirm = await self.user.get_user_auto_confirm(user_id)
            capacity = await self.office_capacity.get_weekday_capacity(cal_date.isoweekday())
            await self.booking.pre_check_booking(user_id, cal_date, capacity)
            await self.booking.create_booking(user_id, cal_date, auto_confirm)

    async def cancel_book_place(self, user_id: int, cal_date: date) -> Optional[int]:
        async with self.session.begin():
            promote_user_id = await self.booking.cancel_booking(user_id, cal_date)
            return promote_user_id

    async def waitlist_place(self, user_id: int, cal_date: date) -> None:
        async with self.session.begin():
            auto_confirm = await self.user.get_user_auto_confirm(user_id)
            capacity = await self.office_capacity.get_weekday_capacity(cal_date.isoweekday())
            is_join = await self.booking.join_queue(user_id, cal_date, auto_confirm, capacity)

        if not is_join:
            raise FreePlaceIsAvailable("✅ Место освободилось — ты записан!")

    async def cancel_waitlist_place(self, user_id: int, cal_date: date) -> None:
        async with self.session.begin():
            await self.booking.leave_from_queue(user_id, cal_date)










