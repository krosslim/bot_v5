from datetime import date
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.user_dto import UserDTO, DictDTO
from src.services.booking_service import BookingService
from src.services.exceptions import UserWarn
from src.services.user_service import UserService


class UserUseCase:
    def __init__(self, user: UserService, booking: BookingService, session: AsyncSession):
        self.user = user
        self.booking = booking
        self.session = session

    async def check_exists(self, user_id: int) -> Optional[UserDTO]:
        async with self.session.begin():
            try:
                user = await self.user.get_user(user_id)
                return user
            except UserWarn:
                return None


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

    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        async with self.session.begin():
            booking_id = await self.booking.confirm_booking(user_id, cal_date)
            return booking_id

    async def get_professions(self) -> List[DictDTO]:
        return await self.user.get_dict_data('professions')

    async def get_products(self) -> List[DictDTO]:
        return await self.user.get_dict_data('products')


