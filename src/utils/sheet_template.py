"""Шаблон листа месяца в Google-таблице посещений. Чистые функции: только запросы Sheets API, без сети.

Раскладка листа — как в прод-таблице, её ждёт Apps Script (doPost пишет A:C и флажки с D, объединяет A1:C1):
    A1:C1         «Обновлено ДД.ММ.ГГГГ ЧЧ:ММ» (объединено)
    A2:A4, B2:B4, C2:C4   «Продукт», «Должность», «ФИО» (каждое объединено по строкам 2–4)
    D2.. строка 2 даты (число-дата в формате «дд.мм»), строка 3 — день недели,
         строка 4 — сколько отметок в день (только рабочие дни)
    A5:C..        сотрудники; D5.. — флажки ИСТИНА/ЛОЖЬ по дням
    после дней    «Факт.» (объединено по строкам 1–4) — сколько дней отмечено у сотрудника; за ним ещё одна колонка
Закреплены 4 строки и 3 колонки. Нерабочие дни (по производственному календарю: выходные, праздники,
но не рабочие субботы) — серые.
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Sequence, Tuple

TEMPLATE_MARKER_KEY = "bot_v5_template"   # developer metadata листа: шаблон создан ботом и готов
TEMPLATE_VERSION = "v2"                   # v2 — раскладка прод-таблицы (Продукт, Должность, ФИО)

PERSON_HEADERS = ["Продукт", "Должность", "ФИО"]   # A, B, C — их заполняет Apps Script (team, position, name)
PERSON_WIDTHS = [140, 166, 240]
FIRST_DATA_COL = 4       # D — первый день месяца (номера колонок и строк с 1, как в A1); в скрипте DAY_COL_FROM
DAY_WIDTH = 40
TOTALS_WIDTH = 46
TAIL_WIDTH = 100
BODY_START_ROW = 5       # первая строка сотрудников
LAST_ROW = 100           # до этой строки формулы и флажки ИСТИНА/ЛОЖЬ
SHEET_ROWS = 300
FONT_FAMILY = "Montserrat"
GRADIENT_MID = 7         # середина градиента в строке 4 (при лимите дня 12 так было в исходном скрипте)

YELLOW = "#FFE4B5"
GRAY_BG = "#808080"
BLACK = "#000000"
GRAY_TEXT = "#888888"
GRADIENT_MIN_COLOR = "#90EE90"
GRADIENT_MID_COLOR = "#00FA9A"
GRADIENT_MAX_COLOR = "#8B0000"

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@dataclass(frozen=True)
class TemplateDay:
    cal_date: date
    is_workday: bool


def col_letter(col: int) -> str:
    """Номер колонки с 1 → буквы A1: 1 → A, 27 → AA"""
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def sheet_a1(title: str, a1: str) -> str:
    return f"'{title.replace(chr(39), chr(39) * 2)}'!{a1}"


def _rgb(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _grid(sheet_id: int, rows: Tuple[int, int], cols: Tuple[int, int]) -> dict:
    """GridRange: индексы с 0, конец не включается"""
    return {"sheetId": sheet_id, "startRowIndex": rows[0], "endRowIndex": rows[1],
            "startColumnIndex": cols[0], "endColumnIndex": cols[1]}


def _pack(indices: List[int]) -> List[Tuple[int, int]]:
    """Подряд идущие индексы → отрезки (начало, конец включительно)"""
    out: List[Tuple[int, int]] = []
    for i in sorted(indices):
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def layout(days: Sequence[TemplateDay]) -> Dict[str, int]:
    last_day_col = FIRST_DATA_COL + len(days) - 1
    totals_col = last_day_col + 1
    return {"last_day_col": last_day_col, "totals_col": totals_col, "cols": totals_col + 1}


def sheet_serial(d: date) -> int:
    """Дата как число таблицы (дни от 30.12.1899): не зависит от локали, в отличие от текста «01.12»"""
    return (d - date(1899, 12, 30)).days


def gradient_limits(capacity: int) -> Tuple[int, int, int]:
    top = max(capacity, 2)
    return 0, min(GRADIENT_MID, top - 1), top


def build_create_requests(sheet_id: int, title: str, days: Sequence[TemplateDay], capacity: int) -> List[dict]:
    """addSheet и всё оформление — одним spreadsheets.batchUpdate: Google выполняет его целиком или никак"""
    if not days:
        raise ValueError("Нет дней месяца — шаблон строить не из чего")
    lay = layout(days)
    cols, totals0 = lay["cols"], lay["totals_col"] - 1
    persons = len(PERSON_HEADERS)
    off_cols = [FIRST_DATA_COL - 1 + i for i, d in enumerate(days) if not d.is_workday]
    work_cols = [FIRST_DATA_COL - 1 + i for i, d in enumerate(days) if d.is_workday]
    lo, mid, hi = gradient_limits(capacity)

    def fmt(grid: dict, cell: dict, fields: str) -> dict:
        return {"repeatCell": {"range": grid, "cell": {"userEnteredFormat": cell}, "fields": fields}}

    requests: List[dict] = [
        {"addSheet": {"properties": {"sheetId": sheet_id, "title": title,
                                     "gridProperties": {"rowCount": SHEET_ROWS, "columnCount": cols}}}},
        {"mergeCells": {"range": _grid(sheet_id, (0, 1), (0, persons)), "mergeType": "MERGE_ALL"}},       # A1:C1
        *({"mergeCells": {"range": _grid(sheet_id, (1, 4), (c, c + 1)), "mergeType": "MERGE_ALL"}}       # A2:A4…C2:C4
          for c in range(persons)),
        {"mergeCells": {"range": _grid(sheet_id, (0, 4), (totals0, totals0 + 1)), "mergeType": "MERGE_ALL"}},
        fmt(_grid(sheet_id, (0, SHEET_ROWS), (0, cols)),
            {"textFormat": {"fontFamily": FONT_FAMILY, "fontSize": 10}}, "userEnteredFormat.textFormat"),
        fmt(_grid(sheet_id, (0, 4), (0, cols)),
            {"backgroundColor": _rgb(YELLOW), "textFormat": {"bold": True},
             "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
            "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold,"
            "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment"),
        fmt(_grid(sheet_id, (1, SHEET_ROWS), (0, persons)),
            {"horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE"},
            "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment"),
        fmt(_grid(sheet_id, (1, 2), (FIRST_DATA_COL - 1, lay["last_day_col"])),
            {"numberFormat": {"type": "DATE", "pattern": "dd.mm"}}, "userEnteredFormat.numberFormat"),
    ]
    for start, end in _pack(off_cols):
        requests.append(fmt(_grid(sheet_id, (0, 4), (start, end + 1)),
                            {"backgroundColor": _rgb(GRAY_BG), "textFormat": {"foregroundColor": _rgb(BLACK)}},
                            "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.foregroundColor"))
        requests.append(fmt(_grid(sheet_id, (4, SHEET_ROWS), (start, end + 1)),
                            {"textFormat": {"foregroundColor": _rgb(GRAY_TEXT)}},
                            "userEnteredFormat.textFormat.foregroundColor"))
    requests.append({"setDataValidation": {
        "range": _grid(sheet_id, (BODY_START_ROW - 1, LAST_ROW), (FIRST_DATA_COL - 1, lay["last_day_col"])),
        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True},
    }})
    if work_cols:
        requests.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [_grid(sheet_id, (3, 4), (c, c + 1)) for c in work_cols],
            "gradientRule": {
                "minpoint": {"color": _rgb(GRADIENT_MIN_COLOR), "type": "NUMBER", "value": str(lo)},
                "midpoint": {"color": _rgb(GRADIENT_MID_COLOR), "type": "NUMBER", "value": str(mid)},
                "maxpoint": {"color": _rgb(GRADIENT_MAX_COLOR), "type": "NUMBER", "value": str(hi)},
            },
        }}})
    requests += [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 4, "frozenColumnCount": persons}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
    ]
    widths = [(c, c + 1, w) for c, w in enumerate(PERSON_WIDTHS)] + [
        (FIRST_DATA_COL - 1, lay["last_day_col"], DAY_WIDTH),
        (totals0, totals0 + 1, TOTALS_WIDTH),
        (totals0 + 1, cols, TAIL_WIDTH),
    ]
    requests += [{"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": start, "endIndex": end},
        "properties": {"pixelSize": width}, "fields": "pixelSize"}} for start, end, width in widths]
    return requests


def build_values(title: str, days: Sequence[TemplateDay], stamp: str) -> List[dict]:
    """Тексты и формулы — values.batchUpdate с USER_ENTERED: формулы на русском (СЧЁТЕСЛИ, «;»),
    их разбирает локаль таблицы так же, как при вводе руками"""
    lay = layout(days)
    first, last = col_letter(FIRST_DATA_COL), col_letter(lay["last_day_col"])
    totals = col_letter(lay["totals_col"])
    row4 = [f"=СЧЁТЕСЛИ({col_letter(FIRST_DATA_COL + i)}{BODY_START_ROW}:{col_letter(FIRST_DATA_COL + i)}"
            f"{LAST_ROW}; ИСТИНА())" if d.is_workday else "" for i, d in enumerate(days)]
    return [
        {"range": sheet_a1(title, "A1"), "values": [[f"Обновлено {stamp}"]]},
        {"range": sheet_a1(title, f"A2:{col_letter(len(PERSON_HEADERS))}2"), "values": [PERSON_HEADERS]},
        {"range": sheet_a1(title, f"{first}2:{last}2"), "values": [[sheet_serial(d.cal_date) for d in days]]},
        {"range": sheet_a1(title, f"{first}3:{last}3"), "values": [[WEEKDAYS[d.cal_date.weekday()] for d in days]]},
        {"range": sheet_a1(title, f"{first}4:{last}4"), "values": [row4]},
        {"range": sheet_a1(title, f"{totals}1"), "values": [["Факт."]]},
        {"range": sheet_a1(title, f"{totals}{BODY_START_ROW}:{totals}{LAST_ROW}"),
         "values": [[f"=СЧЁТЕСЛИ({first}{r}:{last}{r}; ИСТИНА())"] for r in range(BODY_START_ROW, LAST_ROW + 1)]},
    ]


def marker_request(sheet_id: int) -> dict:
    """Ставится последним: лист без метки бот считает недоделанным или созданным не им"""
    return {"createDeveloperMetadata": {"developerMetadata": {
        "metadataKey": TEMPLATE_MARKER_KEY, "metadataValue": TEMPLATE_VERSION,
        "location": {"sheetId": sheet_id}, "visibility": "DOCUMENT",
    }}}


def header_range(title: str, days: Sequence[TemplateDay]) -> str:
    """Строки 2–4 над днями месяца: даты, дни недели, формулы"""
    return sheet_a1(title, f"{col_letter(FIRST_DATA_COL)}2:{col_letter(layout(days)['last_day_col'])}4")


def head_range(title: str, days: Sequence[TemplateDay]) -> str:
    """Вся шапка, строки 1–4 до «Факт.» включительно"""
    return sheet_a1(title, f"A1:{col_letter(layout(days)['totals_col'])}4")


def body_range(title: str, days: Sequence[TemplateDay]) -> str:
    """Продукт, должность, ФИО и отметки сотрудников"""
    return sheet_a1(title, f"A{BODY_START_ROW}:{col_letter(layout(days)['last_day_col'])}{LAST_ROW}")


def _row(rows: Sequence[Sequence[str]], i: int, width: int) -> List[str]:
    row = list(rows[i]) if i < len(rows) else []
    return [str(v) for v in row] + [""] * (width - len(row))


_DAY_MONTH = re.compile(r"(\d{1,2})[.,/](\d{1,2})")


def header_matches(days: Sequence[TemplateDay], header: Sequence[Sequence[str]]) -> bool:
    """Строка 2 — даты этого месяца (лист создан, например, старым скриптом). «06.11» таблица может превратить
    в дату и показать как «06.11.2026», поэтому сравниваем пару (день, месяц), а не строку"""
    for d, cell in zip(days, _row(header, 0, len(days))):
        m = _DAY_MONTH.search(cell)
        if not m or (int(m.group(1)), int(m.group(2))) != (d.cal_date.day, d.cal_date.month):
            return False
    return bool(days)


def stale_days(days: Sequence[TemplateDay], header_formulas: Sequence[Sequence[str]]) -> List[date]:
    """Дни, где лист расходится с календарём: формула в строке 4 есть только у рабочих дней"""
    row4 = _row(header_formulas, 2, len(days))
    return [d.cal_date for d, v in zip(days, row4) if d.is_workday != v.strip().startswith("=")]


def is_blank(values: Sequence[Sequence[str]]) -> bool:
    """Ни одного значения — например, шапка листа, создание которого оборвалось до записи значений"""
    return not any(str(v).strip() for row in values for v in row)


def has_body_data(body: Sequence[Sequence[str]]) -> bool:
    """Есть ли в листе ФИО или отметки. FALSE у пустого флажка данными не считается"""
    return any(str(v).strip() not in ("", "FALSE", "ЛОЖЬ") for row in body for v in row)
