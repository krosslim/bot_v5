from typing import Union
from strenum import StrEnum
from enum import auto
from aiogram.filters.callback_data import CallbackData


class MenuStep(StrEnum):
    BOOKING = auto()
    MY_BOOKING = auto()
    SETTINGS = auto()


class BookingStep(StrEnum):
    INIT_BOOKING = auto()
    PAGE = auto()
    WEEK_INFO = auto()
    BOOK = auto()
    UNBOOK = auto()
    LEAVEQ = auto()
    JOINQ = auto()
    INFO = auto()
    GET_BACK_MENU = auto()


class MyBookingStep(StrEnum):
    INIT_MY_BOOKING = auto()
    GET_BACK_MENU = auto()
    GET_INFO = auto()

    BOOKINGS = auto()
    WAITLIST = auto()

    BOOK_DAY = auto()
    CONFIRM_BOOKING = auto()
    CANCEL_BOOKING = auto()
    GET_BACK_MY_BOOKING_DAYS = auto()

    WAITLIST_DAY = auto()
    LEAVE_QUEUE = auto()
    GET_BACK_MY_WAITLIST_DAYS = auto()

    GET_BACK_MY_BOOK_MENU = auto()


class SettingsStep(StrEnum):
    INIT_SETTINGS = auto()
    AUTO_CONFIRM = auto()
    AUTO_CONFIRM_ON = auto()
    AUTO_CONFIRM_OFF = auto()
    GET_BACK_MENU = auto()
    MY_EMPLOYEES = auto()
    ALL_EMPLOYEES = auto()
    EMPLOYEES_PAGINATION = auto()
    EMPLOYEE = auto()


class ChatBookingStep(StrEnum):
    CONFIRM_BOOKING = auto()
    ADD_BOOKING = auto()
    CONFIRM_BOOKING_IN_REMINDER = auto()
    CANCEL_BOOKING_IN_REMINDER = auto()
    ADD_BOOKING_INLINE_CANCEL = auto()


class SettingsCB(CallbackData, prefix = "s"):
    step: SettingsStep
    extra: Union[str, int] | None = None
    idk: str | None = None


class MyBookingCB(CallbackData, prefix="m"):
    step: MyBookingStep
    extra: Union[str, int] | None = None
    idk: str | None = None


class BookingCB(CallbackData, prefix="b"):
    step: BookingStep
    extra: Union[str, int] | None = None
    idk: str


class ChatBookingCB(CallbackData, prefix="chat"):
    step: ChatBookingStep
    extra: Union[str, int] | None = None
    idk: str | None = None




