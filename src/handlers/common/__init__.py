from aiogram import Router

from src.handlers.common.fallback_handler import router as fallback_router

common_combined_router = Router()

common_combined_router.include_routers(
    fallback_router,
)