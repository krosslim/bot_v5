import logging
from datetime import date, timedelta
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models import CalendarDate, SystemConfig
from src.utils.app_configuration.register import SystemTask

logger = logging.getLogger(__name__)


@SystemTask.register("init_is_workday_db", "Настройка is_workday в таблице calendar_dates для 2025")
async def init_is_workday_db(session: AsyncSession) -> None:
    async with session.begin():
        flags = "11111111001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100011110001111000001100000110000011000001100011110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000000111000110000011000001100000110000011000001100000110000011001"
        start = date(2025, 1, 1)
        rows = []

        for i, code in enumerate(flags):
            d = start + timedelta(days=i)
            if code == "1":
                is_workday = False
            else:
                is_workday = True
            rows.append({"cal_date": d, "is_workday": is_workday})


        await session.run_sync(
            lambda sync_session: sync_session.bulk_update_mappings(
                CalendarDate, rows
            )
        )

        await session.execute(insert(SystemConfig)
                              .values(key="init_is_workday_db", value=f"done"))

        logger.info(f"Task 'init_is_workday_db' is done")











