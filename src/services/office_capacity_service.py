from datetime import date
from typing import List

from aiocache import Cache
from aiocache.decorators import cached_stampede
from aiocache.serializers import PickleSerializer

from src.dto.office_capacity_dto import OfficeCapacityDTO, AvailabilityDTO
from src.services.exceptions import NoCapacityInfo
from src.storage.postgres.repository import Repository


class OfficeCapacityService:
    def __init__(self, repo: Repository):
        self.repo = repo

    @cached_stampede(
        ttl=60 * 60 * 24 * 7,
        lease=2,
        cache=Cache.MEMORY,
        namespace="office_capacity",
        key_builder=lambda f, self: "office_capacity",
        serializer=PickleSerializer()
    )
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

