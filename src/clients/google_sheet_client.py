import asyncio
import logging
import ssl
from typing import Optional, Dict, Any, List

import aiohttp
import certifi

from config import settings

logger = logging.getLogger(__name__)

_ssl_ctx = ssl.create_default_context(cafile=certifi.where())


async def update_sheet_data(
        sheet_name: str,
        user_data: List[Dict[Any, Any]],
        timeout: int = 10
) -> Optional[Dict[Any, Any]]:
    """
    Отправляет данные пользователей в Google Sheets.

    Args:
        sheet_name: Название листа
        user_data: Список данных пользователей
        timeout: Таймаут запроса в секундах

    Returns:
        Ответ от API или None в случае ошибки
    """

    # Валидация входных данных
    if not sheet_name or not isinstance(sheet_name, str):
        logger.error("Невалидное имя листа")
        return None

    if not user_data or not isinstance(user_data, list):
        logger.error("Невалидные данные пользователей")
        return None

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(ssl=_ssl_ctx, limit=100, limit_per_host=30)

    headers = {"Content-Type": "application/json"}

    json_data = {
        "sheet": sheet_name,
        "token": settings.GOOGLE_SHEET_TOKEN,
        "users": user_data
    }

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
                if response.status >= 400:
                    error_text = await response.text()
                    logger.error(
                        f"HTTP ошибка {response.status} при обновлении листа '{sheet_name}': {error_text}"
                    )
                    return None

                content_type = response.headers.get('Content-Type', '')
                if 'application/json' not in content_type:
                    logger.warning(
                        f"Неожиданный Content-Type: {content_type}. Ожидался JSON."
                    )

                try:
                    return await response.json()
                except aiohttp.ContentTypeError as e:
                    logger.error(f"Ошибка парсинга JSON ответа: {e}")
                    return None

    except asyncio.TimeoutError:
        logger.error(f"Таймаут запроса ({timeout}s) для листа '{sheet_name}'")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка клиента при обновлении листа '{sheet_name}': {e}")
        return None
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обновлении листа '{sheet_name}': {e}")
        return None