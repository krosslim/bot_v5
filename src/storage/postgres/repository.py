from collections import defaultdict
from datetime import date
from typing import Optional, List, Dict, Union, Sequence, Tuple

from sqlalchemy import select, update, and_, func, not_, or_, extract, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.booking_dto import (DateBookingsDTO, UserBookingDTO,
                                 CancelBookingFifoDTO, BookingStatus, OwnBookingDTO,
                                 WaitlistPositionDTO, WeekVisitsDTO, UserBookingWeekResultDTO)
from src.dto.calendar_dates_dto import CalendarDatesDTO, DigestScheduleDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO, AvailabilityDTO
from src.dto.user_dto import UserDTO, DictDTO
from src.storage.postgres.models import (User, Booking, OfficeCapacityWeekday,
                                         CalendarDate, BookingEvent, Profession, Product,
                                         DigestSchedule)
from src.utils.db_exc_wrapper import with_db_errors, DBError


@with_db_errors
class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

# ---------------------------------------------------------------------------#
#  USERS
# ---------------------------------------------------------------------------#
    async def create_user(self, user_id: int, full_name: str,
                          profession_id: int, product_id: int) -> None:
        new_user = User(user_id=user_id, full_name=full_name, profession_id=profession_id, product_id=product_id)
        self.session.add(new_user)

    async def get_user_by_id(self, user_id: int) -> Optional[UserDTO]:
        result = await self.session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        return UserDTO.model_validate(user)

    async def user_auto_confirm(self, user_id: int) -> bool:
        result = await self.session.execute(
            select(User.auto_confirm).where(User.user_id == user_id)
        )
        return result.scalar_one()

    async def update_full_name(self, user_id: int, full_name: str) -> None:
        stmt = (update(User).where(User.user_id == user_id).values(full_name=full_name))
        await self.session.execute(stmt)

    async def update_auto_confirm(self, user_id: int, auto_confirm: bool) -> None:
        stmt = (update(User).where(User.user_id == user_id).values(auto_confirm=auto_confirm))
        await self.session.execute(stmt)

    async def update_is_active(self, user_id: int, is_active: bool) -> int:
        stmt = (update(User).where(User.user_id == user_id).values(is_active=is_active))
        res = await self.session.execute(stmt)
        return res.rowcount #type: ignore

    async def get_employees(self,
                            limit: int,
                            offset: int,
                            profession_id: int = None,
                            is_active: bool = True
                            ) -> List[UserDTO]:

        stmt = select(User)
        if profession_id is not None:
            stmt = stmt.where(User.profession_id == profession_id, User.is_lead == False)

        stmt = stmt.where(User.is_active == is_active)

        stmt = stmt.limit(limit).offset(offset).order_by(User.full_name)

        res = await self.session.execute(stmt)
        users = res.scalars().all()
        return [UserDTO.model_validate(user) for user in users]



# ---------------------------------------------------------------------------#
#  BOOKINGS
# ---------------------------------------------------------------------------#
    async def bookings_by_range(
            self,
            start: date, end: date,
            status: Union[str, List[str]], sub_status: Optional[Union[str, List[str]]] = None,
    ) -> List[DateBookingsDTO]:

        status_list = [status] if isinstance(status, str) else status

        stmt = (
            select(
                Booking.cal_date, Booking.user_id, User.full_name,
                Booking.status, Booking.sub_status, Booking.created_at, Booking.updated_at
            )
            .join(User, Booking.user_id == User.user_id)
            .where(Booking.cal_date.between(start, end), Booking.status.in_(status_list))
        )

        if sub_status is not None:
            sub_status_list = [sub_status] if isinstance(sub_status, str) else sub_status
            stmt = stmt.where(Booking.sub_status.in_(sub_status_list))

        stmt = stmt.order_by(Booking.cal_date, Booking.created_at)


        rows = await self.session.execute(stmt)
        data = rows.all()

        grouped: Dict[date, List[UserBookingDTO]] = defaultdict(list)
        for cal_date, user_id, full_name, status, sub_status, created_at, updated_at in data:
            grouped[cal_date].append(
                UserBookingDTO(
                    user_id=user_id, full_name=full_name,
                    status=status, sub_status=sub_status,
                    created_at=created_at, updated_at=updated_at
                )
            )
        return [DateBookingsDTO(cal_date=cd, users=grouped[cd]) for cd in sorted(grouped)]

    async def own_active_bookings(
            self,
            user_id: int,
            cal_date: Union[date, Tuple[date, date], List[date]],
    ) -> List[OwnBookingDTO]:

        stmt = (
            select(Booking.booking_id, Booking.cal_date, Booking.user_id, Booking.status,Booking.sub_status)
        )

        if isinstance(cal_date, tuple):
            if len(cal_date) == 2 and all(isinstance(d, date) for d in cal_date):
                start, end = cal_date
                stmt = stmt.where(Booking.cal_date.between(start, end))
            else:
                raise DBError("Кортеж должен содержать ровно 2 объекта date")
        elif isinstance(cal_date, date):
            stmt = stmt.where(Booking.cal_date >= cal_date)
        elif isinstance(cal_date, list):
            stmt = stmt.where(Booking.cal_date.in_(cal_date))
        else:
            raise DBError("Не корректный ввод дат %s", cal_date)

        stmt = stmt.where(
            Booking.user_id == user_id,
            Booking.status.in_([BookingStatus.BOOKED, BookingStatus.WAITLISTED])
        ).order_by(Booking.cal_date)

        result = await self.session.execute(stmt)
        bookings = result.all()
        return [OwnBookingDTO.model_validate(booking) for booking in bookings]

    async def position_in_waitlist(self, user_id: int, date_list: list) -> List[WaitlistPositionDTO]:

        sub_q = (
            select(
                Booking.cal_date,
                Booking.user_id,
                func.row_number().over(
                    partition_by=Booking.cal_date,
                    order_by=[Booking.updated_at, Booking.booking_id]
                ).label('position')
            )
            .where(
                Booking.cal_date.in_(date_list),
                Booking.status == BookingStatus.WAITLISTED
            )
            .subquery()
        )

        stmt = (
            select(
                sub_q.c.cal_date,
                sub_q.c.position
            )
            .where(sub_q.c.user_id == user_id) #type: ignore
            .order_by(sub_q.c.cal_date)
        )

        result = await self.session.execute(stmt)
        rows = result.mappings().all()
        return [
            WaitlistPositionDTO(
                cal_date=row["cal_date"],
                position=row["position"]
            )
            for row in rows
        ]

    async def confirm_booking(self, user_id: int, cal_date: date) -> Optional[int]:
        stmt = (
            update(Booking).where(
                Booking.user_id == user_id,
                Booking.cal_date == cal_date,
                Booking.sub_status == BookingStatus.RESERVED
            ).values(sub_status=BookingStatus.CONFIRMED, updated_at=func.now())
        ).returning(Booking.booking_id)
        res = await self.session.execute(stmt)
        row = res.first()
        return int(row[0]) if row else None


    async def get_user_booking_for_date(self, user_id: int, cal_date: date) -> Optional[OwnBookingDTO]:
        stmt = (
            select(Booking.booking_id, Booking.cal_date, Booking.user_id, Booking.status,Booking.sub_status)
            .where(
                Booking.cal_date == cal_date,
                Booking.user_id == user_id,
                Booking.status == BookingStatus.BOOKED
            )
            .limit(1)
        )
        res = await self.session.execute(stmt)
        booking = res.first()
        if booking is None:
            return None
        return OwnBookingDTO.model_validate(booking)

    async def get_week_visits(self, start: date, end: date) -> List[WeekVisitsDTO]:

        # stmt = (
        #     select(Booking.cal_date, func.count(Booking.booking_id).label("visits"))
        #     .where(Booking.cal_date.between(start, end), Booking.status == BookingStatus.BOOKED)
        #     .group_by(Booking.cal_date)
        # )

        stmt = (
            select(CalendarDate.cal_date, CalendarDate.visit_count.label("visits"))
            .where(CalendarDate.cal_date >= start, CalendarDate.cal_date <= end)
        )

        res = await self.session.execute(stmt)
        rows = res.mappings().all()
        return [
            WeekVisitsDTO(
                cal_date=row["cal_date"],
                visits=row["visits"]
            )
            for row in rows
        ]

    async def get_users_max_bookings(self, start: date, end: date) -> List[UserBookingWeekResultDTO]:

        counts = (
            select(
                Booking.user_id,
                User.full_name,
                func.count(Booking.booking_id).label("booking_count"),
            )
            .join(User, User.user_id == Booking.user_id)
            .where(
                Booking.cal_date.between(start, end),
                Booking.status == BookingStatus.BOOKED,
            )
            .group_by(Booking.user_id, User.full_name)
            .cte("counts")
        )

        max_count_subq = select(func.max(counts.c.booking_count)).scalar_subquery()

        stmt = (
            select(
                counts.c.user_id,
                counts.c.full_name,
                counts.c.booking_count
            )
            .where(counts.c.booking_count == max_count_subq) #type: ignore
        )

        res = await self.session.execute(stmt)
        rows = res.mappings().all()

        return [UserBookingWeekResultDTO.model_validate(row) for row in rows]

    # -------------------- ОБЩЕЕ (запись истории бронирования) --------------------
    async def insert_event(
            self, booking_id: int, status: str, sub_status: str, user_id: int
    ) -> None:

        event = BookingEvent(booking_id=booking_id,
                           status=status,
                           sub_status=sub_status,
                           updated_by=user_id)
        self.session.add(event)

    # -------------------- ОБЩЕЕ (занять слот: бронь / лист ожидания) --------------------
    async def take_capacity_slot(
            self, user_id: int, cal_date: date, capacity: int, waitlist: bool
    ) -> bool:
        conditions = [
            CalendarDate.cal_date == cal_date,
            CalendarDate.visit_count < capacity,
        ]

        if waitlist:
            not_exists_booked = ~select(Booking.booking_id).where(
                Booking.user_id == user_id,
                Booking.cal_date == cal_date,
                Booking.status == BookingStatus.BOOKED,
            ).exists()
            conditions.append(not_exists_booked)

        stmt = (
            update(CalendarDate)
            .where(and_(*conditions))
            .values(visit_count=CalendarDate.visit_count + 1, updated_at=func.now())
        )

        res = await self.session.execute(stmt)
        return (res.rowcount or 0) == 1


    # -------------------- ЗАБРОНИРОВАТЬ МЕСТО --------------------
    async def upsert_booked(
            self, user_id: int, cal_date: date, status: str, sub_status: str
    ) -> Optional[int]:
        stmt = (
            pg_insert(Booking)
            .values(user_id=user_id, cal_date=cal_date, status=status,sub_status=sub_status)
            .on_conflict_do_update(
                index_elements=[Booking.user_id, Booking.cal_date],
                set_=dict(status=status, sub_status=sub_status, updated_at=func.now()),
                where=Booking.status != status
            )
            .returning(Booking.booking_id)
        )
        res = await self.session.execute(stmt)
        row = res.first()
        return int(row[0]) if row else None


    # -------------------- ОТМЕНА БРОНИРОВАНИЯ --------------------
    async def cancel_booking(
            self,
            cancel_user_id: int,
            cal_date: date,
            cancel_sub_status: str | None
    ) -> CancelBookingFifoDTO:

        if cancel_sub_status is None:
            cancel_sub_status = BookingStatus.CANCELED_CHANGED_MIND

        # отмена
        cancel_stmt = (
            update(Booking)
            .where(
                Booking.user_id == cancel_user_id,
                Booking.cal_date == cal_date,
                Booking.status == BookingStatus.BOOKED
            )
            .values(status=BookingStatus.CANCELED, sub_status=cancel_sub_status, updated_at=func.now())
            .returning(Booking.booking_id)
        )
        cancel_res = await self.session.execute(cancel_stmt)
        cancel_row = cancel_res.first()
        if not cancel_row:
            return CancelBookingFifoDTO(canceled_user_id=None, promoted_user_id=None)

        canceled_id = int(cancel_row[0])
        await self.insert_event(
            canceled_id, BookingStatus.CANCELED, cancel_sub_status, cancel_user_id
        )

        # поиск замены
        head_sub_q = (
            select(Booking.booking_id)
            .where(Booking.cal_date == cal_date, Booking.status == BookingStatus.WAITLISTED)
            .order_by(Booking.created_at, Booking.booking_id)
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )

        promote_stmt = (
            update(Booking)
            .where(Booking.booking_id == head_sub_q, Booking.status == BookingStatus.WAITLISTED)
            .values(status=BookingStatus.BOOKED, sub_status=BookingStatus.CONFIRMED, updated_at=func.now())
            .returning(Booking.booking_id, Booking.user_id)
        )
        res_promote = await self.session.execute(promote_stmt)
        promoted_row = res_promote.first()

        if promoted_row:
            promoted_id = int(promoted_row[0])
            promoted_user_id = int(promoted_row[1])
            await self.insert_event(
                promoted_id, BookingStatus.BOOKED, BookingStatus.CONFIRMED, promoted_user_id
            )
            return CancelBookingFifoDTO(canceled_user_id=cancel_user_id, promoted_user_id=promoted_user_id)

        dec_stmt = (
            update(CalendarDate)
            .where(CalendarDate.cal_date == cal_date, CalendarDate.visit_count > 0)
            .values(visit_count=CalendarDate.visit_count - 1, updated_at=func.now())
        )
        await self.session.execute(dec_stmt)
        return CancelBookingFifoDTO(canceled_user_id=cancel_user_id, promoted_user_id=None)


    # -------------------- ИЗМЕНИТЬ СТАТУС БРОНИРОВАНИЯ --------------------
    async def update_booking_status(
            self,
            cal_date: date,
            current_status: BookingStatus,
            current_sub_status: BookingStatus,
            status: BookingStatus,
            sub_status: BookingStatus
    ) -> int:

        upd_stmt = (
            update(Booking)
            .where(
                Booking.cal_date == cal_date,
                Booking.status == current_status,
                Booking.sub_status == current_sub_status
            )
            .values(status=status, sub_status=sub_status, updated_at=func.now())
            .returning(Booking.booking_id, Booking.user_id)
        )

        res = await self.session.execute(upd_stmt)
        rows = res.fetchall()
        if not rows:
            return 0

        events_payload = [
            {
                "booking_id": r.booking_id,
                "status": status,
                "sub_status": sub_status,
                "updated_by": r.user_id
            }
            for r in rows
        ]
        await self.session.execute(pg_insert(BookingEvent), events_payload)

        return len(events_payload)


    # -------------------- ВСТАТЬ В ОЧЕРЕДЬ --------------------
    async def upsert_waitlisted(self, user_id: int, cal_date: date) -> Optional[int]:
        stmt = (
            pg_insert(Booking)
            .values(
                user_id=user_id,
                cal_date=cal_date,
                status=BookingStatus.WAITLISTED,
                sub_status=BookingStatus.WAITLISTED_MANUAL
            )
            .on_conflict_do_update(
                index_elements=[Booking.user_id, Booking.cal_date],
                set_=dict(status=BookingStatus.WAITLISTED, sub_status=BookingStatus.WAITLISTED_MANUAL, updated_at=func.now()),
                where=Booking.status.notin_((BookingStatus.BOOKED, BookingStatus.WAITLISTED)),
            )
            .returning(Booking.booking_id)
        )
        res = await self.session.execute(stmt)
        row = res.first()
        return int(row[0]) if row else None

    # -------------------- ВЫЙТИ ИЗ ОЧЕРЕДИ --------------------
    async def leave_waitlist(self, user_id: int, cal_date: date) -> Optional[int]:
        stmt = (
            update(Booking)
            .where(
                Booking.user_id == user_id,
                Booking.cal_date == cal_date,
                Booking.status == BookingStatus.WAITLISTED,
            )
            .values(status=BookingStatus.CANCELED, sub_status=BookingStatus.CANCELED_CHANGED_MIND, updated_at=func.now())
            .returning(Booking.booking_id)
        )
        res = await self.session.execute(stmt)
        row = res.first()
        if not row:
            return None
        return int(row[0])


    # -------------------- ПРОВЕРКА АПДЕЙТОВ ПО БРОНИРОВАНИЯ --------------------
    async def has_booking_changes(self, month_offset: int = 0) -> bool:
        month_shift = func.make_interval(0, month_offset)
        month_shift_next = func.make_interval(0, month_offset + 1)

        subq = (
            select(1)
            .where(
                Booking.updated_at >= func.now() - text("interval '60 seconds'"),
                Booking.cal_date >= func.date_trunc(
                    "month", func.current_date() + month_shift
                ),
                Booking.cal_date < func.date_trunc(
                    "month", func.current_date() + month_shift_next
                ),
            )
        )

        stmt = select(subq.exists())
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # -------------------- ПОЛУЧЕНИЕ ДАННЫХ ДЛЯ GOOGLE-ТАБЛИЦЫ --------------------
    async def bookings_data_for_sheet(self, start: date, end: date) -> Sequence[RowMapping]:
        stmt = (
            select(
                User.user_id,
                User.full_name.label("name"),
                Product.name.label("team"),
                Profession.name.label("position"),
                Booking.cal_date
            )
            .join(Product, Product.id == User.product_id)
            .join(Profession, Profession.id == User.profession_id)
            .outerjoin(
                Booking,
                and_(
                    Booking.cal_date.between(start, end),
                    Booking.user_id == User.user_id,
                    Booking.status == BookingStatus.BOOKED,
                ),
            )
            .where(User.is_active.is_(True))
            .order_by(User.full_name, Booking.cal_date)
        )
        result = await self.session.execute(stmt)

        return result.mappings().all()


    # -------------------- ПРОВЕРКА АПДЕЙТОВ ПО БРОНИРОВАНИЯ ДЛЯ ДНЯ --------------------
    async def has_booking_changes_for_day(self, cal_date: date) -> bool:

        subq = (
            select(1)
            .where(
                Booking.cal_date == cal_date,
                Booking.updated_at.between(
                    func.now() - text("interval '60 seconds'"),
                    func.now()
                )
            )
        )

        stmt = select(subq.exists())
        result = await self.session.execute(stmt)
        return result.scalar_one()


# ---------------------------------------------------------------------------#
#  OFFICE CAPACITY
# ---------------------------------------------------------------------------#
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

    async def weekday_capacity(self, weekday: int) -> Optional[int]:
        stmt = (
            select(
                OfficeCapacityWeekday.capacity,
            ).where(
                OfficeCapacityWeekday.weekday == weekday,
            )
        )
        result = await self.session.execute(stmt)

        if result is None:
            return None
        return result.scalar()


    async def get_availability(self, start: date, end: date) -> List[AvailabilityDTO]:
        stmt = (
            select(
                CalendarDate.cal_date,
                CalendarDate.is_holiday,
                CalendarDate.is_weekend,
                not_(
                    or_(
                        CalendarDate.visit_count >= OfficeCapacityWeekday.capacity,
                        CalendarDate.is_holiday == True
                    )
                ).label('is_available')
            )
            .join(
                OfficeCapacityWeekday,
                extract('ISODOW', CalendarDate.cal_date) == OfficeCapacityWeekday.weekday
            )
            .where(CalendarDate.cal_date.between(start, end))
        )
        result = await self.session.execute(stmt)
        rows = result.mappings().all()
        return [
            AvailabilityDTO(
                cal_date=row["cal_date"],
                is_holiday=row["is_holiday"],
                is_available=row["is_available"],
                is_weekend=row["is_weekend"]
            )
            for row in rows
        ]

# ---------------------------------------------------------------------------#
#  CALENDAR DATES
# ---------------------------------------------------------------------------#
    async def get_calendar_dates_by_range(self, cal_date_start: date,
                                   cal_date_end: date) -> List[CalendarDatesDTO]:
        stmt = select(
            CalendarDate.cal_date,
            CalendarDate.is_holiday,
            CalendarDate.is_weekend,
            CalendarDate.is_workday
        ).where(
            CalendarDate.cal_date.between(cal_date_start, cal_date_end),
        ).order_by(CalendarDate.cal_date)

        result = await self.session.execute(stmt)
        return [CalendarDatesDTO(**m) for m in result.mappings()]

    async def get_workday(self, cal_date: date) -> bool:
        result = await self.session.execute(
            select(CalendarDate.is_workday).where(CalendarDate.cal_date == cal_date)
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------#
#  PROFESSIONS & PRODUCTS
# ---------------------------------------------------------------------------#
    async def get_dict_data(self, dict_type: str) -> List[DictDTO]:

        if dict_type == 'professions':
            result = await self.session.execute(
                select(Profession.id, Profession.name)
            )
        else:
            result = await self.session.execute(
                select(Product.id, Product.name)
            )
        return [DictDTO(**m) for m in result.mappings()]


# ---------------------------------------------------------------------------#
#  DIGEST SCHEDULE
# ---------------------------------------------------------------------------#
    async def upsert_chat_message_id(self, cal_date: date, message_id: int) -> None:
        stmt = (
            pg_insert(DigestSchedule)
            .values(cal_date=cal_date, message_id=message_id)
            .on_conflict_do_update(
                index_elements=[DigestSchedule.cal_date],
                set_=dict(message_id=message_id),
                where=(DigestSchedule.cal_date == cal_date)
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return None


    async def get_chat_message_id(self, cal_date: date) -> int | None:
        result = await self.session.execute(
            select(DigestSchedule.message_id).where(DigestSchedule.cal_date == cal_date)
        )
        return result.scalar_one_or_none()


    async def get_last_message(self) -> Optional[DigestScheduleDTO]:

        res = await self.session.execute(
            select(
                DigestSchedule.cal_date,
                DigestSchedule.message_id,
                DigestSchedule.created_at
            )
            .order_by(DigestSchedule.cal_date.desc())
            .limit(1)
        )
        message = res.first()

        if not message:
            return None

        return DigestScheduleDTO.model_validate(message)


