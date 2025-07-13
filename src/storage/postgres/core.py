from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)

from config import Config


def create_engine(cfg: Config) -> AsyncEngine:
    return create_async_engine(
        cfg.POSTGRES_URL,
        pool_timeout=cfg.POSTGRES_POOL_TIMEOUT,
        pool_recycle=cfg.POSTGRES_POOL_RECYCLE,
        pool_size=cfg.POSTGRES_POOL_SIZE,
        max_overflow=cfg.POSTGRES_MAX_OVERFLOW,
        pool_pre_ping=cfg.POSTGRES_POOL_PRE_PING,
        echo=cfg.POSTGRES_ECHO,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise