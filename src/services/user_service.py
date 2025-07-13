from src.storage.postgres.repository import Repository
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def check_user(self, telegram_id: int) -> bool:
        try:
            user = await self.repo.check_user_exists(telegram_id=telegram_id)
            if not user:
                await self.repo.create_user(telegram_id=telegram_id)
            return True
        except SQLAlchemyError as e:
            logger.error(e)
            return False

