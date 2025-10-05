from aiogram import Router

from src.handlers.user.booking_handler import router as booking_router
from src.handlers.user.booking_remind_handler import router as booking_remind_router
from src.handlers.user.my_booking_handler import router as my_booking_router
from src.handlers.user.start_handler import router as start_router
from src.middlewares.booking_session_middleware import BookingSessionMiddleware

booking_router.callback_query.middleware.register(BookingSessionMiddleware())


user_combined_router = Router()
user_combined_router.include_routers(start_router, booking_router, my_booking_router, booking_remind_router)

