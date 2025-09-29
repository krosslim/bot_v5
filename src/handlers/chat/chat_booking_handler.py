from datetime import date

from aiogram import Router, F
from aiogram.types import CallbackQuery
from dishka import FromDishka

from src.services.exceptions import BookingError
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.messages.booking_remind_mess import build_digest_message
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.today import effective_today

router = Router()


@router.callback_query(ChatBookingCB.filter(F.step.in_({ChatBookingStep.ADD_BOOKING, ChatBookingStep.CONFIRM_BOOKING})))
async def handle_chat_booking(call: CallbackQuery, callback_data: ChatBookingCB, uc: FromDishka[BookingUseCase]):
    step = callback_data.step
    cal_date = date.fromisoformat(callback_data.extra)
    today = effective_today()

    if cal_date < today:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer(text="⚠️ День прошел. Бронирование невозможно",
                          show_alert=True)
        return

    try:

        if not await uc.get_user_for_chat_booking(call.from_user.id):
            await call.answer(text="⚠️ Для выполнения действия требуется регистрация в боте,"
                                   "который указан в сообщении",
                              show_alert=True)
        else:
            if step == ChatBookingStep.ADD_BOOKING:
                await uc.book_place(user_id=call.from_user.id, cal_date=cal_date, auto_confirm=True)
                await call.answer(text="✅ Место успешно забронировано", show_alert=True)
            else:
                booking_id = await uc.confirm_booking(user_id=call.from_user.id, cal_date=cal_date)
                if booking_id:
                    await call.answer(text="✅ Бронь подтверждена", show_alert=True)
                else:
                    if await uc.user_booking_for_date(user_id=call.from_user.id, cal_date=cal_date):
                        await call.answer(text="✅ Бронь уже подтверждена. Повторное подтверждение не требуется",
                                          show_alert=True)
                    else:
                        await call.answer(text="⚠️ Бронь для подтверждения отсутствует", show_alert=True)

    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)

    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выполнить действие.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)

    try:
        bookings, capacity = await uc.chat_booking_data(cal_date=cal_date)
        await call.message.edit_text(
            text=build_digest_message(bookings, capacity, cal_date),
            reply_markup=confirm_kb(bookings, capacity, cal_date),
            disable_web_page_preview=True
        )
    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выполнить действие.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)


