from src.handlers.user import user_combined_router
from src.handlers.common import common_combined_router
from aiogram import Router

bot_combined_router = Router()

bot_combined_router.include_routers(
    user_combined_router,

    common_combined_router
)