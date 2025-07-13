from dishka import Provider, provide, Scope
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker
from redis.asyncio import Redis
from config import Config
from src.services.user_service import UserService
from src.storage.postgres.core import get_session, create_engine, build_session_factory
from typing import AsyncGenerator

from src.storage.postgres.repository import Repository


class PostgresProvider(Provider):

    @provide(scope=Scope.APP)
    def provide_config(self) -> Config:
        return Config()

    @provide(scope=Scope.APP)
    async def provide_engine(self, cfg: Config) -> AsyncGenerator[AsyncEngine, None]:
        engine = create_engine(cfg)
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def provide_session_factory(
            self, engine: AsyncEngine
    ) -> async_sessionmaker[AsyncSession]:
        return build_session_factory(engine)

    @provide(scope=Scope.REQUEST)
    async def provide_db_session(self, session_factory: async_sessionmaker[AsyncSession]) \
            -> AsyncGenerator[AsyncSession, None]:
        async with get_session(session_factory) as session:
            yield session


class RedisProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_redis(self, c: Config) -> AsyncGenerator[Redis, None]:
        redis = Redis.from_url(c.REDIS_URL, decode_responses=True)
        yield redis
        await redis.close()

class RepositoryProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> Repository:
        return Repository(session)

class ServiceProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_user_service(self, user_repository: Repository) -> UserService:
        return UserService(user_repository)

