import logging
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dishka import AsyncContainer

from src.jobs.cron_jobs import (
    cleanup_booking_session_job,
    chat_remind_job,
    sheet_update_job,
    week_result_job
)

from config import settings as s

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

    sched.add_job(
        partial(chat_remind_job, container, sched),
        trigger=CronTrigger(
            hour=s.REMIND_JOB_HOUR,
            minute=s.REMIND_JOB_MINUTES,
            timezone=sched.timezone
        ),
        id="chat_remind_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True
    )
    logger.info("register job: chat_remind_job | everyday, hour=%s, minute=%s",
                s.REMIND_JOB_HOUR, s.REMIND_JOB_MINUTES)

    sched.add_job(
        partial(sheet_update_job, container),
        trigger=IntervalTrigger(minutes=1),
        id="sheet_update_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True
    )
    logger.info("register job: sheet_update_job | Interval 1 minute")

    sched.add_job(
        partial(week_result_job, container),
        trigger=CronTrigger(
            day_of_week="fri,sat",
            hour=s.FRIDAY_JOB_HOUR,
            minute=s.FRIDAY_JOB_MINUTES,
            timezone=sched.timezone
        ),
        id="week_result_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    logger.info("register job: week_result_job | day_of_week=fri/sat, hour= %s, minute= %s", s.FRIDAY_JOB_HOUR, s.FRIDAY_JOB_MINUTES)



    # --- Для тестов ---
    # sched.add_job(
    #     partial(week_result_job, container),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="week_result_job_test",
    #     max_instances=1,
    #     coalesce=True,
    #     misfire_grace_time=60,
    # )

    # --- Для тестов ---
    # sched.add_job(
    #     partial(chat_remind_job, container, sched),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="chat_remind_job_test",
    #     max_instances=1,
    #     misfire_grace_time=60,
    #     coalesce=True
    # )