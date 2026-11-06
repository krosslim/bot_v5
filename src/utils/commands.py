from aiogram.types import BotCommand

def get_commands_list() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Перезагрузить бота"),
        BotCommand(command="menu", description="Вернуться в меню бота"),
        # Не нужная фича, также с появлением виджетов, где щас строго до 10 мест, эта фича будет ломать логику
        # BotCommand(command="missed", description="Отметиться за прошедшие дни")
    ]