from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings


def week_summary_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Забронировать место",
                url=f"https://t.me/{settings.BOT_USERNAME}?start="
            )]
        ]
    )