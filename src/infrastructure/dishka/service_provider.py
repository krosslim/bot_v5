from dishka import Provider, provide, Scope

from src.services.booking_service import BookingService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.services.tech_service import TechService
from src.services.user_service import UserService
from src.storage.postgres.repository import Repository
from src.storage.redis.store import RedisStore


class ServiceProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_user_service(self, repo: Repository) -> UserService:
        return UserService(repo)

    @provide(scope=Scope.REQUEST)
    def provide_booking_service(self, repo: Repository) -> BookingService:
        return BookingService(repo)

    @provide(scope=Scope.REQUEST)
    def provide_office_capacity_service(self, repo: Repository) -> OfficeCapacityService:
        return OfficeCapacityService(repo)

    @provide(scope=Scope.REQUEST)
    def provide_calendar_dates_service(self, repo: Repository) -> CalendarDatesService:
        return CalendarDatesService(repo)

    @provide(scope=Scope.REQUEST)
    def provide_tech_service(self, store: RedisStore, repo: Repository) -> TechService:
        return TechService(store, repo)

