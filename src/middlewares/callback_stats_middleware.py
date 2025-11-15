import re
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from redis.asyncio import Redis

from src.utils.data import ContainerMiddlewareData
from src.utils.tz_day import d_tz


class CallbackStatsMiddleware(BaseMiddleware):

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: CallbackQuery,
            data: ContainerMiddlewareData
    ) -> Any:
        user_id = event.from_user.id
        step = re.search(r":([^:]*):", event.data).group(1)
        today = d_tz().isoformat()
        global_key = f"cb_stat:step:{today}"
        ttl_seconds = 31 * 24 * 60 * 60

        container = data["dishka_container"]
        redis = await container.get(Redis)

        pipe = redis.pipeline()

        pipe.hincrby(global_key, step, 1)
        pipe.expire(global_key, ttl_seconds)

        if user_id is not None:
            user_key = f"cb_stat:user:{user_id}:{today}"
            pipe.hincrby(user_key, step, 1)
            pipe.expire(user_key, ttl_seconds)

        await pipe.execute()

        return await handler(event, data)