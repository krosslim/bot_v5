import asyncio
import logging
import sys

from aiogram import Dispatcher, Bot

from aiogram.client.default import DefaultBotProperties

from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods import DeleteWebhook
from aiogram.enums import ParseMode
from dishka.integrations.aiogram import setup_dishka

from config import Config


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout
    )


logger = logging.getLogger(__name__)

cfg = Config()
bot = Bot(token=cfg.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = RedisStorage.from_url(cfg.REDIS_URL)
dp = Dispatcher(storage=storage)


async def main() -> None:
    setup_logging()
    logger.info("Запуск бота…")
    try:
        await bot(DeleteWebhook(drop_pending_updates=True))

        # DI-контейнер:
        from src.infrastructure import di_container
        setup_dishka(di_container, dp, auto_inject=True)

        # handlers:
        from src.handlers import combined
        dp.include_router(combined)

        await dp.start_polling(bot)

    finally:
        logger.info("Закрытие соединений…")

        await dp.storage.close()
        await bot.session.close()
        await di_container.close()

        logger.info("Бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())