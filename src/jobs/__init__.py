import logging
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dishka import AsyncContainer

from src.jobs.cron_jobs import cleanup_booking_session_job, chat_remind_job, sheet_update_job, check_chat_remind_job

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

    # sched.add_job(
    #     partial(chat_remind_job, container),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="chat_remind_job",
    #     max_instances=1,
    #     misfire_grace_time=60,
    #     coalesce=True
    # )

    sched.add_job(
        partial(chat_remind_job, container),
        trigger=CronTrigger(day_of_week="mon,tue,wed,thu,sun", hour=16, minute=00, timezone=sched.timezone),
        id="chat_remind_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True
    )
    logger.info("register job: chat_remind_job | day_of_week='mon,tue,wed,thu,sun', hour=16, minute=00")

    sched.add_job(
        partial(sheet_update_job, container),
        trigger=IntervalTrigger(minutes=1),
        id="sheet_update_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True
    )
    logger.info("register job: sheet_update_job | Interval 1 minute")

    evening = CronTrigger(
        day_of_week="mon,tue,wed,thu,sun",
        hour="16-23",
        minute="*",
        second=0,
        timezone=sched.timezone
    )

    morning_next = CronTrigger(
        day_of_week="mon,tue,wed,thu,fri",
        hour="0-11",
        minute="*",
        second=0,
        timezone=sched.timezone
    )
    sched.add_job(
        partial(check_chat_remind_job, container),
        trigger=OrTrigger([evening, morning_next]),
        id="check_chat_remind_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    logger.info("register job: check_chat_remind_job")

