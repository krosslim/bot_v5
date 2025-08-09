from datetime import date
from typing import List

from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.storage.postgres.repository import Repository


class CalendarDatesService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_calendar_dates_by_range(self, week_start: date,
                                  week_end: date) -> List[CalendarDatesDTO]:
        data = await self.repo.get_calendar_dates_by_range(week_start, week_end)
        return data