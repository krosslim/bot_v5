"""Настройки виджетов, которые админ меняет в боте («Настройки → Меню админа → Виджеты»), без перезапуска.

Все настройки хранятся одной JSON-строкой в system_config (ключ widgets) и держатся в памяти: клавиатуры
строятся часто, ходить за ними в БД каждый раз незачем. Бот работает в одном экземпляре, поэтому копия
в памяти всегда актуальна — её меняет только update_widgets. Строки нет → всё выключено, как раньше.
"""
import json
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.alert_service import Alert, AlertService
from src.storage.postgres.repository import Repository
from src.utils.db_exc_wrapper import DBError

logger = logging.getLogger(__name__)

WIDGETS_KEY = "widgets"
ADMINS_TTL = 300                     # список админов для режима «только админам» обновляется раз в 5 минут
MONTHS_CHOICES = (0, 1, 2, 3, 6, 12) # сколько месяцев листать в календаре; лишнее отрежется по лимиту chat_data
MAX_MONTHS = 12


class WidgetsMode(StrEnum):
    OFF = "off"
    ADMINS = "admins"
    ALL = "all"


MODE_TITLES = {
    WidgetsMode.OFF: "выключены",
    WidgetsMode.ADMINS: "только админам",
    WidgetsMode.ALL: "всем",
}


def months_title(n: int) -> str:
    return "нет" if n == 0 else f"{n} мес."


def digest_title(on: bool) -> str:
    return "виджетом" if on else "текстом"


def _months(value: Any) -> int:
    try:
        return min(max(int(value), 0), MAX_MONTHS)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class WidgetsSetting:
    mode: WidgetsMode = WidgetsMode.OFF     # виджеты в личке: выключены / только админам / всем
    digest: bool = False                    # дайджест в группе уходит виджетом (иначе текстом)
    history_months: int = 0                 # сколько прошлых месяцев можно листать в календаре (только просмотр)
    future_months: int = 0                  # сколько месяцев после текущего можно листать вперёд
    changed_by: Optional[str] = None
    changed_at: Optional[datetime] = None

    def dumps(self) -> str:
        return json.dumps({
            "mode": self.mode.value, "digest": self.digest,
            "history_months": self.history_months, "future_months": self.future_months,
            "by": self.changed_by, "at": self.changed_at.isoformat() if self.changed_at else None,
        }, ensure_ascii=False)

    @classmethod
    def loads(cls, raw: Optional[str]) -> "WidgetsSetting":
        """Нечитаемое значение не роняет бота: непонятные поля берутся по умолчанию (выключено)"""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {"mode": str(data)}
        except ValueError:
            data = {"mode": raw}                       # руками записали просто «all»
        try:
            mode = WidgetsMode(str(data.get("mode", "off")).strip().lower())
        except ValueError:
            logger.error("feature_flags | непонятный режим в %s=%r — виджеты выключены", WIDGETS_KEY, raw)
            mode = WidgetsMode.OFF
        at = data.get("at")
        try:
            changed_at = datetime.fromisoformat(at) if at else None
        except (TypeError, ValueError):
            changed_at = None
        return cls(mode, data.get("digest") is True, _months(data.get("history_months")),
                   _months(data.get("future_months")), data.get("by"), changed_at)

    def changes_from(self, old: "WidgetsSetting") -> List[str]:
        """Что поменялось — строки для алерта и лога"""
        out = []
        if self.mode != old.mode:
            out.append(f"Виджеты в личке: {MODE_TITLES[old.mode]} → {MODE_TITLES[self.mode]}")
        if self.digest != old.digest:
            out.append(f"Дайджест в группе: {digest_title(old.digest)} → {digest_title(self.digest)}")
        if self.history_months != old.history_months:
            out.append(f"Прошлые месяцы в календаре: {months_title(old.history_months)} → "
                       f"{months_title(self.history_months)}")
        if self.future_months != old.future_months:
            out.append(f"Месяцы вперёд в календаре: {months_title(old.future_months)} → "
                       f"{months_title(self.future_months)}")
        return out


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
        """При старте бота. Если БД недоступна — всё выключено, бот работает на старых экранах"""
        try:
            async with self.session_factory() as session:
                raw = await Repository(session).get_system_value(WIDGETS_KEY)
            self._widgets = WidgetsSetting.loads(raw)
        except DBError:
            logger.error("feature_flags | не удалось прочитать %s — виджеты выключены", WIDGETS_KEY)
            self._widgets = WidgetsSetting()
        w = self._widgets
        logger.info("feature_flags | виджеты: %s, дайджест: %s, календарь: назад %s, вперёд %s",
                    MODE_TITLES[w.mode], digest_title(w.digest), months_title(w.history_months),
                    months_title(w.future_months))
        return w

    @property
    def widgets(self) -> WidgetsSetting:
        return self._widgets

    @property
    def widgets_mode(self) -> WidgetsMode:
        return self._widgets.mode

    @property
    def digest_widget(self) -> bool:
        return self._widgets.digest

    @property
    def any_widgets(self) -> bool:
        """Работает ли хоть какой-то виджет: в личке или дайджест"""
        return self._widgets.mode != WidgetsMode.OFF or self._widgets.digest

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
    async def update_widgets(self, actor_name: str, **changes: Any) -> bool:
        """Поменять настройки: mode, digest, history_months, future_months. False — ничего не изменилось.
        DBError пробрасывается: настройки в памяти остаются прежними"""
        old = self._widgets
        if "history_months" in changes:
            changes["history_months"] = _months(changes["history_months"])
        if "future_months" in changes:
            changes["future_months"] = _months(changes["future_months"])
        new = replace(old, **changes)
        diff = new.changes_from(old)
        if not diff:
            return False
        new = replace(new, changed_by=actor_name, changed_at=datetime.now(self.tz))
        async with self.session_factory() as session:
            async with session.begin():
                await Repository(session).set_system_value(WIDGETS_KEY, new.dumps())
        self._widgets = new
        self._admins_at = None                        # при включении «только админам» — свежий список
        logger.warning("feature_flags | %s", "; ".join(diff))
        await self.alerts.notify(Alert("Настройки виджетов изменены", "\n".join(diff), level=logging.WARNING))
        return True
