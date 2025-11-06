import logging
from datetime import date
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.services.exceptions import BookingError
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.ui.keyboard.bookings_inline_kb import render_booking_week_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.menu_inline_kb import own_booking_kb
from src.ui.messages.auto_book_mess import build_promote_message
from src.ui.messages.help_booking_mess import render_help_booking_mess3
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

    _, _, week_offset = week_range(int(callback_data.extra) if callback_data.extra else None)

    await state.update_data(week_offset=week_offset)

    state_data = await state.get_data()
    help_page = state_data.get('help_page', None)

    await _render_booking_page(call, week_offset, uc, state, help_page)


# действие "забронировать"
@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.BOOK})))
async def handle_book_action(call: CallbackQuery,
                             callback_data: BookingCB,
                             uc: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
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

    await _render_booking_page(call, week_offset, uc, state, help_page)

# действие "отменить бронь"
@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.UNBOOK})))
async def handle_book_cancel_action(call: CallbackQuery,
                                    callback_data: BookingCB,
                                    uc: FromDishka[BookingUseCase],
                                    state: FSMContext
                                    ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await promote_user_after_cancel(call, uc, cal_date)
    except BookingError as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось отменить бронь.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, uc, state, help_page)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.JOINQ})))
async def handle_queue_join(call: CallbackQuery,
                            callback_data: BookingCB,
                            uc: FromDishka[BookingUseCase],
                            state: FSMContext
                            ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.waitlist_place(call.from_user.id, cal_date)
        await call.answer(text="Записали тебя в очередь!\nОтправим пуш, если появится место",
                          show_alert=True)
    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось встать в очередь.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await _render_booking_page(call, week_offset, uc, state, help_page)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.LEAVEQ})))
async def handle_queue_leave(call: CallbackQuery,
                             callback_data: BookingCB,
                             uc: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
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

    await _render_booking_page(call, week_offset, uc, state, help_page)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.WEEK_INFO})))
async def handle_booking_help(call: CallbackQuery, uc: FromDishka[BookingUseCase], state: FSMContext):

    try:
        state_data = await state.get_data()
        week_offset = int(state_data.get('week_offset', 0))
        help_page = state_data.get('help_page', None)

        if not help_page:
            help_page = 1
        else:
            help_page = None

        await state.update_data(help_page=help_page)
        await _render_booking_page(call, week_offset, uc, state, help_page)

    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось получить инструкцию.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.GET_BACK_MENU})))
async def handle_back_menu_button(call: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    if state_data:
        await state.clear()
    await call.message.edit_text(text = bot_menu_mess(), reply_markup=get_menu_kb())


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.INFO})))
async def handle_week_info(call: CallbackQuery, callback_data: BookingCB, state: FSMContext):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
    if help_page:
        special_text = f"Вернуть обычный режим:\nжми •{callback_data.extra}•"
    else:
        special_text = f"• Узнать статус дня:\n{callback_data.extra}"

    msg = (
        "• Сменить неделю: ← →\n───────────\n"
        f"{special_text}"
    )

    if week_offset < 0:
        await call.answer(text=msg, show_alert=True)
        return

    await call.answer(text="• Записаться: жми ПН–ПТ\n───────────\n"+msg, show_alert=True)


# ---------------------------------------------- helpers ----------------------------------------------
async def _render_booking_page(
        call: CallbackQuery,
        week_offset: int,
        uc: BookingUseCase,
        state: FSMContext,
        help_page: Optional[int] = None
) -> None:
    try:
        monday, sunday, _ = week_range(week_offset)
        active, capacity, calendar = await uc.booking_page_data(start=monday, end=sunday)

        if help_page:
            await call.message.edit_text(
                text=render_help_booking_mess3(active, capacity, calendar, call.from_user.id),
                reply_markup=render_booking_week_kb(active, capacity, calendar, call.from_user.id, week_offset, help_page)
            )
        else:
            await call.message.edit_text(
                text=render_booking_week_mess(active, capacity, calendar, call.from_user.id),
                reply_markup=render_booking_week_kb(active, capacity, calendar, call.from_user.id, week_offset, help_page)
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


async def promote_user_after_cancel(
        call: CallbackQuery | None,
        uc: BookingUseCase,
        cal_date: date,
        bot: Bot | None = None,
        user_id: int | None = None,
        cancel_sub_status: str | None = None
) -> Optional[int]:

    if call:
        user_id = call.from_user.id

    if call is None and user_id is None:
        return None

    promote_user_id = await uc.cancel_book_place(user_id, cal_date, cancel_sub_status)
    if promote_user_id:
        try:
            if call and bot is None:
                await call.bot.send_message(
                    chat_id=promote_user_id,
                    text=build_promote_message(cal_date=cal_date),
                    reply_markup=own_booking_kb()
                )

            elif bot and call is None:
                await bot.send_message(
                    chat_id=promote_user_id,
                    text=build_promote_message(cal_date=cal_date),
                    reply_markup=own_booking_kb()
                )
            else:
                logger.exception(f"Сообщение для user_id {promote_user_id} не отправлено. Аргументы функции заданы неверно")
                return None
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.exception(f"Не удалось отправить сообщение {promote_user_id}")

        return promote_user_id