import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


class ExceptionMiddleware(BaseMiddleware):

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)

        except TelegramBadRequest as e:
            logger.error("Telegram API exception: %s", e, exc_info=False)

        except Exception as e:
            logger.exception("Unhandled exception: %s", e)
            await self._safe_reply(
                event,
                "<b>⚠️ Ошибка:</b> Что-то пошло не так.",
            )
            return None

    @staticmethod
    async def _safe_reply(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, Message):
                await event.answer(text)
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            if isinstance(event, Update) and event.message:
                await event.message.answer(text)
        except Exception as e:
            logger.warning("Cannot send error reply: %s", e, exc_info=True)