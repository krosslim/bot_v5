import re
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from src.services.tech_service import TechService
from src.utils.data import ContainerMiddlewareData


class ThrottlingMiddleware(BaseMiddleware):

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: CallbackQuery,
            data: ContainerMiddlewareData
    ) -> Any:
        user_id = event.from_user.id

        idk = re.search(r"[^:]*$", event.data).group()

        container = data["dishka_container"]
        tech_service = await container.get(TechService)

        set_key = await tech_service.set_throttling_key(
                user_id=user_id, idk=idk,ttl=2
        )

        if set_key is False:
            await event.answer()
            return

        return await handler(event, data)