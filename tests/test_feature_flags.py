"""Режим виджетов из админки без БД и Telegram: python -m unittest discover -s tests -t ."""
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from src.services import feature_flags as module
from src.services.feature_flags import ADMINS_TTL, FeatureFlags, WidgetsMode, WidgetsSetting
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.handlers.common.setting_handler import parse_widgets_change
from src.ui.keyboard.settings_inline_kb import (render_lead_admin_menu_kb, render_widgets_boss_kb,
                                                render_widgets_months_kb, render_widgets_settings_kb)
from src.utils.db_exc_wrapper import DBError


class FakeDB:
    def __init__(self, value=None, admins=(1,)):
        self.value = value
        self.admins = list(admins)
        self.admin_queries = 0
        self.fail = False


class FakeRepository:
    def __init__(self, db: FakeDB):
        self.db = db

    async def get_system_value(self, key):
        if self.db.fail:
            raise DBError("down")
        return self.db.value

    async def set_system_value(self, key, value):
        if self.db.fail:
            raise DBError("down")
        self.db.value = value

    async def active_admin_ids(self):
        if self.db.fail:
            raise DBError("down")
        self.db.admin_queries += 1
        return self.db.admins


class FakeSession:
    def __init__(self, db):
        self.db = db

    @asynccontextmanager
    async def begin(self):
        yield


class FakeSessionFactory:
    def __init__(self, db):
        self.db = db

    @asynccontextmanager
    async def __call__(self):
        yield FakeSession(self.db)


class FakeAlerts:
    def __init__(self):
        self.sent = []

    async def notify(self, alert):
        self.sent.append(alert)
        return 1


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _user(user_id, full_name):
    from datetime import datetime
    from src.dto.user_dto import UserDTO
    return UserDTO(user_id=user_id, full_name=full_name, is_active=True, auto_confirm=False, auto_join_queue=False,
                   is_admin=False, is_lead=False, profession_id=1, product_id=1, week_visit_plan=None,
                   birth_date=None, created_at=datetime(2026, 1, 1))


def button_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class FeatureFlagsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDB()
        self.alerts = FakeAlerts()
        self.clock = Clock()
        self.flags = FeatureFlags(FakeSessionFactory(self.db), self.alerts, clock=self.clock)
        patcher = patch.object(module, "Repository", lambda session: FakeRepository(session.db))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_no_row_means_off(self):
        await self.flags.load()
        self.assertEqual(self.flags.widgets_mode, WidgetsMode.OFF)
        self.assertFalse(await self.flags.widgets_for(1))

    async def test_db_down_on_start_means_off(self):
        self.db.fail = True
        await self.flags.load()
        self.assertEqual(self.flags.widgets_mode, WidgetsMode.OFF)

    async def test_modes(self):
        await self.flags.update_widgets("Админ", mode=WidgetsMode.ADMINS)
        self.assertTrue(await self.flags.widgets_for(1))         # админ
        self.assertFalse(await self.flags.widgets_for(2))        # обычный сотрудник
        await self.flags.update_widgets("Админ", mode=WidgetsMode.ALL)
        self.assertTrue(await self.flags.widgets_for(2))
        await self.flags.update_widgets("Админ", mode=WidgetsMode.OFF)
        self.assertFalse(await self.flags.widgets_for(1))

    async def test_set_mode_persists_and_alerts(self):
        self.assertTrue(await self.flags.update_widgets("Иванов Иван", mode=WidgetsMode.ALL))
        saved = json.loads(self.db.value)
        self.assertEqual((saved["mode"], saved["by"]), ("all", "Иванов Иван"))
        self.assertEqual([a.title for a in self.alerts.sent], ["Настройки виджетов изменены"])
        self.assertEqual(self.alerts.sent[0].text, "Виджеты в личке: выключены → всем")
        self.assertNotIn("Иванов", self.alerts.sent[0].text)                # имя только в БД, не в алерте
        # после перезапуска режим тот же
        again = FeatureFlags(FakeSessionFactory(self.db), FakeAlerts())
        await again.load()
        self.assertEqual(again.widgets_mode, WidgetsMode.ALL)
        self.assertEqual(again.widgets.changed_by, "Иванов Иван")

    async def test_digest_and_months_persist(self):
        await self.flags.update_widgets("Админ", digest=True, history_months=3, future_months=2)
        self.assertTrue(self.flags.digest_widget and self.flags.any_widgets)
        self.assertEqual(self.flags.widgets_mode, WidgetsMode.OFF)              # режим в личке не тронут
        self.assertEqual(self.alerts.sent[-1].text.splitlines(), [
            "Дайджест в группе: текстом → виджетом",
            "Прошлые месяцы в календаре: нет → 3 мес.",
            "Месяцы вперёд в календаре: нет → 2 мес.",
        ])
        again = FeatureFlags(FakeSessionFactory(self.db), FakeAlerts())
        await again.load()
        w = again.widgets
        self.assertEqual((w.digest, w.history_months, w.future_months), (True, 3, 2))

    async def test_boss_persists_and_alerts(self):
        self.assertTrue(await self.flags.update_widgets("Админ", boss_id=42, boss_name="Петров Дмитрий"))
        self.assertEqual(self.alerts.sent[-1].text, "Руководитель на схеме: не выбран → Дмитрий П.")
        again = FeatureFlags(FakeSessionFactory(self.db), FakeAlerts())
        await again.load()
        self.assertEqual((again.widgets.boss_id, again.widgets.boss_name), (42, "Петров Дмитрий"))
        # Тот же человек с новым ФИО — не изменение: виджеты и так берут имя из users по boss_id
        self.assertFalse(await self.flags.update_widgets("Админ", boss_id=42, boss_name="Петров Дмитрий Иванович"))
        self.assertTrue(await self.flags.update_widgets("Админ", boss_id=None, boss_name=None))
        self.assertEqual(self.alerts.sent[-1].text, "Руководитель на схеме: Дмитрий П. → не выбран")

    def test_boss_loads_defensively(self):
        self.assertIsNone(WidgetsSetting.loads('{"mode": "all"}').boss_id)
        broken = WidgetsSetting.loads('{"boss_id": "abc", "boss_name": "Кто-то"}')
        self.assertEqual((broken.boss_id, broken.boss_name), (None, None))

    async def test_months_are_clamped(self):
        await self.flags.update_widgets("Админ", history_months=100, future_months=-5)
        self.assertEqual((self.flags.widgets.history_months, self.flags.widgets.future_months), (12, 0))

    async def test_same_mode_is_noop(self):
        self.assertFalse(await self.flags.update_widgets("Админ", mode=WidgetsMode.OFF))
        self.assertIsNone(self.db.value)
        self.assertEqual(self.alerts.sent, [])

    async def test_failed_save_keeps_old_mode(self):
        self.db.fail = True
        with self.assertRaises(DBError):
            await self.flags.update_widgets("Админ", mode=WidgetsMode.ALL)
        self.assertEqual(self.flags.widgets_mode, WidgetsMode.OFF)
        self.assertEqual(self.alerts.sent, [])

    async def test_admin_list_is_cached(self):
        await self.flags.update_widgets("Админ", mode=WidgetsMode.ADMINS)
        for _ in range(5):
            await self.flags.widgets_for(1)
        self.assertEqual(self.db.admin_queries, 1)
        self.db.admins = [2]                                     # назначили нового админа
        self.assertFalse(await self.flags.widgets_for(2))        # пока кэш живой — по-старому
        self.clock.now += ADMINS_TTL
        self.assertTrue(await self.flags.widgets_for(2))
        self.assertEqual(self.db.admin_queries, 2)

    async def test_admin_list_survives_db_error(self):
        await self.flags.update_widgets("Админ", mode=WidgetsMode.ADMINS)
        self.assertTrue(await self.flags.widgets_for(1))
        self.db.fail = True
        self.clock.now += ADMINS_TTL
        self.assertTrue(await self.flags.widgets_for(1))         # прежний список


class SettingParseTest(unittest.TestCase):
    def test_plain_and_broken_values(self):
        self.assertEqual(WidgetsSetting.loads("all").mode, WidgetsMode.ALL)          # записали руками
        self.assertEqual(WidgetsSetting.loads(" ADMINS ").mode, WidgetsMode.ADMINS)
        self.assertEqual(WidgetsSetting.loads('{"mode": "nope"}').mode, WidgetsMode.OFF)
        self.assertEqual(WidgetsSetting.loads(None).mode, WidgetsMode.OFF)
        broken = WidgetsSetting.loads('{"mode": "all", "digest": "yes", "history_months": "x", "future_months": 99}')
        self.assertEqual((broken.mode, broken.digest, broken.history_months, broken.future_months),
                         (WidgetsMode.ALL, False, 0, 12))

    def test_button_values(self):
        self.assertEqual(parse_widgets_change("mode=admins")[0], {"mode": WidgetsMode.ADMINS})
        self.assertEqual(parse_widgets_change("digest=on")[0], {"digest": True})
        self.assertEqual(parse_widgets_change("history=6")[0], {"history_months": 6})
        self.assertEqual(parse_widgets_change("future=0")[0], {"future_months": 0})
        for bad in ("mode=x", "digest=1", "history=5", "future=-1", "x=1", "", None):
            self.assertIsNone(parse_widgets_change(bad), bad)


class KeyboardsTest(unittest.TestCase):
    def test_menu_hides_my_bookings_only_with_widgets(self):
        self.assertIn("Мои брони", button_texts(get_menu_kb()))
        self.assertIn("Мои брони", button_texts(get_menu_kb(False)))
        self.assertNotIn("Мои брони", button_texts(get_menu_kb(True)))

    def test_widgets_button_only_in_admin_menu(self):
        self.assertIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(None, is_admin=True)))
        self.assertNotIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(5)))

    def test_widgets_screen_marks_current_mode(self):
        texts = button_texts(render_widgets_settings_kb(WidgetsSetting(WidgetsMode.ADMINS, True, 3, 0)))
        self.assertEqual(texts[:6], ["⚪️ Выключены", "🔘 Только админам", "⚪️ Всем", "📰 Дайджест в группе: виджетом",
                                     "⬅️ Прошлые месяцы: 3 мес.", "➡️ Месяцы вперёд: нет"])

    def test_widgets_screen_shows_boss(self):
        self.assertIn("👤 Руководитель на схеме: не выбран", button_texts(render_widgets_settings_kb(WidgetsSetting())))
        setting = WidgetsSetting(boss_id=42, boss_name="Петров Дмитрий")
        self.assertIn("👤 Руководитель на схеме: Дмитрий П.", button_texts(render_widgets_settings_kb(setting)))

    def test_boss_picker(self):
        employees = [_user(i, f"Сотрудник{i:02d} Имя") for i in range(1, 24)]
        texts = button_texts(render_widgets_boss_kb(employees, 0, 3))
        self.assertEqual(texts[:4], ["⚪️ Сотрудник01 И.", "⚪️ Сотрудник02 И.", "🔘 Сотрудник03 И.", "⚪️ Сотрудник04 И."])
        self.assertEqual(texts[-4:], ["1 / 3", "›", "✖️ Убрать руководителя", "« Виджеты"])
        last = button_texts(render_widgets_boss_kb(employees, 99, None))     # страница за пределами — последняя
        self.assertEqual(last[-3:], ["‹", "3 / 3", "« Виджеты"])
        self.assertNotIn("✖️ Убрать руководителя", last)

    def test_months_picker(self):
        texts = button_texts(render_widgets_months_kb("history", 3))
        self.assertEqual(texts, ["⚪️ нет", "⚪️ 1 мес.", "⚪️ 2 мес.", "🔘 3 мес.", "⚪️ 6 мес.", "⚪️ 12 мес.", "« Виджеты"])

    def test_callback_data_fits_telegram_limit(self):
        boss_kb = render_widgets_boss_kb([_user(10 ** 19 - 1, "Константинопольская Александра")] * 30, 1, 10 ** 19 - 1)
        for markup in (render_widgets_settings_kb(WidgetsSetting()), render_widgets_months_kb("future", 12), boss_kb):
            for row in markup.inline_keyboard:
                for b in row:
                    self.assertLessEqual(len(b.callback_data.encode()), 64, b.callback_data)


if __name__ == "__main__":
    unittest.main()
