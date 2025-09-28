from datetime import date
from typing import Optional, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.booking_dto import OwnBookingDTO, BookingStatus, WaitlistPositionDTO, DateBookingsDTO
from src.dto.user_dto import UserDTO
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.exceptions import FreePlaceIsAvailable, NoActiveBooking
from src.services.exceptions import UserWarn
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

    async def week_state(self, start: date, end: date) -> tuple:
        async with self.session.begin():
            data = await self.office_capacity.availability_by_range(start, end)

            has_holiday = False
            has_available = True

            for i in data:
                if i.is_holiday:
                    has_holiday = True
                elif (not i.is_holiday) and (not i.is_available):
                    has_available = False
            return has_holiday, has_available

    async def own_active_bookings(self, user_id: int) -> Tuple[List[OwnBookingDTO], List[WaitlistPositionDTO]]:
        async with self.session.begin():
            bookings = await self.booking.get_own_active_bookings(user_id)

            if not bookings:
                raise NoActiveBooking("❗️В настоящий момент у вас нет активных записей\n\n"
                                      "↓ Нажмите кнопку ↓\n\n🆕 Забронировать место\n\n ↑ для бронирования ↑")

            date_list = []
            wait_list_position = []

            for i in bookings:
                if i.status == BookingStatus.WAITLISTED:
                    date_list.append(i.cal_date)

            if date_list:
                wait_list_position = await self.booking.get_waitlist_position(user_id, date_list)
                # Если есть данные по листу ожидания, то чистим bookings от WAITLISTED
                bookings = [b for b in bookings if getattr(b, "status", None) == BookingStatus.BOOKED]

            return bookings, wait_list_position

    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        async with self.session.begin():
            return await self.booking.confirm_booking(user_id, cal_date)

    async def chat_booking_data(self, cal_date: date) -> Tuple[DateBookingsDTO, int]:

        weekday = cal_date.isoweekday()
        bookings = await self.booking.get_bookings_for_remind(cal_date)
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













