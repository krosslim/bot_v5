"""Клиент производственного календаря isdayoff.ru.

GET https://isdayoff.ru/api/getdata?year=YYYY → по символу на день года: 1 — нерабочий, 0 — рабочий.
Ошибки приходят телом ответа: 100 — неверная дата (HTTP 400), 101 — данных нет (HTTP 404, например год,
на который ещё нет постановления о переносах), 199 — ошибка сервиса.
"""
import asyncio
import logging
import ssl
from typing import Optional

import aiohttp
import certifi

logger = logging.getLogger(__name__)

ISDAYOFF_URL = "https://isdayoff.ru/api/getdata"
USER_AGENT = "bot_v5-calendar-sync"

_ssl_ctx = ssl.create_default_context(cafile=certifi.where())


class IsDayOffError(Exception):
    """isdayoff.ru недоступен или ответил ошибкой"""


class IsDayOffClient:
    def __init__(self, url: str = ISDAYOFF_URL):
        self.url = url

    async def fetch_year(self, year: int, timeout: float = 10, attempts: int = 3) -> Optional[str]:
        """Строка флагов на год. None — у сервиса нет данных на этот год (код 101).
        Сеть и ответы 5xx повторяются с паузой; остальные ошибки — сразу IsDayOffError"""
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return await self._request(year, timeout)
            except _Retryable as e:
                last_error = e.__cause__ or e
                logger.warning("isdayoff.ru %s | попытка %s/%s | %s", year, attempt, attempts, last_error)
                if attempt < attempts:
                    await asyncio.sleep(2 * attempt)
        raise IsDayOffError(f"isdayoff.ru {year}: нет ответа после {attempts} попыток: {last_error}") from last_error

    async def _request(self, year: int, timeout: float) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    connector=aiohttp.TCPConnector(ssl=_ssl_ctx),
                    headers={"User-Agent": USER_AGENT},
            ) as session:
                async with session.get(self.url, params={"year": str(year)}) as response:
                    body = (await response.text()).strip()
                    status = response.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise _Retryable() from e

        if status == 200:
            return body
        if body == "101":
            return None
        if status >= 500 or body == "199":
            raise _Retryable() from IsDayOffError(f"HTTP {status}: {body[:50]}")
        raise IsDayOffError(f"isdayoff.ru {year}: HTTP {status}: {body[:50]}")


class _Retryable(Exception):
    pass
