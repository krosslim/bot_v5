from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.utils.get_week_range import week_range


class BookingUseCase:

    def __init__(self,
                 booking: BookingService,
                 office_capacity: OfficeCapacityService,
                 calendar_dates: CalendarDatesService):

        self.booking = booking
        self.office_capacity = office_capacity
        self.calendar_dates = calendar_dates


    async def booking_page_data(self, week_offset: int, user_id: int) -> tuple:

        monday, friday, _ = week_range(week_offset)

        active = await self.booking.get_active_bookings_by_range(monday, friday)
        mine = await self.booking.get_user_bookings_by_range(user_id, monday, friday)
        caps = await self.office_capacity.get_office_capacity()
        cal = await self.calendar_dates.get_calendar_dates_by_range(monday, friday)

        return active, mine, caps, cal



