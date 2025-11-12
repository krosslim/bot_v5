import re
from typing import List

from src.dto.user_dto import UserDTO, DictDTO
from src.services.exceptions import UserNotFound, FullNameIsIncorrect
from src.storage.postgres.repository import Repository


class UserService:

    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_user(self, user_id: int) -> UserDTO:
        user = await self.repo.get_user_by_id(user_id)
        if user is None:
            raise UserNotFound
        return user

    async def get_users(self,
                        limit: int,
                        offset: int,
                        profession_id: int = None
                        ) -> List[UserDTO]:
        return await self.repo.get_employees(limit, offset, profession_id)

    async def create_user(self, user_id: int, full_name: str,
                          profession_id: int, product_id: int) -> None:
        user = await self.repo.get_user_by_id(user_id)
        if user is None:
            await self.repo.create_user(user_id, full_name, profession_id, product_id)
        else:
            await self.repo.update_full_name(user_id, full_name)

    async def get_user_auto_confirm(self, user_id: int) -> bool:
        return await self.repo.user_auto_confirm(user_id)

    async def update_auto_confirm(self, user_id: int, auto_confirm: bool) -> None:
        return await self.repo.update_auto_confirm(user_id, auto_confirm)

    @staticmethod
    def check_full_name(full_name: str) -> bool:

        words = full_name.strip().split()
        if len(words) == 2 and all(re.match(r'^[а-яёА-ЯЁ]{2,}$', word) for word in words):
            return True
        else:
            raise FullNameIsIncorrect

    async def get_dict_data(self, dict_type: str) -> List[DictDTO]:
        return await self.repo.get_dict_data(dict_type)

    async def update_is_active(self, user_id: int, is_active: bool) -> int:
        return await self.repo.update_is_active(user_id, is_active)




