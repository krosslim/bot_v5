"""Режим виджетов из админки без БД и Telegram: python -m unittest discover -s tests -t ."""
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from src.services import feature_flags as module
from src.services.feature_flags import ADMINS_TTL, FeatureFlags, WidgetsMode, WidgetsSetting
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.settings_inline_kb import render_lead_admin_menu_kb, render_widgets_settings_kb
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
        await self.flags.set_widgets_mode(WidgetsMode.ADMINS, "Админ")
        self.assertTrue(await self.flags.widgets_for(1))         # админ
        self.assertFalse(await self.flags.widgets_for(2))        # обычный сотрудник
        await self.flags.set_widgets_mode(WidgetsMode.ALL, "Админ")
        self.assertTrue(await self.flags.widgets_for(2))
        await self.flags.set_widgets_mode(WidgetsMode.OFF, "Админ")
        self.assertFalse(await self.flags.widgets_for(1))

    async def test_set_mode_persists_and_alerts(self):
        self.assertTrue(await self.flags.set_widgets_mode(WidgetsMode.ALL, "Иванов Иван"))
        saved = json.loads(self.db.value)
        self.assertEqual((saved["mode"], saved["by"]), ("all", "Иванов Иван"))
        self.assertEqual([a.title for a in self.alerts.sent], ["Режим виджетов изменён"])
        self.assertIn("выключены → всем", self.alerts.sent[0].text)
        # после перезапуска режим тот же
        again = FeatureFlags(FakeSessionFactory(self.db), FakeAlerts())
        await again.load()
        self.assertEqual(again.widgets_mode, WidgetsMode.ALL)
        self.assertEqual(again.widgets.changed_by, "Иванов Иван")

    async def test_same_mode_is_noop(self):
        self.assertFalse(await self.flags.set_widgets_mode(WidgetsMode.OFF, "Админ"))
        self.assertIsNone(self.db.value)
        self.assertEqual(self.alerts.sent, [])

    async def test_failed_save_keeps_old_mode(self):
        self.db.fail = True
        with self.assertRaises(DBError):
            await self.flags.set_widgets_mode(WidgetsMode.ALL, "Админ")
        self.assertEqual(self.flags.widgets_mode, WidgetsMode.OFF)
        self.assertEqual(self.alerts.sent, [])

    async def test_admin_list_is_cached(self):
        await self.flags.set_widgets_mode(WidgetsMode.ADMINS, "Админ")
        for _ in range(5):
            await self.flags.widgets_for(1)
        self.assertEqual(self.db.admin_queries, 1)
        self.db.admins = [2]                                     # назначили нового админа
        self.assertFalse(await self.flags.widgets_for(2))        # пока кэш живой — по-старому
        self.clock.now += ADMINS_TTL
        self.assertTrue(await self.flags.widgets_for(2))
        self.assertEqual(self.db.admin_queries, 2)

    async def test_admin_list_survives_db_error(self):
        await self.flags.set_widgets_mode(WidgetsMode.ADMINS, "Админ")
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


class KeyboardsTest(unittest.TestCase):
    def test_menu_hides_my_bookings_only_with_widgets(self):
        self.assertIn("Мои брони", button_texts(get_menu_kb()))
        self.assertIn("Мои брони", button_texts(get_menu_kb(False)))
        self.assertNotIn("Мои брони", button_texts(get_menu_kb(True)))

    def test_widgets_button_only_in_admin_menu(self):
        self.assertIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(None, is_admin=True)))
        self.assertNotIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(5)))

    def test_widgets_screen_marks_current_mode(self):
        texts = button_texts(render_widgets_settings_kb(WidgetsMode.ADMINS))
        self.assertEqual(texts[:3], ["⚪️ Выключены", "🔘 Только админам", "⚪️ Всем"])


if __name__ == "__main__":
    unittest.main()
