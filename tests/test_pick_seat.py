"""Выбор места без БД: python -m unittest discover -s tests -t ."""
import unittest
from datetime import date

from src.services.booking_service import BookingService
from src.services.exceptions import SeatIsTaken, SeatNotFound
from src.ui.widgets.layout import SEATS

DAY = date(2026, 11, 11)


class _Repo:
    def __init__(self, taken):
        self.taken = set(taken)

    async def taken_seats(self, cal_date: date) -> set:
        return self.taken


class PickSeatTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_free_seat(self):
        svc = BookingService(_Repo({SEATS[0], SEATS[1]}))
        self.assertEqual(await svc.pick_seat(DAY), SEATS[2])

    async def test_all_seats_taken_gives_booking_without_seat(self):
        # Лимит дня больше числа мест: бронь создаётся без номера места, а не падает «мест нет»
        svc = BookingService(_Repo(SEATS))
        self.assertIsNone(await svc.pick_seat(DAY))

    async def test_chosen_seat_is_validated(self):
        svc = BookingService(_Repo({SEATS[0]}))
        self.assertEqual(await svc.pick_seat(DAY, SEATS[1]), SEATS[1])
        with self.assertRaises(SeatIsTaken):
            await svc.pick_seat(DAY, SEATS[0])
        with self.assertRaises(SeatNotFound):
            await svc.pick_seat(DAY, max(SEATS) + 1)


if __name__ == "__main__":
    unittest.main()
