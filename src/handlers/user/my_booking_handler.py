import logging
from datetime import date

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.handlers.user.booking_handler import promote_user_after_cancel
from src.services.exceptions import BookingError
from src.ui.keyboard.actions import MyBookingCB, MyBookingStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.my_booking_inline_kb import render_my_booking_kb, render_book_day_kb
from src.ui.messages.my_booking_mess import render_my_booking_mess, render_book_day_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError

router = Router()

logger = logging.getLogger(__name__)

@router.callback_query(MyBookingCB.filter(F.step.in_({
    MyBookingStep.INIT_MY_BOOKING,
    MyBookingStep.BOOKINGS,
    MyBookingStep.WAITLIST,
    MyBookingStep.GET_BACK_MY_BOOK_MENU,
    MyBookingStep.GET_BACK_MY_BOOKING_DAYS,
    MyBookingStep.GET_BACK_MY_WAITLIST_DAYS,
    MyBookingStep.CANCEL_BOOKING,
    MyBookingStep.LEAVE_QUEUE,
    MyBookingStep.CONFIRM_BOOKING
})))
async def handle_my_booking_page(call: CallbackQuery, callback_data: MyBookingCB, uc: FromDishka[BookingUseCase]):
    step = callback_data.step
    user_id = call.from_user.id

    try:
        if step == MyBookingStep.CANCEL_BOOKING:
            cancel_dt = _parse_iso_date(callback_data.extra)
            await promote_user_after_cancel(call, uc, cancel_dt)
        elif step == MyBookingStep.LEAVE_QUEUE:
            cancel_dt = _parse_iso_date(callback_data.extra)
            await uc.cancel_waitlist_place(user_id, cancel_dt)
        elif step == MyBookingStep.CONFIRM_BOOKING:
            confirm_dt = _parse_iso_date(callback_data.extra)
            await uc.confirm_booking(user_id, confirm_dt)

        bookings, waitlist = await uc.own_active_bookings(user_id)

        has_bookings_block = bool(bookings)
        has_waitlist_block = bool(waitlist)

        if step == MyBookingStep.BOOKINGS or step == MyBookingStep.GET_BACK_MY_BOOKING_DAYS:
            data = (bookings, [])
            if has_waitlist_block:
                back_btn = MyBookingStep.GET_BACK_MY_BOOK_MENU
                back_btn_text = "« Вернуться назад"
            else:
                back_btn = MyBookingStep.GET_BACK_MENU
                back_btn_text = "« Выйти"
        elif step == MyBookingStep.WAITLIST or step == MyBookingStep.GET_BACK_MY_WAITLIST_DAYS:
            data = ([], waitlist)
            if has_bookings_block:
                back_btn = MyBookingStep.GET_BACK_MY_BOOK_MENU
                back_btn_text = "« Вернуться назад"
            else:
                back_btn = MyBookingStep.GET_BACK_MENU
                back_btn_text = "« Выйти"
        else:
            data = (bookings, waitlist)
            back_btn = MyBookingStep.GET_BACK_MENU
            back_btn_text = "« Выйти"

        await call.message.edit_text(
            text=render_my_booking_mess(data),
            reply_markup=render_my_booking_kb(data, back_btn, back_btn_text),
        )
    except (ValueError, TypeError):
        await call.answer("⚠️ Ошибка: некорректный формат даты.", show_alert=True)
    except BookingError as e:
        try:
            await call.message.edit_text(text=bot_menu_mess(), reply_markup=get_menu_kb())
        except TelegramBadRequest:
            await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(
            text="⚠️ Ошибка: Не удалось выполнить операцию.\nНемного подождите и попробуйте ещё раз.",
            show_alert=True
        )

@router.callback_query(MyBookingCB.filter(F.step.in_({MyBookingStep.GET_BACK_MENU})))
async def handle_get_back_menu(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())


@router.callback_query(MyBookingCB.filter(F.step.in_(
    {
        MyBookingStep.BOOK_DAY,
        MyBookingStep.WAITLIST_DAY,
    }
)))
async def handle_day_info(call: CallbackQuery, callback_data: MyBookingCB):
    data = callback_data.extra

    if callback_data.step == MyBookingStep.BOOK_DAY:
        date_str, sub_status = data.split("|", 1)
        await call.message.edit_text(
            text=render_book_day_mess(date_str, sub_status),
            reply_markup=render_book_day_kb(date_str, sub_status)
        )
    else:
        await call.message.edit_text(
            text=render_book_day_mess(data, "в листе ожидания"),
            reply_markup=render_book_day_kb(data, "")
        )


# ---------------------------------------------- helpers ----------------------------------------------
def _parse_iso_date(extra: str | int | None) -> date:
    if extra is None:
        raise ValueError("empty extra")
    return date.fromisoformat(str(extra))