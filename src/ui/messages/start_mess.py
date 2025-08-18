
def bot_init_mess(full_name: str) -> str:
    if full_name == "":
        return ("<b>Начнём!</b>\n\n"
                "🤖 Это бот для бронирования мест и учета посещений офиса на Ордынке "
                "сотрудниками <b>CC-Team.</b>\n\n"
                "Для начала напиши <b>фамилию и имя</b> ⤵︎︎")
    return (f"<b>С возвращением, {full_name}!</b>\n\n"
            f"Выбери пункт меню ⤵︎")


def finish_start_reg_mess() -> str:
    return (f"<b>Отлично! Теперь тебе доступен весь функционал бота</b>\n\n"
            f"Выбери пункт меню ⤵ ︎")

def bot_menu_mess() -> str:
    return "<b>Выбери пункт меню ⤵</b>"


def start_db_exc_mess() -> str:
    return ("<b>⚠️ Ошибка: Сервис временно не доступен.</b>\n\n"
            "Подождите немного и перезапустите бота /start")