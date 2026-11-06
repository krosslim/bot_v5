from aiogram.exceptions import TelegramBadRequest

# Ответы Telegram, которые означают не сбой, а обычную ситуацию: их пишем в лог как WARNING, без алерта
HARMLESS_BAD_REQUESTS = (
    "message is not modified",   # повторное нажатие: текст и клавиатура не изменились
    "query is too old",          # на callback ответили позже, чем через 15 секунд
)


def is_harmless_bad_request(e: TelegramBadRequest) -> bool:
    message = (e.message or "").lower()
    return any(pattern in message for pattern in HARMLESS_BAD_REQUESTS)
