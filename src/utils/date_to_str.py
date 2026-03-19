from datetime import date

months = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

def format_date_ru(d: date) -> str:
    return f"{d.day} {months[d.month - 1]}"
