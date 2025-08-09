from aiogram import Dispatcher
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from src.middlewares.chat_member_middleware import ChatMembershipMiddleware
from src.middlewares.exception_middleware import ExceptionMiddleware
from src.middlewares.throttling_middleware import ThrottlingMiddleware


def setup_outer_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(ExceptionMiddleware())


def setup_inner_middlewares(dp: Dispatcher, chat_id: int) -> None:
    dp.message.middleware(ChatMembershipMiddleware(chat_id))
    dp.callback_query.middleware(ChatMembershipMiddleware(chat_id))

    dp.callback_query.middleware(ThrottlingMiddleware())

    dp.callback_query.middleware(CallbackAnswerMiddleware(text="Ок"))
