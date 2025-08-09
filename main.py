import asyncio
import logging

from aiogram import Dispatcher, Bot
from aiogram.methods import DeleteWebhook
from dishka.integrations.aiogram import setup_dishka
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config, setup_logging
from src.handlers import bot_combined_router
from src.infrastructure.dishka import container
from src.middlewares import setup_inner_middlewares, setup_outer_middlewares
from src.utils.commands import get_commands_list


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    bot: Bot = await container.get(Bot)
    dp: Dispatcher = await container.get(Dispatcher)
    settings: Config = await container.get(Config)

    setup_dishka(container=container, router=dp, auto_inject=True)

    await bot(DeleteWebhook(drop_pending_updates=True))

    setup_outer_middlewares(dp)
    setup_inner_middlewares(dp, settings.TG_CHAT_ID)

    dp.include_router(bot_combined_router)
    await bot.set_my_commands(get_commands_list())

    scheduler: AsyncIOScheduler = await container.get(AsyncIOScheduler)
    scheduler.start()

    try:
        logger.info("Запуск бота…")
        await dp.start_polling(bot)

    finally:
        logger.info("Закрытие соединений…")
        await container.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())