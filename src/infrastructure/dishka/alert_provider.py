from typing import AsyncGenerator

from aiogram import Bot
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.alert_service import AdminRecipients, AlertService
from src.storage.redis.store import RedisStore


class AlertProvider(Provider):

    @provide(scope=Scope.APP)
    async def provide_alert_service(
            self, bot: Bot, session_factory: async_sessionmaker[AsyncSession], store: RedisStore,
    ) -> AsyncGenerator[AlertService, None]:
        # Получатели — админы бота. Отдельный чат для алертов: ChatRecipients([chat_id])
        alerts = AlertService(bot, AdminRecipients(session_factory), store)
        await alerts.start()
        try:
            yield alerts
        finally:
            await alerts.stop()
