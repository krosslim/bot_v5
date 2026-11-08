"""Сборка HTML виджетов из шаблонов. HTML нельзя изменить после отправки, поэтому всё постоянное вшивается здесь."""
import json
import re
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from src.ui.widgets.layout import LAYOUT_TOP_ROWS, OFFICE_LAYOUT, LayoutCell, LayoutItem
from src.ui.widgets.state import short_name

MAX_HTML_BYTES = 32768   # лимит Telegram на исходный HTML
MAX_ZLIB_BYTES = 4096    # лимит Telegram на HTML после zlib -9

_DIR = Path(__file__).parent


class WidgetTooLarge(ValueError):
    pass


def _js(value: Any) -> str:
    # JSON — валидный литерал JS. "</" экранируем, чтобы строка не закрыла <script>
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _merge_foreign(row: List[LayoutCell]) -> List[LayoutCell]:
    """Подряд идущие места другой команды → одна полоса: ["x", "x", 1] → ["x2", 1]"""
    out: List[LayoutCell] = []
    for c in row:
        if c == "x" and out and isinstance(out[-1], str) and out[-1].startswith("x"):
            out[-1] = f"x{int(out[-1][1:]) + 1}"
        else:
            out.append("x1" if c == "x" else c)
    return out


def widget_layout() -> List[LayoutItem]:
    """Схема для виджетов: столы с местами другой команды, склеенными в полосы (виджет рисует их одной ячейкой)"""
    return [item if isinstance(item, str) else [_merge_foreign(item[0]), item[1], _merge_foreign(item[2])]
            for item in OFFICE_LAYOUT]


@lru_cache(maxsize=None)
def _template(name: str) -> str:
    """Шаблон без переносов строк в <style> и <script>: смысла они не несут, а в лимите 4 КБ — байты.
    В скриптах каждая строка заканчивается на ; { } , или + и ни одна не начинается с ( [ / + - ` —
    склейка не меняет разбор (тест test_templates_join_safely). Цвета темы (--tg-theme-*) без запасных значений:
    рендерер Telegram задаёт палитру всегда, его собственные UA-стили тоже берут её без запасных"""
    html = (_DIR / f"{name}.html").read_text(encoding="utf-8")
    for tag in ("style", "script"):
        html = re.sub(rf"<{tag}>(.*?)</{tag}>", lambda m: f"<{tag}>" + re.sub(r"\n\s*", "", m.group(1)) + f"</{tag}>",
                      html, count=1, flags=re.S)
    return html


def _fill(template: str, values: Dict[str, Any]) -> str:
    for key, value in values.items():
        template = template.replace(f"__{key}__", _js(value))
    return template


def widget_size(html: str) -> Tuple[int, int]:
    raw = html.encode("utf-8")
    return len(raw), len(zlib.compress(raw, 9))


def _checked(html: str) -> str:
    raw, packed = widget_size(html)
    if raw > MAX_HTML_BYTES or packed > MAX_ZLIB_BYTES:
        raise WidgetTooLarge(f"HTML виджета {raw} Б, после zlib {packed} Б (лимиты {MAX_HTML_BYTES} / {MAX_ZLIB_BYTES})")
    return html


@lru_cache(maxsize=64)
def render_booking_widget(
        target_user_id: Optional[int] = None, target_name: Optional[str] = None, boss: str = "",
) -> str:
    """Личный виджет. target_* — бронь админом за сотрудника: виджет добавит @user_id к каждому запросу.
    boss — короткое имя руководителя на схеме (WidgetUseCase.boss_label), пустое — место со штриховкой."""
    return _checked(_fill(_template("booking"), {
        "LAYOUT": widget_layout(),
        "TOP": LAYOUT_TOP_ROWS,
        "BOSS": boss,
        "USER": str(target_user_id) if target_user_id else "",
        # Короткое имя: длина HTML не зависит от длины ФИО, иначе длинное имя упрётся в лимит 4 КБ
        "AS": f"Бронь за сотрудника: {short_name(target_name or '', 20)}" if target_user_id else "",
    }))


@lru_cache(maxsize=4)
def render_digest_widget(boss: str = "") -> str:
    """Дайджест в группе. Отправлять с allow_queries=True: без него у виджета нет TelegramWidget.viewer.
    Дедлайн подтверждения для таймера приходит в chat_data (поле e), а не в HTML: он свой у каждой даты"""
    return _checked(_fill(_template("digest"), {
        "LAYOUT": widget_layout(),
        "TOP": LAYOUT_TOP_ROWS,
        "BOSS": boss,
        "BOT": settings.BOT_USERNAME,
    }))
