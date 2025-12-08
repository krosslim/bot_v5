from datetime import date
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.user_dto import UserDTO, DictDTO, UserStatisticsDTO
from src.services.exceptions import UserWarn
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
            except UserWarn:
                return None

    async def get_users(self,
                        limit: int,
                        offset: int,
                        profession_id: int = None
                        ) -> List[UserDTO]:
        async with self.session.begin():
            return await self.user.get_users(limit, offset, profession_id)

    async def create_user(self, user_id: int, full_name: str,
                          profession_id: int, product_id: int) -> None:
        async with self.session.begin():
            await self.user.create_user(user_id, full_name, profession_id, product_id)


    def check_full_name(self, full_name: str) -> Optional[bool]:
        if self.user.check_full_name(full_name):
            return True

    async def user_auto_confirm(self, user_id: int) -> bool:
        async with self.session.begin():
            return await self.user.get_user_auto_confirm(user_id)

    async def update_auto_confirm(self, user_id: int, auto_confirm: bool) -> None:
        async with self.session.begin():
            await self.user.update_auto_confirm(user_id, auto_confirm)

    async def update_is_active(self, user_id: int, is_active: bool) -> int:
        async with self.session.begin():
            return await self.user.update_is_active(user_id, is_active)

    async def get_professions(self) -> List[DictDTO]:
        return await self.user.get_dict_data('professions')

    async def get_products(self) -> List[DictDTO]:
        return await self.user.get_dict_data('products')

    async def set_visit_plan(self, user_id: int, week_visit_plan: int = None) -> None:
        async with self.session.begin():
            await self.user.set_visit_plan(user_id, week_visit_plan)

    async def visit_plan_report(
            self,
            start: date,
            end: date,
            profession_id: int = None
    ) -> List[UserStatisticsDTO]:
        async with self.session.begin():
            return await self.user.visit_plan_report(start, end, profession_id)
