from typing import AsyncGenerator

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from dishka import Provider, Scope, provide

from config import Config


class BotProvider(Provider):

    @provide(scope=Scope.APP)
    async def bot(self, cfg: Config) -> AsyncGenerator[Bot, None]:
        bot = Bot(
            token=cfg.TOKEN,
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

