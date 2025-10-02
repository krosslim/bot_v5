from datetime import date
from typing import List, Optional, Dict, Any

from src.dto.booking_dto import (DateBookingsDTO, BookingStatus, OwnBookingDTO,
                                 WaitlistPositionDTO, WeekVisitsDTO, UserBookingWeekResultDTO)
from src.services.exceptions import (FreePlaceIsNotFound, BookingIsAlreadyExist,
                                     CancelIsAlreadyExist, UserIsAlreadyInWaitingList, UserIsAlreadyLeaveQueue)
from src.storage.postgres.repository import Repository
from src.utils.month_first_last_by_offset import month_first_last
from src.utils.today import effective_today


class BookingService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_active_bookings_by_range(self, start: date, end: date) -> List[DateBookingsDTO]:
        data = await self.repo.bookings_by_range(
            start, end, [BookingStatus.BOOKED, BookingStatus.WAITLISTED]
        )
        return data

    async def get_bookings_for_remind(self, tomorrow: date) -> List[DateBookingsDTO]:
        data = await self.repo.bookings_by_range(
            tomorrow, tomorrow, [BookingStatus.BOOKED]
        )
        return data

    async def get_own_active_bookings(self, user_id: int) -> List[OwnBookingDTO]:

        today = effective_today()
        bookings = await self.repo.own_active_bookings(user_id, today)
        return bookings

    async def get_waitlist_position(self, user_id: int, date_list: list) -> List[WaitlistPositionDTO]:
        position = await self.repo.position_in_waitlist(user_id, date_list)
        return position

    async def pre_check_booking(self, user_id: int, cal_date: date, capacity: int) -> bool:
        check = await self.repo.take_capacity_slot(user_id, cal_date, capacity, False)
        if not check:
            raise FreePlaceIsNotFound("⏳ Мест уже нет, но ты можешь встать в очередь.")
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


    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        booking_id = await self.repo.confirm_booking(user_id, cal_date)
        if booking_id:
            await self.repo.insert_event(booking_id, BookingStatus.BOOKED, BookingStatus.CONFIRMED, user_id)
        return booking_id


    async def get_booking_changes(self, month_offset: int = 0) -> bool:
        return await self.repo.has_booking_changes(month_offset)


    async def get_users_month_bookings(self, month_offset: int = 0) -> List[Dict[str, Any]]:

        start, end = month_first_last(month_offset)
        data = await self.repo.bookings_data_for_sheet(start, end)

        grouped = {}

        for item in data:
            key = (item['team'], item['position'], item['name'])

            if key not in grouped:
                grouped[key] = []

            if item['cal_date'] is not None:
                grouped[key].append(item['cal_date'])

        result = []
        for (team, position, name), dates in grouped.items():
            result.append({
                'team': team,
                'position': position,
                'name': name,
                'days': [d.strftime('%d.%m') for d in sorted(dates)],
            })

        return result


    async def get_booking_changes_for_day(self, cal_date: date) -> bool:
        return await self.repo.has_booking_changes_for_day(cal_date)


    async def get_user_booking_for_day(self, user_id: int, cal_date: date) -> Optional[OwnBookingDTO]:
        return await self.repo.get_user_booking_for_date(user_id, cal_date)


    async def week_visits(self, start: date, end: date) -> List[WeekVisitsDTO]:
        return await self.repo.get_week_visits(start, end)

    async def week_max(self, start: date, end: date) -> List[UserBookingWeekResultDTO]:
        return await self.repo.get_users_max_bookings(start, end)







