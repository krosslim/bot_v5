from aiogram import Router

from src.handlers.chat.chat_booking_handler import router as chat_booking_router
from src.handlers.chat.chat_member_handler import router as chat_member_router
from src.handlers.chat.chat_cancel_handler import router as chat_cancel_router

chat_combined_router = Router()

chat_combined_router.include_routers(chat_booking_router, chat_member_router, chat_cancel_router)