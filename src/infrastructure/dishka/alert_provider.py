from typing import AsyncGenerator

from aiogram import Bot
from dishka import Provider, Scope, provide

from config import Config
from src.services.alert_service import AlertService, ChatRecipients
from src.storage.redis.store import RedisStore


class AlertProvider(Provider):

    @provide(scope=Scope.APP)
    async def provide_alert_service(self, bot: Bot, cfg: Config, store: RedisStore) -> AsyncGenerator[AlertService, None]:
        # Все алерты уходят в отдельный чат TG_ALERTS_CHAT_ID (бот должен в нём состоять и иметь право писать)
        alerts = AlertService(bot, ChatRecipients([cfg.TG_ALERTS_CHAT_ID]), store)
        await alerts.start()
        try:
            yield alerts
        finally:
            await alerts.stop()
