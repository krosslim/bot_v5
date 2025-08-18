from datetime import date
from typing import List, Optional

from src.dto.booking_dto import DateBookingsDTO, BookingStatus
from src.services.exceptions import (FreePlaceIsNotFound, BookingIsAlreadyExist,
                                     CancelIsAlreadyExist, UserIsAlreadyInWaitingList, UserIsAlreadyLeaveQueue)
from src.storage.postgres.repository import Repository


class BookingService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_active_bookings_by_range(self, start: date, end: date) -> List[DateBookingsDTO]:
        data = await self.repo.bookings_by_range(
            start, end, [BookingStatus.BOOKED, BookingStatus.WAITLISTED]
        )
        return data


    async def pre_check_booking(self, user_id: int, cal_date: date, capacity: int) -> bool:
        check = await self.repo.take_capacity_slot(user_id, cal_date, capacity, False)
        if not check:
            raise FreePlaceIsNotFound("⏳ Мест уже нет, но ты можешь встать в очередь, "
                                      "нажав на кнопку еще раз.")
        return check


    async def create_booking(self, user_id: int, cal_date: date, auto_confirm: bool) -> None:

        if auto_confirm:
            sub_status = BookingStatus.CONFIRMED
        else:
            sub_status = BookingStatus.RESERVED

        booking_id = await self.repo.upsert_booked(user_id, cal_date, BookingStatus.BOOKED, sub_status)
        if booking_id:
            await self.repo.insert_event(booking_id, BookingStatus.BOOKED, sub_status, user_id)
        else:
            raise BookingIsAlreadyExist("✅ У тебя уже есть бронь на этот день! "
                             "Повторная бронь не требуется.")


    async def cancel_booking(self, user_id: int, cal_date: date) -> Optional[int]:

        cancel_promote = await self.repo.cancel_booking(user_id, cal_date)

        if cancel_promote.canceled_user_id is None:
            raise CancelIsAlreadyExist("✅ У тебя больше нет брони на этот день! "
                                       "Повторная отмена не требуется.")
        if cancel_promote.promoted_user_id:
            return cancel_promote.promoted_user_id


    async def join_queue(self, user_id: int, cal_date: date, auto_confirm: bool, capacity: int) -> bool:
        check = await self.repo.take_capacity_slot(user_id, cal_date, capacity, True)
        if check:
            await self.create_booking(user_id, cal_date, auto_confirm)
            return False

        booking_id = await self.repo.upsert_waitlisted(user_id, cal_date)
        if not booking_id:
            raise UserIsAlreadyInWaitingList(f"ℹ️ Ты уже в очереди!\nЧтобы выйти, нажми кнопку с 🚪")
        await self.repo.insert_event(booking_id, BookingStatus.WAITLISTED, BookingStatus.WAITLISTED_MANUAL, user_id)
        return True

    async def leave_from_queue(self, user_id: int, cal_date: date) -> None:

        booking_id = await self.repo.leave_waitlist(user_id, cal_date)
        if not booking_id:
            raise UserIsAlreadyLeaveQueue("ℹ️ Ты уже вышел из очереди!")

        await self.repo.insert_event(booking_id, BookingStatus.CANCELED, BookingStatus.CANCELED_CHANGED_MIND, user_id)










