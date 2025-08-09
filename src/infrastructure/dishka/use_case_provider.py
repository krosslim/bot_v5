from dishka import Provider, provide, Scope

from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.use_cases.booking_use_case import BookingUseCase


class UseCaseProvider(Provider):

    @provide(scope=Scope.REQUEST)
    def provide_booking_use_case(self,
                                 booking: BookingService,
                                 office_capacity: OfficeCapacityService,
                                 calendar_dates: CalendarDatesService
                                 ) -> BookingUseCase:
        return BookingUseCase(booking, office_capacity, calendar_dates)