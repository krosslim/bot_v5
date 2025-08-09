from typing import AsyncGenerator
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import Provider, Scope, provide, AsyncContainer

from src.jobs import register_jobs


class SchedulerProvider(Provider):
    """Создаёт AsyncIOScheduler, регистрирует cron-задачи и гасит его при shutdown."""

    def __init__(self, tz: str = "Europe/Moscow") -> None:
        super().__init__()
        self._tz = tz

    @provide(scope=Scope.APP)
    async def scheduler(self, container: AsyncContainer) -> AsyncGenerator[AsyncIOScheduler, None]:
        sched = AsyncIOScheduler(timezone=self._tz)
        register_jobs(sched, container)
        try:
            yield sched
        finally:
            sched.shutdown(wait=False)