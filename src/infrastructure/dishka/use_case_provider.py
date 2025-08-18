from dishka import Provider, provide, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.services.user_service import UserService
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.user_use_case import UserUseCase


class UseCaseProvider(Provider):

    @provide(scope=Scope.REQUEST)
    def provide_booking_use_case(self,
                                 session: AsyncSession,
                                 booking: BookingService,
                                 office_capacity: OfficeCapacityService,
                                 calendar_dates: CalendarDatesService,
                                 user: UserService
                                 ) -> BookingUseCase:
        return BookingUseCase(session, booking, office_capacity, calendar_dates, user)

    @provide(scope=Scope.REQUEST)
    def provide_user_use_case(self, user: UserService, session: AsyncSession) -> UserUseCase:
        return UserUseCase(user, session)