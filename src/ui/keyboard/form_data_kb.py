from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.dto.user_dto import DictDTO


def get_dict_kb(dict_data: List[DictDTO]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=item.name, callback_data=f"{str(item.id)}#{str(item.name)}")]
        for item in dict_data
    ])
    return kb

def get_skip_birthday_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="SKIP_BIRTHDAY")]
    ])

def get_confirmation_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сохранить", callback_data="SAVE")],
        [InlineKeyboardButton(text="Начать заново", callback_data="DELETE")],
    ])