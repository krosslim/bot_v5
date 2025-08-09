from dishka import make_async_container

from config import settings
from src.infrastructure.dishka.bot_provider import BotProvider
from src.infrastructure.dishka.config_provider import ConfigProvider
from src.infrastructure.dishka.postgres_provider import PostgresProvider
from src.infrastructure.dishka.redis_provider import RedisProvider
from src.infrastructure.dishka.redis_store_provider import RedisStoreProvider
from src.infrastructure.dishka.repository_provider import RepositoryProvider
from src.infrastructure.dishka.scheduler_provider import SchedulerProvider
from src.infrastructure.dishka.service_provider import ServiceProvider
from src.infrastructure.dishka.use_case_provider import UseCaseProvider

container = make_async_container(
    ConfigProvider(settings),
    BotProvider(),
    PostgresProvider(),
    RedisProvider(),
    RedisStoreProvider(),
    RepositoryProvider(),
    ServiceProvider(),
    UseCaseProvider(),
    SchedulerProvider(),

)