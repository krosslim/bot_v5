from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models import User


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

# -----------------------------USER-------------------------------------
    async def create_user(self, telegram_id: int) -> User:
        user = User(telegram_id=telegram_id)
        self.session.add(user)
        return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def check_user_exists(self, telegram_id: int) -> bool:
        result = await self.session.execute(
            select(User.telegram_id).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none() is not None


# -----------------------------NEXT-------------------------------------