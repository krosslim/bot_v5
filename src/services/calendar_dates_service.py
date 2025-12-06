from datetime import date
from typing import List

from aiocache import Cache
from aiocache.decorators import cached_stampede
from aiocache.serializers import PickleSerializer

from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.storage.postgres.repository import Repository
from src.services.exceptions import CalDateIsNotFound, NoDataForMissedBooking
from src.utils.month_first_last_by_offset import month_first_last
from src.utils.today import effective_today


class CalendarDatesService:
    def __init__(self, repo: Repository):
        self.repo = repo

    @cached_stampede(
        ttl=60 * 60 * 24 * 7,
        lease=2,
        cache=Cache.MEMORY,
        namespace="calendar_dates",
        key_builder=lambda f, self, week_start, week_end: (
                f"calendar_dates:{week_start.isoformat()}:{week_end.isoformat()}"
        ),
        serializer=PickleSerializer(),
    )
    async def get_calendar_dates_by_range(self, week_start: date,
                                  week_end: date) -> List[CalendarDatesDTO]:
        data = await self.repo.get_calendar_dates_by_range(week_start, week_end)
        return data

    async def is_workday(self, cal_date: date) -> bool:
        return await self.repo.get_workday(cal_date)

    async def get_cal_date(self, cal_date: date) -> CalendarDatesDTO:

        date_info = await self.repo.get_cal_date(cal_date)

        if date_info is None:
            raise CalDateIsNotFound("Не удалось получить данные по дате %s", cal_date)
        return date_info


    async def cal_date_without_bookings(
            self,
            user_id: int,
            prev_month: bool
    ) -> List[CalendarDatesDTO]:

        if prev_month:
            start, end = month_first_last(-1)
        else:
            end = effective_today()
            start = date(end.year, end.month, 1)

        if start == end:
            month_str = self.get_month_name(end.month)
            raise NoDataForMissedBooking(
                f"Отметиться за прошедшие дни <b>{month_str}</b> пока нельзя.\n"
                "Если вы хотите отметиться за дни предыдущего месяца, введите: <code>/missed -1</code>\n\n"
                "Для выхода в меню: <b>/menu</b>"
            )

        data = await self.repo.cal_date_without_bookings(start, end, user_id)

        if not data:
            month_str = self.get_month_name(end.month)
            raise NoDataForMissedBooking(
                f"Отметиться за прошедшие дни <b>{month_str}</b> нельзя.\nНет доступных дней\n\n"
                f"Для выхода в меню: <b>/menu</b>"
            )
        return data

    @staticmethod
    def get_month_name(month_num: int) -> str:
        if not 1 <= month_num <= 12:
            raise ValueError("Номер месяца должен быть от 1 до 12")

        months = [
            "января", "февраля", "марта", "апреля",
            "мая", "июня", "июля", "августа",
            "сентября", "октября", "ноября", "декабря"
        ]
        return months[month_num - 1]
