import logging
from datetime import date

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.services.exceptions import BookingError
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.ui.keyboard.bookings_inline_kb import render_booking_week_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.auto_book_mess import build_promote_message
from src.ui.messages.help_booking_mess import render_help_booking_mess
from src.ui.messages.start_mess import bot_menu_mess
from src.ui.messages.week_booking_mess import render_booking_week_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.get_week_range import week_range

router = Router()

logger = logging.getLogger(__name__)

# стартовая страница / пагинация бронирования
@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.INIT_BOOKING, BookingStep.PAGE})))
async def handle_booking_page(call: CallbackQuery,
                              callback_data: BookingCB,
                              uc: FromDishka[BookingUseCase],
                              state: FSMContext):

    week_offset = int(callback_data.extra) if callback_data.extra else 0
    await _render_booking_page(call, week_offset, uc, state)


# действие "забронировать"
@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.BOOK})))
async def handle_book_action(call: CallbackQuery,
                             callback_data: BookingCB,
                             uc: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.book_place(user_id=call.from_user.id, cal_date=cal_date)
    except BookingError as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text ="⚠️ Ошибка: Не удалось забронировать место.\n"
                                "Немного подождите и попробуйте еще раз.",
                          show_alert = True
                          )

    await _render_booking_page(call, week_offset, uc, state)

# действие "отменить бронь"
@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.UNBOOK})))
async def handle_book_cancel_action(call: CallbackQuery,
                                    callback_data: BookingCB,
                                    uc: FromDishka[BookingUseCase],
                                    state: FSMContext
                                    ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        promote_user_id = await uc.cancel_book_place(call.from_user.id, cal_date)
        if promote_user_id:
            try:
                await call.bot.send_message(chat_id=promote_user_id, text=build_promote_message(cal_date=cal_date))
            except TelegramBadRequest as e_tg:
                logger.exception(f"Не удалось отправить сообщение {promote_user_id} | {str(e_tg)}")
    except BookingError as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось отменить бронь.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, uc, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.JOINQ})))
async def handle_queue_join(call: CallbackQuery,
                            callback_data: BookingCB,
                            uc: FromDishka[BookingUseCase],
                            state: FSMContext
                            ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.waitlist_place(call.from_user.id, cal_date)
    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось встать в очередь.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, uc, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.LEAVEQ})))
async def handle_queue_leave(call: CallbackQuery,
                             callback_data: BookingCB,
                             uc: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.cancel_waitlist_place(call.from_user.id, cal_date)
    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выйти из очереди.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, uc, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.INFO})))
async def handle_booking_help(call: CallbackQuery, uc: FromDishka[BookingUseCase], state: FSMContext):

    try:
        state_data = await state.get_data()
        week_offset = int(state_data.get('week_offset', 0))
        start, end, _ = week_range(week_offset)
        has_holiday, has_available = await uc.week_state(start, end)

        await call.answer(text=render_help_booking_mess(has_holiday, has_available), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось получить инструкцию.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.GET_BACK_MENU})))
async def handle_back_menu_button(call: CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())


# ---------------------------------------------- helpers ----------------------------------------------
async def _render_booking_page(call: CallbackQuery, week_offset: int, uc: BookingUseCase, state: FSMContext) -> None:
    try:
        monday, friday, _ = week_range(week_offset)
        active, capacity, calendar = await uc.booking_page_data(monday=monday, friday=friday)
        await call.message.edit_text(
            text=render_booking_week_mess(active, capacity, calendar, call.from_user.id),
            reply_markup=render_booking_week_kb(active, capacity, calendar, call.from_user.id, week_offset)
        )
    except DBError:
        await call.answer(text="ℹ️ Данные сохранены, но расписание получить не удалось.\n"
                               "Возвращаемся в меню.",
                          show_alert=True
                          )
        if await state.get_state():
            await state.clear()
        try:
            await call.message.edit_text(
                text=bot_menu_mess(),
                reply_markup=get_menu_kb(),
            )
        except TelegramBadRequest:
            return
