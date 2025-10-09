import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import CallbackQuery
from dishka import FromDishka

from config import settings as s
from src.handlers.user.booking_handler import promote_user_after_cancel
from src.services.exceptions import BookingError
from src.ui.keyboard.actions import ChatBookingCB, ChatBookingStep
from src.ui.keyboard.menu_inline_kb import own_booking_kb, get_menu_kb
from src.ui.messages.start_mess import bot_menu_mess
from src.use_cases.booking_use_case import BookingUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.tommorow import fmt_date_ru

router = Router()

logger = logging.getLogger(__name__)

@router.callback_query(ChatBookingCB.filter(F.step.in_(
    {ChatBookingStep.CONFIRM_BOOKING_IN_REMINDER, ChatBookingStep.CANCEL_BOOKING_IN_REMINDER}
)))
async def handle_booking_action(call: CallbackQuery, callback_data: ChatBookingCB, uc: FromDishka[BookingUseCase]):

    step = callback_data.step

    cal_date = date.fromisoformat(callback_data.extra)
    tomorrow = date.today() + timedelta(days=1)
    str_tomorrow = fmt_date_ru(tomorrow)

    if cal_date != tomorrow:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer(text="⚠️ Неверная дата брони",
                          show_alert=True)
        return

    current_time = datetime.now(tz=ZoneInfo(s.MSC_TZ)).time()
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
                await call.answer(text="✅ Бронь на завтра подтверждена", show_alert=True)
                await call.bot.send_message(
                    chat_id=call.from_user.id,
                    text=f"<b>{str_tomorrow} → Подтверждено</b>\n\n"
                         f"<blockquote><b>Как подключить автоподтверждение?</b>\n"
                         f"/menu → ⚙ Настройки → Автоподтверждение брони</blockquote>",
                    reply_markup=own_booking_kb(),
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

            await promote_user_after_cancel(call, uc, cal_date)

            await call.message.edit_reply_markup(reply_markup=None)
            await call.answer(text="✅ Бронь на завтра отменена", show_alert=True)
            await call.bot.send_message(chat_id=call.from_user.id, text=f"<b>{str_tomorrow} → Отменено</b>")
            await call.bot.send_message(chat_id=call.from_user.id, text=bot_menu_mess(), reply_markup=get_menu_kb())

    except BookingError as e:
        await call.answer(text=str(e), show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)

    except DBError:
        await call.answer(text="⚠️ Ошибка: Не удалось выполнить действие.\n"
                               "Немного подождите и попробуйте еще раз.",
                          show_alert=True)







