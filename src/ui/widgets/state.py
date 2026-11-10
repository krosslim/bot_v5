"""Состояние виджетов: chat_data и ответы на запросы. Чистые функции без БД и Telegram.

Тексты здесь, а не в HTML: так HTML укладывается в 4 КБ, а формулировки можно менять без новых сообщений.
"""
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

MAX_DATA_BYTES = 1024  # лимит Telegram на chat_data и на ответ виджету

MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

EXPIRED_TEXT = "Это окно закрыто"   # окно заменено новым или закрыто «Выйти», а удалить его Telegram не дал
UNAVAILABLE_SEAT = "u"   # место сверх лимита дня (в т.ч. занято бронью без seat_no): штриховка, без нажатия
DIGEST_UNAVAILABLE = UNAVAILABLE_SEAT


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def data_size(s: str) -> int:
    return len(s.encode("utf-8"))


def short_name(full_name: str, limit: int = 14) -> str:
    """В боте имя хранится как «Фамилия Имя» → «Имя Ф.»"""
    parts = (full_name or "").split()
    if len(parts) >= 2:
        name = f"{parts[1]} {parts[0][0]}."
    else:
        name = (full_name or "—").strip()
    return name if len(name) <= limit else name[:limit - 1] + "…"


def people(n: int) -> str:
    """1 человек, 2 человека, 5 человек, 22 человека"""
    return f"{n} человека" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else f"{n} человек"


def was_people(n: int) -> str:
    """Был 1 человек, Было 2 человека, Было 5 человек"""
    if n == 0:
        return "Никого не было"
    return ("Был " if n % 10 == 1 and n % 100 != 11 else "Было ") + people(n)


def day_title(d: date) -> str:
    return f"{WEEKDAYS_SHORT[d.weekday()].capitalize()}, {d.day} {MONTHS_GEN[d.month - 1]}"


def day_short(d: date) -> str:
    return f"{WEEKDAYS_SHORT[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


# ---------------------------------------------------------------------------#
#  Календарь личного виджета
# ---------------------------------------------------------------------------#
@dataclass(frozen=True)
class CalendarDay:
    cal_date: date
    is_weekend: bool
    is_holiday: bool
    is_workday: bool
    visit_count: int
    capacity: int
    my_status: Optional[str] = None  # BOOKED / WAITLISTED / None


def day_code(day: CalendarDay, first_bookable: date, horizon: date) -> str:
    """w выходной, h праздник, x ещё не открыт или нет данных, b моя бронь, q очередь, f есть места, n мест нет.
    Закрытые дни (прошлые и сегодня после WORK_END_HOUR): v у меня была бронь, p брони не было — открываются для просмотра"""
    if not day.is_workday:
        return "h" if day.is_holiday and not day.is_weekend else "w"
    if day.cal_date < first_bookable:
        return "v" if day.my_status == "BOOKED" else "p"
    if day.cal_date > horizon:
        return "x"
    if day.my_status == "BOOKED":
        return "b"
    if day.my_status == "WAITLISTED":
        return "q"
    return "f" if day.visit_count < day.capacity else "n"


def shift_month(d: date, months: int) -> date:
    """Первое число месяца, отстоящего от d на months (отрицательное — назад)"""
    n = d.year * 12 + d.month - 1 + months
    return date(n // 12, n % 12 + 1, 1)


def _month_starts(start: date, end: date) -> List[date]:
    months, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        months.append(cur)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def calendar_last_month(today: date, horizon: date, future_months: int = 0) -> date:
    """Первое число последнего месяца календаря: месяц горизонта бронирования или today + future_months, что дальше"""
    return max(date(horizon.year, horizon.month, 1), shift_month(today, max(future_months, 0)))


def build_calendar_data(
        days: Sequence[CalendarDay], today: date, first_bookable: date, horizon: date, history_months: int = 0,
        expires: Optional[int] = None, future_months: int = 0,
) -> str:
    """m — месяцы [ГГГГ-ММ, название, коды дней], c — индекс текущего месяца (с него открывается календарь),
    e — unix-время, после которого виджет предложит «Обновить».
    Месяцы: от history_months назад до future_months вперёд, но не раньше конца месяца горизонта бронирования.
    Если не влезает в chat_data, отбрасывается самый далёкий от сегодня месяц (самый старый или самый дальний впереди);
    текущий месяц и месяцы до горизонта бронирования остаются всегда"""
    by_date = {d.cal_date: d for d in days}
    months = []
    for m in _month_starts(shift_month(today, -max(history_months, 0)), calendar_last_month(today, horizon, future_months)):
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        codes = []
        for i in range((nxt - m).days):
            d = date(m.year, m.month, i + 1)
            info = by_date.get(d)
            codes.append(day_code(info, first_bookable, horizon) if info else "x")
        months.append([f"{m.year}-{m.month:02d}", f"{MONTHS_NOM[m.month - 1]} {m.year}", "".join(codes)])
    current = f"{today.year}-{today.month:02d}"
    keep_to = f"{horizon.year}-{horizon.month:02d}"
    while True:
        keys = [m[0] for m in months]
        c = keys.index(current)
        data = {"t": today.isoformat(), "c": c, "m": months}
        if expires:
            data["e"] = expires
        out = dumps(data)
        if data_size(out) <= MAX_DATA_BYTES:
            return out
        back = c if c > 0 else -1                                    # насколько далеко самый старый месяц
        ahead = len(months) - 1 - c if keys[-1] > max(current, keep_to) else -1  # и самый дальний впереди
        if back < 0 and ahead < 0:
            return out
        if back >= ahead:
            months.pop(0)
        else:
            months.pop()


def build_expired_data() -> str:
    return dumps({"x": EXPIRED_TEXT})


# ---------------------------------------------------------------------------#
#  Схема дня
# ---------------------------------------------------------------------------#
@dataclass(frozen=True)
class SeatHolder:
    user_id: int
    full_name: str
    seat_no: Optional[int]
    confirmed: bool


@dataclass(frozen=True)
class QueueEntry:
    user_id: int
    full_name: str


@dataclass(frozen=True)
class DaySeats:
    cal_date: date
    capacity: int
    holders: List[SeatHolder] = field(default_factory=list)   # все BOOKED, в т.ч. без места
    queue: List[QueueEntry] = field(default_factory=list)     # WAITLISTED в порядке продвижения

    def queue_ids(self) -> List[int]:
        return [e.user_id for e in self.queue]

    def by_seat(self) -> Dict[int, SeatHolder]:
        return {h.seat_no: h for h in self.holders if h.seat_no}

    def holder(self, user_id: int) -> Optional[SeatHolder]:
        return next((h for h in self.holders if h.user_id == user_id), None)

    def is_full(self) -> bool:
        return len(self.holders) >= self.capacity

    def free_seats(self, seats: Sequence[int]) -> List[int]:
        if self.is_full():
            return []
        taken = self.by_seat()
        return [s for s in seats if s not in taken]


def _seat_list(day: DaySeats, seats: Sequence[int], name_limit: int) -> list:
    taken, free = day.by_seat(), set(day.free_seats(seats))
    out = []
    for n in range(1, max(seats) + 1):
        if n in taken:
            out.append(short_name(taken[n].full_name, name_limit))
        elif n in free:
            out.append(0)
        else:
            out.append(UNAVAILABLE_SEAT)   # стул есть, но лимит дня выбран
    return out


def build_day_state(
        day: DaySeats,
        seats: Sequence[int],
        subject_id: int,
        subject_name: str,
        self_view: bool,
        readonly: bool,
        ok: Optional[str] = None,
        er: Optional[str] = None,
        today: Optional[date] = None,
) -> str:
    """Подзаголовок h — короткая фраза без разделителей «·». today нужен для текстов закрытых дней.
    Отмена брони и выход из очереди — кнопками под схемой, поэтому подсказок «нажмите, чтобы отменить» нет"""
    me = day.holder(subject_id)
    queue = day.queue_ids()
    qp = queue.index(subject_id) + 1 if subject_id in queue else 0
    ql = len(day.queue)
    booked = len(day.holders)
    limit = min(day.capacity, len(seats))
    free = max(0, min(limit - booked, len(day.free_seats(seats))))
    who = short_name(subject_name)

    if readonly and today and day.cal_date <= today:
        h = was_people(booked)          # прошлые дни и сегодня после WORK_END_HOUR:WORK_END_MINUTES
    elif readonly:
        h = "Бронирование закрыто"
    elif me and not me.seat_no:
        h = "Бронь есть, но место не выбрано. Нажмите на свободное"
    elif qp:
        h = "Мест нет, " + ("вы" if self_view else who) + f" №{qp} в очереди"
    elif free:
        h = f"Свободно {free} из {limit}"
    else:
        h = f"Мест нет, в очереди {people(ql)}" if ql else "Мест нет"

    state = {
        "d": day.cal_date.isoformat(),
        "t": day_title(day.cal_date),
        "h": h,
        "m": me.seat_no if me and me.seat_no else 0,
        "st": "B" if me else "Q" if qp else "",
        "ro": 1 if readonly else 0,
    }
    if ok:
        state["ok"] = ok
    if er:
        state["er"] = er
    for limit in (14, 9, 6):
        state["s"] = _seat_list(day, seats, limit)
        out = dumps(state)
        if data_size(out) <= MAX_DATA_BYTES:
            return out
    return out


# ---------------------------------------------------------------------------#
#  Дайджест в группе
# ---------------------------------------------------------------------------#
def build_digest_data(day: DaySeats, seats: Sequence[int], closed: bool, deadline: Optional[int] = None) -> str:
    """chat_data дайджеста в группе. Она одна на всех: виджет сам находит в ней зрителя по TelegramWidget.viewer.

    d, t — дата и заголовок; f/c — «Свободно f из c» под датой, считается как в личном виджете (build_day_state):
    места сверх лимита дня (capacity) не свободны и не входят в c; e — дедлайн подтверждения (unix-время,
    deadline) для таймера у неподтверждённой брони, только в открытом дне; x — день закрыт (после WORK_END дня
    визита), значение — строка под датой вместо «Свободно f из c» («Было 5 человек»).
    s — по элементу на место: 0 свободно, [короткое имя, подтверждено 0/1, user_id] занято, "u" сверх лимита дня.
    q — очередь в порядке продвижения: [короткое имя, user_id]; пустая очередь — поля нет.
    Не влезает в MAX_DATA_BYTES — имена укорачиваются до 14, 9, 6 символов, затем в q остаются только user_id
    (виджет пишет «Очередь: N человек»).

    Приватность: user_id сотрудников лежат в данных виджета, а их технически может прочитать любой участник группы.
    Имена там и так есть, а id в Telegram не секретны. Брони без места (лимит дня больше числа мест на схеме)
    в данные не попадают: такую настройку дайджест не поддерживает"""
    taken, free = day.by_seat(), set(day.free_seats(seats))
    total = min(day.capacity, len(seats))
    free_count = max(0, min(total - len(day.holders), len(free)))
    out = ""
    for limit, queue_names in ((14, True), (9, True), (6, True), (6, False)):
        s = []
        for n in range(1, max(seats) + 1):
            if n in taken:
                h = taken[n]
                s.append([short_name(h.full_name, limit), 1 if h.confirmed else 0, h.user_id])
            else:
                s.append(0 if n in free else DIGEST_UNAVAILABLE)
        data = {"d": day.cal_date.isoformat(), "t": day_title(day.cal_date), "f": free_count, "c": total}
        if closed:
            data["x"] = was_people(len(day.holders))
        elif deadline:
            data["e"] = deadline
        data["s"] = s
        if day.queue:
            data["q"] = [[short_name(e.full_name, limit), e.user_id] if queue_names else e.user_id for e in day.queue]
        out = dumps(data)
        if data_size(out) <= MAX_DATA_BYTES:
            return out
    return out
