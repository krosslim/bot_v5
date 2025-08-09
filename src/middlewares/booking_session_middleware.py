import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from src.services.tech_service import TechService
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.utils.data import ContainerMiddlewareData


class BookingSessionMiddleware(BaseMiddleware):

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: CallbackQuery,
            data: ContainerMiddlewareData
    ) -> Any:

        user_id = event.from_user.id
        message_id = event.message.message_id
        current_timestamp = int(time.time())
        callback_data = BookingCB.unpack(event.data).step

        container = data["dishka_container"]
        tech_service = await container.get(TechService)

        if callback_data == BookingStep.GET_BACK_MENU:
            await tech_service.finish_booking_session(
                user_data=f"{user_id}:{message_id}",
            )
        else:
            await tech_service.start_booking_session(
                user_data=f"{user_id}:{message_id}",
                session_limit=current_timestamp,
            )

        return await handler(event, data)