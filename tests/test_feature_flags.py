"""Способ бронирования в личке и настройки виджетов из админки без БД и Telegram:
python -m unittest discover -s tests -t ."""
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from src.services import feature_flags as module
from src.services.feature_flags import ADMINS_TTL, Audience, BookingUi, FeatureFlags, WidgetsSetting
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.handlers.common.setting_handler import parse_widgets_change
from src.ui.keyboard.settings_inline_kb import (render_lead_admin_menu_kb, render_widgets_boss_kb,
                                                render_widgets_months_kb, render_widgets_settings_kb)
from src.ui.messages.settings_mess import render_widgets_settings_mess
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

    async def test_no_row_means_basic(self):
        await self.flags.load()
        self.assertEqual(self.flags.booking_ui, BookingUi.BASIC)
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.BASIC)
        self.assertFalse(self.flags.any_widgets)

    async def test_db_down_on_start_means_basic(self):
        self.db.fail = True
        await self.flags.load()
        self.assertEqual(self.flags.booking_ui, BookingUi.BASIC)

    async def test_ui_and_audience(self):
        await self.flags.update_widgets("Админ", ui=BookingUi.WIDGETS)          # аудитория по умолчанию: админы
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.WIDGETS)   # админ
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.BASIC)     # обычный сотрудник
        await self.flags.update_widgets("Админ", audience=Audience.ALL)
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.WIDGETS)
        await self.flags.update_widgets("Админ", ui=BookingUi.RICH)
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.RICH)
        self.assertTrue(self.flags.any_widgets)
        await self.flags.update_widgets("Админ", audience=Audience.ADMINS)
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.RICH)
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.BASIC)
        await self.flags.update_widgets("Админ", ui=BookingUi.BASIC)
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.BASIC)

    async def test_set_ui_persists_and_alerts(self):
        self.assertTrue(await self.flags.update_widgets("Иванов Иван", ui=BookingUi.WIDGETS, audience=Audience.ALL))
        saved = json.loads(self.db.value)
        self.assertEqual((saved["ui"], saved["audience"], saved["mode"], saved["by"]),
                         ("widgets", "all", "all", "Иванов Иван"))           # mode: для отката на старую версию
        self.assertEqual([a.title for a in self.alerts.sent], ["Настройки виджетов изменены"])
        self.assertEqual(self.alerts.sent[0].text.splitlines(), [
            "Способ бронирования в личке: базовый → виджеты",
            "Кому способ бронирования: только админам → всем",
        ])
        self.assertNotIn("Иванов", self.alerts.sent[0].text)                # имя только в БД, не в алерте
        # после перезапуска способ тот же
        again = FeatureFlags(FakeSessionFactory(self.db), FakeAlerts())
        await again.load()
        self.assertEqual((again.widgets.ui, again.widgets.audience), (BookingUi.WIDGETS, Audience.ALL))
        self.assertEqual(again.widgets.changed_by, "Иванов Иван")

    async def test_rich_is_off_for_old_version(self):
        await self.flags.update_widgets("Админ", ui=BookingUi.RICH, audience=Audience.ALL)
        saved = json.loads(self.db.value)
        self.assertEqual((saved["ui"], saved["audience"], saved["mode"]), ("rich", "all", "off"))
        self.assertEqual(self.alerts.sent[-1].text.splitlines()[0], "Способ бронирования в личке: базовый → Rich")

    async def test_old_row_becomes_new(self):
        """Строка старой версии читается без потерь, первая же правка пишет новые поля и сохраняет остальное"""
        self.db.value = json.dumps({"mode": "admins", "digest": True, "history_months": 3, "future_months": 2,
                                    "boss_id": 42, "boss_name": "Петров Дмитрий", "by": "Старый Админ",
                                    "at": "2026-11-09T23:33:35+03:00"})
        await self.flags.load()
        w = self.flags.widgets
        self.assertEqual((w.ui, w.audience, w.digest, w.history_months, w.future_months, w.boss_id),
                         (BookingUi.WIDGETS, Audience.ADMINS, True, 3, 2, 42))
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.WIDGETS)
        await self.flags.update_widgets("Админ", ui=BookingUi.RICH)
        saved = json.loads(self.db.value)
        self.assertEqual((saved["ui"], saved["audience"], saved["mode"], saved["digest"], saved["boss_id"]),
                         ("rich", "admins", "off", True, 42))
        self.assertEqual(self.alerts.sent[-1].text, "Способ бронирования в личке: виджеты → Rich")

    async def test_digest_and_months_persist(self):
        await self.flags.update_widgets("Админ", digest=True, history_months=3, future_months=2)
        self.assertTrue(self.flags.digest_widget and self.flags.any_widgets)
        self.assertEqual(self.flags.booking_ui, BookingUi.BASIC)                # способ в личке не тронут
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

    async def test_same_ui_is_noop(self):
        self.assertFalse(await self.flags.update_widgets("Админ", ui=BookingUi.BASIC))
        self.assertFalse(await self.flags.update_widgets("Админ", audience=Audience.ADMINS))
        self.assertIsNone(self.db.value)
        self.assertEqual(self.alerts.sent, [])

    async def test_failed_save_keeps_old_ui(self):
        self.db.fail = True
        with self.assertRaises(DBError):
            await self.flags.update_widgets("Админ", ui=BookingUi.RICH)
        self.assertEqual(self.flags.booking_ui, BookingUi.BASIC)
        self.assertEqual(self.alerts.sent, [])

    async def test_admin_list_is_cached(self):
        await self.flags.update_widgets("Админ", ui=BookingUi.RICH, audience=Audience.ADMINS)
        for _ in range(5):
            await self.flags.booking_ui_for(1)
        self.assertEqual(self.db.admin_queries, 1)
        self.db.admins = [2]                                                  # назначили нового админа
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.BASIC)  # пока кэш живой — по-старому
        self.clock.now += ADMINS_TTL
        self.assertEqual(await self.flags.booking_ui_for(2), BookingUi.RICH)
        self.assertEqual(self.db.admin_queries, 2)

    async def test_admin_list_survives_db_error(self):
        await self.flags.update_widgets("Админ", ui=BookingUi.WIDGETS, audience=Audience.ADMINS)
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.WIDGETS)
        self.db.fail = True
        self.clock.now += ADMINS_TTL
        self.assertEqual(await self.flags.booking_ui_for(1), BookingUi.WIDGETS)   # прежний список


class SettingParseTest(unittest.TestCase):
    def assert_ui(self, raw, ui, audience):
        w = WidgetsSetting.loads(raw)
        self.assertEqual((w.ui, w.audience), (ui, audience), raw)

    def test_old_values(self):
        self.assert_ui('{"mode": "off"}', BookingUi.BASIC, Audience.ADMINS)
        self.assert_ui('{"mode": "admins"}', BookingUi.WIDGETS, Audience.ADMINS)
        self.assert_ui('{"mode": "all", "digest": true}', BookingUi.WIDGETS, Audience.ALL)
        self.assert_ui("all", BookingUi.WIDGETS, Audience.ALL)                    # записали руками
        self.assert_ui(" ADMINS ", BookingUi.WIDGETS, Audience.ADMINS)
        self.assert_ui('{"digest": true}', BookingUi.BASIC, Audience.ADMINS)      # поля нет: как «выключено»
        self.assert_ui(None, BookingUi.BASIC, Audience.ADMINS)

    def test_new_values(self):
        self.assert_ui('{"ui": "rich", "audience": "all", "mode": "off"}', BookingUi.RICH, Audience.ALL)
        self.assert_ui('{"ui": "widgets", "audience": "admins", "mode": "admins"}', BookingUi.WIDGETS, Audience.ADMINS)
        self.assert_ui('{"ui": "basic"}', BookingUi.BASIC, Audience.ADMINS)
        self.assert_ui('{"ui": "RICH"}', BookingUi.RICH, Audience.ADMINS)        # аудитории нет: только админам

    def test_unreadable_values_mean_basic_with_error(self):
        for raw in ('{"mode": "nope"}', "rich", '{"ui": "fancy", "audience": "all"}'):
            with self.assertLogs(module.logger, "ERROR"):
                self.assert_ui(raw, BookingUi.BASIC, Audience.ADMINS)
        with self.assertLogs(module.logger, "ERROR"):
            self.assert_ui('{"ui": "rich", "audience": "everyone"}', BookingUi.RICH, Audience.ADMINS)
        broken = WidgetsSetting.loads('{"mode": "all", "digest": "yes", "history_months": "x", "future_months": 99}')
        self.assertEqual((broken.ui, broken.digest, broken.history_months, broken.future_months),
                         (BookingUi.WIDGETS, False, 0, 12))

    def test_dumps_roundtrip(self):
        for ui in BookingUi:
            for audience in Audience:
                w = WidgetsSetting.loads(WidgetsSetting(ui, audience, True, 3, 1).dumps())
                self.assertEqual((w.ui, w.audience, w.digest, w.history_months, w.future_months),
                                 (ui, audience, True, 3, 1))

    def test_changes_from(self):
        old = WidgetsSetting()
        self.assertEqual(WidgetsSetting(BookingUi.RICH).changes_from(old),
                         ["Способ бронирования в личке: базовый → Rich"])
        self.assertEqual(WidgetsSetting(audience=Audience.ALL).changes_from(old),
                         ["Кому способ бронирования: только админам → всем"])
        self.assertEqual(WidgetsSetting(BookingUi.BASIC, Audience.ADMINS).changes_from(
            WidgetsSetting(BookingUi.WIDGETS, Audience.ALL)),
            ["Способ бронирования в личке: виджеты → базовый", "Кому способ бронирования: всем → только админам"])
        self.assertEqual(WidgetsSetting().changes_from(WidgetsSetting()), [])

    def test_button_values(self):
        self.assertEqual(parse_widgets_change("ui=rich")[0], {"ui": BookingUi.RICH})
        self.assertEqual(parse_widgets_change("ui=basic")[0], {"ui": BookingUi.BASIC})
        self.assertEqual(parse_widgets_change("aud=all")[0], {"audience": Audience.ALL})
        self.assertEqual(parse_widgets_change("aud=admins")[1], "Кому: только админам")
        # кнопка с экрана, открытого до обновления
        self.assertEqual(parse_widgets_change("mode=admins")[0], {"ui": BookingUi.WIDGETS, "audience": Audience.ADMINS})
        self.assertEqual(parse_widgets_change("digest=on")[0], {"digest": True})
        self.assertEqual(parse_widgets_change("history=6")[0], {"history_months": 6})
        self.assertEqual(parse_widgets_change("future=0")[0], {"future_months": 0})
        for bad in ("ui=x", "ui=off", "aud=nobody", "mode=x", "digest=1", "history=5", "future=-1", "x=1", "", None):
            self.assertIsNone(parse_widgets_change(bad), bad)


class KeyboardsTest(unittest.TestCase):
    def test_menu_hides_my_bookings_with_widgets_and_rich(self):
        self.assertIn("Мои брони", button_texts(get_menu_kb()))
        self.assertIn("Мои брони", button_texts(get_menu_kb(BookingUi.BASIC)))
        self.assertNotIn("Мои брони", button_texts(get_menu_kb(BookingUi.WIDGETS)))
        self.assertNotIn("Мои брони", button_texts(get_menu_kb(BookingUi.RICH)))

    def test_widgets_button_only_in_admin_menu(self):
        self.assertIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(None, is_admin=True)))
        self.assertNotIn("🧩 Виджеты", button_texts(render_lead_admin_menu_kb(5)))

    def test_widgets_screen_marks_current_ui_and_audience(self):
        texts = button_texts(render_widgets_settings_kb(WidgetsSetting(BookingUi.RICH, Audience.ADMINS, True, 3, 0)))
        self.assertEqual(texts[:8], ["⚪️ Базовый", "⚪️ Виджеты", "🔘 Rich", "⚪️ Всем", "🔘 Только админам",
                                     "📰 Дайджест в группе: виджетом", "⬅️ Прошлые месяцы: 3 мес.",
                                     "➡️ Месяцы вперёд: нет"])
        texts = button_texts(render_widgets_settings_kb(WidgetsSetting(BookingUi.WIDGETS, Audience.ALL)))
        self.assertEqual(texts[:5], ["⚪️ Базовый", "🔘 Виджеты", "⚪️ Rich", "🔘 Всем", "⚪️ Только админам"])

    def test_widgets_screen_text(self):
        text = render_widgets_settings_mess(WidgetsSetting(BookingUi.RICH, Audience.ALL), True, False)
        self.assertIn("Бронирование в личке: <b>Rich</b>, <b>всем</b>", text)
        self.assertIn("не знает Rich Messages", text)
        self.assertIn("• Rich:", text)
        self.assertNotIn("·", text)
        basic = render_widgets_settings_mess(WidgetsSetting(), True, True)
        self.assertIn("Бронирование в личке: <b>базовый</b>\n", basic)      # аудитория у базового не важна
        self.assertIn("✅ Bot API поддерживает виджеты и Rich Messages", basic)

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
