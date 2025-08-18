from typing import Union
from strenum import StrEnum
from enum import auto
from aiogram.filters.callback_data import CallbackData


class MenuStep(StrEnum):
    BOOKING = auto()
    MY_BOOKING = auto()
    SETTINGS = auto()
    INFO = auto()


class BookingStep(StrEnum):
    INIT_BOOKING = auto()
    PAGE = auto()
    BOOK = auto()
    UNBOOK = auto()
    LEAVEQ = auto()
    JOINQ = auto()
    INFO = auto()
    GET_BACK_MENU = auto()


class SettingsStep(StrEnum):
    INIT_SETTINGS = auto()
    AUTO_CONFIRM = auto()
    AUTO_CONFIRM_ON = auto()
    AUTO_CONFIRM_OFF = auto()
    GET_BACK_MENU = auto()


class SettingsCB(CallbackData, prefix = "s"):
    step: SettingsStep
    extra: Union[str, int] | None = None
    idk: str | None = None


class MenuCB(CallbackData, prefix="m"):
    step: MenuStep
    extra: Union[str, int] | None = None
    idk: str | None = None


class BookingCB(CallbackData, prefix="b"):
    step: BookingStep
    extra: Union[str, int] | None = None
    idk: str





