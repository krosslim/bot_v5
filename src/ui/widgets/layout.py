"""Схема зала. Меняется вместе с кодом, в БД хранится только номер места (bookings.seat_no)."""
from typing import List, Tuple, Union

CABINET_LABEL = "Кабинет Анны А."
BOSS_LABEL = "Дмитрий К."

# Элементы сверху вниз:
#   "подпись"                            — помещение на всю ширину (не бронируется, рисуется штриховкой)
#   [верхний ряд, "подпись", нижний ряд] — стол: столешница и места по обе её стороны.
#                                          Стол рисуется отдельным «островом», между столами — проход
# Места в ряду слева (окно) направо (коридор):
#   "x"    — место другой команды (штриховка, не бронируется)
#   "b"    — место руководителя (неактивная ячейка с BOSS_LABEL)
#   число  — номер места команды
LayoutCell = Union[int, str]
LayoutItem = Union[str, List[Union[List[LayoutCell], str]]]
OFFICE_LAYOUT: List[LayoutItem] = [
    CABINET_LABEL,
    [["x", "x", "x", "x"], "Стол 1", [1, 2, "b", "x"]],
    [[3, 4, 5, 6], "Стол 2", [7, 8, 9, 10]],
]

# Сколько верхних элементов рисуется над подписями «← Окно» / «Коридор →» (окно слева, коридор справа)
LAYOUT_TOP_ROWS = 1


def _team_seats() -> Tuple[int, ...]:
    seats = []
    for item in OFFICE_LAYOUT:
        if isinstance(item, str):
            continue
        top, _, bottom = item
        seats.extend(c for c in (*top, *bottom) if isinstance(c, int) and not isinstance(c, bool))
    return tuple(sorted(seats))


# Номера мест команды по порядку автоподбора. Сейчас мест 10 (1–10).
# Каждая бронь получает первое свободное место (BookingService.pick_seat), в том числе при WIDGETS_ENABLED=false.
# Сколько броней на день, решает лимит office_capacity_weekdays.capacity, а не схема: если лимит больше
# len(SEATS), брони сверх числа мест создаются без номера места (seat_no = NULL).
# Для текстового режима это незаметно. В виджетах держите capacity <= len(SEATS): виджет рассчитан на схему,
# человек без места видит «Бронь есть, но место не выбрано», а в дайджесте-виджете его нет вовсе.
SEATS: Tuple[int, ...] = _team_seats()
