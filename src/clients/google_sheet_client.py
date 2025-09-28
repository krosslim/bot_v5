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

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(ssl=_ssl_ctx)
    headers = {"Content-Type": "application/json"}
    json_data = {
        "sheet": f"{sheet_name}",
        "token": f"{settings.GOOGLE_SHEET_TOKEN}",
        "users": user_data
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout_config, connector=connector) as session:
            async with session.post(url=settings.GOOGLE_SHEET_URL, json=json_data, headers=headers) as response:
                return await response.json()
    except aiohttp.ClientError as e:
        logger.exception(f"Ошибка клиента: {e}")
        return None
    except asyncio.TimeoutError:
        logger.exception("Таймаут запроса")
        return None
    except Exception as e:
        logger.exception(f"Неожиданная ошибка: {e}")
        return None
