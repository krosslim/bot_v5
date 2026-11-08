"""Метка «жив» для healthcheck контейнера (health.py).

Бот обновляет файл, пока работает его цикл событий; проверка смотрит только возраст файла. Раньше health.py сам
ходил в Telegram (getMe): отдельный процесс с импортом aiogram и новым TLS-соединением шёл ~10 с при таймауте 10 с
и во время деплоя, пока стартует бот, не укладывался ни разу. Модуль без зависимостей: health.py его импортирует.
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

LIVENESS_FILE = Path(os.getenv("LIVENESS_FILE", "/tmp/bot_alive"))
BEAT_EVERY = 15   # секунд между обновлениями метки
MAX_AGE = 60      # метка старше — цикл событий бота завис или бот не дошёл до polling

logger = logging.getLogger(__name__)


def beat(path: Path = LIVENESS_FILE) -> None:
    path.touch()


async def beat_forever(path: Path = LIVENESS_FILE, every: float = BEAT_EVERY) -> None:
    while True:
        try:
            beat(path)
        except OSError as e:
            logger.warning("liveness | не удалось обновить метку %s | %s", path, e)
        await asyncio.sleep(every)


def clear(path: Path = LIVENESS_FILE) -> None:
    """Штатная остановка: без метки healthcheck сразу видит, что бот не работает"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def is_alive(path: Path = LIVENESS_FILE, max_age: float = MAX_AGE, now: Optional[float] = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age
