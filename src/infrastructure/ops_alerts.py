"""Операционные алерты: пропущенные задачи планировщика и перезапуск бота после сбоя.

1. Пропуск во время работы. Если цикл событий был занят дольше misfire_grace_time, APScheduler пропускает
   запуск и пишет только WARNING. watch_missed_jobs ловит событие EVENT_JOB_MISSED и шлёт алерт.
2. Простой и сбой. Задачи живут в памяти, и после перезапуска расписание считается с текущего момента:
   запуск, пришедшийся на время, пока бот не работал, просто теряется. RunMonitor раз в минуту пишет
   в Redis метку «жив», а при штатной остановке — время остановки. При старте по этим меткам видно,
   упал ли прошлый запуск и какие cron-задачи (дайджест, отмена неподтверждённых и т. п.) пришлись на простой.
"""
import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Collection, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.job import Job
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from src.services.alert_service import Alert, AlertService
from src.storage.redis.store import RedisStore

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "bot:heartbeat"       # время последнего «жив» (ISO), обновляется раз в HEARTBEAT_EVERY
STOPPED_KEY = "bot:stopped_at"        # время последней штатной остановки (ISO)
HEARTBEAT_EVERY = 60
MAX_RUNS_PER_JOB = 50                 # при простое в несколько дней не перебирать расписание бесконечно
RUN_AT_STARTUP = {"calendar_sync_job"}  # эти задачи выполняются и при старте бота: их пропуск не страшен


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.MSC_TZ))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo(settings.MSC_TZ)).strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------#
#  1. Пропуск запуска во время работы
# ---------------------------------------------------------------------------#
def watch_missed_jobs(scheduler: BaseScheduler, alerts: AlertService) -> None:
    def on_missed(event: JobExecutionEvent) -> None:
        # Атрибуты задачи читаем осторожно: исключение здесь APScheduler проглотит, и алерт не уйдёт
        job = scheduler.get_job(event.job_id)
        grace_sec = getattr(job, "misfire_grace_time", None)
        next_run_time = getattr(job, "next_run_time", None)
        grace = f"{grace_sec} с" if grace_sec is not None else "допустимое время"
        next_run = f"\nСледующий запуск: {_fmt(next_run_time)}" if next_run_time else ""
        alerts.notify_nowait(Alert(
            f"Пропущен запуск задачи {event.job_id}",
            f"Плановое время: {_fmt(event.scheduled_run_time)}. Бот был занят дольше {grace}, "
            f"и планировщик пропустил запуск.{next_run}",
            level=logging.ERROR, key=f"scheduler:missed:{event.job_id}",
        ))

    scheduler.add_listener(on_missed, EVENT_JOB_MISSED)


# ---------------------------------------------------------------------------#
#  2. Сбой и простой
# ---------------------------------------------------------------------------#
@dataclass(frozen=True)
class PreviousRun:
    crashed: bool                        # прошлый запуск закончился без штатной остановки
    last_seen: Optional[datetime]        # когда бот точно ещё работал; None — первый запуск


def previous_run(heartbeat: Optional[datetime], stopped_at: Optional[datetime]) -> PreviousRun:
    """При штатной остановке время остановки позже последнего «жив», при падении — нет"""
    if heartbeat is None:
        return PreviousRun(crashed=False, last_seen=stopped_at)
    if stopped_at is not None and stopped_at >= heartbeat:
        return PreviousRun(crashed=False, last_seen=stopped_at)
    return PreviousRun(crashed=True, last_seen=heartbeat)


def missed_runs(
        jobs: Iterable[Job], since: datetime, until: datetime, skip: Collection[str] = (),
) -> List[Tuple[str, datetime, int]]:
    """Запуски cron-задач в окне (since, until]: (id, первый пропущенный запуск, сколько всего).
    Интервальные задачи (раз в 1–3 минуты) и разовые (date) не считаются: их пропуск во время простоя
    неизбежен и сам по себе ничего не ломает. skip — задачи, которые и так выполняются при старте"""
    result = []
    for job in jobs:
        if job.id in skip or isinstance(job.trigger, (IntervalTrigger, DateTrigger)):
            continue
        first, count = None, 0
        fire = job.trigger.get_next_fire_time(None, since + timedelta(microseconds=1))
        while fire is not None and fire <= until and count < MAX_RUNS_PER_JOB:
            first = first or fire
            count += 1
            fire = job.trigger.get_next_fire_time(fire, fire + timedelta(microseconds=1))
        if first:
            result.append((job.id, first, count))
    return sorted(result, key=lambda r: r[1])


def _parse(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class RunMonitor:
    def __init__(self, store: RedisStore, alerts: AlertService, scheduler: BaseScheduler):
        self.store = store
        self.alerts = alerts
        self.scheduler = scheduler
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Вызывать после scheduler.start(): проверяет прошлый запуск и начинает писать «жив»"""
        try:
            prev = previous_run(_parse(await self.store.get_value(HEARTBEAT_KEY)),
                                _parse(await self.store.get_value(STOPPED_KEY)))
            await self._beat()
        except Exception as e:
            logger.warning("run_monitor | Redis недоступен, проверка прошлого запуска пропущена | %s", e)
            prev = None
        self._task = asyncio.create_task(self._heartbeat(), name="run-monitor")
        if prev is not None:
            await self._report(prev, _now())

    async def stop(self) -> None:
        """Штатная остановка: без этой метки следующий запуск сочтёт, что бот упал"""
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        try:
            await self.store.set_value(STOPPED_KEY, _now().isoformat())
        except Exception as e:
            logger.warning("run_monitor | не удалось записать время остановки | %s", e)

    async def _beat(self) -> None:
        await self.store.set_value(HEARTBEAT_KEY, _now().isoformat())

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_EVERY)
            try:
                await self._beat()
            except Exception as e:
                logger.warning("run_monitor | не удалось обновить метку «жив» | %s", e)

    async def _report(self, prev: PreviousRun, now: datetime) -> None:
        if prev.crashed:
            await self.alerts.notify(Alert(
                "Бот перезапустился после сбоя",
                f"Прошлый запуск завершился без штатной остановки: падение процесса, нехватка памяти "
                f"или перезагрузка сервера. Последний признак жизни: {_fmt(prev.last_seen)}.\n"
                f"Причину ищите в логах контейнера: docker compose logs bot",
                level=logging.ERROR,
            ))
        if prev.last_seen is None:
            return
        missed = missed_runs(self.scheduler.get_jobs(), prev.last_seen, now, skip=RUN_AT_STARTUP)
        if missed:
            lines = [f"• {job_id} — {_fmt(first)}" + (f" и ещё {count - 1}" if count > 1 else "")
                     for job_id, first, count in missed]
            await self.alerts.notify(Alert(
                "Пока бот не работал, пропущены задачи",
                f"Бот не работал с {_fmt(prev.last_seen)} по {_fmt(now)}. Эти запуски не выполнились "
                f"и сами не повторятся:\n" + "\n".join(lines),
                level=logging.WARNING,
            ))
