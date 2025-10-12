import logging

from aiogram import Router, F, Bot
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.types import Message, ChatMemberUpdated
from dishka import FromDishka

from config import settings as s
from src.dto.booking_dto import BookingStatus
from src.handlers.user.booking_handler import promote_user_after_cancel
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.user_use_case import UserUseCase

router = Router()

logger = logging.getLogger(__name__)


@router.message(F.chat.id == s.TG_CHAT_ID, F.new_chat_member)
async def handle_new_chat_member(msg: Message, uc: FromDishka[UserUseCase]):

    members = [user for user in msg.new_chat_members if not user.is_bot]

    if not members:
        logger.info("No members found for new chat member")
        return

    for user in members:
        if await uc.update_is_active(user.id, True):
            continue

        name = _link(user.id, user.first_name)
        await msg.reply(
            "<b>В нашей команде пополнение 🎉</b>\n\n"
            f"<b>{name}</b>, добро пожаловать!\n"
            "Расскажи, пожалуйста, о себе — в какую команду присоединился и на какую позицию 😊\n\n"
            "<blockquote>P.S. Если ты из Москвы, зарегистрируйся в боте "
            f"<b>@{s.BOT_USERNAME}</b>, чтобы бронировать места в офисе.</blockquote>"
        )


@router.chat_member(F.chat.id == s.TG_CHAT_ID, ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_left_chat_member(
        event: ChatMemberUpdated,
        bot: Bot,
        u_uc: FromDishka[UserUseCase],
        b_uc: FromDishka[BookingUseCase]
):

    if event.new_chat_member.user.is_bot:
        return

    member = event.new_chat_member.user.id

    await u_uc.update_is_active(member, False)
    logger.info("User %s is left from chat", member)

    active = await b_uc.my_bookings(member)

    if not active:
        return

    for i in active:
        if i.status == BookingStatus.BOOKED:
            await promote_user_after_cancel(
                call=None,
                uc=b_uc,
                cal_date=i.cal_date,
                bot=bot,
                user_id=member,
                cancel_sub_status=BookingStatus.CANCELED_LEFT_CHAT
            )
            continue

        await b_uc.update_by_status(
            i.cal_date,
            BookingStatus.WAITLISTED,  # текущий
            BookingStatus.WAITLISTED_MANUAL,
            BookingStatus.CANCELED,  # Новый
            BookingStatus.CANCELED_LEFT_CHAT
        )


# ----------------------------------------------helpers----------------------------------------------
def _link(user_id: int, first_name: str) -> str:
    if first_name == 'ᅠ':
        first_name = 'Jonson'
    return f'<a href="tg://user?id={user_id}">{first_name}</a>'

