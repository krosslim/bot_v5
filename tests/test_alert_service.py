"""AlertService без Telegram и Redis: python -m unittest discover -s tests -t ."""
import logging
import unittest

from aiogram.exceptions import TelegramForbiddenError

from src.services.alert_service import MAX_MESSAGE_LEN, Alert, AlertService, ChatRecipients, format_alert


class FakeBot:
    def __init__(self, blocked=()):
        self.sent = []
        self.blocked = set(blocked)

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(None, "Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text))


class FakeStore:
    def __init__(self, broken=False):
        self.keys = {}
        self.broken = broken

    async def set_nx_key_ttl(self, key, ttl):
        if self.broken:
            raise ConnectionError("redis is down")
        if key in self.keys:
            return None
        self.keys[key] = ttl
        return True


class BrokenRecipients:
    async def chat_ids(self):
        raise RuntimeError("db is down")


def service(bot=None, recipients=(1, 2), store=None):
    rec = recipients if hasattr(recipients, "chat_ids") else ChatRecipients(recipients)
    return AlertService(bot or FakeBot(), rec, store or FakeStore())


class FormatTest(unittest.TestCase):
    def test_html_is_escaped_and_level_has_icon(self):
        text = format_alert(Alert("<b>x</b>", "a & b <tag>", level=logging.ERROR))
        self.assertTrue(text.startswith("❌ <b>&lt;b&gt;x&lt;/b&gt;</b>"))
        self.assertIn("a &amp; b &lt;tag&gt;", text)
        self.assertTrue(format_alert(Alert("t", level=logging.INFO)).startswith("ℹ️"))
        self.assertTrue(format_alert(Alert("t", level=logging.CRITICAL)).startswith("🔥"))

    def test_long_text_fits_telegram_limit(self):
        for body in ("x" * 10_000, "&" * 5_000):
            with self.subTest(body=body[:3]):
                text = format_alert(Alert("t", body))
                self.assertLessEqual(len(text), MAX_MESSAGE_LEN)
                self.assertTrue(text.endswith("…"))


class NotifyTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_to_every_recipient(self):
        bot = FakeBot()
        self.assertEqual(await service(bot).notify(Alert("t")), 2)
        self.assertEqual([c for c, _ in bot.sent], [1, 2])

    async def test_same_key_is_sent_once_per_window(self):
        alerts = service()
        self.assertEqual(await alerts.notify(Alert("t", key="k")), 2)
        self.assertEqual(await alerts.notify(Alert("t", key="k")), 0)
        self.assertEqual(await alerts.notify(Alert("t", key="other")), 2)
        self.assertEqual(await alerts.notify(Alert("t")), 2)      # без key повторы не отсекаются

    async def test_redis_failure_does_not_lose_alert(self):
        self.assertEqual(await service(store=FakeStore(broken=True)).notify(Alert("t", key="k")), 2)

    async def test_blocked_admin_does_not_stop_others(self):
        bot = FakeBot(blocked={1})
        with self.assertLogs("src.services.alert_service", level=logging.WARNING) as logs:
            self.assertEqual(await service(bot, recipients=(1, 2, 3)).notify(Alert("t")), 2)
        self.assertTrue(all(r.levelno == logging.WARNING for r in logs.records))   # не выше WARNING

    async def test_recipients_failure_returns_zero(self):
        with self.assertLogs("src.services.alert_service", level=logging.WARNING):
            self.assertEqual(await service(recipients=BrokenRecipients()).notify(Alert("t")), 0)

    async def test_notify_nowait_uses_background_queue(self):
        bot = FakeBot()
        alerts = service(bot)
        self.assertFalse(alerts.notify_nowait(Alert("before start")))
        await alerts.start()
        self.assertTrue(alerts.notify_nowait(Alert("queued")))
        await alerts.stop()                                     # stop дожидается отправки очереди
        self.assertEqual(len(bot.sent), 2)
        self.assertFalse(alerts.notify_nowait(Alert("after stop")))


if __name__ == "__main__":
    unittest.main()
