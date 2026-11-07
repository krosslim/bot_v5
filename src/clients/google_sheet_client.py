import asyncio
import json
import logging
import re
import ssl
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlsplit

import aiohttp
import certifi

from config import settings

logger = logging.getLogger(__name__)

_ssl_ctx = ssl.create_default_context(cafile=certifi.where())

BODY_LOG_LIMIT = 800          # сколько символов ответа писать в лог
OK_STATUSES = {"ok", "success", "done", "updated"}


def _host(url: Any) -> str:
    """Только хост: в адресе Apps Script и в редиректе на googleusercontent есть ключи, их в лог не пишем."""
    return urlsplit(str(url)).netloc or "?"


def _short(text: str) -> str:
    """Текст ответа для лога: HTML-страницу ошибки Google сводим к видимому тексту."""
    if "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= BODY_LOG_LIMIT else text[:BODY_LOG_LIMIT] + "…"


def _looks_failed(data: Any) -> Optional[str]:
    """Признак ошибки в JSON-ответе скрипта (сам скрипт отвечает 200 даже при ошибке)."""
    if not isinstance(data, dict):
        return None
    if data.get("error") or data.get("errors"):
        return "в ответе есть поле error"
    if data.get("success") is False or data.get("ok") is False:
        return "success/ok = false"
    status = data.get("status")
    if isinstance(status, str) and status.lower() not in OK_STATUSES:
        return f"status = {status!r}"
    return None


async def update_sheet_data(
        sheet_name: str,
        user_data: List[Dict[Any, Any]],
        timeout: int = 10
) -> Optional[Dict[Any, Any]]:
    """
    Отправляет данные пользователей в Google Sheets (веб-приложение Apps Script, doPost).

    Args:
        sheet_name: Название листа
        user_data: Список данных пользователей
        timeout: Таймаут запроса в секундах

    Returns:
        Ответ от API или None в случае ошибки
    """

    if not sheet_name or not isinstance(sheet_name, str):
        logger.error("Невалидное имя листа")
        return None

    if not user_data or not isinstance(user_data, list):
        logger.error("Невалидные данные пользователей для листа '%s': %r", sheet_name, type(user_data).__name__)
        return None

    if not settings.GOOGLE_SHEET_URL:
        logger.error("GOOGLE_SHEET_URL не задан — лист '%s' не обновлён", sheet_name)
        return None
    if not settings.GOOGLE_SHEET_TOKEN:
        logger.warning("GOOGLE_SHEET_TOKEN пустой — скрипт, скорее всего, отклонит запрос")

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(ssl=_ssl_ctx, limit=100, limit_per_host=30)

    headers = {"Content-Type": "application/json"}

    json_data = {
        "sheet": sheet_name,
        "token": settings.GOOGLE_SHEET_TOKEN,
        "users": user_data
    }

    users_with_days = sum(1 for u in user_data if u.get("days"))
    days_total = sum(len(u.get("days") or []) for u in user_data)
    payload_bytes = len(json.dumps(json_data, ensure_ascii=False).encode())
    logger.debug(
        "sheet_update | → '%s' | POST %s | сотрудников %d (с бронями %d), отметок %d, %d байт",
        sheet_name, _host(settings.GOOGLE_SHEET_URL), len(user_data), users_with_days, days_total, payload_bytes,
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("sheet_update | '%s' | users=%s", sheet_name,
                     json.dumps(user_data, ensure_ascii=False)[:4000])

    started = time.monotonic()
    try:
        async with aiohttp.ClientSession(
                timeout=timeout_config,
                connector=connector,
                raise_for_status=False
        ) as session:
            async with session.post(
                    url=settings.GOOGLE_SHEET_URL,
                    json=json_data,
                    headers=headers
            ) as response:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                text = await response.text()
                content_type = response.headers.get('Content-Type', '')
                redirects = " → ".join(f"{r.status} {_host(r.url)}" for r in response.history) or "нет"
                logger.debug(
                    "sheet_update | ← '%s' | HTTP %s за %d мс | редиректы: %s | итоговый хост %s | %s | %d символов",
                    sheet_name, response.status, elapsed_ms, redirects, _host(response.url),
                    content_type or "без Content-Type", len(text),
                )

                if response.status >= 400:
                    logger.error(
                        "HTTP ошибка %s при обновлении листа '%s': %s", response.status, sheet_name, _short(text)
                    )
                    return None

                if 'application/json' not in content_type:
                    # Apps Script при исключении в doPost или без doPost отдаёт HTML-страницу с кодом 200
                    logger.error(
                        "Скрипт ответил не JSON при обновлении листа '%s' (Content-Type %s): %s",
                        sheet_name, content_type or "—", _short(text),
                    )
                    return None

                try:
                    data = json.loads(text)
                except ValueError as e:
                    logger.error("Ошибка парсинга JSON ответа для листа '%s': %s | %s", sheet_name, e, _short(text))
                    return None

                failed = _looks_failed(data)
                if failed:
                    logger.error("Скрипт сообщил об ошибке при обновлении листа '%s' (%s): %s",
                                 sheet_name, failed, _short(text))
                    return None
                logger.info("sheet_update | '%s' обновлён за %d мс | сотрудников %d, отметок %d | %s",
                            sheet_name, elapsed_ms, len(user_data), days_total, _short(text))
                return data

    except asyncio.TimeoutError:
        logger.error(f"Таймаут запроса ({timeout}s) для листа '{sheet_name}'")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка клиента при обновлении листа '{sheet_name}': {e}")
        return None
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обновлении листа '{sheet_name}': {e}")
        return None
