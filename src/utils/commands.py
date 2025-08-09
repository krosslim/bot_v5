from aiogram.types import BotCommand

def get_commands_list() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Перезагрузить бота"),
        BotCommand(command="menu", description="Вернуться в меню бота")
    ]