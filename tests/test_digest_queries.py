"""Запросы дайджеста v2 (g*) на заглушках BookingUseCase и WidgetUseCase: python -m unittest discover -s tests -t ."""
import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from config import settings
from src.dto.booking_dto import BookingStatus, CancelBookingFifoDTO
from src.handlers.widget import widget_query_handler as h
from src.services.exceptions import (FreePlaceIsAvailable, SeatIsTaken, UserIsAlreadyInWaitingList,
                                     UserIsAlreadyLeaveQueue)
from src.ui.widgets.state import MAX_DATA_BYTES, DaySeats, QueueEntry, SeatHolder, data_size
from src.use_cases.booking_use_case import BookingUseCase
from src.use_cases.widget_use_case import WidgetUseCase
from src.utils.db_exc_wrapper import DBError

ME = 111
MESSAGE_ID = 10
TODAY = datetime.now(ZoneInfo(settings.MSC_TZ)).date()
OPEN = TODAY + timedelta(days=30)   # дедлайн подтверждения далеко впереди
BOSS = "Петров Дмитрий"


def _day(cal_date: date = OPEN, mine=None, full=False, queue=(), capacity=10) -> DaySeats:
    """Заняты 1 (Смирнов) и 3; mine — бронь ME на месте 4: True подтверждена, False нет; full — заняты все 10"""
    holders = [SeatHolder(201, "Смирнов Алексей", 1, True), SeatHolder(203, "Кузнецова Мария", 3, False)]
    if mine is not None:
        holders.append(SeatHolder(ME, "Иванов Иван", 4, mine))
    if full:
        holders += [SeatHolder(200 + n, f"Сотрудник{n} Пётр", n, True) for n in (2, 5, 6, 7, 8, 9, 10)]
        if mine is None:
            holders.append(SeatHolder(204, "Сотрудник4 Пётр", 4, True))
    return DaySeats(cal_date, capacity, holders, [QueueEntry(uid, name) for uid, name in queue])


class FakeUC:
    """BookingUseCase: day — схема дня; fail — метод → исключение, которое он бросит"""

    def __init__(self, day: DaySeats, registered=True, message_id=MESSAGE_ID, promoted=None, fail=None):
        self.day, self.registered, self.message_id, self.promoted = day, registered, message_id, promoted
        self.fail = fail or {}
        self.calls = []

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail[name]

    async def digest_message_id(self, cal_date):
        return self.message_id

    async def widget_day(self, cal_date):
        return self.day, True

    async def user_or_none(self, user_id):
        return SimpleNamespace(user_id=user_id) if self.registered else None

    async def book_place(self, user_id, cal_date, auto_confirm=None, seat_no=None):
        self._call("book", user_id, seat_no, auto_confirm)
        return seat_no

    async def move_seat(self, user_id, cal_date, seat_no):
        self._call("move", user_id, seat_no)

    async def confirm_booking(self, user_id, cal_date):
        self._call("confirm", user_id)
        return None if "confirm_none" in self.fail else 1

    async def cancel_book_place(self, user_id, cal_date, cancel_sub_status):
        self._call("cancel", user_id, cancel_sub_status)
        return CancelBookingFifoDTO(canceled_user_id=user_id, promoted_user_id=self.promoted, seat_no=4)

    async def waitlist_place(self, user_id, cal_date):
        self._call("queue", user_id)

    async def cancel_waitlist_place(self, user_id, cal_date):
        self._call("leave", user_id)


class FakeWidgets:
    def __init__(self, uc: FakeUC, bookable=True):
        self.uc, self.bookable = uc, bookable
        self.refreshed = []

    async def is_bookable(self, cal_date):
        return self.bookable

    async def seat_holder_name(self, cal_date, seat):
        if seat == "b":
            return BOSS
        holder = self.uc.day.by_seat().get(seat)
        return holder.full_name if holder else None

    async def refresh_digest(self, cal_date):
        self.refreshed.append(("digest", cal_date))

    async def refresh_user_widget(self, user_id):
        self.refreshed.append(("user", user_id))


class FakeContainer:
    def __init__(self, uc, widgets):
        self.deps = {BookingUseCase: uc, WidgetUseCase: widgets}

    async def get(self, cls):
        return self.deps[cls]


class FakeBot:
    def __init__(self):
        self.messages, self.answers = [], []

    async def send_message(self, **kw):
        self.messages.append(kw)

    async def __call__(self, method):
        self.answers.append(method)


def _query(data, user_id=ME, message_id=MESSAGE_ID):
    return SimpleNamespace(id="q1", data=data, message_id=message_id, from_user=SimpleNamespace(id=user_id),
                           chat=SimpleNamespace(id=settings.TG_CHAT_ID, type="supergroup"))


class DigestQueriesTest(unittest.IsolatedAsyncioTestCase):
    async def ask(self, data, day=None, bookable=True, **uc_kw):
        self.uc = FakeUC(day or _day(), **uc_kw)
        self.widgets = FakeWidgets(self.uc, bookable)
        self.bot = FakeBot()
        answer = await h._handle_digest(_query(data), self.bot, FakeContainer(self.uc, self.widgets))
        self.assertLessEqual(data_size(json.dumps(answer, ensure_ascii=False)), MAX_DATA_BYTES)
        return answer

    def assertUnchanged(self):
        self.assertEqual(self.uc.calls, [])
        self.assertEqual(self.widgets.refreshed, [])

    async def test_unknown_and_stale(self):
        self.assertEqual(await self.ask("gb:2026-11-12:b"), {"er": h.UNKNOWN_TEXT})
        for data in (f"gn:{OPEN}:1", f"gb:{OPEN}:2", f"gc:{OPEN}"):
            self.assertEqual(await self.ask(data, message_id=MESSAGE_ID + 1), {"er": h.STALE_DIGEST_TEXT})
            self.assertUnchanged()

    async def test_full_names(self):
        """Имена — всем: без регистрации и в закрытом дне. Из очереди — только тех, кто в ней сейчас"""
        day = _day(queue=((351, "Лебедев Никита"),))
        closed = dict(day=day, bookable=False, registered=False)
        self.assertEqual(await self.ask(f"gn:{OPEN}:1", **closed), {"n": "Смирнов Алексей"})
        self.assertEqual(await self.ask(f"gn:{OPEN}:b", **closed), {"n": BOSS})
        self.assertEqual(await self.ask(f"gn:{OPEN}:2", **closed), {"er": h.SEAT_FREE_TEXT})
        self.assertEqual(await self.ask(f"gu:{OPEN}:351", **closed), {"n": "Лебедев Никита"})
        # 201 бронирует место, но не в очереди: по его id имя не отдаём
        self.assertEqual(await self.ask(f"gu:{OPEN}:201", **closed), {"er": h.NOT_IN_QUEUE_TEXT})
        self.assertUnchanged()

    async def test_unregistered_and_closed(self):
        for cmd in (f"gb:{OPEN}:2", f"gc:{OPEN}", f"gx:{OPEN}", f"gq:{OPEN}", f"gl:{OPEN}"):
            self.assertEqual(await self.ask(cmd, registered=False), {"er": h.NOT_REGISTERED_TEXT, "u": 1})
            self.assertUnchanged()
            self.assertEqual(await self.ask(cmd, day=_day(mine=False), bookable=False), {"er": h.DAY_CLOSED_TEXT})
            self.assertUnchanged()

    async def test_take_seat(self):
        """Без брони — бронь на выбранное место; автоподтверждение по общему правилу (auto_confirm не задан)"""
        self.assertEqual(await self.ask(f"gb:{OPEN}:2"), {"ok": h.BOOKED_TEXT})
        self.assertEqual(self.uc.calls, [("book", ME, 2, None)])
        self.assertEqual(self.widgets.refreshed, [("digest", OPEN), ("user", ME)])

    async def test_move_seat(self):
        self.assertEqual(await self.ask(f"gb:{OPEN}:2", day=_day(mine=True)), {"ok": h.MOVED_TEXT})
        self.assertEqual(self.uc.calls, [("move", ME, 2)])

    async def test_seat_refusals(self):
        self.assertEqual(await self.ask(f"gb:{OPEN}:2", day=_day(mine=False)), {"er": h.CONFIRM_FIRST_TEXT})
        self.assertUnchanged()
        self.assertEqual(await self.ask(f"gb:{OPEN}:1"), {"er": "Это место только что заняли"})
        self.assertUnchanged()
        self.assertEqual(await self.ask(f"gb:{OPEN}:11"), {"er": "Такого места нет"})
        self.assertUnchanged()
        # Лимит дня выбран: стулья сверх него недоступны, в том числе для пересадки
        self.assertEqual(await self.ask(f"gb:{OPEN}:2", day=_day(mine=True, capacity=3)), {"er": "Свободных мест нет"})
        self.assertUnchanged()

    async def test_race_and_db_errors(self):
        """Гонку с другой бронью ловит BookingUseCase, ошибку БД — общий текст; данные не обновляются"""
        taken = await self.ask(f"gb:{OPEN}:2", fail={"book": SeatIsTaken("Это место только что заняли")})
        self.assertEqual(taken, {"er": "Это место только что заняли"})
        self.assertEqual(self.widgets.refreshed, [])
        self.assertEqual(await self.ask(f"gb:{OPEN}:2", fail={"book": DBError("down")}), {"er": h.DB_ERROR_TEXT})
        self.assertEqual(self.widgets.refreshed, [])

    async def test_confirm(self):
        self.assertEqual(await self.ask(f"gc:{OPEN}", day=_day(mine=False)), {"ok": h.CONFIRMED_TEXT})
        self.assertEqual(self.uc.calls, [("confirm", ME)])
        self.assertEqual(self.widgets.refreshed, [("digest", OPEN), ("user", ME)])
        # Уже подтверждена: успех без изменений, а данные виджета обновятся
        self.assertEqual(await self.ask(f"gc:{OPEN}", day=_day(mine=True)), {"ok": h.CONFIRMED_TEXT})
        self.assertEqual(self.uc.calls, [])
        self.assertEqual(await self.ask(f"gc:{OPEN}"), {"er": "Брони на этот день уже нет"})
        self.assertEqual(await self.ask(f"gc:{OPEN}", day=_day(mine=False), fail={"confirm_none": None}),
                         {"er": "Брони на этот день уже нет"})

    async def test_confirm_after_deadline(self):
        """Дедлайн — накануне в CANCEL_BOOKING_JOB_HOUR:MINUTES: для сегодняшней даты он уже прошёл"""
        self.assertEqual(await self.ask(f"gc:{TODAY}", day=_day(TODAY, mine=False)), {"er": h.CONFIRM_LATE_TEXT})
        self.assertUnchanged()

    async def test_cancel(self):
        self.assertEqual(await self.ask(f"gx:{OPEN}", day=_day(mine=True)), {"ok": h.CANCELED_TEXT})
        self.assertEqual(self.uc.calls, [("cancel", ME, BookingStatus.CANCELED_CHANGED_MIND)])
        self.assertEqual(await self.ask(f"gx:{OPEN}"), {"er": "Брони на этот день уже нет"})
        self.assertUnchanged()

    async def test_cancel_promotes_queue(self):
        answer = await self.ask(f"gx:{OPEN}", day=_day(mine=False, full=True, queue=((351, "Лебедев Никита"),)),
                                promoted=351)
        self.assertEqual(answer, {"ok": h.CANCELED_PROMOTED_TEXT})
        self.assertEqual(self.widgets.refreshed, [("digest", OPEN), ("user", ME), ("user", 351)])
        self.assertEqual([m["chat_id"] for m in self.bot.messages], [351])

    async def test_queue(self):
        full = _day(full=True)
        self.assertEqual(await self.ask(f"gq:{OPEN}", day=full), {"ok": h.QUEUED_TEXT})
        self.assertEqual(self.uc.calls, [("queue", ME)])
        # Место успело освободиться: waitlist_place сам бронирует
        self.assertEqual(await self.ask(f"gq:{OPEN}", day=full, fail={"queue": FreePlaceIsAvailable("")}),
                         {"ok": h.QUEUE_BOOKED_TEXT})
        self.assertEqual(self.widgets.refreshed, [("digest", OPEN), ("user", ME)])
        self.assertEqual(await self.ask(f"gq:{OPEN}", day=full, fail={"queue": UserIsAlreadyInWaitingList("")}),
                         {"er": "Вы уже в очереди"})
        self.assertEqual(await self.ask(f"gq:{OPEN}", day=_day(mine=True, full=True)),
                         {"er": "У вас уже есть бронь на этот день"})
        self.assertUnchanged()

    async def test_leave_queue(self):
        day = _day(full=True, queue=((ME, "Иванов Иван"),))
        self.assertEqual(await self.ask(f"gl:{OPEN}", day=day), {"ok": h.LEFT_QUEUE_TEXT})
        self.assertEqual(self.uc.calls, [("leave", ME)])
        self.assertEqual(await self.ask(f"gl:{OPEN}", fail={"leave": UserIsAlreadyLeaveQueue("")}),
                         {"er": "Вы уже вышли из очереди"})
        self.assertEqual(self.widgets.refreshed, [])


class DigestRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def answer(self, data, uc):
        bot = FakeBot()
        await h.process_widget_query(_query(data), bot, FakeContainer(uc, FakeWidgets(uc)))
        return json.loads(bot.answers[0].data)

    async def test_crash_answers_with_error(self):
        """Необработанное исключение — красная строка в виджете, а не молчание до таймаута"""
        uc = FakeUC(_day())

        async def boom(cal_date):
            raise RuntimeError("boom")
        uc.digest_message_id = boom
        with self.assertLogs(h.logger, "ERROR"):
            self.assertEqual(await self.answer(f"gb:{OPEN}:2", uc), {"er": h.DB_ERROR_TEXT})

    async def test_old_command_is_unknown(self):
        """Команды дайджеста до v2 (s:) больше не принимаются"""
        self.assertEqual(await self.answer(f"s:{OPEN}:2", FakeUC(_day())), {"er": h.UNKNOWN_TEXT})


if __name__ == "__main__":
    unittest.main()
