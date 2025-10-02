from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    SmallInteger,
    Integer,
    Boolean,
    Date,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import expression


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------#
#  User & User Settings & User Booking Weekdays
# ---------------------------------------------------------------------------#
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.true())
    auto_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    auto_join_queue: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    is_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    profession_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("professions.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("products.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    booking_weekdays: Mapped[List["UserBookingWeekday"]] = relationship(back_populates="user")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="user")
    updated_booking_events: Mapped[List["BookingEvent"]] = relationship(back_populates="updated_by_user")
    professions: Mapped["Profession"] = relationship(back_populates="user")
    products: Mapped["Product"] = relationship(back_populates="user")


class UserBookingWeekday(Base):
    __tablename__ = "user_book_weekdays"
    __table_args__ = (UniqueConstraint("user_id", "weekday"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    user: Mapped["User"] = relationship(back_populates="booking_weekdays")


class Profession(Base):
    __tablename__ = "professions"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    user: Mapped["User"] = relationship(back_populates="professions")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    user: Mapped["User"] = relationship(back_populates="products")


# ---------------------------------------------------------------------------#
#  Calendar Dates & Office Capacity Weekdays
# ---------------------------------------------------------------------------#
class CalendarDate(Base):
    __tablename__ = "calendar_dates"

    cal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_workday: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    bookings: Mapped[List["Booking"]] = relationship(back_populates="calendar_date")


class OfficeCapacityWeekday(Base):
    __tablename__ = "office_capacity_weekdays"

    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    short_name: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


# ---------------------------------------------------------------------------#
#  Bookings & Booking Events & Booking Status Dictionary
# ---------------------------------------------------------------------------#
class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("user_id", "cal_date"),)

    booking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    cal_date: Mapped[date] = mapped_column(Date, ForeignKey("calendar_dates.cal_date"), nullable=False)
    status: Mapped[str] = mapped_column(Text, ForeignKey("booking_status_dict.slug"), nullable=False)
    sub_status: Mapped[str] = mapped_column(Text, ForeignKey("booking_status_dict.slug"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    user: Mapped["User"] = relationship(back_populates="bookings")
    calendar_date: Mapped["CalendarDate"] = relationship(back_populates="bookings")

    status_dict: Mapped["BookingStatusDict"] = relationship(
        foreign_keys=[status], back_populates="bookings_as_status"
    )
    sub_status_dict: Mapped["BookingStatusDict"] = relationship(
        foreign_keys=[sub_status], back_populates="bookings_as_sub_status"
    )

    events: Mapped[List["BookingEvent"]] = relationship(back_populates="booking")


class BookingStatusDict(Base):
    __tablename__ = "booking_status_dict"

    slug: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    parent_slug: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("booking_status_dict.slug"), nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # relationships
    parent: Mapped[Optional["BookingStatusDict"]] = relationship(
        remote_side=[slug], back_populates="children"
    )
    children: Mapped[List["BookingStatusDict"]] = relationship(back_populates="parent")

    bookings_as_status: Mapped[List["Booking"]] = relationship(
        foreign_keys="Booking.status", back_populates="status_dict"
    )
    bookings_as_sub_status: Mapped[List["Booking"]] = relationship(
        foreign_keys="Booking.sub_status", back_populates="sub_status_dict"
    )

    events_as_status: Mapped[List["BookingEvent"]] = relationship(
        foreign_keys="BookingEvent.status", back_populates="status_dict"
    )
    events_as_sub_status: Mapped[List["BookingEvent"]] = relationship(
        foreign_keys="BookingEvent.sub_status", back_populates="sub_status_dict"
    )


class BookingEvent(Base):
    __tablename__ = "booking_events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.booking_id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, ForeignKey("booking_status_dict.slug"), nullable=False)
    sub_status: Mapped[str] = mapped_column(Text, ForeignKey("booking_status_dict.slug"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)

    # relationships
    booking: Mapped["Booking"] = relationship(back_populates="events")
    status_dict: Mapped["BookingStatusDict"] = relationship(
        foreign_keys=[status], back_populates="events_as_status"
    )
    sub_status_dict: Mapped["BookingStatusDict"] = relationship(
        foreign_keys=[sub_status], back_populates="events_as_sub_status"
    )
    updated_by_user: Mapped["User"] = relationship(back_populates="updated_booking_events")


# ---------------------------------------------------------------------------#
#  Key–value config
# ---------------------------------------------------------------------------#
class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))