"""Rich Messages (Bot API 10.1-10.3): проверка адреса Bot API и защита от пропавших кастомных эмодзи.

Сами методы есть в aiogram 3.31 (SendRichMessage, InputRichMessage, EditMessageText(rich_message=...)), мост
как для виджетов не нужен.
"""
import re
from typing import Any, Set

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.methods import SendRichMessage
from aiogram.types import InputRichMessage, Message

_EMOJI_ID = re.compile(r'emoji-id="(\d+)"')


async def rich_supported(bot: Bot) -> bool:
    """Знает ли Bot API по этому адресу Rich Messages. Без побочных эффектов: отправка в несуществующий чат 0.
    400 «chat not found» значит метод есть, 404 Not Found значит метода нет. Ошибку сервера (502 у бота,
    которого основной адрес после беты не обслуживает) и сетевую тоже считаем «нет»: включать Rich вслепую незачем"""
    try:
        await bot(SendRichMessage(chat_id=0, rich_message=InputRichMessage(html="<p>.</p>")))
    except TelegramBadRequest:
        return True
    except TelegramAPIError:
        return False
    except Exception:
        return False
    return True


def emoji_ids(html: str) -> Set[str]:
    """id кастомных эмодзи в отправляемом HTML"""
    return set(_EMOJI_ID.findall(html))


def _found_ids(node: Any, found: Set[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "custom_emoji" and node.get("custom_emoji_id"):
            found.add(str(node["custom_emoji_id"]))
        for value in node.values():
            _found_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _found_ids(value, found)


def missing_emoji(message: Any, html: str) -> Set[str]:
    """Какие кастомные эмодзи из отправленного HTML Telegram не показал. Без лишних запросов: sendRichMessage и
    editMessageText и так возвращают сообщение целиком. Эмодзи, который нельзя показать (удалён набор, неверный id,
    у владельца бота пропал Premium), сервер принимает без ошибки и молча заменяет подписью, поэтому нехватка id
    в ответе и есть заглушка. Ответ не сообщение (True у inline-сообщений) проверить нельзя: пустое множество"""
    if not isinstance(message, Message):
        return set()
    found: Set[str] = set()
    _found_ids(message.rich_message.model_dump() if message.rich_message else {}, found)
    return emoji_ids(html) - found
