import logging
from datetime import date

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.services.booking_service import BookingService
from src.services.exceptions import BookingServiceExceptions
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.ui.keyboard.bookings_inline_kb import get_booking_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.text.auto_book_mess import build_promote_message
from src.ui.text.start_mess import bot_menu_mess
from src.ui.text.week_booking_mess import render_week
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.get_week_range import week_range

router = Router()

logger = logging.getLogger(__name__)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.INIT_BOOKING})))
async def handle_booking_page(call: CallbackQuery,
                              use_case: FromDishka[BookingUseCase],
                              state: FSMContext,
                              ):

    _, _, week_offset = week_range()
    await state.update_data(week_offset=week_offset)
    await _render_booking_page(call, week_offset, True, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.PAGE})))
async def handle_booking_pagination(call: CallbackQuery,
                                    callback_data: BookingCB,
                                    use_case: FromDishka[BookingUseCase],
                                    state: FSMContext
                                    ):

    _, _, week_offset = week_range(int(callback_data.extra))
    await state.update_data(week_offset=week_offset)
    await _render_booking_page(call, week_offset, False, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.BOOK})))
async def handle_book_action(call: CallbackQuery,
                             callback_data: BookingCB,
                             svc_bs: FromDishka[BookingService],
                             use_case: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):

    week_offset = await _get_week_offset(state)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await svc_bs.create_booking(user_id = call.from_user.id, cal_date = cal_date)
    except BookingServiceExceptions as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text =
                          "⚠️ Ошибка: Не удалось забронировать место.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert = True
                          )

    await _render_booking_page(call, week_offset, False, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.UNBOOK})))
async def handle_book_cancel_action(call: CallbackQuery,
                                    callback_data: BookingCB,
                                    svc_bs: FromDishka[BookingService],
                                    use_case: FromDishka[BookingUseCase],
                                    state: FSMContext
                                    ):

    week_offset = await _get_week_offset(state)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        cancel = await svc_bs.cancel_booking(user_id = call.from_user.id, cal_date = cal_date)
        if cancel.waiter_user_id:
            try:
                await call.bot.send_message(chat_id=cancel.waiter_user_id,
                                        text=build_promote_message(cal_date=cancel.cal_date))
            except TelegramBadRequest as e_tg:
                logger.exception(f"handle_book_cancel_action {cancel.waiter_user_id} | {str(e_tg)}")
    except BookingServiceExceptions as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось отменить бронь.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, False, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.JOINQ})))
async def handle_queue_join(call: CallbackQuery,
                            callback_data: BookingCB,
                            svc_bs: FromDishka[BookingService],
                            use_case: FromDishka[BookingUseCase],
                            state: FSMContext
                            ):

    week_offset = await _get_week_offset(state)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await svc_bs.join_queue(
            user_id=call.from_user.id,
            cal_date=cal_date
        )
    except BookingServiceExceptions as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось встать в очередь.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, False, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.LEAVEQ})))
async def handle_queue_leave(call: CallbackQuery,
                             callback_data: BookingCB,
                             svc_bs: FromDishka[BookingService],
                             use_case: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):

    week_offset = await _get_week_offset(state)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await svc_bs.leave_from_queue(
            user_id=call.from_user.id, cal_date=cal_date
        )
    except BookingServiceExceptions as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось выйти из очереди.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, False, use_case, state)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.INFO})))
async def handle_booking_help(call: CallbackQuery):

    await call.answer(
        text="⚪️ — Места еще есть\n\n"
             "🟢 — Ты уже забронировал\n"
             "───────────\n"
             "🔴 — Мест нет\nДля записи в очередь, нажми кнопку c ⏳\n\n"
             "🟡️ — Ты в очереди\nДля выхода из очереди, нажми кнопку с 🚪\n"
             "───────────\n"
             "🌴 — Праздничный день",
        show_alert=True
    )


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.GET_BACK_MENU})))
async def handle_back_menu_button(call: CallbackQuery, state: FSMContext) -> None:

    if state:
        await state.clear()

    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())


# ----------------------------------------------хэлперы----------------------------------------------
async def _get_week_offset(state: FSMContext) -> int:
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    return week_offset


async def _render_booking_page(
        call: CallbackQuery,
        week_offset: int,
        from_menu: bool,
        booking_use_case: BookingUseCase,
        state: FSMContext,
) -> None:

    try:
        active, mine, caps, cal = await booking_use_case.booking_page_data(
            week_offset=week_offset, user_id=call.from_user.id
        )

        text = render_week(active, caps, cal, mine)
        kb = get_booking_kb(active, caps, cal, mine, week_offset)
        await call.message.edit_text(text, reply_markup=kb)

    except Exception as e:
        logger.exception(f"Не удалось отрисовать расписание для бронирования: {str(e)}")
        if from_menu:
            await call.answer(
                "❌ Не удалось получить расписание.\nПопробуйте ещё раз позже.",
                show_alert=True,
            )
            return
        else:
            await call.answer(
                "ℹ️ Данные сохранены, но расписание получить не удалось.\n"
                "Возвращаемся в меню.", show_alert=True
            )
            if await state.get_state():
                await state.clear()

            await call.message.edit_text(
                text=bot_menu_mess(),
                reply_markup=get_menu_kb(),
            )