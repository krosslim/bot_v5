from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from dishka.integrations.aiogram import CONTAINER_NAME

from src.handlers.widget.widget_query_handler import process_widget_query
from src.infrastructure.telegram.widgets import extract_widget_query


class WidgetQueryMiddleware(BaseMiddleware):
    """Перехватывает апдейт widget_query до диспетчера.

    aiogram до поддержки Bot API 10.4 (3.31 — это 10.3) не знает этот тип: кладёт его в Update.model_extra,
    а в _listen_update пропускает с предупреждением. Outer-middleware на dp.update срабатывает раньше и обрабатывает запрос сам.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            query = extract_widget_query(event)
            if query is not None:
                await process_widget_query(query, data["bot"], data[CONTAINER_NAME])
                return None
        return await handler(event, data)
