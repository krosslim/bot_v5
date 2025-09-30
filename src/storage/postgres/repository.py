from collections import defaultdict
from datetime import date
from typing import Optional, List, Dict, Union, Sequence

from sqlalchemy import select, update, and_, func, not_, or_, extract, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.dto.booking_dto import (DateBookingsDTO, UserBookingDTO,
                                 CancelBookingFifoDTO, BookingStatus, OwnBookingDTO, WaitlistPositionDTO)
from src.dto.calendar_dates_dto import CalendarDatesDTO
from src.dto.office_capacity_dto import OfficeCapacityDTO, AvailabilityDTO
from src.dto.user_dto import UserDTO, DictDTO
from src.storage.postgres.models import (User, Booking, OfficeCapacityWeekday,
                                         CalendarDate, BookingEvent, Profession, Product,
                                         SystemConfig)
from src.utils.db_exc_wrapper import with_db_errors


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

# ---------------------------------------------------------------------------#
#  BOOKINGS
# ---------------------------------------------------------------------------#
    async def bookings_by_range(
            self, start: date, end: date, status: Union[str, List[str]]
    ) -> List[DateBookingsDTO]:

        status_list = [status] if isinstance(status, str) else status

        stmt = (
            select(
                Booking.cal_date, Booking.user_id, User.full_name,
                Booking.status, Booking.sub_status, Booking.created_at
            )
            .join(User, Booking.user_id == User.user_id)
            .where(Booking.cal_date.between(start, end), Booking.status.in_(status_list))
            .order_by(Booking.cal_date, Booking.created_at)
        )
        rows = await self.session.execute(stmt)
        data = rows.all()

        grouped: Dict[date, List[UserBookingDTO]] = defaultdict(list)
        for cal_date, user_id, full_name, status, sub_status, created_at in data:
            grouped[cal_date].append(
                UserBookingDTO(
                    user_id=user_id, full_name=full_name, status=status, sub_status=sub_status, created_at=created_at
                )
            )
        return [DateBookingsDTO(cal_date=cd, users=grouped[cd]) for cd in sorted(grouped)]

    async def own_active_bookings(self, user_id: int, start: date) -> List[OwnBookingDTO]:

        stmt = (
            select(Booking.booking_id, Booking.cal_date, Booking.user_id, Booking.status,Booking.sub_status)
            .where(
                Booking.cal_date >= start,
                Booking.user_id == user_id,
                Booking.status.in_([BookingStatus.BOOKED, BookingStatus.WAITLISTED])
            )
            .order_by(Booking.cal_date)
        )
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
                    order_by=[Booking.created_at, Booking.booking_id]
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
            .where(sub_q.c.user_id == user_id)
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
    async def cancel_booking(self, cancel_user_id: int, cal_date: date) -> CancelBookingFifoDTO:
        # отмена
        cancel_stmt = (
            update(Booking)
            .where(
                Booking.user_id == cancel_user_id,
                Booking.cal_date == cal_date,
                Booking.status == BookingStatus.BOOKED
            )
            .values(status=BookingStatus.CANCELED, sub_status=BookingStatus.CANCELED_CHANGED_MIND, updated_at=func.now())
            .returning(Booking.booking_id)
        )
        cancel_res = await self.session.execute(cancel_stmt)
        cancel_row = cancel_res.first()
        if not cancel_row:
            return CancelBookingFifoDTO(canceled_user_id=None, promoted_user_id=None)

        canceled_id = int(cancel_row[0])
        await self.insert_event(
            canceled_id, BookingStatus.CANCELED, BookingStatus.CANCELED_CHANGED_MIND, cancel_user_id
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
                is_available=row["is_available"]
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
            CalendarDate.is_weekend
        ).where(
            CalendarDate.cal_date.between(cal_date_start, cal_date_end),
        ).order_by(CalendarDate.cal_date)

        result = await self.session.execute(stmt)
        return [CalendarDatesDTO(**m) for m in result.mappings()]


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
#  SYSTEM CONFIG
# ---------------------------------------------------------------------------#
    async def upsert_chat_message_id(self, message_id: str) -> None:
        stmt = (
            pg_insert(SystemConfig)
            .values(key="chat_digest_message_id", value=message_id)
            .on_conflict_do_update(
                index_elements=[SystemConfig.key],
                set_=dict(value=message_id),
                where=(SystemConfig.key == "chat_digest_message_id")
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return None

    async def get_chat_message_id(self) -> str | None:
        result = await self.session.execute(
            select(SystemConfig.value).where(SystemConfig.key == 'chat_digest_message_id')
        )
        return result.scalar_one_or_none()