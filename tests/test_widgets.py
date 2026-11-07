"""Проверки виджетов без БД и Telegram: python -m unittest discover -s tests"""
import json
import re
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
from src.utils.today import widget_data_expiry

from src.handlers.widget.widget_query_handler import parse_group, parse_private
from src.ui.widgets.layout import OFFICE_LAYOUT, SEATS
from src.ui.widgets.render import (MAX_ZLIB_BYTES, _merge_foreign, render_booking_widget, render_digest_widget,
                                   widget_layout, widget_size)
from src.ui.widgets.state import (MAX_DATA_BYTES, CalendarDay, DaySeats, SeatHolder, build_calendar_data,
                                  build_day_state, build_digest_data, data_size, day_code, people,
                                  shift_month, short_name, was_people)

LONG_NAME = "Константинопольская Александра"   # «Александра К.» — самое длинное, что влезает


def _full_day(cal_date: date, confirmed: bool = False) -> DaySeats:
    holders = [SeatHolder(user_id=1000 + n, full_name=LONG_NAME, seat_no=n, confirmed=confirmed) for n in SEATS]
    return DaySeats(cal_date=cal_date, capacity=len(SEATS), holders=holders, queue=list(range(2000, 2008)))


class TemplatesTest(unittest.TestCase):
    def test_sizes_within_telegram_limits(self):
        for html in (render_booking_widget(), render_booking_widget(1234567890123, LONG_NAME), render_digest_widget()):
            raw, packed = widget_size(html)
            self.assertLessEqual(packed, MAX_ZLIB_BYTES)
            self.assertNotIn("__LAYOUT__", html)
            self.assertNotIn("__", html.split("<script>")[1].split("var T")[0])

    def test_layout_and_admin_target_are_embedded(self):
        html = render_booking_widget(42, "Иванов Иван")
        self.assertIn(json.dumps(widget_layout(), ensure_ascii=False, separators=(",", ":")), html)
        self.assertIn('U="42"', html)
        self.assertIn("Бронь за сотрудника: Иван И.", html)
        self.assertIn('U=""', render_booking_widget())

    def test_exit_button(self):
        html = render_booking_widget()
        self.assertIn('data-e="1">\'+(pd==\'e\'?SP:\'« Выйти\')+\'</button>', html)
        self.assertIn("rq('x','e')", html)

    def test_back_button_at_bottom(self):
        html = render_booking_widget()
        self.assertIn('<div class="ft"><button class="bt" data-k="1">« Назад</button>\'+q+\'</div>', html)
        self.assertNotIn('class="nv" data-k', html)

    def test_no_seat_numbers_on_map(self):
        """Номера мест не показываются: в ячейке только имя или призыв к действию"""
        for html in (render_booking_widget(), render_digest_widget()):
            self.assertNotIn("<u>", html)
            self.assertNotIn(".s u{", html)
        html = render_booking_widget()
        # Своё место уже есть или «занять» только что нажато: остальные свободные места — тише, «пересесть»
        self.assertIn("var mv=D.m||/^s/.test(pd)", html)
        self.assertIn("(mv?'пересесть':'занять')", html)

    def test_legend_only_for_codes_on_screen(self):
        html = render_booking_widget()
        self.assertIn("'fСвободно|bЕсть бронь|vБыла бронь|qОчередь|nМест нет'", html)
        self.assertIn("if(k.indexOf(x[0])>=0)", html)

    def test_pending_spinner_instead_of_overlay(self):
        for html in (render_booking_widget(), render_digest_widget()):
            self.assertIn("@keyframes sp", html)
            self.assertNotIn(".bz", html)
            # Спиннер — обычный элемент вместо содержимого кнопки: клиент Telegram не центрирует
            # абсолютный псевдоэлемент через calc() и обрезает его overflow:hidden
            self.assertIn('<i class="sp"></i>', html)
            self.assertNotIn(".ld", html)

    def test_long_admin_name_does_not_grow_html(self):
        """Подпись «Бронь за сотрудника» — короткое имя: длина ФИО не приближает виджет к лимиту 4 КБ"""
        short = widget_size(render_booking_widget(1, "Иванов Иван"))[1]
        huge = widget_size(render_booking_widget(1234567890123, "Константинопольская-Длинноименная " * 3))[1]
        self.assertLessEqual(huge - short, 40)
        # Запас на будущие правки схемы; всё, что меняется в рантайме (id и имя сотрудника), уже в худшем значении
        self.assertLessEqual(huge, MAX_ZLIB_BYTES - 80)

    def test_stale_window_offers_reopen(self):
        html = render_booking_widget()
        self.assertIn("C.x||old()?xp()", html)
        self.assertIn("if(t.o)return rq('o','o')", html)
        self.assertIn("Открыть заново", html)

    def test_cancel_by_button_not_by_seat(self):
        html = render_booking_widget()
        self.assertIn("D.st=='B'?b('lv','c','Отменить бронь')", html)
        self.assertNotIn("rq('c:'", html)

    def test_no_mass_opacity(self):
        """Не больше 16 элементов с opacity < 1 одновременно, иначе «Paint limit exceeded»: только нажатая кнопка"""
        for html in (render_booking_widget(), render_digest_widget()):
            css = html.split("</style>")[0]
            rules = [r for r in re.findall(r"([^{}]+)\{[^}]*opacity", css)]
            self.assertEqual([r.strip() for r in rules], ["button:active"])

    def test_foreign_seats_merged_into_strips(self):
        """Подряд идущие места другой команды виджет рисует одной полосой"""
        self.assertEqual(_merge_foreign(["x", "x", "x", "x"]), ["x4"])
        self.assertEqual(_merge_foreign([1, 2, "b", "x"]), [1, 2, "b", "x1"])
        self.assertEqual(_merge_foreign(["x", 1, "x", "x"]), ["x1", 1, "x2"])
        flat = [c for item in widget_layout() if not isinstance(item, str) for row in (item[0], item[2]) for c in row]
        self.assertEqual(sorted(c for c in flat if isinstance(c, int)), list(SEATS))

    def test_seats(self):
        self.assertEqual(SEATS, tuple(range(1, 11)))
        tables = [item for item in OFFICE_LAYOUT if not isinstance(item, str)]
        self.assertTrue(all(len(t) == 3 and isinstance(t[1], str) for t in tables))


class RequestParsingTest(unittest.TestCase):
    def test_private(self):
        r = parse_private("b:2026-11-12:10@1234567890")
        self.assertEqual((r.cmd, r.cal_date, r.seat, r.target), ("b", date(2026, 11, 12), 10, 1234567890))
        self.assertEqual(parse_private("d:2026-11-12").seat, None)
        self.assertEqual(parse_private("lq:2026-11-12").cmd, "lq")
        for bad in ("x:2026-11-12", "b:2026-13-40:1", "b:2026-11-12:1@", "", "d:2026-11-12;drop"):
            self.assertIsNone(parse_private(bad), bad)
        self.assertLessEqual(len("lq:2026-11-12:10@12345678901234567890".encode()), 64)

    def test_group(self):
        self.assertEqual(parse_group("s:2026-11-10:5"), (date(2026, 11, 10), 5))
        self.assertIsNone(parse_group("b:2026-11-10:5"))


class StateTest(unittest.TestCase):
    def test_short_name(self):
        self.assertEqual(short_name("Иванов Иван"), "Иван И.")
        self.assertEqual(short_name("Мадонна"), "Мадонна")
        self.assertLessEqual(len(short_name(LONG_NAME)), 14)

    def test_day_state_worst_case_fits(self):
        day = _full_day(date(2026, 11, 12))
        for self_view in (True, False):
            out = build_day_state(day, SEATS, 1001, LONG_NAME, self_view, False, er="Это место только что заняли")
            self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
            state = json.loads(out)
            self.assertEqual(state["m"], 1)
            self.assertEqual(state["st"], "B")
            self.assertEqual(len(state["s"]), len(SEATS))

    def test_day_state_free_full_queue(self):
        d = date(2026, 11, 12)
        free = json.loads(build_day_state(DaySeats(d, 10), SEATS, 1, "Иванов Иван", True, False))
        self.assertEqual(free["s"], [0] * 10)
        self.assertIn("Свободно 10 из 10", free["h"])
        queued = json.loads(build_day_state(_full_day(d), SEATS, 2001, "Иванов Иван", True, False))
        self.assertEqual((queued["st"], queued["m"]), ("Q", 0))
        self.assertIn("№2 в очереди", queued["h"])

    def test_capacity_below_seats_marks_rest_unavailable(self):
        d = date(2026, 11, 12)
        holders = [SeatHolder(1, "Иванов Иван", 3, True), SeatHolder(2, "Петров Пётр", None, True)]
        state = json.loads(build_day_state(DaySeats(d, 2, holders), SEATS, 9, "Сидоров Сидор", True, False))
        self.assertEqual(state["s"][2], "Иван И.")
        self.assertTrue(all(v == "недоступно" for i, v in enumerate(state["s"]) if i != 2))

    def test_digest_worst_case_fits(self):
        out = build_digest_data(_full_day(date(2026, 11, 10)), SEATS, closed=False)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        self.assertEqual(json.loads(out)["s"][0], ["Александра К.", 0])

    def test_day_codes(self):
        first, horizon = date(2026, 11, 10), date(2026, 12, 6)
        mk = lambda d, **kw: CalendarDay(**{**dict(cal_date=d, is_weekend=False, is_holiday=False, is_workday=True,
                                                   visit_count=0, capacity=10, my_status=None), **kw})
        self.assertEqual(day_code(mk(date(2026, 11, 7), is_weekend=True, is_holiday=True, is_workday=False), first, horizon), "w")
        self.assertEqual(day_code(mk(date(2026, 11, 4), is_holiday=True, is_workday=False), first, horizon), "h")
        self.assertEqual(day_code(mk(date(2026, 11, 9)), first, horizon), "p")
        self.assertEqual(day_code(mk(date(2026, 10, 1), my_status="BOOKED"), first, horizon), "v")
        self.assertEqual(day_code(mk(date(2026, 11, 9), visit_count=10), first, horizon), "p")
        self.assertEqual(day_code(mk(date(2026, 12, 7)), first, horizon), "x")
        self.assertEqual(day_code(mk(date(2026, 11, 12), my_status="BOOKED"), first, horizon), "b")
        self.assertEqual(day_code(mk(date(2026, 11, 12), my_status="WAITLISTED"), first, horizon), "q")
        self.assertEqual(day_code(mk(date(2026, 11, 12), visit_count=10), first, horizon), "n")
        self.assertEqual(day_code(mk(date(2026, 11, 12), visit_count=3), first, horizon), "f")
        self.assertEqual(day_code(mk(date(2026, 11, 14), is_weekend=True, is_workday=True), first, horizon), "f")

    def test_calendar_months(self):
        data = json.loads(build_calendar_data([], date(2026, 11, 9), date(2026, 11, 10), date(2026, 12, 6)))
        self.assertEqual([m[0] for m in data["m"]], ["2026-11", "2026-12"])
        self.assertEqual([len(m[2]) for m in data["m"]], [30, 31])
        self.assertEqual(data["m"][0][1], "Ноябрь 2026")
        self.assertEqual(data["t"], "2026-11-09")
        self.assertEqual(data["c"], 0)
        self.assertNotIn("e", data)
        with_expiry = json.loads(build_calendar_data([], date(2026, 11, 9), date(2026, 11, 10), date(2026, 12, 6),
                                                     expires=1794000000))
        self.assertEqual(with_expiry["e"], 1794000000)

    def test_calendar_history(self):
        data = json.loads(build_calendar_data([], date(2026, 2, 9), date(2026, 2, 10), date(2026, 3, 8), 3))
        self.assertEqual([m[0] for m in data["m"]], ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03"])
        self.assertEqual(data["c"], 3)

    def test_calendar_history_fits_chat_data(self):
        """Длинная история не ломает chat_data: старые месяцы отбрасываются, текущий и будущие остаются"""
        today = date(2026, 12, 30)
        days = [CalendarDay(today - timedelta(days=i), False, False, True, 0, 10, "BOOKED") for i in range(400)]
        out = build_calendar_data(days, today, today, date(2027, 1, 31), 24)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        data = json.loads(out)
        self.assertEqual([m[0] for m in data["m"]][-2:], ["2026-12", "2027-01"])
        self.assertEqual(data["m"][data["c"]][0], "2026-12")
        self.assertGreater(len(data["m"]), 6)

    def test_widget_data_expiry(self):
        tz = ZoneInfo(settings.MSC_TZ)
        end = settings.WORK_END_HOUR
        before = datetime(2026, 11, 10, end - 1, 30, tzinfo=tz)
        after = datetime(2026, 11, 10, end, 0, tzinfo=tz)
        self.assertEqual(widget_data_expiry(before), int(datetime(2026, 11, 10, end, settings.WORK_END_MINUTES, tzinfo=tz).timestamp()))
        self.assertEqual(widget_data_expiry(after), int(datetime(2026, 11, 11, 0, 0, tzinfo=tz).timestamp()))

    def test_shift_month(self):
        self.assertEqual(shift_month(date(2026, 2, 28), -3), date(2025, 11, 1))
        self.assertEqual(shift_month(date(2026, 11, 15), 2), date(2027, 1, 1))

    def test_people_plural(self):
        self.assertEqual([people(n) for n in (1, 2, 4, 5, 11, 12, 21, 22)],
                         ["1 человек", "2 человека", "4 человека", "5 человек", "11 человек", "12 человек",
                          "21 человек", "22 человека"])
        self.assertEqual([was_people(n) for n in (0, 1, 3, 7, 11, 21)],
                         ["Никого не было", "Был 1 человек", "Было 3 человека", "Было 7 человек",
                          "Было 11 человек", "Был 21 человек"])

    def test_closed_day_texts(self):
        d = date(2026, 10, 12)
        day = DaySeats(d, 10, [SeatHolder(1, "Иванов Иван", 3, True), SeatHolder(2, "Петров Пётр", 5, True)])
        past = json.loads(build_day_state(day, SEATS, 1, "Иванов Иван", True, True, today=date(2026, 11, 6)))
        self.assertEqual((past["ro"], past["h"], past["m"]), (1, "Было 2 человека", 3))
        today = json.loads(build_day_state(day, SEATS, 1, "Иванов Иван", True, True, today=d))
        self.assertEqual(today["h"], "Было 2 человека")     # сегодня после WORK_END — как прошедший день
        self.assertEqual(json.loads(build_day_state(day, SEATS, 1, "Иванов Иван", True, True))["h"],
                         "Бронирование закрыто")

    def test_subtitles_have_no_separators_or_seat_numbers(self):
        d = date(2026, 11, 12)
        day = DaySeats(d, 10, [SeatHolder(1, "Иванов Иван", 7, True)])
        own = json.loads(build_day_state(day, SEATS, 1, "Иванов Иван", True, False))
        self.assertEqual((own["h"], own["st"]), ("Свободно 9 из 10", "B"))
        admin = json.loads(build_day_state(day, SEATS, 1, "Иванов Иван", False, False))
        self.assertEqual(admin["h"], "Свободно 9 из 10")
        free = json.loads(build_day_state(day, SEATS, 9, "Сидоров Сидор", True, False))
        self.assertEqual(free["h"], "Свободно 9 из 10")
        full = json.loads(build_day_state(_full_day(d), SEATS, 9, "Сидоров Сидор", True, False))
        self.assertEqual(full["h"], "Мест нет, в очереди 8 человек")
        no_queue = DaySeats(d, 10, _full_day(d).holders)
        self.assertEqual(json.loads(build_day_state(no_queue, SEATS, 9, "Сидоров Сидор", True, False))["h"],
                         "Мест нет")
        limited = DaySeats(d, 8, [SeatHolder(1, "Иванов Иван", 7, True)])
        self.assertEqual(json.loads(build_day_state(limited, SEATS, 9, "Сидоров Сидор", True, False))["h"],
                         "Свободно 7 из 8")
        for state in (own, admin, free, full):
            self.assertNotIn("·", state["h"])
            self.assertNotIn("7", state["h"])

if __name__ == "__main__":
    unittest.main()
