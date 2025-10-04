from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import Provider, Scope, provide, AsyncContainer

from config import settings as s
from src.jobs import register_jobs


class SchedulerProvider(Provider):

    def __init__(self) -> None:
        super().__init__()
        self._tz = s.MSC_TZ

    @provide(scope=Scope.APP)
    async def scheduler(self, container: AsyncContainer) -> AsyncGenerator[AsyncIOScheduler, None]:
        sched = AsyncIOScheduler(timezone=self._tz)
        register_jobs(sched, container)
        try:
            yield sched
        finally:
            if sched.running:
                sched.shutdown(wait=False)