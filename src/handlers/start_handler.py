from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from dishka import FromDishka


from src.services.user_service import UserService

router = Router()

@router.message(CommandStart())
async def start_handler(message: Message, service: FromDishka[UserService]):
    user = await service.check_user(message.from_user.id)
    if user:
        await message.answer(text="Привет")
        return
    await message.answer('Ошибка')



