"""Флаги, которые админ переключает в боте («Настройки → Меню админа → Виджеты»), без перезапуска.

Режим виджетов хранится в system_config (ключ widgets_mode) и держится в памяти: клавиатуры строятся часто,
ходить за ним в БД каждый раз незачем. Бот работает в одном экземпляре, поэтому копия в памяти всегда
актуальна — её меняет только set_mode. Строки нет → виджеты выключены.
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, FrozenSet, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.alert_service import Alert, AlertService
from src.storage.postgres.repository import Repository
from src.utils.db_exc_wrapper import DBError

logger = logging.getLogger(__name__)

WIDGETS_MODE_KEY = "widgets_mode"
ADMINS_TTL = 300                     # список админов для режима «только админам» обновляется раз в 5 минут


class WidgetsMode(StrEnum):
    OFF = "off"
    ADMINS = "admins"
    ALL = "all"


MODE_TITLES = {
    WidgetsMode.OFF: "выключены",
    WidgetsMode.ADMINS: "только админам",
    WidgetsMode.ALL: "всем",
}


@dataclass(frozen=True)
class WidgetsSetting:
    mode: WidgetsMode = WidgetsMode.OFF
    changed_by: Optional[str] = None
    changed_at: Optional[datetime] = None

    def dumps(self) -> str:
        return json.dumps({"mode": self.mode.value, "by": self.changed_by,
                           "at": self.changed_at.isoformat() if self.changed_at else None}, ensure_ascii=False)

    @classmethod
    def loads(cls, raw: Optional[str]) -> "WidgetsSetting":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {"mode": str(data)}
        except ValueError:
            data = {"mode": raw}                       # руками записали просто «all»
        try:
            mode = WidgetsMode(str(data.get("mode", "")).strip().lower())
        except ValueError:
            logger.error("feature_flags | непонятное значение %s=%r — виджеты выключены", WIDGETS_MODE_KEY, raw)
            return cls()
        at = data.get("at")
        try:
            changed_at = datetime.fromisoformat(at) if at else None
        except ValueError:
            changed_at = None
        return cls(mode, data.get("by"), changed_at)


class FeatureFlags:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], alerts: AlertService,
                 tz: str = "Europe/Moscow", clock: Callable[[], float] = time.monotonic):
        self.session_factory = session_factory
        self.tz = ZoneInfo(tz)
        self.alerts = alerts
        self.clock = clock
        self._widgets = WidgetsSetting()
        self._admins: FrozenSet[int] = frozenset()
        self._admins_at: Optional[float] = None

    # ------------------------------------------------------------------ чтение
    async def load(self) -> WidgetsSetting:
        """При старте бота. Если БД недоступна — виджеты выключены, бот работает на старых экранах"""
        try:
            async with self.session_factory() as session:
                raw = await Repository(session).get_system_value(WIDGETS_MODE_KEY)
            self._widgets = WidgetsSetting.loads(raw)
        except DBError:
            logger.error("feature_flags | не удалось прочитать %s — виджеты выключены", WIDGETS_MODE_KEY)
            self._widgets = WidgetsSetting()
        logger.info("feature_flags | виджеты: %s", MODE_TITLES[self._widgets.mode])
        return self._widgets

    @property
    def widgets(self) -> WidgetsSetting:
        return self._widgets

    @property
    def widgets_mode(self) -> WidgetsMode:
        return self._widgets.mode

    async def widgets_for(self, user_id: int) -> bool:
        """Показывать ли этому пользователю виджеты вместо старых экранов"""
        mode = self._widgets.mode
        if mode == WidgetsMode.ALL:
            return True
        if mode == WidgetsMode.OFF:
            return False
        return user_id in await self._admin_ids()

    async def _admin_ids(self) -> FrozenSet[int]:
        now = self.clock()
        if self._admins_at is not None and now - self._admins_at < ADMINS_TTL:
            return self._admins
        try:
            async with self.session_factory() as session:
                self._admins = frozenset(await Repository(session).active_admin_ids())
        except DBError:
            logger.warning("feature_flags | список админов не обновлён, используется прежний")
        self._admins_at = now
        return self._admins

    # ------------------------------------------------------------------ запись
    async def set_widgets_mode(self, mode: WidgetsMode, actor_name: str) -> bool:
        """Сохранить режим. False — он и так был таким. DBError пробрасывается: режим не меняется"""
        if mode == self._widgets.mode:
            return False
        previous = self._widgets.mode
        setting = WidgetsSetting(mode, actor_name, datetime.now(self.tz))
        async with self.session_factory() as session:
            async with session.begin():
                await Repository(session).set_system_value(WIDGETS_MODE_KEY, setting.dumps())
        self._widgets = setting
        self._admins_at = None                        # при включении «только админам» — свежий список
        logger.warning("feature_flags | виджеты: %s → %s", MODE_TITLES[previous], MODE_TITLES[mode])
        await self.alerts.notify(Alert(
            "Режим виджетов изменён",
            f"Виджеты: {MODE_TITLES[previous]} → {MODE_TITLES[mode]}",
            level=logging.WARNING,
        ))
        return True
