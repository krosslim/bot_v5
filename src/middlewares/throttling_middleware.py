from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from typing import Any, Awaitable, Callable, Dict
from src.services.tech_service import TechService
from src.ui.keyboard.actions import BookingCB, MenuCB
from src.utils.data import ContainerMiddlewareData


class ThrottlingMiddleware(BaseMiddleware):

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: CallbackQuery,
            data: ContainerMiddlewareData
    ) -> Any:
        user_id = event.from_user.id

        container = data["dishka_container"]
        tech_service = await container.get(TechService)

        try:
            idk = BookingCB.unpack(event.data).idk
        except ValueError:
            idk = MenuCB.unpack(event.data).idk

        set_key = await tech_service.set_throttling_key(
                user_id=user_id, idk=idk,ttl=3
        )

        if set_key is False:
            await event.answer()
            return

        return await handler(event, data)