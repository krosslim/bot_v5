from src.handlers.start_handler import router as start_router
from aiogram import Router


combined = Router()

router_list = combined.include_router(
    start_router
)