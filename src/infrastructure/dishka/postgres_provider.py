from typing import AsyncGenerator

from dishka import Provider, provide, Scope
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker

from config import Config
from src.storage.postgres.core import get_session, create_engine, build_session_factory


class PostgresProvider(Provider):

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
    async def provide_db_session(self, session_factory: async_sessionmaker[AsyncSession]
                                 ) -> AsyncGenerator[AsyncSession, None]:
        async with get_session(session_factory) as session:
            yield session