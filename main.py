import asyncio
import logging
from functools import partial

from aiogram import Dispatcher, Bot
from aiogram.methods import DeleteWebhook
from aiogram.types import BotCommandScopeAllPrivateChats
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka.integrations.aiogram import setup_dishka
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config, setup_logging
from src.handlers import bot_combined_router
from src.infrastructure.dishka import container
from src.infrastructure.log_alerts import AlertLogHandler
from src.infrastructure.ops_alerts import RunMonitor, watch_missed_jobs
from src.infrastructure.telegram.widgets import WIDGET_QUERY_UPDATE, widgets_supported
from src.jobs.cron_jobs import sheet_template_job
from src.middlewares import setup_inner_middlewares, setup_outer_middlewares
from src.middlewares.widget_query_middleware import WidgetQueryMiddleware
from src.services.alert_service import AlertService
from src.storage.redis.store import RedisStore
from src.use_cases.calendar_sync_use_case import CalendarSyncUseCase
from src.utils.app_configuration.register import init_system_tasks
from src.utils.commands import get_commands_list


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    bot: Bot = await container.get(Bot)
    bot_info = await bot.get_me()
    dp: Dispatcher = await container.get(Dispatcher)
    settings: Config = await container.get(Config)

    # Записи лога ERROR и выше → алерт в TG_ALERTS_CHAT_ID (с одного места в коде не чаще раза в час)
    alerts: AlertService = await container.get(AlertService)
    alert_log_handler = AlertLogHandler(alerts)
    logging.getLogger().addHandler(alert_log_handler)

    setup_dishka(container=container, router=dp, auto_inject=True)

    await bot(DeleteWebhook(drop_pending_updates=True))

    setup_outer_middlewares(dp)
    setup_inner_middlewares(dp, settings.TG_CHAT_ID)
    dp.update.outer_middleware(WidgetQueryMiddleware())   # Bot API 10.4: запросы из виджетов

    dp.include_router(bot_combined_router)
    await bot.set_my_commands(get_commands_list(), scope=BotCommandScopeAllPrivateChats())

    if (settings.WIDGETS_ENABLED or settings.DIGEST_WIDGET_ENABLED) and not await widgets_supported(bot):
        logger.error(
            "Bot API по адресу %s не знает методы виджетов (sendWidget). Bot API 10.4 сейчас доступен "
            "на бете: TELEGRAM_API_BASE=https://api.telegram.org/beta. Пока это не исправлено, "
            "бот показывает старые экраны, а дайджест уходит текстом.",
            settings.TELEGRAM_API_BASE,
        )

    scheduler: AsyncIOScheduler = await container.get(AsyncIOScheduler)
    watch_missed_jobs(scheduler, alerts)        # алерт, если планировщик пропустил запуск во время работы
    scheduler.start()

    # Метка «жив» в Redis: при следующем старте видно, был ли сбой и какие задачи пришлись на простой
    run_monitor = RunMonitor(await container.get(RedisStore), alerts, scheduler)
    await run_monitor.start()

    async with container() as req:
        session: AsyncSession = await req.get(AsyncSession)
        await init_system_tasks(session)

    # Дни календаря на текущий и следующий год должны быть в БД до первых броней
    async with container() as req:
        try:
            calendar: CalendarSyncUseCase = await req.get(CalendarSyncUseCase)
            await calendar.sync(quick=True)
        except Exception:
            logger.exception("Синхронизация производственного календаря при старте не удалась")

    # Шаблоны листов в Google-таблице — в фоне через планировщик, чтобы не задерживать polling
    scheduler.add_job(partial(sheet_template_job, container), id="sheet_template_startup_job", replace_existing=True)

    try:
        logger.info("Инициализация бота: %s", bot_info)
        if settings.WIDGETS_ENABLED or settings.DIGEST_WIDGET_ENABLED:
            # widget_query aiogram не знает, поэтому сам его в allowed_updates не добавит
            await dp.start_polling(bot, allowed_updates=[*dp.resolve_used_update_types(), WIDGET_QUERY_UPDATE])
        else:
            await dp.start_polling(bot)

    finally:
        logger.info("Закрытие соединений…")
        await run_monitor.stop()
        logging.getLogger().removeHandler(alert_log_handler)
        await container.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())
