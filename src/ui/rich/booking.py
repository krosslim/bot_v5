"""Rich-календарь бронирования в личке: HTML для sendRichMessage / editMessageText(rich_message=...).
Чистые функции без БД и Telegram.

Эталон вида: «предфинальное 2» из прототипа scripts/rich_booking_probe.py (final_calendar(second=True), day_view).
Календарь: заголовок <h2> «Месяц год», шапка «Пн ... Вс» отдельной компактной таблицей без сетки, даты второй
компактной таблицей с сеткой, каждая дата кнопкой link с одним кастомным эмодзи (цвет числа передаёт состояние),
легенда в <footer>, внизу один ряд кнопок во всю ширину: «Сегодня» и «Настройки» иконками, «←» и «→» листают
месяцы. Inline-клавиатуры под сообщением нет: календарь отправляется и правится без reply_markup.
Экран дня: дата <h2>, состояние <h5> (тексты build_day_state), схема мест рядами кнопок, <hr/>, «Назад» и действие.

Ограничения Rich Messages: цвета текста нет (цвет только у стилей кнопок), <b> внутри кнопки в ряду Telegram
выбрасывает, <p> внутри <footer> нельзя (сервер выбросит footer). Лимит 32768 символов и 500 блоков.
"""
import html
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from src.ui.keyboard.actions import RichCB, SettingsCB, SettingsStep
from src.ui.rich.emoji import (CHAIR, DAY_EMOJI, DESK_EMOJI, LEGEND, LEGEND_EMOJI, LOOK, SETTINGS_ICON, SIDE_CORRIDOR,
                               SIDE_WINDOW, TODAY_ICON, emoji, emoji_strip)
from src.ui.widgets.layout import BOSS_SEAT, LAYOUT_TOP_ROWS, OFFICE_LAYOUT, LayoutCell
from src.ui.widgets.state import MONTHS_NOM, UNAVAILABLE_SEAT, day_title, short_name
from src.utils.idk import gen_idk

MAX_RICH_CHARS = 32768
WEEK_TITLE = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
UNAVAILABLE = "—"   # подпись неактивной кнопки недоступного места (в виджете штриховка)
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
def table_label(name: str) -> str:
    """Подпись стола по центру строки (центр даёт ячейка компактной таблицы: заголовки, <p> и <footer> align
    не принимают). Картинка из эмодзи DESK_EMOJI; для стола без картинки текст в рамке"""
    if name in DESK_EMOJI:
        return f'<table compact><tr><td align="center">{emoji_strip(DESK_EMOJI[name])}</td></tr></table>'
    return f'<table compact bordered><tr><td align="center">{esc(name)}</td></tr></table>'


# Стороны зала: «◀ОКНО» прижато влево, «КОРИДОР▶» вправо
SIDES = (f'<table compact><tr><td align="left">{emoji_strip(SIDE_WINDOW)}</td>'
         f'<td align="right">{emoji_strip(SIDE_CORRIDOR)}</td></tr></table>')


def seat_label(cell: LayoutCell, state: Dict, cal_date: date, boss: Optional[str],
               target: Optional[int] = None) -> Tuple[str, Optional[str], Optional[str]]:
    """(подпись, callback_data, стиль) места, как cell() в booking.html; callback_data None у неактивной.
    state: состояние дня из build_day_state (s: по элементу на место, 0 свободно, "u" сверх лимита дня,
    иначе короткое имя; m: моё место; ro: только просмотр).
    Свободное: стул CHAIR (занять или пересесть), success. Занятое и руководитель: короткое имя стилем link,
    нажатие отвечает полным именем. Своё место: своё имя, primary. Недоступное (другая команда, сверх лимита,
    свободное место закрытого дня, руководитель не выбран): неактивная кнопка «—»"""
    if cell == BOSS_SEAT:
        return (boss, callback("name", cal_date, target, BOSS_SEAT), "link") if boss else (UNAVAILABLE, None, None)
    if not isinstance(cell, int) or isinstance(cell, bool):
        return UNAVAILABLE, None, None
    seats = state.get("s") or []
    value = seats[cell - 1] if 0 < cell <= len(seats) else UNAVAILABLE_SEAT
    if value == 0:
        if state.get("ro"):
            return UNAVAILABLE, None, None
        return CHAIR, callback("seat", cal_date, target, cell), "success"
    if not isinstance(value, str) or value == UNAVAILABLE_SEAT:
        return UNAVAILABLE, None, None
    return value, callback("name", cal_date, target, cell), "primary" if cell == state.get("m") else "link"


def seats_rows(state: Dict, cal_date: date, boss: Optional[str], target: Optional[int] = None) -> List[str]:
    """Столы рядами кнопок, подпись стола между рядами, стороны зала после первого стола. Помещения (кабинет)
    не показываются. Под нижним рядом последнего стола разделитель"""
    out = []
    for i, item in enumerate(OFFICE_LAYOUT):
        if isinstance(item, str):
            continue
        top, name, bottom = item
        out += [button_row([button(*seat_label(c, state, cal_date, boss, target)) for c in top]), table_label(name),
                button_row([button(*seat_label(c, state, cal_date, boss, target)) for c in bottom])]
        if i == LAYOUT_TOP_ROWS:
            out.append(SIDES)
    return out + ["<hr/>"]


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


def render_day(cal_date: date, state: Dict, boss: Optional[str], target: Optional[int] = None,
               target_name: Optional[str] = None) -> str:
    """Экран дня. state: build_day_state, разобранный из JSON (тексты t и h берутся оттуда).
    boss: короткое имя руководителя на схеме или None. «Назад» возвращает календарь месяца этого дня"""
    back = button("Назад", callback("month", cal_date.replace(day=1), target))
    action = day_action(state, cal_date, target)
    out = target_line(target_name if target else None)
    out += [f"<h2>{esc(state.get('t') or day_title(cal_date))}</h2>", f"<h5>{esc(state.get('h') or '')}</h5>",
            *seats_rows(state, cal_date, boss, target), button_row([back, action] if action else [back])]
    return "".join(out)
