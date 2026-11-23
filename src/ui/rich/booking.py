"""Rich-календарь бронирования в личке: HTML для sendRichMessage / editMessageText(rich_message=...).
Чистые функции без БД и Telegram.

Эталон вида: «предфинальное 2» из прототипа scripts/rich_booking_probe.py (final_calendar(second=True), day_view).
Календарь: заголовок <h2> «Месяц год», шапка «Пн ... Вс» отдельной компактной таблицей без сетки, даты второй
компактной таблицей с сеткой, каждая дата кнопкой link с одним кастомным эмодзи (цвет числа передаёт состояние),
легенда в <footer>, внизу один ряд кнопок во всю ширину: «Сегодня» и «Настройки» иконками, «←» и «→» листают
месяцы. Inline-клавиатуры под сообщением нет: календарь отправляется и правится без reply_markup.

Экран дня (вариант «С3» из scripts/rich_seat_list_probe.py): дата <h2>, состояние <h6> (тексты build_day_state,
место руководителя считается занятым местом: «Свободно 3 из 11»), каждый стол раскрывающимся блоком <details>:
в заголовке пиктограмма стола и «места есть», внутри таблица имён без рамки (окно слева, коридор справа),
ряд верхних мест, строка стола «← ОКНО  СТОЛ N  КОРИДОР →», ряд нижних мест. Внизу «Назад» и действие.
Номер места на схеме (SEAT_NUMBERS) только для вида, в callback_data уходит seat_no из БД.

Ограничения Rich Messages: цвета текста нет (цвет только у стилей кнопок), <b> и <sub> внутри кнопки в ряду
Telegram выбрасывает, <p> внутри <footer> нельзя (сервер выбросит footer), голый «\\n» в ячейке схлопывается
в пробел, несколько пробелов подряд в один, ширину колонки задать нельзя. Лимит 32768 символов и 500 блоков.
Кастомных эмодзи в сообщении держать меньше MAX_RICH_EMOJI: на пробе первые 92 вхождения показались, а каждый
новый id после них сервер молча заменил подписью (повторы уже встреченных показывались). Экран дня сейчас 50,
календарь около 40.
"""
import html
import random
from datetime import date, timedelta
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from src.ui.keyboard.actions import RichCB, SettingsCB, SettingsStep
from src.ui.rich.emoji import (CHAIR, DAY_EMOJI, DESK_ICON, DESK_ROW, LEGEND, LEGEND_EMOJI, LOOK, ROW_CORRIDOR,
                               ROW_WINDOW, SEAT_BADGE, SETTINGS_ICON, TODAY_ICON, emoji, emoji_strip)
from src.ui.rich.fit import fit_name, text_width
from src.ui.widgets.layout import BOSS_SEAT, OFFICE_LAYOUT, SEAT_NUMBERS, SEATS, LayoutCell
from src.ui.widgets.state import MONTHS_NOM, DaySeats, day_title, short_name
from src.utils.idk import gen_idk

MAX_RICH_CHARS = 32768
MAX_RICH_EMOJI = 90   # с запасом под границу ~92 (см. описание модуля)
WEEK_TITLE = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
UNAVAILABLE = "—"   # чужое или закрытое место: подпись неактивной кнопки, строка в таблице имён
# Листание месяцев в нижнем ряду: только стрелки, без названий месяцев. Недоступный месяц: стрелка остаётся
# на месте неактивной кнопкой, чтобы ряд не прыгал
NAV_BACK, NAV_FORWARD = "←", "→"
NAV_STYLE = "primary"
DATES_TABLE = "compact bordered"   # даты в сетке; шапка отдельной таблицей «compact» без сетки

# Коды дней (day_code): какие открывают экран дня, какие отвечают только тостом
OPEN_CODES = frozenset("fbqn")       # можно занять, пересесть, отменить, встать или выйти из очереди
READONLY_CODES = frozenset("vp")     # закрытый день: только посмотреть, кто был в офисе
NOT_OPEN_TEXT = "Бронь не открыта"   # x
DAY_OFF_TEXT = "Нерабочий день"      # w, h
TODAY_TEXT = "Календарь обновлён"    # тост на «Сегодня»: открыт текущий месяц по свежим данным


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def callback(cmd: str, day: date, target: Optional[int] = None, seat: Optional[LayoutCell] = None) -> str:
    return RichCB(cmd=cmd, day=day.isoformat(), seat=None if seat is None else str(seat), target=target,
                  idk=gen_idk(4)).pack()


def button(label: str, data: Optional[str] = None, style: Optional[str] = None) -> str:
    """label: обычный текст (экранируется) или готовый <tg-emoji> (как CHAIR), он вставляется как есть.
    data None: неактивная кнопка"""
    st = f' style="{style}"' if style else ""
    text = label if label.startswith("<tg-emoji") else esc(label)
    if data is None:
        return f'<tg-button type="disabled"{st}>{text}</tg-button>'
    return f'<tg-button type="callback_data" data="{esc(data)}"{st}>{text}</tg-button>'


def button_row(buttons: Sequence[str], align: Optional[str] = None) -> str:
    al = f' align="{align}"' if align else ""
    return f"<tg-button-row{al}>" + "".join(buttons) + "</tg-button-row>"


def target_line(target_name: Optional[str]) -> List[str]:
    """Бронь админом за сотрудника: та же подпись, что в виджете (render_booking_widget)"""
    if not target_name:
        return []
    return [f"<h5>{esc('Бронь за сотрудника: ' + short_name(target_name, 20))}</h5>"]


# ---------------------------------------------------------------------------#
#  Календарь
# ---------------------------------------------------------------------------#
def day_emoji_id(day_num: int, code: str, is_today: bool) -> str:
    return DAY_EMOJI[(day_num, LOOK[code], is_today)]


def month_title(month: date) -> str:
    return f"{MONTHS_NOM[month.month - 1]} {month.year}"


def month_tables(month: date, codes: str, today: date, target: Optional[int] = None) -> List[str]:
    """codes: код каждого дня месяца по порядку (day_code), длина = число дней в месяце"""
    first = month.replace(day=1)
    cells = ["<td></td>"] * first.weekday()
    for i, code in enumerate(codes):
        d = first + timedelta(days=i)
        eid = day_emoji_id(d.day, code, d == today)
        cells.append(f'<td align="center"><tg-button type="callback_data" data="{esc(callback("day", d, target))}" '
                     f'style="link">{emoji(eid)}</tg-button></td>')
    cells += ["<td></td>"] * (-len(cells) % 7)
    head = "<tr>" + "".join(f'<th align="center"><b>{w}</b></th>' for w in WEEK_TITLE) + "</tr>"
    body = "".join("<tr>" + "".join(cells[i:i + 7]) + "</tr>" for i in range(0, len(cells), 7))
    return [f"<table compact>{head}</table>", f"<table {DATES_TABLE}>{body}</table>"]


def month_legend(codes: str) -> List[str]:
    """«Бронь», «Был(а)», «Очередь», «Мест нет», только для кодов, которые есть в месяце. Нет таких кодов → пусто.
    Несколько пробелов между пунктами сервер схлопывает в один"""
    items = [f"{emoji(LEGEND_EMOJI[k])} {label}" for k, label in LEGEND if k in codes]
    return [f"<footer>{'  '.join(items)}</footer>"] if items else []


def settings_data() -> str:
    """Та же кнопка, что «Настройки» в главном меню: экран настроек встаёт на место календаря"""
    return SettingsCB(step=SettingsStep.INIT_SETTINGS, idk=gen_idk()).pack()


def calendar_bar(today: date, prev_month: Optional[date], next_month: Optional[date],
                 target: Optional[int] = None) -> List[str]:
    """Нижний ряд календаря во всю ширину, всегда четыре кнопки:
    «Сегодня» иконкой: текущий месяц из любого месяца, на текущем перерисовывает его по свежим данным. Месяц берётся
    на сервере в момент нажатия (day в кнопке не используется), поэтому кнопка в календаре, нарисованном месяц назад,
    всё равно ведёт в текущий;
    «Настройки» иконкой: экран настроек на месте календаря;
    «←» и «→» (primary): соседний месяц. Месяц вне диапазона: стрелка неактивна и без стиля, ряд не прыгает.
    target: бронь админом за сотрудника, календарь остаётся его"""
    back = (button(NAV_BACK, callback("month", prev_month, target), NAV_STYLE) if prev_month
            else button(NAV_BACK))
    forward = (button(NAV_FORWARD, callback("month", next_month, target), NAV_STYLE) if next_month
               else button(NAV_FORWARD))
    return [button_row([button(TODAY_ICON, callback("today", today, target)),
                        button(SETTINGS_ICON, settings_data()), back, forward])]


def render_calendar(
        month: date, codes: str, today: date, prev_month: Optional[date], next_month: Optional[date],
        target: Optional[int] = None, target_name: Optional[str] = None,
) -> str:
    """Календарь месяца. prev_month / next_month: первое число соседнего месяца, если он в диапазоне
    (от history_months назад до calendar_last_month), иначе None"""
    out = target_line(target_name if target else None)
    out.append(f"<h2>{month_title(month)}</h2>")
    out += month_tables(month, codes, today, target)
    out += month_legend(codes)
    out += calendar_bar(today, prev_month, next_month, target)
    return "".join(out)


# ---------------------------------------------------------------------------#
#  Экран дня
# ---------------------------------------------------------------------------#
class Person(NamedTuple):
    """Человек на месте: имя «Имя Ф.» в таблице имён (полное по нажатию отдаёт обработчик, команда name)"""
    user_id: int
    full_name: str


# Что на месте (seat_view)
FREE = "free"         # можно занять или пересесть
MINE = "mine"         # своё (при брони за сотрудника его место)
TAKEN = "taken"       # занято другим
BOSS = "boss"         # руководитель (выбран в админке)
CLOSED = "closed"     # место команды, но занять нельзя: сверх лимита дня, закрытый день, руководитель не выбран
FOREIGN = "foreign"   # место другой команды

FREE_TEXT = "Свободно"
NAME_HINT = "Клик на имя, чтобы увидеть фамилию"   # подвал блока стола: имена в таблице это кнопки
pick_open = random.choice   # какой из столов со свободными местами раскрыть (в тестах подменяется)
SUB_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

# Таблица имён. Telegram растягивает таблицу на всю ширину сообщения (~320 pt на iPhone 390 pt) и делит её между
# колонками по ширине содержимого: на скриншоте колонка с короткими именами ~155 pt. Длинное имя укорачивается
# до NAME_ROOM_PT (оценка fit.text_width, на iPhone совпала с замером в пределах 5 %), чтобы два длинных имени
# в одной строке помещались без переноса: «Максимилиан К.» и «Александра А.» целиком.
# Невидимым заполнением колонки не выравниваются: «⠀» на iPhone оказался шире расчёта, колонка с прочерком
# раздувалась, соседняя переносила строку (строки стола «скакали»)
BADGE_LEAD_PT = 23.0   # номер в рамке с пробелом
NAME_ROOM_PT = 112.0   # под «Имя Ф.» после номера


class Seat(NamedTuple):
    cell: LayoutCell
    kind: str
    number: int = 0                   # номер на схеме (SEAT_NUMBERS), 0 у чужого места
    person: Optional[Person] = None   # кто сидит: MINE, TAKEN, BOSS


def seat_view(cell: LayoutCell, day: DaySeats, state: Dict, boss: Optional[Person]) -> Seat:
    """Что на месте. Занятые берутся из DaySeats (полные имена и user_id из БД), своё место и закрытый день из
    состояния build_day_state (m, ro). Свободное: как у виджета, DaySeats.free_seats (лимит дня выбран:
    свободных нет)"""
    number = SEAT_NUMBERS.get(cell, 0)
    if cell == BOSS_SEAT:
        return Seat(cell, BOSS, number, boss) if boss else Seat(cell, CLOSED, number)
    if not isinstance(cell, int) or isinstance(cell, bool):
        return Seat(cell, FOREIGN)
    holder = day.by_seat().get(cell)
    if holder:
        return Seat(cell, MINE if cell == state.get("m") else TAKEN, number, Person(holder.user_id, holder.full_name))
    if not state.get("ro") and cell in day.free_seats(SEATS):
        return Seat(cell, FREE, number)
    return Seat(cell, CLOSED, number)


def counted(seat: Seat) -> bool:
    """Входит ли место в «из Y»: места команды и руководитель, если он выбран"""
    return seat.kind != FOREIGN and not (seat.cell == BOSS_SEAT and seat.kind == CLOSED)


def seat_badge(number: int) -> Tuple[str, float]:
    """(HTML номера в рамке с пробелом после, оценка ширины в pt). Номера без картинки пишутся цифрами"""
    if number in SEAT_BADGE:
        return emoji(SEAT_BADGE[number]) + " ", BADGE_LEAD_PT
    return f"{number} ", text_width(f"{number} ")


def desk_picture(name: str) -> str:
    """Крупный «СТОЛ N» для строки стола (DESK_ROW); стол без картинки текстом"""
    return emoji_strip(DESK_ROW[name]) if name in DESK_ROW else esc(name.upper())


def name_line(seat: Seat, cal_date: date, target: Optional[int] = None) -> str:
    """Строка места в таблице имён. Занятое: номер и «Имя Ф.» одной кнопкой стилем link, нажатие отвечает полным
    именем (команда name, как у кнопки своего места). Ссылкой на профиль не делаем: у части сотрудников профиль
    закрыт настройками приватности, а по «Имя Ф.» не всегда понятно, кто это. Полужирный внутри кнопки сервер
    выбрасывает, поэтому своё имя не выделено: своё место видно по кнопке primary в ряду мест.
    Свободное: номер и «Свободно» курсивом. Закрытое: номер и «—». Чужое: «—»"""
    if seat.kind == FOREIGN:
        return UNAVAILABLE
    badge, _ = seat_badge(seat.number)
    if seat.kind == FREE:
        return f"{badge}<i>{FREE_TEXT}</i>"
    if seat.kind == CLOSED:
        return badge + UNAVAILABLE
    name = esc(fit_name(short_name(seat.person.full_name, 64), NAME_ROOM_PT))
    data = esc(callback("name", cal_date, target, seat.cell))
    return f'<tg-button type="callback_data" data="{data}" style="link">{badge}{name}</tg-button>'


def sides(row: Sequence[Seat]) -> List[Tuple[Optional[Seat], Optional[Seat]]]:
    """Ряд стола → пары (место у окна, место у коридора): левая половина ряда у окна, правая у коридора"""
    half = (len(row) + 1) // 2
    left, right = list(row[:half]), list(row[half:])
    right += [None] * (len(left) - len(right))
    return list(zip(left, right))


def names_table(top: Sequence[Seat], bottom: Sequence[Seat], cal_date: date, target: Optional[int] = None) -> str:
    """Таблица имён без рамки: слева места у окна, справа у коридора, сначала верхние места стола, потом нижние.
    Строки, где оба места чужие, не показываются. Обе колонки по левому краю: начала строк в колонке на одной
    вертикали. По верху: если имя всё же перенесётся, соседнее не съедет вниз"""
    rows = []
    for a, b in sides(top) + sides(bottom):
        if all(s is None or s.kind == FOREIGN for s in (a, b)):
            continue
        cells = [name_line(s, cal_date, target) if s else "" for s in (a, b)]
        rows.append("<tr>" + "".join(f'<td align="left" valign="top">{c}</td>' for c in cells) + "</tr>")
    return f"<table compact>{''.join(rows)}</table>" if rows else ""


def seat_button(seat: Seat, cal_date: date, readonly: bool, target: Optional[int] = None) -> str:
    """Кнопка места: стул и номер нижним индексом (<sub> в кнопке сервер выбрасывает, поэтому юникодные ₀-₉).
    Свободное: success, занять или пересесть. Своё: неактивная primary (активная казалась кнопкой отмены
    брони; отмена отдельной кнопкой внизу, полное имя по имени в таблице). Занятое, руководитель, закрытое:
    неактивные без цвета. Чужое: неактивный «—»"""
    if seat.kind == FOREIGN:
        return button(UNAVAILABLE)
    label = CHAIR + str(seat.number).translate(SUB_DIGITS)
    if seat.kind == FREE:
        return button(label, callback("seat", cal_date, target, seat.cell), "success")
    if seat.kind == MINE:
        return button(label, None, "primary")
    return button(label)


def desk_row(name: str) -> str:
    """Строка стола без рамки: «← ОКНО» у левого края, «СТОЛ N» крупно ровно по центру, «КОРИДОР →» у правого"""
    return (f'<table compact><tr><td align="left" valign="middle">{emoji_strip(ROW_WINDOW)}</td>'
            f'<td align="center" valign="middle">{desk_picture(name)}</td>'
            f'<td align="right" valign="middle">{emoji_strip(ROW_CORRIDOR)}</td></tr></table>')


def desk_summary(name: str, seats: Sequence[Seat], readonly: bool) -> str:
    """Заголовок блока стола: пиктограмма стола (DESK_ICON, цветом текста; без картинки имя стола текстом) и
    «места есть» («место есть», если свободно одно) или «нет мест»; в закрытом дне «занято N из Y»,
    руководитель входит в Y занятым, если выбран"""
    own = [s for s in seats if counted(s)]
    if readonly:
        state = f"занято {sum(1 for s in own if s.kind in (MINE, TAKEN, BOSS))} из {len(own)}"
    else:
        free = sum(1 for s in own if s.kind == FREE)
        state = "место есть" if free == 1 else "места есть" if free else "нет мест"
    if name in DESK_ICON:
        return f"{emoji_strip(DESK_ICON[name])} {state}"
    return f"{esc(name)}: {state}"


def desk_block(name: str, top: Sequence[Seat], bottom: Sequence[Seat], readonly: bool, is_open: bool,
               cal_date: date, target: Optional[int] = None) -> str:
    """Стол раскрывающимся блоком, у каждого стола одинаково: таблица имён, ряд верхних мест, строка стола, ряд
    нижних мест, разделитель и подсказка в подвале (если в таблице есть имена). Какой стол раскрыт, решает desks.
    В <footer> нельзя <p> (сервер выбросит footer), поэтому текст подсказки без обёртки"""
    body = [names_table(top, bottom, cal_date, target),
            button_row([seat_button(s, cal_date, readonly, target) for s in top]),
            desk_row(name),
            button_row([seat_button(s, cal_date, readonly, target) for s in bottom]),
            "<hr/>"]
    if any(s.kind in (MINE, TAKEN, BOSS) for s in (*top, *bottom)):
        body.append(f"<footer>{NAME_HINT}</footer>")
    return (f"<details{' open' if is_open else ''}><summary>{desk_summary(name, [*top, *bottom], readonly)}</summary>"
            f"{''.join(body)}</details>")


def desks(day: DaySeats, state: Dict, boss: Optional[Person], cal_date: date,
          target: Optional[int] = None) -> List[str]:
    """Столы схемы сверху вниз. Помещения (кабинет) не показываются.
    Раскрыт всегда не больше одного стола: со своим местом (в закрытом дне со своим бывшим), даже если на других
    есть свободные; своего места нет: один из столов со свободными местами, случайный (pick_open), чтобы люди
    не садились всегда за первый; свободных нет нигде: всё свёрнуто"""
    readonly = bool(state.get("ro"))
    tables = [(name, [seat_view(c, day, state, boss) for c in top], [seat_view(c, day, state, boss) for c in bottom])
              for top, name, bottom in (item for item in OFFICE_LAYOUT if not isinstance(item, str))]
    mine = [name for name, top, bottom in tables if any(s.kind == MINE for s in (*top, *bottom))]
    free = [name for name, top, bottom in tables if any(s.kind == FREE for s in (*top, *bottom))]
    opened = mine[0] if mine else pick_open(free) if free else None
    return [desk_block(name, top, bottom, readonly, name == opened, cal_date, target) for name, top, bottom in tables]


def day_action(state: Dict, cal_date: date, target: Optional[int] = None) -> Optional[str]:
    """Кнопка действия рядом с «Назад», как в booking.html: отменить бронь, выйти из очереди или встать в очередь
    (мест нет). В закрытом дне действия нет"""
    if state.get("ro"):
        return None
    if state.get("st") == "B":
        return button("Отменить бронь", callback("cancel", cal_date, target), "danger")
    if state.get("st") == "Q":
        return button("Выйти из очереди", callback("leave", cal_date, target), "danger")
    if 0 not in (state.get("s") or []):
        return button("В очередь", callback("queue", cal_date, target), "primary")
    return None


def render_day(cal_date: date, state: Dict, day: DaySeats, boss: Optional[Person], target: Optional[int] = None,
               target_name: Optional[str] = None) -> str:
    """Экран дня. state: build_day_state по тому же day, разобранный из JSON (тексты t и h, своё место m, статус
    st, закрытый день ro). day: брони дня с полными именами и user_id. boss: руководитель на схеме или None.
    «Назад» возвращает календарь месяца этого дня"""
    back = button("Назад", callback("month", cal_date.replace(day=1), target))
    action = day_action(state, cal_date, target)
    out = target_line(target_name if target else None)
    out += [f"<h2>{esc(state.get('t') or day_title(cal_date))}</h2>", f"<h6>{esc(state.get('h') or '')}</h6>",
            *desks(day, state, boss, cal_date, target), button_row([back, action] if action else [back])]
    return "".join(out)
