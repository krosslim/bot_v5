from aiogram import Bot
from dishka import Provider, provide, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config

from src.clients.isdayoff_client import IsDayOffClient
from src.services.alert_service import AlertService
from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.services.tech_service import TechService
from src.services.user_service import UserService
from src.storage.redis.store import RedisStore
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.calendar_sync_use_case import CalendarSyncUseCase
from src.use_cases.sheet_template_use_case import SheetTemplateUseCase
from src.use_cases.user_use_case import UserUseCase
from src.use_cases.widget_use_case import WidgetUseCase


class UseCaseProvider(Provider):

    @provide(scope=Scope.REQUEST)
    def provide_booking_use_case(self,
                                 session: AsyncSession,
                                 booking: BookingService,
                                 office_capacity: OfficeCapacityService,
                                 calendar_dates: CalendarDatesService,
                                 user: UserService,
                                 tech: TechService,
                                 ) -> BookingUseCase:
        return BookingUseCase(session, booking, office_capacity, calendar_dates, user, tech)

    @provide(scope=Scope.REQUEST)
    def provide_user_use_case(self, user: UserService, session: AsyncSession) -> UserUseCase:
        return UserUseCase(user, session)

    @provide(scope=Scope.REQUEST)
    def provide_widget_use_case(self, bot: Bot, uc: BookingUseCase, tech: TechService, cfg: Config) -> WidgetUseCase:
        return WidgetUseCase(bot, uc, tech, cfg)

    @provide(scope=Scope.REQUEST)
    def provide_calendar_sync_use_case(
            self, session: AsyncSession, calendar: CalendarDatesService, booking: BookingService,
            client: IsDayOffClient, alerts: AlertService, store: RedisStore,
    ) -> CalendarSyncUseCase:
        return CalendarSyncUseCase(session, calendar, booking, client, alerts, store)

    @provide(scope=Scope.REQUEST)
    def provide_sheet_template_use_case(
            self, session: AsyncSession, calendar: CalendarDatesService, office_capacity: OfficeCapacityService,
            alerts: AlertService, cfg: Config,
    ) -> SheetTemplateUseCase:
        return SheetTemplateUseCase(session, calendar, office_capacity, alerts, cfg)
