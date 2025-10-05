import logging
from datetime import date, datetime, time, timedelta

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from dishka import FromDishka

from config import settings as s
from src.services.exceptions import BookingError
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.ui.keyboard.menu_inline_kb import get_menu_kb
from src.ui.messages.auto_book_mess import build_promote_message
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError

router = Router()

logger = logging.getLogger(__name__)

@router.callback_query(ChatBookingCB.filter(F.step.in_(
    {ChatBookingStep.CONFIRM_BOOKING_IN_REMINDER, ChatBookingStep.CANCEL_BOOKING_IN_REMINDER}
)))
async def handle_booking_action(call: CallbackQuery, callback_data: ChatBookingCB, uc: FromDishka[BookingUseCase]):

    step = callback_data.step

    cal_date = date.fromisoformat(callback_data.extra)
    tomorrow = date.today() + timedelta(days=1)

    if cal_date != tomorrow:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer(text="⚠️ Неверная дата брони",
                          show_alert=True)
        return

    current_time = datetime.now().time()
    cancel_time = time(s.CANCEL_BOOKING_JOB_HOUR, s.CANCEL_BOOKING_JOB_MINUTES)

    if current_time > cancel_time:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer(text="⚠️ Время истекло. Выполнить действие невозможно",
                          show_alert=True)
        return

    try:
        if step == ChatBookingStep.CONFIRM_BOOKING_IN_REMINDER:
            booking_id = await uc.confirm_booking(user_id=call.from_user.id, cal_date=cal_date)
            if booking_id:
                await call.message.edit_reply_markup(reply_markup=None)
                await call.answer(text="✅ Бронь подтверждена", show_alert=True)
                await call.bot.send_message(
                    chat_id=call.from_user.id,
                    text=f"{tomorrow} → Бронь подтверждена\n\n<b>Главное меню ⤵</b>",
                    reply_markup=get_menu_kb(),
                )
            else:
                if await uc.user_booking_for_date(user_id=call.from_user.id, cal_date=cal_date):
                    await call.message.edit_reply_markup(reply_markup=None)
                    await call.answer(text="✅ Бронь уже подтверждена. Повторное подтверждение не требуется",
                                      show_alert=True)
                else:
                    await call.message.edit_reply_markup(reply_markup=None)
                    await call.answer(text="⚠️ Бронь для подтверждения отсутствует", show_alert=True)

        if step == ChatBookingStep.CANCEL_BOOKING_IN_REMINDER:
            promote_user_id = await uc.cancel_book_place(call.from_user.id, cal_date)
            if promote_user_id:
                try:
                    await call.bot.send_message(chat_id=promote_user_id, text=build_promote_message(cal_date=cal_date))
                except TelegramBadRequest as e_tg:
                    logger.exception(f"Не удалось отправить сообщение {promote_user_id} | {str(e_tg)}")

            await call.message.edit_reply_markup(reply_markup=None)
            await call.answer(text="✅ Бронь на завтра отменена", show_alert=True)
            await call.bot.send_message(
                chat_id=call.from_user.id,
                text=f"{tomorrow} → Бронь отменена\n\n<b>Главное меню ⤵</b>",
                reply_markup=get_menu_kb(),
            )

    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)

    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выполнить действие.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)







