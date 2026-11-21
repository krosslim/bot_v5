"""Rich-календарь без БД и Telegram: python -m unittest discover -s tests -t .

Сборка HTML календаря и экрана дня (коды дней → id эмодзи, легенда, листание месяцев, длина callback_data),
сверка эмодзи в ответе Telegram (missing_emoji), проверка адреса Bot API, указатель на открытое окно."""
import html
import json
import re
import unittest
from datetime import date

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramServerError
from aiogram.methods import SendRichMessage
from aiogram.types import Message

from src.infrastructure.telegram.rich import emoji_ids, missing_emoji, rich_supported
from src.services.tech_service import TechService
from src.ui.keyboard.actions import RichCB
from src.ui.rich.booking import (CHAIR, MAX_RICH_CHARS, UNAVAILABLE, day_emoji_id, month_legend, render_calendar,
                                 render_day, settings_kb)
from src.ui.rich.emoji import DAY_EMOJI, DESK_EMOJI, LEGEND_EMOJI, LOOK, SIDE_CORRIDOR, SIDE_WINDOW, WH_TODAY_IDS
from src.ui.widgets.layout import OFFICE_LAYOUT, SEATS
from src.ui.widgets.state import DaySeats, QueueEntry, SeatHolder, build_day_state

NOV = date(2026, 11, 1)          # 30 дней, 1-е воскресенье: шесть пустых ячеек перед ним
TODAY = date(2026, 11, 22)       # воскресенье
BIG_ID = 10 ** 20 - 1            # длиннее любого user_id Telegram
LONG_NAME = "Константинопольская Александра"


def buttons(page: str):
    """(callback_data, подпись) всех кнопок callback_data"""
    return [(html.unescape(d), label) for d, label in
            re.findall(r'<tg-button type="callback_data" data="([^"]*)"[^>]*>(.*?)</tg-button>', page)]


def unpack(data: str) -> RichCB:
    return RichCB.unpack(data)


def nov_codes() -> str:
    """Все коды в одном месяце: прошлое (v, p), сегодня и выходные (w), праздник, дни после горизонта"""
    codes = {}
    for day in range(1, 31):
        d = date(2026, 11, day)
        if d.weekday() >= 5:
            codes[day] = "w"
        elif d < TODAY:
            codes[day] = "v" if day % 3 == 0 else "p"
        else:
            codes[day] = "x"
    codes.update({4: "h", 23: "b", 24: "q", 25: "n", 26: "f"})
    return "".join(codes[d] for d in range(1, 31))


def full_state(cal_date: date, readonly: bool = False, me: int = 0) -> dict:
    holders = [SeatHolder(user_id=1000 + n, full_name=LONG_NAME, seat_no=n, confirmed=True) for n in SEATS]
    queue = [QueueEntry(user_id=2000 + i, full_name=LONG_NAME) for i in range(8)]
    day = DaySeats(cal_date=cal_date, capacity=len(SEATS), holders=holders, queue=queue)
    return json.loads(build_day_state(day, SEATS, me or 1, LONG_NAME, True, readonly, today=TODAY))


class CalendarTest(unittest.TestCase):
    def setUp(self):
        self.codes = nov_codes()
        self.page = render_calendar(NOV, self.codes, TODAY, date(2026, 10, 1), date(2026, 12, 1))

    def test_layout(self):
        self.assertTrue(self.page.startswith("<h2>Ноябрь 2026</h2><table compact><tr>"))
        self.assertIn('<th align="center"><b>Пн</b></th>', self.page)
        self.assertIn('<th align="center"><b>Вс</b></th></tr></table><table compact bordered><tr>', self.page)
        dates = self.page.split("<table compact bordered>")[1].split("</table>")[0]
        self.assertTrue(dates.startswith("<tr>" + "<td></td>" * 6 + '<td align="center"><tg-button'))
        self.assertEqual(dates.count("<tr>"), 6)                      # 6 + 30 = 36 ячеек → 6 строк по 7
        self.assertTrue(dates.endswith("<td></td>" * 6 + "</tr>"))   # 36 + 6 = 42

    def test_each_date_is_link_button_with_its_emoji(self):
        days = [(unpack(d), label) for d, label in buttons(self.page) if unpack(d).cmd == "day"]
        self.assertEqual(len(days), 30)
        for i, (cb, label) in enumerate(days):
            d = date(2026, 11, i + 1)
            self.assertEqual(cb.day, d.isoformat())
            code = self.codes[i]
            self.assertEqual(label, f'<tg-emoji emoji-id="{DAY_EMOJI[(d.day, LOOK[code], d == TODAY)]}">📅</tg-emoji>')
        self.assertEqual(self.page.count('style="link"><tg-emoji'), 30)

    def test_codes_to_emoji(self):
        self.assertEqual(day_emoji_id(5, "f", False), DAY_EMOJI[(5, "f", False)])
        self.assertEqual(day_emoji_id(5, "p", False), day_emoji_id(5, "x", False))     # p и x один вид
        self.assertEqual(day_emoji_id(5, "w", False), day_emoji_id(5, "h", False))     # w и h один вид
        self.assertEqual(day_emoji_id(22, "w", True), WH_TODAY_IDS[21])                # выходной сегодня
        self.assertEqual(day_emoji_id(22, "f", True), day_emoji_id(22, "p", True))     # «сегодня» без состояния
        self.assertNotEqual(day_emoji_id(22, "b", True), day_emoji_id(22, "b", False))
        looks = {(d, LOOK[c], t) for d in range(1, 32) for c in "fbqnvpxwh" for t in (False, True)}
        self.assertTrue(looks <= set(DAY_EMOJI))                                          # любой код любого дня
        self.assertEqual(len(DAY_EMOJI), 434)

    def test_legend_only_for_codes_in_month(self):
        legend = month_legend(self.codes)[0]
        self.assertEqual(legend, "<footer>" + "  ".join(
            f'<tg-emoji emoji-id="{LEGEND_EMOJI[k]}">📅</tg-emoji> {label}'
            for k, label in (("b", "Бронь"), ("v", "Был(а)"), ("q", "Очередь"), ("n", "Мест нет"))) + "</footer>")
        self.assertEqual(month_legend("ffxxwwhpp"), [])
        only_queue = month_legend("fqw")[0]
        self.assertIn("Очередь", only_queue)
        self.assertNotIn("Бронь", only_queue)
        self.assertNotIn("<p>", only_queue)                     # <p> в <footer> сервер выбросит

    def test_month_buttons_at_range_edges(self):
        def nav(prev, nxt):
            page = render_calendar(NOV, self.codes, TODAY, prev, nxt)
            return [(unpack(d).day, label) for d, label in buttons(page) if unpack(d).cmd == "month"], page

        both, page = nav(date(2026, 10, 1), date(2026, 12, 1))
        self.assertEqual(both, [("2026-10-01", "← Октябрь"), ("2026-12-01", "Декабрь →")])
        self.assertIn("<tg-button-row><tg-button", page)                # во всю ширину: align не задан
        self.assertNotIn('<tg-button-row align=', page)
        self.assertEqual(nav(None, date(2026, 12, 1))[0], [("2026-12-01", "Декабрь →")])
        self.assertEqual(nav(date(2026, 10, 1), None)[0], [("2026-10-01", "← Октябрь")])
        none, page = nav(None, None)
        self.assertEqual(none, [])
        self.assertNotIn("<tg-button-row", page)
        self.assertNotIn('type="disabled"', page)              # неактивных кнопок нет

    def test_target_in_every_button(self):
        page = render_calendar(NOV, self.codes, TODAY, date(2026, 10, 1), date(2026, 12, 1), BIG_ID, LONG_NAME)
        self.assertTrue(page.startswith("<h5>Бронь за сотрудника: Александра К.</h5><h2>"))
        self.assertTrue(all(unpack(d).target == BIG_ID for d, _ in buttons(page)))
        self.assertNotIn("Бронь за сотрудника", render_calendar(NOV, self.codes, TODAY, None, None))


class DayTest(unittest.TestCase):
    D = date(2026, 11, 26)

    def state(self, seats, me=0, st="", ro=0, h="Свободно 3 из 10"):
        return {"d": self.D.isoformat(), "t": "Чт, 26 ноября", "h": h, "m": me, "st": st, "ro": ro, "s": seats}

    def seat_buttons(self, page):
        return {unpack(d).seat: (unpack(d).cmd, label) for d, label in buttons(page) if unpack(d).cmd in ("seat", "name")}

    def test_seats(self):
        seats = [0, "Анна К.", "Борис С.", 0, "u", 0, "Вы Я.", 0, 0, 0]
        page = render_day(self.D, self.state(seats, me=7, st="B"), "Ирина Б.")
        self.assertTrue(page.startswith("<h2>Чт, 26 ноября</h2><h5>Свободно 3 из 10</h5><tg-button-row>"))
        got = self.seat_buttons(page)
        self.assertEqual(got["1"], ("seat", CHAIR))
        self.assertEqual(got["2"], ("name", "Анна К."))
        self.assertEqual(got["b"], ("name", "Ирина Б."))
        self.assertNotIn("5", got)                                               # сверх лимита дня: неактивна
        self.assertIn('style="primary">Вы Я.</tg-button>', page)              # своё место
        self.assertIn(f'style="success">{CHAIR}</tg-button>', page)
        self.assertIn(f'<tg-button type="disabled">{UNAVAILABLE}</tg-button>', page)   # места другой команды
        self.assertIn("Отменить бронь", page)
        self.assertIn('style="danger"', page)
        self.assertNotIn("В очередь", page)
        self.assertTrue(page.endswith("</tg-button></tg-button-row>"))
        self.assertIn("<hr/>", page)

    def test_table_labels_and_sides(self):
        page = render_day(self.D, self.state([0] * 10), None)
        for name, ids in DESK_EMOJI.items():
            self.assertIn("".join(f'<tg-emoji emoji-id="{i}">📅</tg-emoji>' for i in ids), page)
        self.assertIn(f'<td align="left"><tg-emoji emoji-id="{SIDE_WINDOW[0]}">', page)
        self.assertIn(f'<td align="right"><tg-emoji emoji-id="{SIDE_CORRIDOR[0]}">', page)
        tables = [item[1] for item in OFFICE_LAYOUT if not isinstance(item, str)]
        self.assertTrue(set(tables) <= set(DESK_EMOJI), "новый стол: нужны PNG (scripts/day_emoji_png.py greylabels)")

    def test_no_boss(self):
        got = self.seat_buttons(render_day(self.D, self.state([0] * 10), None))
        self.assertNotIn("b", got)

    def test_actions(self):
        full = ["Анна К."] * 10
        self.assertIn("В очередь", render_day(self.D, self.state(full, h="Мест нет"), None))
        queued = render_day(self.D, self.state(full, st="Q", h="Мест нет, вы №1 в очереди"), None)
        self.assertIn("Выйти из очереди", queued)
        self.assertNotIn("В очередь<", queued)
        self.assertNotIn("Отменить", render_day(self.D, self.state([0] * 10), None))

    def test_readonly_day(self):
        page = render_day(self.D, self.state([0, "Анна К."] + [0] * 8, ro=1, h="Было 1 человек"), None)
        got = self.seat_buttons(page)
        self.assertEqual(set(got), {"2"})                                        # свободные места неактивны
        self.assertNotIn(CHAIR, page)
        cmds = [unpack(d).cmd for d, _ in buttons(page)]
        self.assertEqual(cmds.count("month"), 1)                                 # только «Назад»
        self.assertNotIn("Отменить", page)
        self.assertNotIn("В очередь", page)

    def test_back_returns_month_of_day(self):
        page = render_day(self.D, self.state([0] * 10), None)
        back = [unpack(d) for d, label in buttons(page) if label == "Назад"]
        self.assertEqual([(b.cmd, b.day) for b in back], [("month", "2026-11-01")])

    def test_texts_from_build_day_state(self):
        state = full_state(self.D)
        page = render_day(self.D, state, "Ирина Б.")
        self.assertIn(f"<h5>{state['h']}</h5>", page)
        self.assertIn(f"<h2>{state['t']}</h2>", page)

    def test_names_are_escaped(self):
        page = render_day(self.D, self.state(["<b>Хак</b>"] + [0] * 9), None)
        self.assertNotIn("<b>Хак", page)
        self.assertIn("&lt;b&gt;Хак", page)


class LimitsTest(unittest.TestCase):
    def heaviest(self):
        cal = render_calendar(date(2026, 12, 1), "b" * 31, date(2026, 12, 31), date(2026, 11, 1), date(2027, 1, 1),
                              BIG_ID, LONG_NAME)
        cal = max(cal, render_calendar(date(2026, 12, 1), "bvqn" * 7 + "bvq", date(2026, 12, 31),
                                       date(2026, 11, 1), date(2027, 1, 1), BIG_ID, LONG_NAME), key=len)
        day = render_day(date(2026, 12, 3), full_state(date(2026, 12, 3)), short_name_boss(), BIG_ID, LONG_NAME)
        return cal, day

    def test_callback_data_fits_64_bytes(self):
        cal, day = self.heaviest()
        found = buttons(cal) + buttons(day)
        self.assertTrue(found)
        for data, _ in found:
            self.assertLessEqual(len(data.encode()), 64, data)
            self.assertEqual(unpack(data).target, BIG_ID)
        for row in settings_kb(BIG_ID, TODAY).inline_keyboard:
            for b in row:
                self.assertLessEqual(len(b.callback_data.encode()), 64, b.callback_data)

    def test_size_within_rich_limit(self):
        for page in self.heaviest():
            self.assertLess(len(page), MAX_RICH_CHARS // 2, len(page))

    def test_unique_idk_per_button(self):
        cal, _ = self.heaviest()
        idks = [unpack(d).idk for d, _ in buttons(cal)]
        self.assertGreater(len(set(idks)), len(idks) - 3)        # 4 символа из 62: совпадения редки


def short_name_boss() -> str:
    from src.ui.widgets.state import short_name
    return short_name(LONG_NAME)


class KeyboardTest(unittest.TestCase):
    def test_today_and_settings(self):
        kb = settings_kb(BIG_ID, TODAY)
        self.assertEqual([[b.text for b in row] for row in kb.inline_keyboard], [["Сегодня", "Настройки"]])
        today, settings = kb.inline_keyboard[0]
        cb = unpack(today.callback_data)
        self.assertEqual((cb.cmd, cb.target), ("today", BIG_ID))      # бронь за сотрудника: календарь его
        self.assertIsNone(unpack(settings_kb().inline_keyboard[0][0].callback_data).target)
        self.assertTrue(settings.callback_data.startswith("s:INIT_SETTINGS"))
        self.assertTrue(all(b.style is None for b in kb.inline_keyboard[0]))   # без цвета, как в пробе


class EmojiCheckTest(unittest.TestCase):
    @staticmethod
    def message(*ids):
        return Message.model_validate({
            "message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"},
            "rich_message": {"blocks": [{"type": "paragraph", "text": [
                {"type": "custom_emoji", "custom_emoji_id": i, "alternative_text": "📅"} for i in ids] + [" x"]}]},
        })

    def test_missing_id_is_reported(self):
        page = render_calendar(NOV, nov_codes(), TODAY, None, None)
        sent = emoji_ids(page)
        shown = sorted(sent)[1:]
        self.assertEqual(missing_emoji(self.message(*shown), page), {sorted(sent)[0]})
        self.assertEqual(missing_emoji(self.message(*sent), page), set())

    def test_text_message_or_true(self):
        page = '<p><tg-emoji emoji-id="111">📅</tg-emoji></p>'
        plain = Message.model_validate({"message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"}, "text": "x"})
        self.assertEqual(missing_emoji(plain, page), {"111"})    # Rich превратился в текст: эмодзи нет
        self.assertEqual(missing_emoji(True, page), set())        # inline-сообщение: проверить нечем


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def __call__(self, method):
        self.calls.append(method)
        if self.error:
            raise self.error
        return True


class RichSupportedTest(unittest.IsolatedAsyncioTestCase):
    async def test_answers(self):
        method = SendRichMessage(chat_id=0, rich_message={"html": "<p>.</p>"})
        self.assertTrue(await rich_supported(FakeBot(TelegramBadRequest(method, "Bad Request: chat not found"))))
        self.assertFalse(await rich_supported(FakeBot(TelegramNotFound(method, "Not Found"))))
        self.assertFalse(await rich_supported(FakeBot(TelegramServerError(method, "Bad Gateway"))))
        bot = FakeBot(TelegramBadRequest(method, "chat not found"))
        await rich_supported(bot)
        self.assertEqual(bot.calls[0].chat_id, 0)                 # без побочных эффектов: чата 0 нет


class FakeStore:
    def __init__(self):
        self.data = {}

    async def set_value(self, key, value):
        self.data[key] = value

    async def get_value(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


class PointerTest(unittest.IsolatedAsyncioTestCase):
    async def test_widget_and_rich_pointers(self):
        tech = TechService(FakeStore(), None)
        await tech.set_booking_widget(5, 100, None)
        p = await tech.get_booking_widget(5)
        self.assertEqual((p.message_id, p.target_id, p.rich, p.view), (100, None, False, None))
        await tech.set_booking_widget(5, 101, 42, rich_view="d2026-11-23")
        p = await tech.get_booking_widget(5)
        self.assertEqual((p.message_id, p.target_id, p.rich, p.view), (101, 42, True, "d2026-11-23"))
        tech.store.data["widget:booking:5"] = "102:"                     # значение старой версии
        p = await tech.get_booking_widget(5)
        self.assertEqual((p.message_id, p.rich), (102, False))


if __name__ == "__main__":
    unittest.main()
