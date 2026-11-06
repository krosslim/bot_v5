"""Bot API 10.4: HTML-виджеты. Мост до появления поддержки в aiogram.

Имена методов и полей сверены с widget-sandbox: docs/tgw-format.md и scripts/conformance/test-bot.ts (v0.6.0).
Когда aiogram выпустит поддержку 10.4, модуль заменяется импортами из aiogram.methods / aiogram.types.
"""
from typing import Optional, Union

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNotFound
from aiogram.methods.base import TelegramMethod
from aiogram.types import Chat, Message, TelegramObject, Update, User
from pydantic import Field

WIDGET_QUERY_UPDATE = "widget_query"
SHARED_WIDGET_QUERY_UPDATE = "shared_widget_query"


class SendWidget(TelegramMethod[Message]):
    """Отправить виджет: один HTML-документ ≤ 32 КБ (≤ 4 КБ после zlib)."""

    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: Union[int, str]
    html: str
    width: Optional[int] = None
    height: Optional[int] = None
    allow_queries: Optional[bool] = None
    is_shared: Optional[bool] = None
    chat_data: Optional[str] = None
    public_data: Optional[str] = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    """Ответить на запрос виджета. data ≤ 1024 байт, вызвать в течение 15 секунд."""

    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: Optional[str] = None


class EditMessageWidgetData(TelegramMethod[Union[Message, bool]]):
    """Тихо обновить chat_data виджета (без пометки «изменено»), не чаще раза в секунду на сообщение."""

    __returning__ = Union[Message, bool]
    __api_method__ = "editMessageWidgetData"

    chat_id: Optional[Union[int, str]] = None
    message_id: Optional[int] = None
    inline_message_id: Optional[str] = None
    chat_data: Optional[str] = None
    public_data: Optional[str] = None


class WidgetQuery(TelegramObject):
    """Апдейт widget_query: пользователь нажал в виджете, виджет вызвал TelegramWidget.request(data)."""

    id: str
    from_user: User = Field(..., alias="from")
    data: str
    chat: Optional[Chat] = None
    message_id: Optional[int] = None
    inline_message_id: Optional[str] = None
    chat_instance: Optional[str] = None
    chat_type: Optional[str] = None
    widget_id: Optional[Union[int, str]] = None


async def widgets_supported(bot: Bot) -> bool:
    """Есть ли методы виджетов на этом адресе Bot API. Без побочных эффектов: ответ на несуществующий запрос.
    404 Not Found — метода нет (обычный Bot API до 10.4), 400 «query ID is invalid» — метод есть."""
    try:
        await bot(AnswerWidgetQuery(widget_query_id="0"))
    except TelegramNotFound:
        return False
    except TelegramAPIError:
        return True
    return True


def extract_widget_query(update: Update) -> Optional[WidgetQuery]:
    """aiogram не знает этот тип апдейта и складывает его в model_extra."""
    raw = (update.model_extra or {}).get(WIDGET_QUERY_UPDATE)
    if raw is None:
        return None
    return WidgetQuery.model_validate(raw)
