import logging
from datetime import datetime, timedelta
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.combining import OrTrigger
from dishka import AsyncContainer

from config import settings as s
from src.jobs.cron_jobs import (
    cleanup_booking_session_job,
    chat_remind_job,
    sheet_update_job,
    week_result_job,
    check_chat_remind_reserve_job,
    remind_to_confirm_booking_job,
    cancel_waitlist_bookings_job,
    cancel_not_confirmed_booking_job
)

logger = logging.getLogger(__name__)


def register_jobs(sched: AsyncIOScheduler, container: AsyncContainer) -> None:

    sched.add_job(
        partial(cleanup_booking_session_job, container),
        trigger=IntervalTrigger(minutes=3),
        id="cleanup_booking_session_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
        replace_existing = True
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
        coalesce=True,
        replace_existing = True
    )
    logger.info("register job: chat_remind_job | everyday, hour=%s, minute=%s",
                s.REMIND_JOB_HOUR, s.REMIND_JOB_MINUTES)


    sched.add_job(
        partial(sheet_update_job, container),
        trigger=IntervalTrigger(minutes=1),
        id="sheet_update_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
        replace_existing=True
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
        replace_existing = True
    )
    logger.info("register job: week_result_job | day_of_week=fri/sat, hour= %s, minute= %s", s.FRIDAY_JOB_HOUR, s.FRIDAY_JOB_MINUTES)


    run_dt = datetime.now(tz=sched.timezone) + timedelta(seconds=10)
    sched.add_job(
        partial(check_chat_remind_reserve_job, container, sched),
        trigger='date',
        id="check_chat_remind_reserve_job",
        run_date=run_dt,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True
    )
    logger.info("register job: check_chat_remind_reserve_job | next run_dt=%s", run_dt)


    sched.add_job(
        partial(remind_to_confirm_booking_job, container),
        trigger=OrTrigger([
            CronTrigger(
            hour=s.CONFIRM_REMIND_JOB_HOUR,
            minute=s.CONFIRM_REMIND_JOB_MINUTES,
            timezone=sched.timezone
            ),
            CronTrigger(
                hour=s.CONFIRM_REMIND_REPEAT_JOB_HOUR,
                minute=s.CONFIRM_REMIND_REPEAT_JOB_MINUTES,
                timezone=sched.timezone
            )
        ]),
        id="remind_to_confirm_booking_job",
        max_instances = 1,
        coalesce = True,
        misfire_grace_time = 60,
        replace_existing = True
    )

    logger.info("register job: remind_to_confirm_booking_job | every day | first at: %s:%s, second at %s:%s",
                s.CONFIRM_REMIND_JOB_HOUR, s.CONFIRM_REMIND_JOB_MINUTES,
                s.CONFIRM_REMIND_REPEAT_JOB_HOUR, s.CONFIRM_REMIND_REPEAT_JOB_MINUTES)

    run_minute = s.WORK_END_MINUTES+1
    sched.add_job(
        partial(cancel_waitlist_bookings_job, container),
        trigger=CronTrigger(
            hour=s.WORK_END_HOUR,
            minute=run_minute,
            timezone=sched.timezone
        ),
        id="cancel_waitlist_bookings_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
        replace_existing=True
    )
    logger.info("register job: cancel_waitlist_bookings_job | every day | start at: %s:%s", s.WORK_END_HOUR, run_minute)


    sched.add_job(
        partial(cancel_not_confirmed_booking_job, container),
        trigger=CronTrigger(
            hour=s.CANCEL_BOOKING_JOB_HOUR,
            minute=s.CANCEL_BOOKING_JOB_MINUTES,
            timezone=sched.timezone
        ),
        id="cancel_not_confirmed_booking_job",
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
        replace_existing=True
    )
    logger.info("register job: cancel_not_confirmed_booking_job | every day | start at: %s:%s",
                s.CANCEL_BOOKING_JOB_HOUR, s.CANCEL_BOOKING_JOB_MINUTES)



    # --- Для тестов ---
    # sched.add_job(
    #     partial(week_result_job, container),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="week_result_job_test",
    #     max_instances=1,
    #     coalesce=True,
    #     misfire_grace_time=60,
    # )

    # sched.add_job(
    #     partial(chat_remind_job, container, sched),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="chat_remind_job_test",
    #     max_instances=1,
    #     misfire_grace_time=60,
    #     coalesce=True
    # )

    # sched.add_job(
    #     partial(remind_to_confirm_booking_job, container, sched),
    #     trigger=IntervalTrigger(seconds=10),
    #     id="remind_to_confirm_booking_job_test",
    #     max_instances=1,
    #     misfire_grace_time=60,
    #     coalesce=True
    # )