"""Операционные алерты без Redis, Telegram и запуска планировщика: python -m unittest discover -s tests -t ."""
import logging
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.infrastructure import ops_alerts
from src.infrastructure.ops_alerts import (HEARTBEAT_KEY, STOPPED_KEY, RunMonitor, missed_runs, previous_run,
                                           watch_missed_jobs)
from src.middlewares.exception_middleware import ExceptionMiddleware
from src.utils.telegram_errors import is_harmless_bad_request

TZ = ZoneInfo("Europe/Moscow")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def scheduler() -> BackgroundScheduler:
    """Как в register_jobs, но без запуска: get_jobs() отдаёт задачи с настоящими триггерами"""
    sched = BackgroundScheduler(timezone=TZ)
    noop = lambda: None  # noqa: E731
    sched.add_job(noop, CronTrigger(hour=16, minute=0, timezone=TZ), id="chat_remind_job")
    sched.add_job(noop, CronTrigger(hour=9, minute=0, timezone=TZ), id="birthday_job")
    sched.add_job(noop, CronTrigger(hour=4, minute=10, timezone=TZ), id="calendar_sync_job")
    sched.add_job(noop, OrTrigger([CronTrigger(hour=18, minute=30, timezone=TZ),
                                   CronTrigger(hour=21, minute=0, timezone=TZ)]), id="remind_to_confirm_booking_job")
    sched.add_job(noop, IntervalTrigger(minutes=1, timezone=TZ), id="sheet_update_job")
    sched.add_job(noop, "date", run_date=at(6, 16, 30), id="check_chat_remind_reserve_job")
    return sched


class FakeStore:
    def __init__(self, values=None, broken=False):
        self.values = dict(values or {})
        self.broken = broken

    async def get_value(self, key):
        if self.broken:
            raise ConnectionError("redis is down")
        return self.values.get(key)

    async def set_value(self, key, value, ttl=None):
        if self.broken:
            raise ConnectionError("redis is down")
        self.values[key] = value


class FakeAlerts:
    def __init__(self):
        self.sent, self.queued = [], []

    async def notify(self, alert):
        self.sent.append(alert)
        return 1

    def notify_nowait(self, alert):
        self.queued.append(alert)
        return True


class PreviousRunTest(unittest.TestCase):
    def test_first_start(self):
        self.assertEqual(previous_run(None, None), ops_alerts.PreviousRun(crashed=False, last_seen=None))

    def test_clean_stop(self):
        prev = previous_run(at(6, 15, 59), at(6, 16, 0))
        self.assertEqual((prev.crashed, prev.last_seen), (False, at(6, 16, 0)))

    def test_crash_after_old_clean_stop(self):
        prev = previous_run(at(6, 15, 59), at(5, 10, 0))
        self.assertEqual((prev.crashed, prev.last_seen), (True, at(6, 15, 59)))

    def test_crash_without_any_stop(self):
        self.assertTrue(previous_run(at(6, 15, 59), None).crashed)


class MissedRunsTest(unittest.TestCase):
    def test_only_cron_jobs_in_window(self):
        missed = missed_runs(scheduler().get_jobs(), at(6, 15, 0), at(6, 17, 0))
        self.assertEqual(missed, [("chat_remind_job", at(6, 16, 0), 1)])

    def test_or_trigger_and_several_days(self):
        missed = dict((job_id, (first, count)) for job_id, first, count
                      in missed_runs(scheduler().get_jobs(), at(6, 18, 0), at(8, 10, 0), skip={"calendar_sync_job"}))
        self.assertNotIn("calendar_sync_job", missed)
        self.assertEqual(missed["remind_to_confirm_booking_job"], (at(6, 18, 30), 4))
        self.assertEqual(missed["chat_remind_job"], (at(7, 16, 0), 1))
        self.assertEqual(missed["birthday_job"], (at(7, 9, 0), 2))

    def test_run_exactly_at_last_seen_is_not_missed(self):
        self.assertEqual(missed_runs(scheduler().get_jobs(), at(6, 16, 0), at(6, 16, 5)), [])

    def test_long_downtime_is_capped(self):
        _, _, count = missed_runs(scheduler().get_jobs(), at(1, 0, 0), at(1, 0, 0) + timedelta(days=200))[0]
        self.assertEqual(count, ops_alerts.MAX_RUNS_PER_JOB)


class RunMonitorTest(unittest.IsolatedAsyncioTestCase):
    async def run_start(self, store, now=at(6, 16, 10)):
        alerts = FakeAlerts()
        monitor = RunMonitor(store, alerts, scheduler())
        with patch.object(ops_alerts, "_now", return_value=now):
            await monitor.start()
            await monitor.stop()
        return alerts

    async def test_first_start_is_silent_and_writes_heartbeat(self):
        store = FakeStore()
        alerts = await self.run_start(store)
        self.assertEqual(alerts.sent, [])
        self.assertIn(HEARTBEAT_KEY, store.values)
        self.assertIn(STOPPED_KEY, store.values)

    async def test_crash_reports_restart_and_missed_digest(self):
        store = FakeStore({HEARTBEAT_KEY: at(6, 15, 59).isoformat(), STOPPED_KEY: at(5, 10, 0).isoformat()})
        alerts = await self.run_start(store)
        self.assertEqual([a.title for a in alerts.sent],
                         ["Бот перезапустился после сбоя", "Пока бот не работал, пропущены задачи"])
        self.assertEqual(alerts.sent[0].level, logging.ERROR)
        self.assertIn("chat_remind_job — 06.11.2026 16:00", alerts.sent[1].text)

    async def test_jobs_run_at_startup_are_not_reported(self):
        store = FakeStore({HEARTBEAT_KEY: at(6, 4, 0).isoformat(), STOPPED_KEY: at(6, 4, 1).isoformat()})
        alerts = await self.run_start(store, now=at(6, 4, 30))   # простой пришёлся на calendar_sync_job (04:10)
        self.assertEqual(alerts.sent, [])

    async def test_clean_restart_during_digest_reports_only_missed(self):
        store = FakeStore({HEARTBEAT_KEY: at(6, 15, 58).isoformat(), STOPPED_KEY: at(6, 15, 59).isoformat()})
        alerts = await self.run_start(store)
        self.assertEqual([a.title for a in alerts.sent], ["Пока бот не работал, пропущены задачи"])

    async def test_quick_clean_restart_is_silent(self):
        store = FakeStore({HEARTBEAT_KEY: at(6, 12, 0).isoformat(), STOPPED_KEY: at(6, 12, 0).isoformat()})
        self.assertEqual((await self.run_start(store, now=at(6, 12, 1))).sent, [])

    async def test_redis_down_does_not_break_startup(self):
        with self.assertLogs(ops_alerts.logger, level=logging.WARNING):
            alerts = await self.run_start(FakeStore(broken=True))
        self.assertEqual(alerts.sent, [])


class WatchMissedJobsTest(unittest.TestCase):
    def test_missed_event_becomes_alert(self):
        sched, alerts = scheduler(), FakeAlerts()
        watch_missed_jobs(sched, alerts)
        sched._dispatch_event(JobExecutionEvent(EVENT_JOB_MISSED, "chat_remind_job", "default", at(6, 16, 0)))
        self.assertEqual(len(alerts.queued), 1)
        alert = alerts.queued[0]
        self.assertEqual(alert.title, "Пропущен запуск задачи chat_remind_job")
        self.assertEqual(alert.key, "scheduler:missed:chat_remind_job")
        self.assertIn("06.11.2026 16:00", alert.text)


class HarmlessBadRequestTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def bad_request(text):
        return TelegramBadRequest(None, f"Bad Request: {text}")

    def test_patterns(self):
        self.assertTrue(is_harmless_bad_request(self.bad_request(
            "message is not modified: specified new message content and reply markup are exactly the same")))
        self.assertTrue(is_harmless_bad_request(self.bad_request(
            "query is too old and response timeout expired or query ID is invalid")))
        self.assertFalse(is_harmless_bad_request(self.bad_request("chat not found")))

    async def test_middleware_log_level(self):
        for text, level in (("message is not modified", "WARNING"), ("chat not found", "ERROR")):
            async def handler(event, data, text=text):
                raise self.bad_request(text)

            with self.subTest(text=text), self.assertLogs("src.middlewares.exception_middleware") as logs:
                await ExceptionMiddleware()(handler, object(), {})
            self.assertEqual([r.levelname for r in logs.records], [level])


if __name__ == "__main__":
    unittest.main()
