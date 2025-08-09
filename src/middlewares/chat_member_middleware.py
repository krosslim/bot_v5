from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    TelegramObject,
    Message,
    CallbackQuery,
)


class ChatMembershipMiddleware(BaseMiddleware):

    def __init__(self, chat_id: int):
        self.chat_id = chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any | None:
        bot: Bot = data["bot"]

        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        try:
            member = await bot.get_chat_member(self.chat_id, user_id)
            if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                await bot.send_message(
                    user_id,
                    "<b>⚠️ Ошибка:</b> Доступ к боту запрещен",
                )
                return None
        except TelegramBadRequest:
            await bot.send_message(
                user_id,
                "<b>⚠️ Ошибка:</b> Доступ к боту запрещен",
            )
            return None

        return await handler(event, data)