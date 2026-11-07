"""Тестовые брони для проверки виджета выбора места. Только для локальной базы.

    python scripts/dev_seed_bookings.py              # сценарии 9–30 ноября 2026 + прошлые дни, «я» = единственный админ
    python scripts/dev_seed_bookings.py --me 123456   # явно указать свой user_id
    python scripts/dev_seed_bookings.py --only-past   # только прошлые дни, сценарии не трогать
    python scripts/dev_seed_bookings.py --history-months 6   # глубина прошлых дней (по умолчанию 3)

Прошлые дни — рабочие дни, которые видны в календаре виджета: от --history-months месяцев назад
до начала сценариев. Каждый день — случайная, но одинаковая при каждом запуске рассадка; у меня бронь
примерно в половине дней. Всё подтверждено (неподтверждённые брони отменяются вечером накануне).

Скрипт можно перезапускать: он удаляет все брони в диапазоне и раскладывает их заново,
пересчитывает calendar_dates.visit_count. Пользователи и лимиты не меняются.
"""
import argparse
import asyncio
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from config import settings  # noqa: E402
from src.ui.widgets.layout import SEATS  # noqa: E402
from src.ui.widgets.state import shift_month  # noqa: E402
from src.utils.tz_day import d_tz  # noqa: E402

START, END = date(2026, 11, 9), date(2026, 11, 30)

# Сценарии по дням. others — сколько коллег с местами, queue — сколько коллег в очереди,
# me — моё место ("Q" — я в очереди, None — без брони), confirmed — подтверждена ли моя бронь
SCENARIOS = {
    date(2026, 11, 9):  dict(others=4, title="свободно 6 из 10: бронь любого места"),
    date(2026, 11, 10): dict(others=5, me=3, confirmed=False, title="моё место 3: отмена и пересадка"),
    date(2026, 11, 11): dict(others=10, title="мест нет, очереди нет: «Встать в очередь»"),
    date(2026, 11, 12): dict(others=10, me="Q", queue=1, title="мест нет, я №1 в очереди: «Выйти из очереди»"),
    date(2026, 11, 13): dict(others=2, me=7, confirmed=True, title="моё место 7, на этаже почти пусто"),
    date(2026, 11, 16): dict(others=9, title="одно свободное место"),
    date(2026, 11, 17): dict(others=10, queue=2, title="мест нет, в очереди двое: встану №3"),
    date(2026, 11, 18): dict(others=9, me=1, confirmed=True, queue=1,
                             title="моё место 1, день полный, очередь: отмена отдаст стул первому в очереди"),
    date(2026, 11, 19): dict(others=0, title="пустой день"),
    date(2026, 11, 20): dict(others=2, title="пятница, почти пусто"),
    date(2026, 11, 23): dict(others=7, title="свободно 3"),
    date(2026, 11, 24): dict(others=10, title="мест нет"),
    date(2026, 11, 25): dict(others=6, me=5, confirmed=False, title="моё место 5"),
    date(2026, 11, 26): dict(others=8, title="свободно 2"),
    date(2026, 11, 27): dict(others=0, title="пустой день"),
    date(2026, 11, 30): dict(others=3, me=10, confirmed=False, title="моё место 10, крайнее у коридора"),
}


INSERT = text(
    "INSERT INTO bookings (user_id, cal_date, status, sub_status, seat_no, created_at, updated_at) "
    "VALUES (:u, :d, :st, :sub, :seat, now() - make_interval(mins => :age), now() - make_interval(mins => :age))"
)


def history_range(months: int) -> tuple[date, date]:
    return shift_month(d_tz(), -months), START - timedelta(days=1)


async def clear_range(conn, start: date, end: date) -> int:
    await conn.execute(text(
        "DELETE FROM booking_events WHERE booking_id IN "
        "(SELECT booking_id FROM bookings WHERE cal_date BETWEEN :s AND :e)"
    ), {"s": start, "e": end})
    return (await conn.execute(text(
        "DELETE FROM bookings WHERE cal_date BETWEEN :s AND :e"
    ), {"s": start, "e": end})).rowcount


async def recount(conn, start: date, end: date) -> None:
    await conn.execute(text(
        "UPDATE calendar_dates c SET visit_count = "
        "(SELECT count(*) FROM bookings b WHERE b.cal_date = c.cal_date AND b.status = 'BOOKED'), "
        "updated_at = now() WHERE c.cal_date BETWEEN :s AND :e"
    ), {"s": start, "e": end})


async def seed_history(conn, me: int, others: list[int], months: int) -> None:
    start, end = history_range(months)
    if start > end:
        return
    days = (await conn.execute(text(
        "SELECT c.cal_date, w.capacity FROM calendar_dates c "
        "JOIN office_capacity_weekdays w ON w.weekday = extract(ISODOW FROM c.cal_date) "
        "WHERE c.cal_date BETWEEN :s AND :e AND c.is_workday ORDER BY c.cal_date"
    ), {"s": start, "e": end})).all()
    deleted = await clear_range(conn, start, end)
    mine_days = 0
    for d, capacity in days:
        rnd = random.Random(d.toordinal())
        limit = min(capacity, len(SEATS), len(others) + 1)
        if limit <= 0:
            continue
        seats = list(SEATS)
        rnd.shuffle(seats)
        people = others[:]
        rnd.shuffle(people)
        mine = rnd.random() < 0.5
        count = rnd.randint(max(limit // 3, 1), limit)          # от трети до полного зала
        seated = ([me] if mine else []) + people[:count - mine]
        for i, (u, seat) in enumerate(zip(seated, seats)):
            await conn.execute(INSERT, {"u": u, "d": d, "st": "BOOKED", "sub": "CONFIRMED", "seat": seat, "age": 600 - i})
        if rnd.random() < 0.3 and len(people) > count:          # кто-то передумал: на схеме не видно
            await conn.execute(INSERT, {"u": people[count], "d": d, "st": "CANCELED",
                                        "sub": "CANCELED_CHANGED_MIND", "seat": None, "age": 100})
        mine_days += mine
    await recount(conn, start, end)
    print(f"Прошлые дни {start:%d.%m.%Y}–{end:%d.%m.%Y}: удалено броней {deleted}, "
          f"заполнено рабочих дней {len(days)}, из них с моей бронью {mine_days}")


def guard_local(url: str) -> None:
    host = urlparse(url.replace("+asyncpg", "")).hostname
    if host not in ("localhost", "127.0.0.1"):
        sys.exit(f"Отказ: POSTGRES_URL указывает на {host}. Скрипт только для локальной базы.")


async def main(me_arg: int | None, only_past: bool, history_months: int) -> None:
    guard_local(settings.POSTGRES_URL)
    engine = create_async_engine(settings.POSTGRES_URL)
    async with engine.begin() as conn:
        admins = (await conn.execute(text("SELECT user_id FROM users WHERE is_admin"))).scalars().all()
        me = me_arg or (admins[0] if len(admins) == 1 else None)
        if me is None:
            sys.exit(f"Укажите --me <user_id>: админов {len(admins)}")

        # Коллеги для заполнения: активные, кроме меня
        others = (await conn.execute(text(
            "SELECT user_id FROM users WHERE is_active AND user_id <> :me ORDER BY user_id"
        ), {"me": me})).scalars().all()
        await seed_history(conn, me, list(others), history_months)
        if only_past:
            await engine.dispose()
            print("\nГотово. Откройте «Забронировать место» заново, чтобы календарь подтянул данные.")
            return

        need = max(s.get("others", 0) + s.get("queue", 0) for s in SCENARIOS.values())
        if len(others) < need:
            sys.exit(f"Нужно минимум {need} активных пользователей кроме вас, есть {len(others)}")

        missing = (await conn.execute(text(
            "SELECT count(*) FROM generate_series(CAST(:s AS date), CAST(:e AS date), '1 day') d "
            "WHERE NOT EXISTS (SELECT 1 FROM calendar_dates c WHERE c.cal_date = d::date)"
        ), {"s": START, "e": END})).scalar()
        if missing:
            sys.exit(f"В calendar_dates нет {missing} дат из диапазона {START}–{END}")

        deleted = await clear_range(conn, START, END)
        insert = INSERT
        print(f"\nСценарии: удалено броней {deleted}. Я: {me}\n")
        for d, sc in sorted(SCENARIOS.items()):
            rnd = random.Random(d.toordinal())          # одинаковая раскладка при каждом запуске
            free = [s for s in SEATS if s != sc.get("me")]
            rnd.shuffle(free)
            people = others[:]
            rnd.shuffle(people)
            seated, queued = people[:sc.get("others", 0)], people[sc.get("others", 0):][:sc.get("queue", 0)]

            for i, (u, seat) in enumerate(zip(seated, free)):
                sub = "CONFIRMED" if rnd.random() < 0.7 else "RESERVED"
                await conn.execute(insert, {"u": u, "d": d, "st": "BOOKED", "sub": sub, "seat": seat, "age": 600 - i})

            mine = sc.get("me")
            queue = ([me] if mine == "Q" else []) + queued
            for i, u in enumerate(queue):                # порядок очереди = created_at
                await conn.execute(insert, {"u": u, "d": d, "st": "WAITLISTED", "sub": "WAITLISTED_MANUAL",
                                            "seat": None, "age": 300 - i})
            if isinstance(mine, int):
                await conn.execute(insert, {"u": me, "d": d, "st": "BOOKED",
                                            "sub": "CONFIRMED" if sc.get("confirmed") else "RESERVED",
                                            "seat": mine, "age": 450})
            print(f"{d:%d.%m} {d:%a}  {sc['title']}")

        await recount(conn, START, END)
    await engine.dispose()
    print("\nГотово. Откройте «Забронировать место» заново, чтобы календарь подтянул данные.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--me", type=int, help="ваш user_id (по умолчанию — единственный админ)")
    parser.add_argument("--only-past", action="store_true", help="заполнить только прошлые дни, сценарии не трогать")
    parser.add_argument("--history-months", type=int, default=3,
                        help="сколько прошлых месяцев заполнить (как «Прошлые месяцы» в Меню админа → Виджеты)")
    args = parser.parse_args()
    asyncio.run(main(args.me, args.only_past, args.history_months))
