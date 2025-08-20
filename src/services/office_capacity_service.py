from typing import List
from datetime import date
from src.dto.office_capacity_dto import OfficeCapacityDTO, AvailabilityDTO
from src.services.exceptions import NoCapacityInfo
from src.storage.postgres.repository import Repository


class OfficeCapacityService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_office_capacity(self) -> List[OfficeCapacityDTO]:
        data = await self.repo.get_office_capacity()
        return data

    async def get_weekday_capacity(self, weekday: int) -> int:

        data = await self.repo.weekday_capacity(weekday)
        if data is None or data == 0:
            raise NoCapacityInfo("⚠️ Не удалось выполнить действие.\nЗа указанный день отсутствует информация о лимитах")
        return data

    async def availability_by_range(self, start: date, end: date) -> List[AvailabilityDTO]:
        data = await self.repo.get_availability(start, end)
        return data

