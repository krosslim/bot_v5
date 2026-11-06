from datetime import date
from typing import List, Optional, Dict, Any, Union, Tuple

from src.dto.booking_dto import (DateBookingsDTO, BookingStatus, OwnBookingDTO,
                                 WaitlistPositionDTO, WeekVisitsDTO, UserBookingWeekResultDTO)
from src.services.exceptions import (FreePlaceIsNotFound, BookingIsAlreadyExist,
                                     CancelIsAlreadyExist, UserIsAlreadyInWaitingList, UserIsAlreadyLeaveQueue,
                                     SeatIsTaken, SeatNotFound, NoActiveBooking)
from src.dto.booking_dto import CancelBookingFifoDTO, DaySeatRowDTO, CalendarWidgetRowDTO
from src.dto.calendar_dates_dto import DayBookingDTO
from src.storage.postgres.repository import Repository
from src.ui.widgets.layout import SEATS
from src.utils.month_first_last_by_offset import month_first_last


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
            tomorrow,
            tomorrow,
            [BookingStatus.BOOKED, BookingStatus.CANCELED],
            [BookingStatus.CONFIRMED, BookingStatus.RESERVED, BookingStatus.CANCELED_NOT_CONFIRMED]
        )
        return data

    async def get_bookings_by_status(
            self,
            start: date,
            end: date,
            status_list: Union[str, List[str]],
            sub_status_list: Optional[Union[str, List[str]]] = None
    ) -> List[DateBookingsDTO]:

        if sub_status_list is not None:
            return await self.repo.bookings_by_range(start, end, status_list, sub_status_list)

        return await self.repo.bookings_by_range(start, end, status_list)

    async def get_own_active_bookings(
            self,
            user_id: int,
            cal_date: Union[date, Tuple[date, date], List[date]],
    ) -> List[OwnBookingDTO]:

        bookings = await self.repo.own_active_bookings(user_id, cal_date)
        return bookings

    async def get_waitlist_position(self, user_id: int, date_list: list) -> List[WaitlistPositionDTO]:
        position = await self.repo.position_in_waitlist(user_id, date_list)
        return position

    async def pre_check_booking(self, user_id: int, cal_date: date, capacity: int) -> bool:
        check = await self.repo.take_capacity_slot(user_id, cal_date, capacity, False)
        if not check:
            raise FreePlaceIsNotFound("⏳ Мест уже нет, но вы можете встать в очередь.")
        return check

    async def pick_seat(self, cal_date: date, preferred: Optional[int] = None) -> Optional[int]:
        """Свободное место на день. Вызывать после блокировки дня (take_capacity_slot / lock_cal_date).

        preferred — место, выбранное в виджете: если его нет на схеме или оно занято, бронь не создаётся.
        Без preferred — первое свободное место, а если все места схемы заняты — None: бронь без номера места.
        Число броней ограничивает лимит дня (take_capacity_slot), схема зала его не урезает,
        поэтому capacity может быть больше len(SEATS)."""
        taken = await self.repo.taken_seats(cal_date)
        if preferred:
            if preferred not in SEATS:
                raise SeatNotFound("Такого места нет на схеме")
            if preferred in taken:
                raise SeatIsTaken("Это место только что заняли")
            return preferred
        return next((seat for seat in SEATS if seat not in taken), None)

    async def day_seat_rows(self, cal_date: date) -> List[DaySeatRowDTO]:
        return await self.repo.day_seat_rows(cal_date)

    async def calendar_widget_rows(self, user_id: int, start: date, end: date) -> List[CalendarWidgetRowDTO]:
        return await self.repo.calendar_widget_rows(user_id, start, end)

    async def move_seat(self, user_id: int, cal_date: date, seat_no: int) -> None:
        """Пересадка: разрешена всегда, если место свободно"""
        await self.repo.lock_cal_date(cal_date)
        booking = await self.repo.get_user_booking_for_date(user_id, cal_date)
        if booking is None:
            raise NoActiveBooking("Брони на этот день нет")
        if booking.seat_no == seat_no:
            raise SeatIsTaken("Это место уже ваше")
        await self.pick_seat(cal_date, seat_no)
        await self.repo.set_seat(user_id, cal_date, seat_no)


    async def create_booking(
            self, user_id: int, cal_date: date, auto_confirm: bool, seat_no: Optional[int] = None
    ) -> None:

        if auto_confirm:
            sub_status = BookingStatus.CONFIRMED
        else:
            sub_status = BookingStatus.RESERVED

        booking_id = await self.repo.upsert_booked(user_id, cal_date, BookingStatus.BOOKED, sub_status, seat_no)
        if booking_id:
            await self.repo.insert_event(booking_id, BookingStatus.BOOKED, sub_status, user_id, seat_no)
        else:
            raise BookingIsAlreadyExist("✅ У вас уже есть бронь на этот день! "
                             "Повторная бронь не требуется.")


    async def cancel_booking(self, user_id: int, cal_date: date, cancel_sub_status: str | None) -> CancelBookingFifoDTO:

        # Блокировка дня: отмена, повышение из очереди и выдача мест идут по очереди
        await self.repo.lock_cal_date(cal_date)
        cancel_promote = await self.repo.cancel_booking(user_id, cal_date, cancel_sub_status)

        if cancel_promote.canceled_user_id is None:
            raise CancelIsAlreadyExist("✅ У вас больше нет брони на этот день! "
                                       "Повторная отмена не требуется.")

        # У отменённой брони могло не быть места — тогда повышенному выдаём первое свободное, если оно есть
        if cancel_promote.promoted_user_id and cancel_promote.seat_no is None:
            seat = await self.pick_seat(cal_date)
            if seat:
                await self.repo.set_seat(cancel_promote.promoted_user_id, cal_date, seat)
                cancel_promote = cancel_promote.model_copy(update={"seat_no": seat})
        return cancel_promote


    async def join_queue(self, user_id: int, cal_date: date, auto_confirm: bool, capacity: int) -> bool:
        check = await self.repo.take_capacity_slot(user_id, cal_date, capacity, True)
        if check:
            seat = await self.pick_seat(cal_date)
            await self.create_booking(user_id, cal_date, auto_confirm, seat)
            return False

        booking_id = await self.repo.upsert_waitlisted(user_id, cal_date)
        if not booking_id:
            raise UserIsAlreadyInWaitingList("ℹ️ Вы уже в очереди!\nЧтобы выйти, нажмите кнопку с 🚪")
        await self.repo.insert_event(booking_id, BookingStatus.WAITLISTED, BookingStatus.WAITLISTED_MANUAL, user_id)
        return True

    async def leave_from_queue(self, user_id: int, cal_date: date) -> None:

        booking_id = await self.repo.leave_waitlist(user_id, cal_date)
        if not booking_id:
            raise UserIsAlreadyLeaveQueue("ℹ️ Вы уже вышли из очереди!")

        await self.repo.insert_event(booking_id, BookingStatus.CANCELED, BookingStatus.CANCELED_CHANGED_MIND, user_id)


    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        booking_id = await self.repo.confirm_booking(user_id, cal_date)
        if booking_id:
            await self.repo.insert_event(booking_id, BookingStatus.BOOKED, BookingStatus.CONFIRMED, user_id)
        return booking_id

    async def update_booking_status(
            self,
            cal_date: date,
            current_status: BookingStatus,
            current_sub_status: BookingStatus,
            status: BookingStatus,
            sub_status: BookingStatus
    ) -> int:
        return await self.repo.update_booking_status(cal_date, current_status, current_sub_status, status, sub_status)


    async def get_booking_changes(self, month_offset: int = 0) -> bool:

        start, end = month_first_last(month_offset)
        return await self.repo.has_booking_changes(start, end)


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


    async def get_user_booking_for_day(self, user_id: int, cal_date: date, for_update: bool = False) -> Optional[OwnBookingDTO]:
        return await self.repo.get_user_booking_for_date(user_id, cal_date, for_update)


    async def week_visits(self, start: date, end: date) -> List[WeekVisitsDTO]:
        return await self.repo.get_week_visits(start, end)


    async def week_max(self, start: date, end: date) -> List[UserBookingWeekResultDTO]:
        return await self.repo.get_users_max_bookings(start, end)


    async def book_missed(
            self,
            user_id: int,
            cal_date: date
    ) -> None:
        return await self.repo.book_missed(user_id, cal_date)

    async def active_bookings_on(self, cal_dates: List[date]) -> List[DayBookingDTO]:
        return await self.repo.active_bookings_on(cal_dates)
