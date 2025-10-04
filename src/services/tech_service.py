import logging
from datetime import date
from typing import List, Optional

from src.dto.calendar_dates_dto import DigestScheduleDTO
from src.dto.user_dto import UserBookingSessionDTO
from src.storage.postgres.repository import Repository
from src.storage.redis.store import RedisStore

logger = logging.getLogger(__name__)

class TechService:
    def __init__(self, store: RedisStore, repo: Repository):
        self.store = store
        self.repo = repo


    async def set_throttling_key(self, user_id: int, idk: str, ttl: int) -> bool:
        key = f"throttle:{user_id}:{idk}"
        res = await self.store.set_nx_key_ttl(key, ttl)
        if res is None:
            return False
        return res


    async def start_booking_session(self, user_data: str, session_limit: int) -> None:
        return await self.store.z_add("booking_session", user_data, session_limit)


    async def finish_booking_session(self, user_data: str) -> None:
        res = await self.store.z_rem("booking_session", user_data)
        if not res:
            logger.warning(f"No booking session found for {user_data}")


    async def get_booking_session(self, session_limit) -> List[UserBookingSessionDTO]:

        res = await self.store.z_range_by_score(
            "booking_session", "-inf", session_limit)

        if not res:
            return []

        try:
            result = [
                UserBookingSessionDTO(
                    user_id=int(i.split(":")[0]),
                    message_id=int(i.split(":")[1]),
                )
                for i, k in res
            ]
            return result
        except (ValueError, IndexError):
            logger.exception(f"no valid data: {res}")
            return []


    async def finish_multiple_booking_sessions(self, data: List[UserBookingSessionDTO]) -> None:
        values = []
        for i, k in data:
            values.append(f"{i.user_id}:{i.message_id}")

        res = await self.store.z_rem_multiple("booking_session", *values)
        if not res:
            logger.warning(f"finish_multiple_booking_sessions | No booking session found for {data}")


    async def upsert_chat_message_id(self, cal_date: date, message_id: int) -> None:
        return await self.repo.upsert_chat_message_id(cal_date, message_id)

    async def get_chat_message_id(self, cal_date: date) -> int | None:
        return await self.repo.get_chat_message_id(cal_date)

    async def last_message(self) -> Optional[DigestScheduleDTO]:
        return await self.repo.get_last_message()
