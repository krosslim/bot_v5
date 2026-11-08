"""Выход из группы и отмена через чат снимают из очереди только этого человека: python -m unittest discover -s tests -t .

Раньше очередь снималась update_by_status по дате и подстатусу, без user_id: уходила вся очередь на эти даты."""
import unittest
from datetime import date
from types import SimpleNamespace

from src.dto.booking_dto import BookingStatus, CancelBookingFifoDTO
from src.handlers.chat.chat_cancel_handler import handle_cancel_reason
from src.handlers.chat.chat_member_handler import handle_left_chat_member
from src.services.booking_service import BookingService
from src.services.exceptions import UserIsAlreadyLeaveQueue

USER = 5
D1, D2, D3 = date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16)


class FakeUC:
    def __init__(self, bookings, left=()):
        self.bookings = bookings
        self.left = set(left)        # даты, на которых человек уже вышел из очереди
        self.calls = []

    async def my_bookings(self, user_id, cal_dates):
        return self.bookings

    async def dates_by_cache_key(self, key):
        return [b.cal_date for b in self.bookings]

    async def cancel_book_place(self, user_id, cal_date, cancel_sub_status):
        self.calls.append(("cancel", user_id, cal_date, cancel_sub_status))
        return CancelBookingFifoDTO(canceled_user_id=user_id, promoted_user_id=None, seat_no=1)

    async def cancel_waitlist_place(self, user_id, cal_date, sub_status=BookingStatus.CANCELED_CHANGED_MIND):
        self.calls.append(("leave", user_id, cal_date, sub_status))
        if cal_date in self.left:
            raise UserIsAlreadyLeaveQueue("ℹ️ Вы уже вышли из очереди!")


class FakeUsers:
    async def update_is_active(self, user_id, is_active):
        pass


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, *args, **kw):
        self.sent.append((args, kw))

    async def edit_message_reply_markup(self, **kw):
        pass


def _bookings():
    return [SimpleNamespace(cal_date=D1, status=BookingStatus.BOOKED),
            SimpleNamespace(cal_date=D2, status=BookingStatus.WAITLISTED),
            SimpleNamespace(cal_date=D3, status=BookingStatus.WAITLISTED)]


class ChatQueueCancelTest(unittest.IsolatedAsyncioTestCase):
    async def test_left_chat(self):
        uc = FakeUC(_bookings(), left={D2})   # на D2 успел выйти сам: остальные даты всё равно снимаются
        event = SimpleNamespace(new_chat_member=SimpleNamespace(user=SimpleNamespace(id=USER, is_bot=False)))
        await handle_left_chat_member(event, FakeBot(), FakeUsers(), uc)
        self.assertEqual(uc.calls, [("cancel", USER, D1, BookingStatus.CANCELED_LEFT_CHAT),
                                    ("leave", USER, D2, BookingStatus.CANCELED_LEFT_CHAT),
                                    ("leave", USER, D3, BookingStatus.CANCELED_LEFT_CHAT)])

    async def test_cancel_via_chat(self):
        uc = FakeUC(_bookings())
        res = SimpleNamespace(result_id=f"key|{BookingStatus.CANCELED_ILL}", from_user=SimpleNamespace(id=USER),
                              inline_message_id="m1")
        await handle_cancel_reason(res, FakeBot(), uc)
        self.assertEqual(uc.calls, [("cancel", USER, D1, BookingStatus.CANCELED_ILL),
                                    ("leave", USER, D2, BookingStatus.CANCELED_ILL),
                                    ("leave", USER, D3, BookingStatus.CANCELED_ILL)])


class FakeRepo:
    def __init__(self, booking_id=77):
        self.booking_id = booking_id
        self.calls = []

    async def leave_waitlist(self, user_id, cal_date, sub_status):
        self.calls.append(("leave", user_id, cal_date, sub_status))
        return self.booking_id

    async def insert_event(self, booking_id, status, sub_status, user_id):
        self.calls.append(("event", booking_id, status, sub_status, user_id))


class LeaveQueueServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_sub_status_reaches_booking_and_event(self):
        repo = FakeRepo()
        await BookingService(repo).leave_from_queue(USER, D2, BookingStatus.CANCELED_LEFT_CHAT)
        self.assertEqual(repo.calls, [("leave", USER, D2, BookingStatus.CANCELED_LEFT_CHAT),
                                      ("event", 77, BookingStatus.CANCELED, BookingStatus.CANCELED_LEFT_CHAT, USER)])

    async def test_default_is_changed_mind(self):
        repo = FakeRepo()
        await BookingService(repo).leave_from_queue(USER, D2)
        self.assertEqual(repo.calls[0][3], BookingStatus.CANCELED_CHANGED_MIND)

    async def test_not_in_queue(self):
        with self.assertRaises(UserIsAlreadyLeaveQueue):
            await BookingService(FakeRepo(booking_id=None)).leave_from_queue(USER, D2)


if __name__ == "__main__":
    unittest.main()
