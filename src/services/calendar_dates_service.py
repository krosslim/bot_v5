from datetime import date
from typing import List

from aiocache import Cache
from aiocache.decorators import cached_stampede
from aiocache.serializers import PickleSerializer

from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.storage.postgres.repository import Repository


class CalendarDatesService:
    def __init__(self, repo: Repository):
        self.repo = repo

    @cached_stampede(
        ttl=60 * 60 * 24 * 7,
        lease=2,
        cache=Cache.MEMORY,
        namespace="calendar_dates",
        key_builder=lambda f, self, week_start, week_end: (
                f"calendar_dates:{week_start.isoformat()}:{week_end.isoformat()}"
        ),
        serializer=PickleSerializer(),
    )
    async def get_calendar_dates_by_range(self, week_start: date,
                                  week_end: date) -> List[CalendarDatesDTO]:
        data = await self.repo.get_calendar_dates_by_range(week_start, week_end)
        return data

    async def is_workday(self, cal_date: date) -> bool:
        return await self.repo.get_workday(cal_date)
