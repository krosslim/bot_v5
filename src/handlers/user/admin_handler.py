"""Служебные команды администратора (в меню команд не показываются)."""
import logging
import re
from datetime import date, timedelta
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramNotFound
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from dishka import FromDishka

from config import settings
from src.services.tech_service import TechService
from src.ui.keyboard.booking_remind_kb import confirm_kb
from src.ui.messages.booking_remind_mess import build_digest_message_v2
from src.ui.widgets.render import WidgetTooLarge
from src.ui.widgets.state import day_short
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.widget_use_case import WidgetUseCase
from src.utils.db_exc_wrapper import DBError
from src.utils.today import effective_today

router = Router()

logger = logging.getLogger(__name__)

USAGE = ("<b>/digest_now</b> — отправить дайджест в группу сейчас\n"
         "<blockquote>/digest_now — на ближайший рабочий день\n"
         "/digest_now 10.11 — на указанную дату</blockquote>")


def _parse_date(arg: str, today: date) -> Optional[date]:
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", arg.strip())
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    # 05.01 в декабре — это январь следующего года
    return date(today.year + 1, month, day) if d < today - timedelta(days=180) else d


@router.message(Command("digest_now"), F.chat.type == ChatType.PRIVATE)
async def handle_digest_now(
        msg: Message,
        command: CommandObject,
        bot: Bot,
        uc: FromDishka[BookingUseCase],
        widgets: FromDishka[WidgetUseCase],
        tech_svc: FromDishka[TechService],
):
    try:
        user = await uc.user_or_none(msg.from_user.id)
        if user is None or not user.is_admin:
            await msg.answer("⚠️ Команда доступна только администраторам")
            return

        first = effective_today()
        if command.args:
            target = _parse_date(command.args, first)
            if target is None:
                await msg.answer(USAGE)
                return
            if target < first:
                await msg.answer(f"⚠️ Бронирование на {day_short(target)} уже закрыто")
                return
            if not await uc.is_workday(target):
                await msg.answer(f"⚠️ {day_short(target).capitalize()} — нерабочий день")
                return
        else:
            target = first
            for _ in range(14):
                if await uc.is_workday(target):
                    break
                target += timedelta(days=1)
            else:
                await msg.answer("⚠️ В ближайшие две недели нет рабочих дней в календаре")
                return

        if settings.DIGEST_WIDGET_ENABLED:
            message = await widgets.send_digest(target)
            kind = "виджетом"
        else:
            bookings, capacity = await uc.chat_booking_data(cal_date=target)
            message = await bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=build_digest_message_v2(bookings, capacity, target),
                reply_markup=confirm_kb(bookings, capacity, target),
                disable_web_page_preview=True,
            )
            kind = "текстом (DIGEST_WIDGET_ENABLED=false)"

        # Нажатия в виджете принимаются только из сообщения, записанного здесь
        await tech_svc.upsert_chat_message_id(cal_date=target, message_id=message.message_id)
        logger.info("digest_now | admin=%s date=%s message_id=%s", user.user_id, target, message.message_id)

        await msg.answer(
            f"✅ Дайджест на {day_short(target)} отправлен в группу {kind}.\n"
            "<blockquote>Сообщение не закреплено. Предыдущий дайджест на эту дату перестанет принимать нажатия.</blockquote>"
        )

    except TelegramNotFound:
        logger.error("digest_now | Bot API %s не знает sendWidget", settings.TELEGRAM_API_BASE)
        await msg.answer("⚠️ Этот адрес Bot API не поддерживает виджеты.\n"
                         "<blockquote>Укажите в .env TELEGRAM_API_BASE=https://api.telegram.org/beta "
                         "и перезапустите бота</blockquote>")
    except (TelegramAPIError, WidgetTooLarge) as e:
        logger.error("digest_now | %s", e)
        if "INPUT_MEDIA_WIDGET_NOT_ALLOWED" in str(e):
            await msg.answer("⚠️ Telegram пока не разрешает этому боту отправлять виджеты в группу.\n"
                             "<blockquote>Личный виджет работает. Для дайджеста поставьте в .env "
                             "DIGEST_WIDGET_ENABLED=false — он будет уходить текстом, как раньше</blockquote>")
        else:
            await msg.answer(f"⚠️ Telegram не принял дайджест:\n<code>{e}</code>")
    except DBError:
        await msg.answer("⚠️ Ошибка базы данных. Попробуйте ещё раз.")
