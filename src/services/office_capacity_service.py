from typing import List

from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.storage.postgres.repository import Repository


class OfficeCapacityService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_office_capacity(self) -> List[OfficeCapacityDTO]:
        data = await self.repo.get_office_capacity()
        return data


