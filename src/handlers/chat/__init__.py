from aiogram import Router

from src.handlers.chat.chat_booking_handler import router as chat_booking_router

chat_combined_router = Router()

chat_combined_router.include_routers(chat_booking_router)