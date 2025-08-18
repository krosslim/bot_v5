from src.dto.user_dto import UserDTO
from src.services.exceptions import UserNotFound
from src.storage.postgres.repository import Repository


class UserService:

    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_user(self, user_id: int) -> UserDTO:
        user = await self.repo.get_user_by_id(user_id)
        if user is None:
            raise UserNotFound
        return user

    async def create_user(self, user_id: int, full_name: str) -> None:
        user = await self.repo.get_user_by_id(user_id)
        if user is None:
            await self.repo.create_user(user_id, full_name)
        else:
            await self.repo.update_full_name(user_id, full_name)


    async def get_user_auto_confirm(self, user_id: int) -> bool:
        return await self.repo.user_auto_confirm(user_id)

    async def update_auto_confirm(self, user_id: int, auto_confirm: bool) -> None:
        return await self.repo.update_auto_confirm(user_id, auto_confirm)




