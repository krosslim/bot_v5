import asyncio
from datetime import date

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from dishka import FromDishka

from config import settings as s
from src.dto.booking_dto import DateBookingsDTO
from src.services.exceptions import BookingError
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.messages.booking_remind_mess import build_digest_message_v2
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.today import effective_today

router = Router()

_pending_updates: dict[tuple[int, int], asyncio.Task] = {}

# Действия в чате по бронированию
@router.callback_query(
    ChatBookingCB.filter(
        F.step.in_({ChatBookingStep.ADD_BOOKING, ChatBookingStep.CONFIRM_BOOKING})
    )
)
async def handle_chat_booking(
    call: CallbackQuery, callback_data: ChatBookingCB, uc: FromDishka[BookingUseCase]
):
    step = callback_data.step
    cal_date = date.fromisoformat(callback_data.extra)
    today = effective_today()

    if cal_date < today:
        await _day_left_alert(call)
        await call.message.edit_reply_markup(reply_markup=None)
        return

    try:
        if not await uc.get_user_for_chat_booking(call.from_user.id):
            await _user_not_registration_alert(call)
        else:
            if step == ChatBookingStep.ADD_BOOKING:
                await uc.book_place(
                    user_id=call.from_user.id, cal_date=cal_date, auto_confirm=True
                )
                await call.answer(
                    text="✅ Место успешно забронировано", show_alert=True
                )
            else:
                booking_id = await uc.confirm_booking(
                    user_id=call.from_user.id, cal_date=cal_date
                )
                if booking_id:
                    await call.answer(text="✅ Бронь подтверждена", show_alert=True)
                else:
                    if await uc.user_booking_for_date(
                        user_id=call.from_user.id, cal_date=cal_date
                    ):
                        await call.answer(
                            text="✅ Бронь уже подтверждена. Повторное подтверждение не требуется",
                            show_alert=True,
                        )
                    else:
                        await call.answer(
                            text="⚠️ Бронь для подтверждения отсутствует",
                            show_alert=True,
                        )

    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)

    except DBError:
        await call.answer(
            text="⚠️ Ошибка: Не удалось выполнить действие.\n"
            "Немного подождите и попробуйте еще раз.",
            show_alert=True,
        )

    try:
        bookings, capacity = await uc.chat_booking_data(cal_date=cal_date)
        schedule_digest_update(
            bot=call.bot,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            cal_date=cal_date,
            bookings=bookings,
            capacity=capacity,
        )
    except DBError:
        await call.answer(
            text="⚠️ Ошибка: Не удалось выполнить действие.\n"
            "Немного подождите и попробуйте еще раз.",
            show_alert=True,
        )


@router.callback_query(
    ChatBookingCB.filter(F.step.in_({ChatBookingStep.ADD_BOOKING_INLINE_CANCEL}))
)
async def handle_chat_inline_booking(
    call: CallbackQuery,
    callback_data: ChatBookingCB,
    uc: FromDishka[BookingUseCase],
):
    cal_date = date.fromisoformat(callback_data.extra)
    today = effective_today()

    if cal_date < today:
        await _day_left_alert(call)
        await call.bot.edit_message_reply_markup(
            inline_message_id=call.inline_message_id, reply_markup=None
        )
        return

    try:
        if not await uc.get_user_for_chat_booking(call.from_user.id):
            await _user_not_registration_alert(call)
            return

        await uc.book_place(user_id=call.from_user.id, cal_date=cal_date)
        await call.bot.edit_message_reply_markup(
            inline_message_id=call.inline_message_id, reply_markup=None
        )
        await call.answer(text="✅ Место успешно забронировано", show_alert=True)

    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)

    except DBError:
        await call.answer(
            text="⚠️ Ошибка: Не удалось выполнить действие.\n"
            "Немного подождите и попробуйте еще раз.",
            show_alert=True,
        )


# ----------------------------------------------helpers----------------------------------------------
async def _day_left_alert(call: CallbackQuery) -> None:
    await call.answer(text=f"⚠️ Бронь возможна только до {s.WORK_END_HOUR}:{s.WORK_END_MINUTES:02d}",
                      show_alert=True)


async def _user_not_registration_alert(call: CallbackQuery) -> None:
    await call.answer(
        text="⚠️ Для выполнения действия требуется регистрация в боте,"
        "который указан в сообщении",
        show_alert=True,
    )


def schedule_digest_update(
    bot: Bot,
    chat_id: int,
    message_id: int,
    cal_date: date,
    bookings: DateBookingsDTO,
    capacity: int
):
    key = (chat_id, message_id)

    old = _pending_updates.get(key)

    if old and not old.done():
        old.cancel()

    task = asyncio.create_task(
        _debounced_update(key, bot, chat_id, message_id, cal_date, bookings, capacity)
    )

    _pending_updates[key] = task


async def _debounced_update(
    key: tuple[int, int],
    bot: Bot,
    chat_id: int,
    message_id: int,
    cal_date: date,
    bookings: DateBookingsDTO,
    capacity: int
):
    try:

        await asyncio.sleep(0.5)

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=build_digest_message_v2(bookings, capacity, cal_date),
            reply_markup=confirm_kb(bookings, capacity, cal_date),
            disable_web_page_preview=True,
        )
    except asyncio.CancelledError:
        return
    finally:
        current = _pending_updates.get(key)
        if current is asyncio.current_task():
            del _pending_updates[key]