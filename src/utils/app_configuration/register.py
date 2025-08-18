import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.storage.postgres.models import SystemConfig

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class TaskSpec:
    key: str
    func: Callable[[AsyncSession], Awaitable[None]]
    description: Optional[str] = None


class SystemTask:
    _registry: Dict[str, TaskSpec] = {}

    @classmethod
    def register(cls, key: str, description: str | None = None):
        def deco(func: Callable[[AsyncSession], Awaitable[None]]):
            spec = TaskSpec(key=key, func=func, description=description)
            if key in cls._registry:
                raise ValueError(f"Task with key '{key}' already registered")
            cls._registry[key] = spec
            return func
        return deco

    @classmethod
    def all(cls) -> List[TaskSpec]:
        return list(cls._registry.values())


async def init_system_tasks(session: AsyncSession) -> None:

    try:
        async with session.begin():
            result = await session.execute(select(SystemConfig.key))
            done_keys = set(result.scalars().all())

        for spec in SystemTask.all():
            key = spec.key
            if key in done_keys:
                continue

            try:
                logger.info(f"Find new task key '{key}'")
                await spec.func(session)
            except Exception as e:
                logger.exception("System task %s is not done: %s", key, e)

    except Exception as e:
        logger.exception("System tasks are not done: %s", e)

