import re
from datetime import timedelta, date
from enum import auto
from typing import Tuple, Optional

from strenum import StrEnum

from config import settings
from src.utils.today import effective_today


class ActionType(StrEnum):
    """Типы действий"""
    CANCEL = auto()
    CANCEL_RANGE = auto()
    CHANGE = auto()


class InlineInputError(Exception):
    """Исключение для ошибок валидации"""
    pass


# ------------------------
# Константы и утилиты
# ------------------------

WEEK_LIMIT = settings.PAGINATION_LIMIT_WEEKS
WORKDAYS = {0, 1, 2, 3, 4}  # пн–пт


def _normalize(s: str) -> str:
    """Нормализует ввод: заменяет «красивые» дефисы, соединяет пробелы, убирает пробелы вокруг дефиса."""
    s = s.strip()
    for d in {'–', '—', '−'}:
        s = s.replace(d, '-')
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*-\s*', '-', s)
    return s


def _rules_text(current_date: date) -> str:
    a, b = _date_example_str(current_date)
    return (
        f"Пример: {a} или {a}-{b} (неск. дней)\n"
        # f"Обмен: {a} {b} (моя → желаемая)"
    )


def _split_two_dates(text: str, sep: str, err: str) -> Tuple[str, str]:
    """Разделяет строку на две части по ровно одному разделителю."""
    if text.count(sep) != 1:
        raise InlineInputError(err)
    left, right = text.split(sep)
    if not left or not right:
        raise InlineInputError(err)
    return left, right


def _ensure_within_weeks(
    d: date, current_date: date, *, label: str = "Дата", future_only: bool = False
) -> None:
    """
    Проверяет, что дата не в прошлом (или строго в будущем) и в пределах WEEK_LIMIT недель от current_date.
    Future only = True — требовать строгое будущее (используется для желаемой даты в обмене).
    """
    if future_only:
        if d <= current_date:
            raise InlineInputError(f"{label} должна быть строго в будущем")
    else:
        if d < current_date:
            raise InlineInputError(f"{label} не может быть в прошлом")

    max_date = current_date + timedelta(weeks=WEEK_LIMIT)
    if d > max_date:
        raise InlineInputError(f"{label} должна быть в пределах {WEEK_LIMIT} недель от текущей даты")


def _same_week(d1: date, d2: date) -> bool:
    """Проверяет, что даты в одной календарной неделе (пн–вс)."""
    monday1 = d1 - timedelta(days=d1.weekday())
    monday2 = d2 - timedelta(days=d2.weekday())
    return monday1 == monday2


def _validate_change_week_and_workdays(d1: date, d2: date) -> None:
    """Обмен возможен только в одну неделю и только в рабочие дни."""
    if not _same_week(d1, d2):
        raise InlineInputError("Обмен возможен только в рамках одной календарной недели (пн–пт)")
    if d1.weekday() not in WORKDAYS or d2.weekday() not in WORKDAYS:
        raise InlineInputError("Дни обмена должны быть рабочими")


# ------------------------
# Основной validator
# ------------------------

def validate_and_parse_dates(
        user_input: str,
        current_date: Optional[date] = None
) -> Tuple[ActionType, Tuple[date, date], str]:
    """
    Validate ввод пользователя и возвращает тип действия и список дат.

    Args:
        user_input: "13.10", "13.10-17.10", "13.10 15.10"
        current_date: Текущая дата (по умолчанию - сегодня)

    Returns:
        (ActionType, [date,...])

    Raises:
        InlineInputError
    """
    if current_date is None:
        current_date = effective_today()

    user_input = _normalize(user_input)

    # Проверка на пустой ввод после нормализации
    if not user_input:
        raise InlineInputError(_rules_text(current_date))

    # Диспетчеризация по форме после нормализации
    # if ' ' in user_input and '-' not in user_input:
    #     # Обмен: две даты через пробел
    #     action, dates = _validate_change(user_input, current_date)
    #     return action, dates, user_input
    if '-' in user_input and ' ' not in user_input:
        # Отмена диапазона: две даты через дефис
        action, dates = _validate_cancel_range(user_input, current_date)
        return action, dates, user_input
    if '.' in user_input and ' ' not in user_input and '-' not in user_input:
            # Отмена одиночной даты
            action, dates = _validate_cancel(user_input, current_date)
            return action, dates, user_input

    # Иное — показываем правила
    raise InlineInputError(_rules_text(current_date))

# ------------------------
# Частные Validators
# ------------------------

def _validate_cancel(user_input: str, current_date: date) -> Tuple[ActionType, Tuple[date, date]]:
    """Отмена одиночной даты"""
    parsed_date = _parse_date(user_input, current_date)
    _ensure_within_weeks(parsed_date, current_date, label="Дата", future_only=False)
    return ActionType.CANCEL, (parsed_date, parsed_date)

def _validate_cancel_range(user_input: str, current_date: date) -> Tuple[ActionType, Tuple[date, date]]:
    """Отмена диапазона дат"""
    a, b = _date_example_str(current_date)
    left, right = _split_two_dates(
        user_input, '-', f"Диапазон: используйте ровно один дефис (например, {a}-{b})"
    )
    start_date = _parse_date(left, current_date)
    end_date = _parse_date(right, current_date)

    if start_date >= end_date:
        raise InlineInputError("Начальная дата должна быть раньше конечной даты отмены")

    _ensure_within_weeks(start_date, current_date, label="Начальная дата", future_only=False)
    _ensure_within_weeks(end_date, current_date, label="Конечная дата", future_only=False)

    return ActionType.CANCEL_RANGE, (start_date, end_date)

def _validate_change(user_input: str, current_date: date) -> Tuple[ActionType, Tuple[date, date]]:
    """Обмен дат"""
    a, b = _date_example_str(current_date)
    left, right = _split_two_dates(
        user_input, ' ', f"Обмен: две даты через один пробел (например, {a} {b})"
    )
    current_user_date = _parse_date(left, current_date)
    desired_date = _parse_date(right, current_date)

    if current_user_date == desired_date:
        raise InlineInputError("Текущая и желаемая даты не должны совпадать")

    # Ограничения по времени: текущая может быть сегодня/в будущем, желаемая — строго в будущем
    _ensure_within_weeks(current_user_date, current_date, label="Текущая дата", future_only=False)
    _ensure_within_weeks(desired_date, current_date, label="Желаемая дата", future_only=True)

    # Только рабочие дни и в рамках одной недели
    _validate_change_week_and_workdays(current_user_date, desired_date)

    return ActionType.CHANGE, (current_user_date, desired_date)

# ------------------------
# Парсинг даты
# ------------------------

def _parse_date(date_str: str, current_date: date) -> date:
    """
    Парсит дату в формате DD.MM и возвращает объект date.
    Выбор года: если месяц меньше текущего — используем следующий год (прошлое запрещено).
    """
    date_str = date_str.strip()

    if not date_str:
        raise InlineInputError("Дата не может быть пустой")

    if '.' not in date_str:
        a, _ = _date_example_str(current_date)
        raise InlineInputError(f"Дата должна содержать точку (например, {a})")

    parts = date_str.split('.')
    if len(parts) != 2:
        a, _ = _date_example_str(current_date)
        raise InlineInputError(f"Дата должна быть в формате DD.MM (например, {a})")

    day_str, month_str = parts

    if not day_str.isdigit() or not month_str.isdigit():
        raise InlineInputError("День и месяц должны быть числами")

    if len(day_str) != 2 or len(month_str) != 2:
        a, _ = _date_example_str(current_date)
        raise InlineInputError(f"День и месяц должны быть двузначными числами (например, {a})")

    day = int(day_str)
    month = int(month_str)

    if month < 1 or month > 12:
        raise InlineInputError("Месяц должен быть от 01 до 12")
    if day < 1 or day > 31:
        raise InlineInputError("День должен быть от 01 до 31")

    # Определяем год: месяцы «в прошлом» переносятся на следующий год
    year = current_date.year
    if month < current_date.month:
        year += 1

    try:
        parsed_date = date(year, month, day)
    except ValueError as ex:
        raise InlineInputError(f"Некорректная дата: {date_str}. {str(ex)}")

    return parsed_date

# ------------------------
# Вспомогательные функции для примеров/сообщений
# ------------------------

def _date_example_str(today: date) -> Tuple[str, str]:
    next_date = today + timedelta(days=1)
    next_date_str = next_date.strftime("%d.%m")
    current_date_str = today.strftime("%d.%m")
    return current_date_str, next_date_str


# if __name__ == "__main__":
#     test_cases = [
#         "13.10",  # Отмена
#         "17.10",
#         "31.10",
#         "31.11",
#         "31.12",
#
#         "13.10-17.10",  # Отмена диапазона
#         "17.10-20.10",
#         "17.10-30.11",
#         "17.10-18.10",
#
#         "13.10 15.10",  # Обмен
#         "20.10 21.10",
#         "18.10 19.10",
#         "18.10 20.10",
#
#         "32.10",  # Несуществующий день
#         "13.13",  # Несуществующий месяц
#         "13.10-12.10",  # Начало позже конца
#         "13.10 13.10",  # Одинаковые даты для обмена
#         "1.10",  # Неправильный формат (не двузначный)
#         "13-10",  # Неправильный разделитель
#         "",  # Пустой ввод
#         "Hello 12.10",
#         "  13.10  ",
#         "       18.10",
#         "17.10--18.10",
#         "17.10  18.10",
#         "17 . 10",
#         "17.10—18.10",
#         "Hi",
#
#         # Пограничные сценарии конца года (проверяйте на 30.12)
#         "30.12-01.01",
#         "01.01-02.01",
#     ]
#     print(f"Текущая дата: {effective_today()}\n")
#
#     for test_input in test_cases:
#         try:
#             action, dates = validate_and_parse_dates(test_input)
#             print(f"✓ Ввод: '{test_input}'")
#             print(f"  Действие: {action.value}")
#             print(f"  Даты: {dates}")
#             print()
#         except InlineInputError as e:
#             print(f"✗ Ввод: '{test_input}'")
#             print(f"  Ошибка: {e}")
#             print()