from typing import Optional

from src.dto.user_dto import UserDTO
from src.storage.postgres.repository import Repository


class UserService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_user(self, tg_id: int) -> Optional[UserDTO]:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if user is None:
            return None
        return user

    async def create_user(self, tg_id: int, full_name: str) -> None:
        await self.repo.create_user(tg_id, full_name)





