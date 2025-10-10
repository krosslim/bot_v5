import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    TelegramObject,
    CallbackQuery,
)

logger = logging.getLogger(__name__)


class ChatMembershipMiddleware(BaseMiddleware):

    def __init__(
            self,
            chat_id: int,
            *,
            deny_text: str = "⚠️ Доступ к боту запрещен",
    ):
        self.chat_id = chat_id
        self.deny_text = deny_text

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any | None:
        bot: Bot = data["bot"]

        from_user = getattr(event, "from_user", None)
        if not from_user:
            return await handler(event, data)
        user_id = from_user.id

        try:
            member = await bot.get_chat_member(self.chat_id, user_id)
            if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                return await self._deny(event)
            elif member.status == ChatMemberStatus.RESTRICTED:
                ok = bool(getattr(member, "is_member", False))
                if not ok:
                    return await self._deny(event)
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.exception("Bot is not a chat member | chat_id: %s", self.chat_id)
            return None

        return await handler(event, data)

    async def _deny(self, event: TelegramObject) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(text=self.deny_text, show_alert=True)
            except TelegramBadRequest:
                return None

        return None