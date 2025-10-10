import logging

from aiogram import Router, F
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from dishka import FromDishka

from config import settings as s
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


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_left_chat_member(event: ChatMemberUpdated, uc: FromDishka[UserUseCase]):
    member = event.from_user.id
    await uc.update_is_active(member, False)
    logger.info("User %s is left from chat", member)


# ----------------------------------------------helpers----------------------------------------------
def _link(user_id: int, first_name: str) -> str:
    if first_name == 'ᅠ':
        first_name = 'Jonson'
    return f'<a href="tg://user?id={user_id}">{first_name}</a>'

