from typing import AsyncGenerator

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from dishka import Provider, Scope, provide

from config import Config


def api_server(cfg: Config) -> TelegramAPIServer:
    """Адрес Bot API: обычный или бета (Bot API 10.4), на продовом или тестовом сервере Telegram"""
    base = cfg.TG_API_BASE.rstrip("/")
    test = "/test" if cfg.TG_TEST_ENV else ""
    return TelegramAPIServer(
        base=f"{base}/bot{{token}}{test}/{{method}}",
        file=f"{base}/file/bot{{token}}{test}/{{path}}",
    )


class BotProvider(Provider):

    @provide(scope=Scope.APP)
    async def bot(self, cfg: Config) -> AsyncGenerator[Bot, None]:
        bot = Bot(
            token=cfg.TOKEN,
            session=AiohttpSession(api=api_server(cfg)),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            yield bot
        finally:
            await bot.session.close()

    @provide(scope=Scope.APP)
    async def storage(self, cfg: Config) -> AsyncGenerator[RedisStorage, None]:
        storage = RedisStorage.from_url(cfg.REDIS_URL)
        try:
            yield storage
        finally:
            await storage.close()

    @provide(scope=Scope.APP)
    def dispatcher(self, storage: RedisStorage) -> Dispatcher:
        return Dispatcher(storage=storage)

