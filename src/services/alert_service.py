"""Алерты в Telegram — общий сервис для любых уведомлений приложения.

Куда отправлять, решает AlertRecipients: сейчас это чат TG_ALERTS_CHAT_ID (см. AlertProvider).
Один экземпляр на приложение (Scope.APP): его можно получить из джоба, хендлера или стартового кода.

    alerts: AlertService = await container.get(AlertService)
    await alerts.notify(Alert("Заголовок", "текст", level=logging.ERROR, key="уникальный-ключ"))

Повторы: алерты с одинаковым key отправляются не чаще раза в dedup_ttl секунд (метка в Redis).
Синхронный код, например обработчик логов AlertLogHandler (src/infrastructure/log_alerts.py), вызывает
notify_nowait(): алерт кладётся в очередь, отправляет его фоновая задача. Свои сбои сервис пишет в лог
не выше WARNING, а всё, что логируется во время отправки, обработчик логов пропускает (is_sending_alert),
поэтому алерты на ERROR не зацикливаются на ошибках отправки алертов.
"""
import asyncio
import html
import logging
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from src.storage.redis.store import RedisStore

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 4096          # лимит Telegram на текст сообщения
MAX_TITLE_LEN = 200
ICONS = {logging.CRITICAL: "🔥", logging.ERROR: "❌", logging.WARNING: "⚠️", logging.INFO: "ℹ️"}

# Внутри notify: всё, что пишется в лог при отправке алерта (ошибки Redis, Telegram),
# не должно порождать новые алерты — иначе при сбое они пойдут по кругу
_sending_alert: ContextVar[bool] = ContextVar("sending_alert", default=False)


def is_sending_alert() -> bool:
    return _sending_alert.get()


@dataclass(frozen=True)
class Alert:
    title: str
    text: str = ""                  # обычный текст, экранируется при отправке
    level: int = logging.WARNING    # уровни logging: так же удобно передавать record.levelno из обработчика логов
    key: Optional[str] = None       # одинаковые алерты с этим key — не чаще раза в dedup_ttl секунд
    dedup_ttl: int = 3600


class AlertRecipients(Protocol):
    async def chat_ids(self) -> List[int]: ...


class ChatRecipients:
    """Фиксированный список чатов, например отдельная группа для алертов (TG_ALERTS_CHAT_ID)"""

    def __init__(self, chat_ids: Sequence[int]):
        self._chat_ids = list(chat_ids)

    async def chat_ids(self) -> List[int]:
        return list(self._chat_ids)


def _level_icon(level: int) -> str:
    for threshold in sorted(ICONS, reverse=True):
        if level >= threshold:
            return ICONS[threshold]
    return ICONS[logging.INFO]


def format_alert(alert: Alert) -> str:
    """HTML для Telegram: иконка уровня, жирный заголовок и текст. Длинный текст обрезается до лимита"""
    title = alert.title if len(alert.title) <= MAX_TITLE_LEN else alert.title[:MAX_TITLE_LEN - 1] + "…"
    head = f"{_level_icon(alert.level)} <b>{html.escape(title, quote=False)}</b>"
    body = (alert.text or "").strip()
    if not body:
        return head
    out = f"{head}\n\n{html.escape(body, quote=False)}"
    while len(out) > MAX_MESSAGE_LEN:
        body = body[:max(0, int(len(body) * 0.9) - 1)]
        out = f"{head}\n\n{html.escape(body, quote=False)}…"
    return out


class AlertService:
    def __init__(self, bot: Bot, recipients: AlertRecipients, store: RedisStore, queue_size: int = 100):
        self.bot = bot
        self.recipients = recipients
        self.store = store
        self.queue_size = queue_size
        self._queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------------------#
    #  Отправка
    # ---------------------------------------------------------------------------#
    async def notify(self, alert: Alert) -> int:
        """Отправить алерт сейчас. Возвращает, скольким получателям он ушёл (0 — повтор или ошибка)"""
        token = _sending_alert.set(True)
        try:
            return await self._notify(alert)
        finally:
            _sending_alert.reset(token)

    async def _notify(self, alert: Alert) -> int:
        if alert.key and not await self._first_in_window(alert):
            return 0
        try:
            chat_ids = await self.recipients.chat_ids()
        except Exception as e:
            logger.warning("alert | не удалось получить получателей «%s» | %s", alert.title, e)
            return 0
        if not chat_ids:
            logger.warning("alert | нет получателей для «%s»", alert.title)
            return 0

        text = format_alert(alert)
        sent = 0
        for chat_id in chat_ids:
            sent += await self._send(chat_id, text)
        return sent

    def notify_nowait(self, alert: Alert) -> bool:
        """Для синхронного кода и других потоков: алерт в очередь, отправит фоновая задача.
        False — сервис не запущен (start) или уже остановлен"""
        loop = self._loop
        if self._worker is None or loop is None or loop.is_closed():
            return False
        try:
            loop.call_soon_threadsafe(self._enqueue, alert)
        except RuntimeError:
            return False
        return True

    async def _first_in_window(self, alert: Alert) -> bool:
        try:
            return bool(await self.store.set_nx_key_ttl(f"alert:{alert.key}", alert.dedup_ttl))
        except Exception as e:
            # Без Redis повторы не отсечь, но потерять алерт хуже
            logger.warning("alert | Redis недоступен, отправляем без проверки повторов | %s", e)
            return True

    async def _send(self, chat_id: int, text: str) -> int:
        for attempt in (1, 2):
            try:
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
                                            disable_web_page_preview=True)
                return 1
            except TelegramRetryAfter as e:
                if attempt == 2:
                    logger.warning("alert | %s | лимит Telegram, алерт не отправлен", chat_id)
                    return 0
                await asyncio.sleep(min(e.retry_after, 30))
            except TelegramAPIError as e:
                logger.warning("alert | %s | не отправлен | %s", chat_id, e)
                return 0
        return 0

    # ---------------------------------------------------------------------------#
    #  Очередь для notify_nowait
    # ---------------------------------------------------------------------------#
    async def start(self) -> None:
        if self._worker is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._worker = asyncio.create_task(self._run(), name="alert-service")

    async def stop(self, flush_timeout: float = 5) -> None:
        """Остановить фоновую задачу, перед этим дав ей до flush_timeout секунд отправить очередь"""
        if self._worker is None:
            return
        # notify_nowait кладёт алерт в очередь через call_soon_threadsafe: даём циклу выполнить эти вызовы,
        # иначе join увидит пустую очередь и только что отправленные алерты потеряются
        await asyncio.sleep(0)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout=flush_timeout)
        self._worker.cancel()
        with suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    def _enqueue(self, alert: Alert) -> None:
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            logger.warning("alert | очередь переполнена, алерт «%s» отброшен", alert.title)

    async def _run(self) -> None:
        while True:
            alert = await self._queue.get()
            try:
                await self.notify(alert)
            except Exception as e:
                logger.warning("alert | ошибка отправки «%s» | %s", alert.title, e)
            finally:
                self._queue.task_done()
