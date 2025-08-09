from datetime import date
from typing import List

from src.dto.booking_dto import DateBookingsDTO, WeekAttendanceDTO, CancelBookingDTO
from src.services.exceptions import (FreePlaceIsNotFound, BookingIsAlreadyExist,
                                     CancelIsAlreadyExist, FreePlaceIsAvailable,
                                     UserIsAlreadyInWaitingList, UserIsAlreadyPromoted)
from src.storage.postgres.repository import Repository


class BookingService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_active_bookings_by_range(self, week_start: date,
                                  week_end: date) -> List[DateBookingsDTO]:
        data = await self.repo.get_active_bookings_by_range(week_start, week_end)
        return data

    async def get_user_bookings_by_range(self,
                                         user_id: int,
                                         week_start: date,
                                         week_end: date) -> WeekAttendanceDTO:

        bookings = await self.repo.get_user_bookings_by_range(
            user_id, week_start, week_end
        )

        waitlist = await self.repo.get_user_waiting_list_by_range(
            user_id, week_start, week_end
        )
        return WeekAttendanceDTO(
            week_start=week_start,
            week_end=week_end,
            bookings=bookings,
            waitlist=waitlist,
        )

    async def create_booking(self, user_id: int, cal_date: date) -> None:

        exist = await self.repo.get_user_bookings_by_range(
            user_id=user_id, week_start=cal_date, week_end=cal_date)

        if exist:
            raise BookingIsAlreadyExist("✅ У тебя уже есть бронь на этот день! "
                             "Повторная бронь не требуется.")

        free_count = await self.repo.get_free_places_count(cal_date)
        if free_count == 0:
            raise FreePlaceIsNotFound("⏳ Мест уже нет, но ты можешь встать в очередь, "
                             "нажав на кнопку еще раз.")

        auto_confirm = await self.repo.get_auto_confirm_setting(user_id=user_id)

        return await self.repo.create_booking(
            user_id=user_id, cal_date=cal_date, auto_confirm=auto_confirm
        )


    async def cancel_booking(self,
                             user_id: int,
                             cal_date: date
                             ) -> CancelBookingDTO:

        exist = await self.repo.get_user_bookings_by_range(
            user_id=user_id, week_start=cal_date, week_end=cal_date)

        if not exist:
            raise CancelIsAlreadyExist("✅ У тебя больше нет брони на этот день! "
                             "Повторная отмена не требуется.")

        cancel = await self.repo.cancel_booking(user_id=user_id, cal_date=cal_date)
        return cancel


    async def join_queue(self, user_id: int, cal_date: date) -> None:

        check_count = await self.repo.get_free_places_count(cal_date=cal_date)
        if check_count > 0:
            auto_confirm = await self.repo.get_auto_confirm_setting(user_id=user_id)
            await self.repo.create_booking(user_id=user_id,
                                           cal_date=cal_date,
                                           auto_confirm=auto_confirm)
            raise FreePlaceIsAvailable("✅ Место освободилось — ты записан!")

        entry = await self.repo.get_user_waiting_list_by_range(
            user_id, cal_date, cal_date
        )
        if entry:
            raise UserIsAlreadyInWaitingList(f"ℹ️ Ты №{entry[0].position} в очереди. Чтобы выйти, нажми кнопку с 🚪")

        return await self.repo.join_to_queue(
            user_id=user_id, cal_date=cal_date
        )


    async def leave_from_queue(self, user_id: int, cal_date: date) -> None:

        if await self.repo.check_if_user_promoted(user_id, cal_date):
            raise UserIsAlreadyPromoted("ℹ️ Ты уже записан на этот день! "
                          "Чтобы отменить, нажми на кнопку еще раз")

        return await self.repo.leave_from_queue(user_id, cal_date)







