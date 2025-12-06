import logging
from datetime import date
from typing import Optional, List

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.dto.booking_dto import BookingStatus
from src.services.exceptions import BookingError
from src.services.tech_service import TechService
from src.ui.keyboard.actions import BookingCB, BookingStep
from src.ui.keyboard.bookings_inline_kb import render_booking_week_kb
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.keyboard.menu_inline_kb import own_booking_kb
from src.ui.keyboard.missed_days_booking_kb import render_missed_booking_kb
from src.ui.messages.auto_book_mess import build_promote_message
from src.ui.messages.help_booking_mess import render_help_booking_mess3
from src.ui.messages.missed_days_booking_mess import render_missed_booking_mess
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
    user_id = state_data.get('user_id', call.from_user.id)

    await render_booking_page(call, week_offset, uc, state, help_page, user_id)


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
    user_id = state_data.get('user_id', call.from_user.id)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.book_place(user_id=user_id, cal_date=cal_date)
    except BookingError as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text ="⚠️ Ошибка: Не удалось забронировать место.\n"
                                "Немного подождите и попробуйте еще раз.",
                          show_alert = True
                          )

    await render_booking_page(call, week_offset, uc, state, help_page, user_id)

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
    user_id = state_data.get('user_id', None)
    cancel_sub_status = BookingStatus.CANCELED_ADMIN
    if not user_id:
        user_id = call.from_user.id
        cancel_sub_status = BookingStatus.CANCELED_CHANGED_MIND
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await promote_user_after_cancel(call, uc, cal_date, None, user_id, cancel_sub_status)
    except BookingError as e:
        await call.answer(text = str(e), show_alert = True)
    except DBError:
        await call.answer(text=
                          "⚠️ Ошибка: Не удалось отменить бронь.\n"
                          "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await render_booking_page(call, week_offset, uc, state, help_page, user_id)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.JOINQ})))
async def handle_queue_join(call: CallbackQuery,
                            callback_data: BookingCB,
                            uc: FromDishka[BookingUseCase],
                            state: FSMContext
                            ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
    user_id = state_data.get('user_id', call.from_user.id)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.waitlist_place(user_id, cal_date)
        await call.answer(text="Записали тебя в очередь!\n\nОтправим пуш, если появится место",
                          show_alert=True)
    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось встать в очередь.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await render_booking_page(call, week_offset, uc, state, help_page, user_id)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.LEAVEQ})))
async def handle_queue_leave(call: CallbackQuery,
                             callback_data: BookingCB,
                             uc: FromDishka[BookingUseCase],
                             state: FSMContext
                             ):
    state_data = await state.get_data()
    week_offset = int(state_data.get('week_offset', 0))
    help_page = state_data.get('help_page', None)
    user_id = state_data.get('user_id', call.from_user.id)
    cal_date = date.fromisoformat(callback_data.extra)

    try:
        await uc.cancel_waitlist_place(user_id, cal_date)
    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выйти из очереди.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True
                          )

    await render_booking_page(call, week_offset, uc, state, help_page, user_id)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.WEEK_INFO})))
async def handle_booking_help(call: CallbackQuery, uc: FromDishka[BookingUseCase], state: FSMContext):

    try:
        state_data = await state.get_data()
        week_offset = int(state_data.get('week_offset', 0))
        help_page = state_data.get('help_page', None)
        user_id = state_data.get('user_id', call.from_user.id)

        if not help_page:
            help_page = 1
        else:
            help_page = None

        await state.update_data(help_page=help_page)
        await render_booking_page(call, week_offset, uc, state, help_page, user_id)

    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось получить инструкцию.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.GET_BACK_MENU})))
async def handle_back_menu_button(call: CallbackQuery, state: FSMContext):
    if await state.get_data():
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
        special_text = f"• Подробная инструкция:\n{callback_data.extra}"

    msg = (
        "• Сменить неделю: ← →\n───────────\n"
        f"{special_text}"
    )

    if week_offset < 0:
        await call.answer(text=msg, show_alert=True)
        return

    await call.answer(text="• Записаться: жми ПН–ПТ\n───────────\n"+msg, show_alert=True)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.MISSED_NOT_CHOOSEN, BookingStep.MISSED_CHOOSEN})))
async def handle_missed_booking_choose(
        call: CallbackQuery,
        callback_data: BookingCB,
        uc: FromDishka[BookingUseCase],
        state: FSMContext
):
    state_data = await state.get_data()
    choosen_dates_str = state_data.get('choosen_dates', [])
    prev_month = state_data.get('prev_month', False)

    cal_date = callback_data.extra

    if callback_data.step == BookingStep.MISSED_NOT_CHOOSEN:
        choosen_dates_str.append(cal_date)
    else:
        try:
            choosen_dates_str.remove(cal_date)
        except ValueError:
            logger.warning("Не известные данные для удаления из списка | исходный список: %s | Значение из callback: %s",
                           choosen_dates_str, cal_date)
            pass

    await state.update_data(choosen_dates=choosen_dates_str)

    await _render_missed_booking(call, uc, choosen_dates_str, prev_month)


@router.callback_query(BookingCB.filter(F.step.in_({BookingStep.MISSED_CONFIRM})))
async def handle_missed_booking_confirmation(
        call: CallbackQuery,
        uc: FromDishka[BookingUseCase],
        tech_svc: FromDishka[TechService],
        state: FSMContext
):
    state_data = await state.get_data()
    choosen_dates_str = state_data.get('choosen_dates', [])

    # На случай если юзер создал несколько сообщений
    if not choosen_dates_str:
        await call.message.edit_text(
            text=bot_menu_mess(),
            reply_markup=get_menu_kb(),
        )
        await call.answer("⚠️ Не удалось добавить записи.\nПопробуйте еще раз", show_alert=True)
        return

    try:
        user_id = call.from_user.id
        call_msg_id = call.message.message_id
        choosen_dates = _parse_dates_from_iso(choosen_dates_str)

        await uc.book_missed_days(user_id, choosen_dates)
        await call.message.edit_text(text=render_missed_booking_mess(choosen_dates, True))
        await call.answer("✅ Записи успешно добавлены!", show_alert=True)


        # Завершение сессии
        await state.clear()
        await tech_svc.finish_booking_session(user_data=f"{user_id}:{call_msg_id}")

    except (DBError, BookingError) as e:
        await call.answer(text=str(e), show_alert=True)


# ---------------------------------------------- helpers ----------------------------------------------
async def render_booking_page(
        call: CallbackQuery,
        week_offset: int,
        uc: BookingUseCase,
        state: FSMContext,
        help_page: Optional[int] = None,
        user_id: int = None
) -> None:
    try:
        monday, sunday, _ = week_range(week_offset)
        active, capacity, calendar = await uc.booking_page_data(start=monday, end=sunday)
        user_id = call.from_user.id if not user_id else user_id

        if help_page:
            await call.message.edit_text(
                text=render_help_booking_mess3(active, capacity, calendar, user_id),
                reply_markup=render_booking_week_kb(active, capacity, calendar, user_id, week_offset, help_page)
            )
        else:
            await call.message.edit_text(
                text=render_booking_week_mess(active, capacity, calendar, user_id),
                reply_markup=render_booking_week_kb(active, capacity, calendar, user_id, week_offset, help_page)
            )
    except DBError:
        await call.answer(text="ℹ️ Данные сохранены, но расписание получить не удалось.\n"
                               "Возвращаемся в меню.",
                          show_alert=True
                          )
        if await state.get_data():
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
        user_id = call.from_user.id if not user_id else user_id

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
                logger.error(f"Сообщение для user_id {promote_user_id} не отправлено. Аргументы функции заданы неверно")
                return None
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.error(f"Не удалось отправить сообщение {promote_user_id}")

        return promote_user_id


async def _render_missed_booking(
        call: CallbackQuery,
        uc: BookingUseCase,
        choosen_dates_str: List[str],
        prev_month: bool
) -> None:

    try:
        data = await uc.cal_date_without_bookings(call.from_user.id, prev_month)
        choosen_dates = _parse_dates_from_iso(choosen_dates_str)

        await call.message.edit_text(
            text=render_missed_booking_mess(choosen_dates),
            reply_markup=render_missed_booking_kb(data, choosen_dates)
        )

    except (DBError, BookingError) as e:
        await call.answer(text=str(e), show_alert=True)


def _parse_dates_from_iso(
        choosen_dates_str: List[str]
) -> List[date]:
    return list(map(date.fromisoformat, choosen_dates_str))
