from collections import defaultdict
from datetime import date
from typing import Optional, List, Dict
from sqlalchemy import select, func, false, update, literal, exists, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from src.dto.booking_dto import (DateBookingsDTO, UserBookingDTO, UserOwnBookingsDTO,
                                 UserWaitlistDTO, CancelBookingDTO)
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.dto.user_dto import UserDTO
from src.storage.postgres.models import (User, Booking, OfficeCapacityWeekday,
                                         CalendarDate, BookingStateDict, WaitList,
                                         UserSettings)
from src.utils.db_exc_wrapper import with_db_errors

@with_db_errors
class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session
# ───────────────────────────────────────────────────────────────────────────────
#  USERS
# ───────────────────────────────────────────────────────────────────────────────
    async def create_user(self, tg_id: int, full_name: str) -> None:
        new_user = User(user_id=tg_id, full_name=full_name)
        self.session.add(new_user)

    async def get_user_by_tg_id(self, tg_id: int) -> Optional[UserDTO]:
        result = await self.session.execute(
            select(User).where(User.user_id == tg_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        return UserDTO.model_validate(user)


# ───────────────────────────────────────────────────────────────────────────────
#  USERS SETTINGS
# ───────────────────────────────────────────────────────────────────────────────
    async def get_auto_confirm_setting(self, user_id: int) -> bool:

        stmt = (
            select(
                func.coalesce(UserSettings.auto_confirm, false())
            )
            .where(UserSettings.user_id == user_id)
        )

        val = (await self.session.execute(stmt)).scalar_one_or_none()

        return bool(val)


# ───────────────────────────────────────────────────────────────────────────────
#  BOOKINGS
# ───────────────────────────────────────────────────────────────────────────────
    async def get_active_bookings_by_range(self, cal_date_start: date,
                                   cal_date_end: date) -> List[DateBookingsDTO]:
        stmt = (
        select(
            Booking.cal_date,
            User.full_name,
            Booking.status_id,
        )
        .join(User, Booking.user_id == User.user_id)
        .where(
            Booking.cal_date.between(cal_date_start, cal_date_end),
            Booking.status_id.in_((1, 2)), # Только активные
        )
        .order_by(Booking.cal_date, User.full_name)
    )

        rows = await self.session.execute(stmt)
        data = rows.all()

        grouped: Dict[date, List[UserBookingDTO]] = defaultdict(list)
        for cal_date_, full_name, status_id in data:
            grouped[cal_date_].append(UserBookingDTO(full_name=full_name,
                                                     status_id=status_id))

        return [
        DateBookingsDTO(cal_date=cd, users=grouped[cd])
        for cd in sorted(grouped)
    ]

    async def get_user_bookings_by_range(self,
                                         user_id: int,
                                         week_start: date,
                                         week_end: date
                                         ) -> List[UserOwnBookingsDTO]:

        stmt = (
            select(
                Booking.cal_date,
                Booking.status_id,
                BookingStateDict.description
            ).join(BookingStateDict, Booking.status_id == BookingStateDict.state_id)
        ).where(
            Booking.cal_date.between(week_start, week_end),
            Booking.status_id.in_((1, 2)),  # Только активные
            Booking.user_id == user_id,
        ).order_by(Booking.cal_date)

        result = await self.session.execute(stmt)
        return [UserOwnBookingsDTO(**m) for m in result.mappings()]


    async def create_booking(self, user_id: int, cal_date: date, auto_confirm: bool) -> None:

        new_booking = Booking(
            user_id=user_id,
            cal_date=cal_date,
            status_id=1 if not auto_confirm else 2,
            source_id=4,
            confirmed_at=None if not auto_confirm else func.now()
        )
        self.session.add(new_booking)


    async def cancel_booking(self, user_id: int, cal_date: date) -> CancelBookingDTO:

        # 1 - Обновляем статус брони на отменено
        stmt = (
            update(Booking)
            .where(Booking.user_id == user_id,
                   Booking.cal_date == cal_date)
            .values(status_id = 3,
                    cancelled_at=func.now())
        )
        await self.session.execute(stmt)

        # 2 - Убедиться, что есть места
        free_count = await self.get_free_places_count(cal_date)
        if free_count == 0:
            return CancelBookingDTO(cal_date=cal_date)

        # 3 - Получить чела из waitlist
        waiter = (
            await self.session.execute(
                select(WaitList)
                .where(
                    WaitList.cal_date == cal_date,
                    WaitList.cancelled_at.is_(None),
                )
                .order_by(WaitList.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

        if waiter is None:
            return CancelBookingDTO(cal_date=cal_date)

        # 4 - Нужно ли для него делать авто подтверждение брони
        auto_confirm = await self.get_auto_confirm_setting(waiter.user_id)

        try:
            book_to_waiter = await self.session.execute(
                insert(Booking)
                .values(
                    user_id=waiter.user_id,
                    cal_date=cal_date,
                    status_id=1 if not auto_confirm else 2,
                    source_id=6,
                    confirmed_at=None if not auto_confirm else func.now()
                )
                .returning(Booking.booking_id)
            )
            new_booking_id: int = book_to_waiter.scalar_one()
        except IntegrityError:
            await self.session.rollback()
            return CancelBookingDTO(cal_date=cal_date)

        # 5 - помечаем в waitlist, что все четко
        waiter.promoted_booking_id = new_booking_id
        waiter.cancelled_at =func.now()
        return CancelBookingDTO(cal_date=cal_date,
                                waiter_user_id=waiter.user_id)


    async def get_free_places_count(self, cal_date: date) -> int:

        weekday = cal_date.isoweekday()

        capacity_subq = (
            select(OfficeCapacityWeekday.capacity)
            .where(OfficeCapacityWeekday.weekday == weekday)
            .scalar_subquery()
        )

        capacity_expr = func.coalesce(capacity_subq, 0)

        booked_subq = (
            select(func.count(literal(1)))
            .where(
                Booking.cal_date == cal_date,
                Booking.status_id.in_((1, 2)),
            )
            .scalar_subquery()
        )

        stmt = select((capacity_expr - booked_subq).label("free_seats"))

        result = await self.session.execute(stmt)
        return int(result.scalar_one())


# ───────────────────────────────────────────────────────────────────────────────
#  OFFICE CAPACITY
# ───────────────────────────────────────────────────────────────────────────────
    async def get_office_capacity(self) -> List[OfficeCapacityDTO]:
        stmt = (
            select(
                OfficeCapacityWeekday.weekday,
                OfficeCapacityWeekday.short_name,
                OfficeCapacityWeekday.capacity,
            ).order_by(OfficeCapacityWeekday.weekday)
        )

        result = await self.session.execute(stmt)
        return [OfficeCapacityDTO(**m) for m in result.mappings()]


# ───────────────────────────────────────────────────────────────────────────────
#  CALENDAR DATES
# ───────────────────────────────────────────────────────────────────────────────
    async def get_calendar_dates_by_range(self, cal_date_start: date,
                                   cal_date_end: date) -> List[CalendarDatesDTO]:
        stmt = select(
            CalendarDate.cal_date,
            CalendarDate.is_holiday,
            CalendarDate.is_weekend
        ).where(
            CalendarDate.cal_date.between(cal_date_start, cal_date_end),
        ).order_by(CalendarDate.cal_date)

        result = await self.session.execute(stmt)
        return [CalendarDatesDTO(**m) for m in result.mappings()]


# ───────────────────────────────────────────────────────────────────────────────
#  WAIT LIST
# ───────────────────────────────────────────────────────────────────────────────
    async def get_user_waiting_list_by_range(
            self,
            user_id: int,
            week_start: date,
            week_end: date,
    ) -> List[UserWaitlistDTO]:

        queue_with_pos = (
            select(
                WaitList.cal_date,
                WaitList.user_id,
                func.row_number()
                .over(
                    partition_by=WaitList.cal_date,
                    order_by=WaitList.created_at,
                )
                .label("position"),
            )
            .where(WaitList.cancelled_at.is_(None))  # только активные
        ).subquery()

        # ---- основной запрос: берём строки нужного пользователя -------------
        stmt = (
            select(
                queue_with_pos.c.cal_date,
                queue_with_pos.c.position,
            )
            .where(
                queue_with_pos.c.user_id == user_id,
                queue_with_pos.c.cal_date.between(week_start, week_end),
            )
            .order_by(queue_with_pos.c.cal_date)
        )

        result = await self.session.execute(stmt)

        return [ UserWaitlistDTO(**m) for m in result.mappings()]



    async def join_to_queue(self,
                          user_id: int,
                          cal_date: date) -> None:

        join_request = WaitList(user_id=user_id, cal_date=cal_date)
        self.session.add(join_request)


    async def leave_from_queue(self,
                               user_id: int,
                               cal_date: date) -> None:
        stmt = update(
            WaitList
        ).where(
            WaitList.cal_date == cal_date,
            WaitList.cancelled_at.is_(None),
            WaitList.user_id == user_id,
        ).values(
            cancelled_at=func.now()
        )
        await self.session.execute(stmt)



    async def check_if_user_promoted(self,
                                     user_id: int,
                                     cal_date: date) -> bool:
        stmt = (
            select(
                exists().where(
                    WaitList.cal_date == cal_date,
                    WaitList.user_id == user_id,
                    WaitList.promoted_booking_id.isnot(None),
                )
            )
        )
        result = await self.session.scalar(stmt)

        return bool(result)

