"""Алерты на ERROR из логов: python -m unittest discover -s tests -t ."""
import asyncio
import logging
import unittest
from unittest.mock import patch

from src.infrastructure import log_alerts
from src.infrastructure.log_alerts import AlertLogHandler
from src.services.alert_service import AlertService, ChatRecipients
from tests.test_alert_service import FakeBot, FakeStore


class FakeAlerts:
    def __init__(self, accept=True):
        self.queued = []
        self.accept = accept

    def notify_nowait(self, alert):
        if self.accept:
            self.queued.append(alert)
        return self.accept


def make_logger(name: str, handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger


def fail_with(exc_type, logger):
    try:
        raise exc_type("boom")
    except exc_type:
        logger.exception("Не удалось обновить лист")


class AlertLogHandlerTest(unittest.TestCase):
    def setUp(self):
        self.alerts = FakeAlerts()
        self.handler = AlertLogHandler(self.alerts)
        self.log = make_logger("tests.log_alerts", self.handler)

    def test_error_becomes_alert(self):
        self.log.error("HTTP ошибка %s при обновлении листа '%s'", 403, "декабрь 2026")
        self.assertEqual(len(self.alerts.queued), 1)
        alert = self.alerts.queued[0]
        self.assertEqual(alert.title, "ERROR: tests.log_alerts")
        self.assertEqual(alert.level, logging.ERROR)
        self.assertIn("HTTP ошибка 403 при обновлении листа 'декабрь 2026'", alert.text)
        self.assertIn("Где: tests/test_log_alerts.py:", alert.text)
        self.assertTrue(alert.key.startswith("log:"))
        self.assertEqual(alert.dedup_ttl, 3600)

    def test_below_error_is_ignored(self):
        self.log.warning("предупреждение")
        self.log.info("инфо")
        self.assertEqual(self.alerts.queued, [])

    def test_same_place_is_sent_once_even_if_text_changes(self):
        for status in (403, 404, 500):
            self.log.error(f"HTTP ошибка {status}")      # f-строка: текст каждый раз разный
        self.assertEqual(len(self.alerts.queued), 1)

    def test_different_exception_types_from_same_place_are_separate(self):
        for exc_type in (ValueError, ValueError, KeyError):
            fail_with(exc_type, self.log)
        self.assertEqual(len(self.alerts.queued), 2)
        self.assertIn("Traceback", self.alerts.queued[0].text)
        self.assertIn("ValueError: boom", self.alerts.queued[0].text)

    def test_repeat_after_ttl(self):
        with patch.object(log_alerts.time, "monotonic", side_effect=[1000.0, 1000.0 + 3599, 1000.0 + 3601]):
            for _ in range(3):
                self.log.error("одна и та же ошибка")
        self.assertEqual(len(self.alerts.queued), 2)

    def test_alert_service_logger_is_ignored(self):
        for name in ("src.services.alert_service", "src.services.alert_service.worker"):
            make_logger(name, self.handler).error("сбой отправки")
        self.assertEqual(self.alerts.queued, [])

    def test_not_queued_alert_is_not_remembered(self):
        self.alerts.accept = False
        self.log.error("сервис ещё не запущен")
        self.alerts.accept = True
        self.log.error("сервис ещё не запущен")
        self.assertEqual(len(self.alerts.queued), 1)

    def test_long_message_is_cut(self):
        self.log.error("x" * 5000)
        self.assertLess(len(self.alerts.queued[0].text), 1500)


class LogErrorsDuringSendingTest(unittest.IsolatedAsyncioTestCase):
    async def test_error_logged_while_sending_does_not_loop(self):
        """Если при отправке алерта что-то пишет в лог ERROR, нового алерта быть не должно"""
        bot = FakeBot()

        class LoggingRecipients(ChatRecipients):
            async def chat_ids(self):
                logging.getLogger("tests.db").error("сбой во время отправки алерта")
                return await super().chat_ids()

        alerts = AlertService(bot, LoggingRecipients([1]), FakeStore())
        handler = AlertLogHandler(alerts)
        app_log, db_log = make_logger("tests.app", handler), make_logger("tests.db", handler)
        await alerts.start()

        with patch.object(alerts, "notify_nowait", wraps=alerts.notify_nowait) as queued:
            app_log.error("исходная ошибка")
            for _ in range(20):                      # даём фоновой задаче отправить и всё, что она породит
                await asyncio.sleep(0.01)
        await alerts.stop()

        self.assertEqual(queued.call_count, 1)       # ошибка из recipients в очередь не попала
        self.assertEqual(len(bot.sent), 1)
        self.assertIn("исходная ошибка", bot.sent[0][1])
        db_log.handlers = []


if __name__ == "__main__":
    unittest.main()
