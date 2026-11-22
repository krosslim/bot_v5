"""Оценка ширины текста в ячейке таблицы Rich Message, чтобы укоротить длинное имя. Без зависимостей.

Ширину колонки задать нельзя, Telegram берёт её из содержимого, а слишком длинная строка переносится. Поэтому
длинное «Имя Ф.» укорачивается до расчётной ширины: «Максимил… К.».

Откуда числа. Ширины символов сняты один раз с SF Pro 15 pt (текст ячейки на iPhone) и округлены до 1 pt.
Сверка со скриншотом iPhone: «Александ… А.» по оценке 94 pt, на экране ~89 pt. Шрифтов и Pillow во время
работы бота не нужно. На Android и Desktop шрифты другие, отсюда запас в NAME_ROOM_PT (src/ui/rich/booking.py).
Невидимым заполнением ширину не подгоняем: «⠀» (U+2800) на iPhone шире любой оценки по шрифтам macOS.
"""
from typing import Dict

UNKNOWN_PT = 9.0   # символ не из таблицы (средняя ширина буквы)
WIDE_PT = 15.0     # иероглифы, эмодзи и прочее за пределами алфавитов


def _table(groups: Dict[float, str]) -> Dict[str, float]:
    return {ch: w for w, chars in groups.items() for ch in chars}


# Ширина в pt → символы этой ширины (SF Pro 15 pt Regular / Semibold)
REGULAR = _table({
    3: "ijlI . ", 4: "')", 5: "r(", 6: "гft", 7: "кухьяГksvxyJ1-",
    8: "авеёзийлнпстчэЕЁachnuzEFL2", 9: "борцъБВЗКРУХЬЯbdegopqBKPRSVXY0356789…",
    10: "дмыИЙЛНПСТЧCDHNTUZ4", 11: "жфшюАОЦЪЭwAGOQ", 12: "щДМЫM", 13: "ФШm", 14: "ЮW—", 15: "ЖЩ",
})
BOLD = _table({
    3: "  ", 4: "ijlI.'", 5: "()", 6: "frt", 7: "гs-", 8: "взкухьэяГkvxyzFL1",
    9: "абеёийлнопрстчъЕЁЗРУЬabcehnopuEJPR2357", 10: "цБВКТХЯdgqABDKSTVXYZ04689…",
    11: "дмыАИЙЛНПСЧЪЭwCGHNU", 12: "жфшюДОЦOQ", 13: "щМФЫM", 14: "ЖШmW—", 15: "ЩЮ",
})


def text_width(s: str, bold: bool = False) -> float:
    """Оценка ширины строки в pt (текст ячейки, 15 pt). bold: полужирное <b>"""
    table = BOLD if bold else REGULAR
    return sum(table.get(ch, WIDE_PT if ord(ch) >= 0x2E80 else UNKNOWN_PT) for ch in s)


def fit_name(name: str, room: float, bold: bool = False) -> str:
    """Укоротить «Имя Ф.» до room pt: «Максимил… К.». Без инициала укорачивается всё имя. Короче 2 букв не режет"""
    if text_width(name, bold) <= room:
        return name
    first, sep, initial = name.rpartition(" ")
    if not sep:
        first, initial = name, ""
    tail = f" {initial}" if initial else ""
    while len(first) > 2:
        first = first[:-1]
        cut = f"{first}…{tail}"
        if text_width(cut, bold) <= room:
            return cut
    return f"{first}…{tail}"
