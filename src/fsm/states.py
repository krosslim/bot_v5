from aiogram.fsm.state import StatesGroup, State


class CreateUserState(StatesGroup):
    full_name = State()
    profession = State()
    product = State()
    birthday = State()
    confirmation = State()

class UpdateProfileState(StatesGroup):
    birthday = State()
