from aiogram import Router

from src.handlers.chat.chat_booking_handler import router as chat_booking_router
from src.handlers.chat.user_update_handler import router as user_update_router

chat_combined_router = Router()

chat_combined_router.include_routers(chat_booking_router, user_update_router)