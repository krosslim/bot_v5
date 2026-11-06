"""Сборка HTML виджетов из шаблонов. HTML нельзя изменить после отправки, поэтому всё постоянное вшивается здесь."""
import json
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config import settings
from src.ui.widgets.layout import BOSS_LABEL, LAYOUT_TOP_ROWS, OFFICE_LAYOUT
from src.ui.widgets.state import short_name

MAX_HTML_BYTES = 32768   # лимит Telegram на исходный HTML
MAX_ZLIB_BYTES = 4096    # лимит Telegram на HTML после zlib -9

_DIR = Path(__file__).parent


class WidgetTooLarge(ValueError):
    pass


def _js(value: Any) -> str:
    # JSON — валидный литерал JS. "</" экранируем, чтобы строка не закрыла <script>
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


@lru_cache(maxsize=None)
def _template(name: str) -> str:
    return (_DIR / f"{name}.html").read_text(encoding="utf-8")


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
def render_booking_widget(target_user_id: Optional[int] = None, target_name: Optional[str] = None) -> str:
    """Личный виджет. target_* — бронь админом за сотрудника: виджет добавит @user_id к каждому запросу."""
    return _checked(_fill(_template("booking"), {
        "LAYOUT": OFFICE_LAYOUT,
        "TOP": LAYOUT_TOP_ROWS,
        "BOSS": BOSS_LABEL,
        "USER": str(target_user_id) if target_user_id else "",
        # Короткое имя: длина HTML не зависит от длины ФИО, иначе длинное имя упрётся в лимит 4 КБ
        "AS": f"Бронь за сотрудника: {short_name(target_name or '', 20)}" if target_user_id else "",
    }))


@lru_cache(maxsize=1)
def render_digest_widget() -> str:
    return _checked(_fill(_template("digest"), {
        "LAYOUT": OFFICE_LAYOUT,
        "TOP": LAYOUT_TOP_ROWS,
        "BOSS": BOSS_LABEL,
        "BOT": settings.BOT_USERNAME,
    }))
