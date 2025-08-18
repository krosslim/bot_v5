from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.user_dto import UserDTO
from src.services.exceptions import UserWarning
from src.services.user_service import UserService


class UserUseCase:
    def __init__(self, user: UserService, session: AsyncSession):
        self.user = user
        self.session = session

    async def check_exists(self, user_id: int) -> Optional[UserDTO]:
        async with self.session.begin():
            try:
                user = await self.user.get_user(user_id)
                return user
            except UserWarning:
                return None

    async def create_user(self, user_id: int, full_name: str) -> None:
        async with self.session.begin():
            await self.user.create_user(user_id, full_name)

    async def user_auto_confirm(self, user_id: int) -> bool:
        async with self.session.begin():
            return await self.user.get_user_auto_confirm(user_id)

    async def update_auto_confirm(self, user_id: int, auto_confirm: bool) -> None:
        async with self.session.begin():
            await self.user.update_auto_confirm(user_id, auto_confirm)



