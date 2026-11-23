"""Настройки бронирования в личке и виджетов, которые админ меняет в боте («Настройки → Меню админа → Виджеты»),
без перезапуска. Сюда же входит руководитель на схеме зала: сотрудник, чьё имя стоит на месте руководителя.

Все настройки хранятся одной JSON-строкой в system_config (ключ widgets) и держатся в памяти: клавиатуры
строятся часто, ходить за ними в БД каждый раз незачем. Бот работает в одном экземпляре, поэтому копия
в памяти всегда актуальна: её меняет только update_widgets. Строки нет → базовый способ, как раньше.
"""
import json
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.alert_service import Alert, AlertService
from src.ui.widgets.state import short_name
from src.storage.postgres.repository import Repository
from src.utils.db_exc_wrapper import DBError

logger = logging.getLogger(__name__)

WIDGETS_KEY = "widgets"
ADMINS_TTL = 300                     # список админов для режима «только админам» обновляется раз в 5 минут
MONTHS_CHOICES = (0, 1, 2, 3, 6, 12) # сколько месяцев листать в календаре; лишнее отрежется по лимиту chat_data
MAX_MONTHS = 12


class BookingUi(StrEnum):
    """Способ бронирования в личке"""
    BASIC = "basic"      # недельное расписание и «Мои брони»
    WIDGETS = "widgets"  # HTML-виджет Bot API 10.4 (src/ui/widgets/booking.html)
    RICH = "rich"        # календарь Rich Message вместо главного меню (src/ui/rich/booking.py)


class Audience(StrEnum):
    """Кому доступен способ бронирования. Остальные видят базовый"""
    ALL = "all"
    ADMINS = "admins"


UI_TITLES = {
    BookingUi.BASIC: "базовый",
    BookingUi.WIDGETS: "виджеты",
    BookingUi.RICH: "Rich",
}
AUDIENCE_TITLES = {
    Audience.ALL: "всем",
    Audience.ADMINS: "только админам",
}

# Прежнее поле mode (выключены / только админам / всем) → способ и аудитория
LEGACY_MODES: Dict[str, Tuple[BookingUi, Audience]] = {
    "off": (BookingUi.BASIC, Audience.ADMINS),
    "admins": (BookingUi.WIDGETS, Audience.ADMINS),
    "all": (BookingUi.WIDGETS, Audience.ALL),
}


def legacy_mode(ui: BookingUi, audience: Audience) -> str:
    """Значение прежнего поля mode: пишется рядом с новыми, чтобы откат на старую версию бота не включил лишнего.
    Rich старая версия не знает, для неё это «выключены»"""
    if ui == BookingUi.WIDGETS:
        return audience.value
    return "off"


def months_title(n: int) -> str:
    return "нет" if n == 0 else f"{n} мес."


def digest_title(on: bool) -> str:
    return "виджетом" if on else "текстом"


def scheme_title(on: bool) -> str:
    """Вид экрана дня в Rich: схема стола из стульев в заголовке блока или кнопки мест под таблицей имён"""
    return "стулья в заголовке" if on else "кнопки мест"


def boss_title(name: Optional[str]) -> str:
    return short_name(name) if name else "не выбран"


def _user_id(value: Any) -> Optional[int]:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _months(value: Any) -> int:
    try:
        return min(max(int(value), 0), MAX_MONTHS)
    except (TypeError, ValueError):
        return 0


def _ui_and_audience(data: Dict[str, Any], raw: str) -> Tuple[BookingUi, Audience]:
    if "ui" in data:
        try:
            ui = BookingUi(str(data["ui"]).strip().lower())
        except ValueError:
            logger.error("feature_flags | непонятный способ бронирования в %s=%r: базовый", WIDGETS_KEY, raw)
            return BookingUi.BASIC, Audience.ADMINS
        try:
            audience = Audience(str(data.get("audience", Audience.ADMINS)).strip().lower())
        except ValueError:
            logger.error("feature_flags | непонятная аудитория в %s=%r: только админам", WIDGETS_KEY, raw)
            audience = Audience.ADMINS
        return ui, audience
    mode = str(data.get("mode", "off")).strip().lower()
    if mode not in LEGACY_MODES:
        logger.error("feature_flags | непонятный режим в %s=%r: базовый способ", WIDGETS_KEY, raw)
        return BookingUi.BASIC, Audience.ADMINS
    return LEGACY_MODES[mode]


@dataclass(frozen=True)
class WidgetsSetting:
    ui: BookingUi = BookingUi.BASIC         # способ бронирования в личке: базовый / виджеты / Rich
    audience: Audience = Audience.ADMINS    # кому этот способ: всем или только админам (остальным базовый)
    digest: bool = False                    # дайджест в группе уходит виджетом (иначе текстом)
    history_months: int = 0                 # сколько прошлых месяцев можно листать в календаре (только просмотр)
    future_months: int = 0                  # сколько месяцев после текущего можно листать вперёд
    boss_id: Optional[int] = None           # руководитель на схеме зала (users.user_id)
    boss_name: Optional[str] = None         # его ФИО на момент выбора — для экрана админки и алертов;
                                            # виджеты берут актуальное имя из users по boss_id
    changed_by: Optional[str] = None
    changed_at: Optional[datetime] = None
    rich_scheme: bool = False               # экран дня в Rich: стулья в заголовке (иначе кнопки мест)

    def dumps(self) -> str:
        return json.dumps({
            "ui": self.ui.value, "audience": self.audience.value,
            "mode": legacy_mode(self.ui, self.audience), "digest": self.digest,
            "history_months": self.history_months, "future_months": self.future_months,
            "boss_id": self.boss_id, "boss_name": self.boss_name, "rich_scheme": self.rich_scheme,
            "by": self.changed_by, "at": self.changed_at.isoformat() if self.changed_at else None,
        }, ensure_ascii=False)

    @classmethod
    def loads(cls, raw: Optional[str]) -> "WidgetsSetting":
        """Нечитаемое значение не роняет бота: непонятные поля берутся по умолчанию (базовый способ).
        Старая строка с полем mode читается без потерь: off → базовый, admins → виджеты только админам,
        all → виджеты всем"""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {"mode": str(data)}
        except ValueError:
            data = {"mode": raw}                       # руками записали просто «all»
        ui, audience = _ui_and_audience(data, raw)
        at = data.get("at")
        try:
            changed_at = datetime.fromisoformat(at) if at else None
        except (TypeError, ValueError):
            changed_at = None
        boss_id = _user_id(data.get("boss_id"))
        return cls(ui, audience, data.get("digest") is True, _months(data.get("history_months")),
                   _months(data.get("future_months")), boss_id, data.get("boss_name") if boss_id else None,
                   data.get("by"), changed_at, rich_scheme=data.get("rich_scheme") is True)

    def changes_from(self, old: "WidgetsSetting") -> List[str]:
        """Что поменялось — строки для алерта и лога"""
        out = []
        if self.ui != old.ui:
            out.append(f"Способ бронирования в личке: {UI_TITLES[old.ui]} → {UI_TITLES[self.ui]}")
        if self.audience != old.audience:
            out.append(f"Кому способ бронирования: {AUDIENCE_TITLES[old.audience]} → "
                       f"{AUDIENCE_TITLES[self.audience]}")
        if self.digest != old.digest:
            out.append(f"Дайджест в группе: {digest_title(old.digest)} → {digest_title(self.digest)}")
        if self.history_months != old.history_months:
            out.append(f"Прошлые месяцы в календаре: {months_title(old.history_months)} → "
                       f"{months_title(self.history_months)}")
        if self.future_months != old.future_months:
            out.append(f"Месяцы вперёд в календаре: {months_title(old.future_months)} → "
                       f"{months_title(self.future_months)}")
        if self.rich_scheme != old.rich_scheme:
            out.append(f"Экран дня в Rich: {scheme_title(old.rich_scheme)} → {scheme_title(self.rich_scheme)}")
        if self.boss_id != old.boss_id:
            out.append(f"Руководитель на схеме: {boss_title(old.boss_name)} → {boss_title(self.boss_name)}")
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
        """При старте бота. Если БД недоступна, всё выключено: бот работает на базовых экранах"""
        try:
            async with self.session_factory() as session:
                raw = await Repository(session).get_system_value(WIDGETS_KEY)
            self._widgets = WidgetsSetting.loads(raw)
        except DBError:
            logger.error("feature_flags | не удалось прочитать %s: базовый способ, виджеты выключены", WIDGETS_KEY)
            self._widgets = WidgetsSetting()
        w = self._widgets
        logger.info("feature_flags | бронирование в личке: %s, %s; дайджест: %s; календарь: назад %s, вперёд %s",
                    UI_TITLES[w.ui], AUDIENCE_TITLES[w.audience], digest_title(w.digest), months_title(w.history_months),
                    months_title(w.future_months))
        return w

    @property
    def widgets(self) -> WidgetsSetting:
        return self._widgets

    @property
    def booking_ui(self) -> BookingUi:
        """Способ бронирования из настройки, без учёта аудитории"""
        return self._widgets.ui

    @property
    def digest_widget(self) -> bool:
        return self._widgets.digest

    @property
    def any_widgets(self) -> bool:
        """Работает ли хоть что-то кроме базовых экранов: виджеты или Rich в личке, дайджест виджетом"""
        return self._widgets.ui != BookingUi.BASIC or self._widgets.digest

    async def booking_ui_for(self, user_id: int) -> BookingUi:
        """Способ бронирования для этого пользователя: при «только админам» остальные видят базовый"""
        w = self._widgets
        if w.ui == BookingUi.BASIC or w.audience == Audience.ALL:
            return w.ui
        return w.ui if user_id in await self._admin_ids() else BookingUi.BASIC

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
        """Поменять настройки: ui, audience, digest, history_months, future_months, rich_scheme, boss_id + boss_name.
        False: ничего не изменилось.
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
