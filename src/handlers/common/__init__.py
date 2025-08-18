from aiogram import Router

from src.handlers.common.fallback_handler import router as fallback_router
from src.handlers.common.setting_handler import router as settings_router

common_combined_router = Router()

common_combined_router.include_routers(settings_router, fallback_router)