from typing import List

from src.dto.office_capacity_dto import OfficeCapacityDTO
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


