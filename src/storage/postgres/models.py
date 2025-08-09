from __future__ import annotations

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


# ---------------------------------------------------------------------------#
#  Base class
# ---------------------------------------------------------------------------#
class Base(DeclarativeBase):  # type: ignore[override]
    pass


# ---------------------------------------------------------------------------#
#  Lookup table for statuses / sources
# ---------------------------------------------------------------------------#
class BookingStateDict(Base):
    __tablename__ = "booking_state_dict"

    state_id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # "status" | "source"
    description: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------#
#  Core master-data tables
# ---------------------------------------------------------------------------#
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # relationships
    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all,delete-orphan"
    )
    recurring_weekdays: Mapped[List["UserRecurringWeekday"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )
    vacations: Mapped[List["UserVacation"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )
    bookings: Mapped[List["Booking"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )
    waitlist_entries: Mapped[List["WaitList"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )
    prompt_statuses: Mapped[List["UserPromptStatus"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), primary_key=True
    )
    auto_confirm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    default_remind: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.true()
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="settings", uselist=False)


class UserRecurringWeekday(Base):
    """
    Composite primary key  (user_id, weekday)
    weekday: 1 (Monday) … 7 (Sunday)
    """

    __tablename__ = "user_recurring_weekdays"
    __table_args__ = (UniqueConstraint("user_id", "weekday"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), primary_key=True
    )
    weekday: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="recurring_weekdays")


class CalendarDate(Base):
    __tablename__ = "calendar_dates"

    cal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # relationships
    bookings: Mapped[List["Booking"]] = relationship(back_populates="calendar_date")
    waitlist_entries: Mapped[List["WaitList"]] = relationship(
        back_populates="calendar_date"
    )


class OfficeCapacityWeekday(Base):
    """
    Capacity per weekday (1-7).  One row per weekday.
    """

    __tablename__ = "office_capacity_weekdays"

    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    short_name: Mapped[str] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserVacation(Base):
    __tablename__ = "user_vacations"

    vacation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="vacations")


# ---------------------------------------------------------------------------#
#  Bookings & Wait-list
# ---------------------------------------------------------------------------#
class Booking(Base):
    __tablename__ = "bookings"

    booking_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    cal_date: Mapped[date] = mapped_column(
        Date, ForeignKey("calendar_dates.cal_date"), nullable=False
    )
    status_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("booking_state_dict.state_id"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("booking_state_dict.state_id"), nullable=False
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="bookings")
    calendar_date: Mapped[CalendarDate] = relationship(back_populates="bookings")
    status: Mapped[BookingStateDict] = relationship(
        foreign_keys=[status_id], uselist=False
    )
    source: Mapped[BookingStateDict] = relationship(
        foreign_keys=[source_id], uselist=False
    )
    promoted_waitlist_entry: Mapped[Optional["WaitList"]] = relationship(
        back_populates="promoted_booking", uselist=False
    )


class WaitList(Base):
    __tablename__ = "waitlist"

    waitlist_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    cal_date: Mapped[date] = mapped_column(
        Date, ForeignKey("calendar_dates.cal_date"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    promoted_booking_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("bookings.booking_id")
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="waitlist_entries")
    calendar_date: Mapped[CalendarDate] = relationship(back_populates="waitlist_entries")
    promoted_booking: Mapped[Optional[Booking]] = relationship(
        back_populates="promoted_waitlist_entry", uselist=False
    )


# ---------------------------------------------------------------------------#
#  Prompt / notification logs
# ---------------------------------------------------------------------------#
class FridayPromptsLog(Base):
    __tablename__ = "friday_prompts_log"

    prompt_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    sent_on: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    recipients_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    prompt_statuses: Mapped[List["UserPromptStatus"]] = relationship(
        back_populates="prompt", cascade="all,delete-orphan"
    )


class UserPromptStatus(Base):
    __tablename__ = "user_prompt_status"
    __table_args__ = (UniqueConstraint("prompt_id", "user_id"),)

    prompt_status_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    prompt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("friday_prompts_log.prompt_id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    auto_pattern_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    skipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )

    prompt: Mapped[FridayPromptsLog] = relationship(back_populates="prompt_statuses")
    user: Mapped[User] = relationship(back_populates="prompt_statuses")


# ---------------------------------------------------------------------------#
#  Key–value config
# ---------------------------------------------------------------------------#
class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )