
def bot_init_mess(full_name: str) -> str:
    if full_name == "":
        return ("<b>Начнём!</b>\n\n"
                "🤖 Это бот для бронирования мест и учета посещений офиса на Ордынке "
                "сотрудниками <b>CC-Team.</b>\n\n"
                "Для начала напиши <b>фамилию и имя</b> ⤵︎︎")
    return (f"<b>С возвращением, {full_name}!</b>\n"
            f"Выбери пункт меню ⤵︎")


def finish_start_reg_mess() -> str:
    return (f"<b>Отлично! Теперь тебе доступен весь функционал бота</b>\n"
            "<blockquote expandable><b>Что умеет этот бот?</b>\n"
            "• 📅 Забронировать день — выбрать дату и занять место\n"
            "•⏳ Встать в очередь — если все места уже заняты\n"
            "•⚡ Включить авто-подтверждение — чтобы места бронировались быстрее без лишнего подтверждения\n"
            "•👀 Посмотреть свои брони — увидеть расписание на неделю</blockquote>"
            f"Выбери пункт меню ⤵ ︎")

def bot_menu_mess() -> str:
    return "<b>Выбери пункт меню ⤵</b>"


def start_db_exc_mess() -> str:
    return ("<b>⚠️ Ошибка: Сервис временно не доступен.</b>\n\n"
            "Подождите немного и перезапустите бота /start")

def incorrect_full_name_mess() -> str:
    return ("<blockquote><b>⚠️ Ошибка: Некорректный формат данных</b>\nВведите имя и фамилию корректно\nНапример: Иванов Иван</blockquote>\n\n"
            "Введите <b>фамилию и имя</b> ещё раз ⤵︎︎")

def form_data_mess(full_name: str, profession: str | None, product: str | None) -> str:

    if profession is None:
        data = "Укажите <b>должность</b> ⤵︎"
    elif product is None:
        data = "Укажите <b>команду</b> ⤵︎"
    else:
        data = ""

    return ("<b>Форма регистрации</b>\n"
            "<blockquote>"
            f"• Имя: {full_name}\n"
            f"• Должность: {'...' if profession is None else profession}\n"
            f"• Команда: {'...' if product is None else product}"
            "</blockquote>\n\n"
            f"{data}")