import logging
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dishka import AsyncContainer

from src.jobs.cron_jobs import cleanup_booking_session_job

logger = logging.getLogger(__name__)


def register_jobs(sched: AsyncIOScheduler, container: AsyncContainer) -> None:

    sched.add_job(
        partial(cleanup_booking_session_job, container),
        trigger=IntervalTrigger(minutes=3),
        id="cleanup_booking_session_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True
    )
    logger.info("register job: cleanup_booking_session_job | Interval 3 minutes")



