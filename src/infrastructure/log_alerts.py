"""Алерты в чат TG_ALERTS_CHAT_ID на записи лога уровня ERROR и выше.

Подключается в main.py к корневому логгеру. Записи уходят в AlertService.notify_nowait(): emit синхронный,
отправку делает фоновая задача сервиса.

Повторы: ключ — место вызова в коде (файл и строка) и тип исключения, а не текст сообщения. Логи в проекте
часто пишутся f-строками с меняющимися данными (статус, id, текст ответа), и по тексту одна и та же ошибка
выглядела бы каждый раз новой. С одного места алерт приходит не чаще раза в dedup_ttl (по умолчанию час):
сначала проверяет память процесса, затем Redis в AlertService (переживает перезапуск бота).
"""
import hashlib
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Sequence
from zoneinfo import ZoneInfo

from config import settings
from src.services.alert_service import Alert, AlertService, is_sending_alert

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEDUP_TTL = 3600
MAX_MESSAGE_CHARS = 1000
TRACEBACK_LINES = 15
IGNORED_LOGGERS = ("src.services.alert_service",)


def record_location(record: logging.LogRecord) -> str:
    path = Path(record.pathname)
    try:
        path = path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    return f"{path}:{record.lineno}"


def record_key(record: logging.LogRecord) -> str:
    exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    raw = f"{record.name}|{record.pathname}|{record.lineno}|{exc_type}"
    return "log:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _traceback_tail(record: logging.LogRecord) -> Optional[str]:
    if record.exc_info and record.exc_info[0]:
        text = "".join(traceback.format_exception(*record.exc_info))
    elif record.exc_text:
        text = record.exc_text
    else:
        return None
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-TRACEBACK_LINES:])


def build_alert(record: logging.LogRecord, key: str, dedup_ttl: int = DEDUP_TTL) -> Alert:
    message = record.getMessage()
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS - 1] + "…"
    when = datetime.fromtimestamp(record.created, ZoneInfo(settings.MSC_TZ))
    parts = [message]
    tail = _traceback_tail(record)
    if tail:
        parts.append(tail)
    parts.append(
        f"Где: {record_location(record)} ({record.funcName})\n"
        f"Когда: {when:%d.%m.%Y %H:%M:%S} МСК\n"
        f"Повторы с этого места — не чаще раза в {dedup_ttl // 60} мин."
    )
    return Alert(title=f"{record.levelname}: {record.name}", text="\n\n".join(parts), level=record.levelno,
                 key=key, dedup_ttl=dedup_ttl)


class AlertLogHandler(logging.Handler):
    def __init__(
            self,
            alerts: AlertService,
            level: int = logging.ERROR,
            dedup_ttl: int = DEDUP_TTL,
            ignored_loggers: Sequence[str] = IGNORED_LOGGERS,
    ):
        super().__init__(level)
        self.alerts = alerts
        self.dedup_ttl = dedup_ttl
        self.ignored_loggers = tuple(ignored_loggers)
        self._last_sent: Dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if is_sending_alert() or self._ignored(record.name):
                return
            key = record_key(record)
            now = time.monotonic()
            last = self._last_sent.get(key)
            if last is not None and now - last < self.dedup_ttl:
                return
            if self.alerts.notify_nowait(build_alert(record, key, self.dedup_ttl)):
                self._last_sent[key] = now
                self._forget_old(now)
        except Exception:
            self.handleError(record)    # пишет в stderr, а не в лог: так ошибка обработчика не зациклится

    def _ignored(self, name: str) -> bool:
        return any(name == n or name.startswith(n + ".") for n in self.ignored_loggers)

    def _forget_old(self, now: float) -> None:
        if len(self._last_sent) > 1000:
            self._last_sent = {k: t for k, t in self._last_sent.items() if now - t < self.dedup_ttl}
