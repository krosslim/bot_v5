from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Config
from src.services.alert_service import AlertService
from src.services.feature_flags import FeatureFlags


class FeatureFlagsProvider(Provider):

    @provide(scope=Scope.APP)
    def provide_feature_flags(self, session_factory: async_sessionmaker[AsyncSession], alerts: AlertService,
                              cfg: Config) -> FeatureFlags:
        # Один экземпляр на всё время работы: режим держится в памяти, load() вызывается в main.py
        return FeatureFlags(session_factory, alerts, cfg.MSC_TZ)
