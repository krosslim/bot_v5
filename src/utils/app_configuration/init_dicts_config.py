from datetime import date, timedelta
import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models import OfficeCapacityWeekday, CalendarDate, BookingStatusDict, SystemConfig
from src.utils.app_configuration.register import SystemTask

logger = logging.getLogger(__name__)

@SystemTask.register("init_configure_bot_db", "Настройка базовых справочников")
async def init_configure_bot_db(session: AsyncSession) -> None:

    async with session.begin():
        # 1) OfficeCapacityWeekday
        weekdays_payload = [
            {"weekday": 1, "short_name": "ПН", "name": "Понедельник", "capacity": 12},
            {"weekday": 2, "short_name": "ВТ", "name": "Вторник",      "capacity": 12},
            {"weekday": 3, "short_name": "СР", "name": "Среда",         "capacity": 12},
            {"weekday": 4, "short_name": "ЧТ", "name": "Четверг",       "capacity": 12},
            {"weekday": 5, "short_name": "ПТ", "name": "Пятница",       "capacity": 12},
            {"weekday": 6, "short_name": "СБ", "name": "Суббота",       "capacity": 12},
            {"weekday": 7, "short_name": "ВС", "name": "Воскресенье",   "capacity": 12},
        ]
        await session.execute(insert(OfficeCapacityWeekday).values(weekdays_payload))

        # 2) CalendarDate
        flags = "11111111001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100011110001111000001100000110000011000001100011110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000001100000110000011000000111000110000011000001100000110000011000001100000110000011001"
        start = date(2025, 1, 1)

        rows = []

        for i, code in enumerate(flags):
            d = start + timedelta(days=i)
            is_weekend = d.weekday() >= 5
            is_holiday = code == "1"
            rows.append((d, is_weekend, is_holiday))

        cal_payload = [
            {"cal_date": d, "is_weekend": is_w, "is_holiday": is_h}
            for d, is_w, is_h in rows
        ]
        await session.execute(insert(CalendarDate).values(cal_payload))

        # 3) BookingStatusDict
        parents = [
            {"slug": "BOOKED",     "parent_slug": None, "display_name": "ЗАБРОНИРОВАНО", "is_hidden": True},
            {"slug": "CANCELED",  "parent_slug": None, "display_name": "ОТМЕНЕНО", "is_hidden": True},
            {"slug": "WAITLISTED", "parent_slug": None, "display_name": "В ЛИСТЕ ОЖИДАНИЯ", "is_hidden": True},
        ]

        children = [
            # BOOKED
            {"slug": "CONFIRMED", "parent_slug": "BOOKED", "display_name": "ПОДТВЕРЖДЕН", "is_hidden": True},
            {"slug": "RESERVED", "parent_slug": "BOOKED", "display_name": "ОЖИДАЕТ ПОДТВЕРЖДЕНИЯ", "is_hidden": True},

            # CANCELED
            {"slug": "CANCELED_ILL",                   "parent_slug": "CANCELED", "display_name": "БОЛЕЗНЬ", "is_hidden": False},
            {"slug": "CANCELED_FAMILY",                "parent_slug": "CANCELED", "display_name": "СЕМЕЙНОЕ", "is_hidden": False},
            {"slug": "CANCELED_CHANGED_MIND",          "parent_slug": "CANCELED", "display_name": "ПЕРЕДУМАЛ", "is_hidden": False},
            {"slug": "CANCELED_OTHER",                 "parent_slug": "CANCELED", "display_name": "ДРУГОЕ", "is_hidden": False},
            {"slug": "CANCELED_NO_SPOTS_WAITLIST",     "parent_slug": "CANCELED", "display_name": "НЕ БЫЛО МЕСТ ДЛЯ ПЕРЕВОДА ИЗ ЛИСТА ОЖИДАНИЯ", "is_hidden": True},
            {"slug": "CANCELED_NOT_CONFIRMED",         "parent_slug": "CANCELED", "display_name": "БРОНЬ НЕ БЫЛА ПОДТВЕРЖДЕНА", "is_hidden": True},
            {"slug": "CANCELED_ADMIN",                 "parent_slug": "CANCELED", "display_name": "ОТМЕНЕНО АДМИНИСТРАТОРОМ", "is_hidden": True},
            {"slug": "CANCELED_LEFT_CHAT",             "parent_slug": "CANCELED", "display_name": "ВЫШЕЛ ИЗ ЧАТА / УДАЛИЛИ ИЗ ЧАТА", "is_hidden": True},
            {"slug": "CANCELED_VACATION",              "parent_slug": "CANCELED", "display_name": "В ОТПУСКЕ", "is_hidden": False},

            # WAITLISTED
            {"slug": "WAITLISTED_MANUAL",               "parent_slug": "WAITLISTED", "display_name": "ПОЛЬЗОВАТЕЛЬ ВСТАЛ В ОЧЕРЕДЬ", "is_hidden": True},
            {"slug": "WAITLISTED_NO_SPOTS_AUTO",        "parent_slug": "WAITLISTED", "display_name": "НЕ БЫЛО МЕСТ ПРИ АВТОБРОНИРОВАНИИ", "is_hidden": True},
        ]

        await session.execute(insert(BookingStatusDict).values(parents))
        await session.execute(insert(BookingStatusDict).values(children))

        await session.execute(insert(SystemConfig)
                .values(key="init_configure_bot_db", value=f"done"))

        logger.info(f"Task 'init_configure_bot_db' is done")


