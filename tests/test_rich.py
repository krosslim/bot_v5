"""Rich-календарь без БД и Telegram: python -m unittest discover -s tests -t .

Сборка HTML календаря и экрана дня (коды дней → id эмодзи, легенда, листание месяцев, столы блоками <details>,
таблица имён, кнопки мест, длина callback_data),
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
from src.use_cases.widget_use_case import WidgetUseCase
from src.ui.keyboard.actions import RichCB
from src.ui.rich.booking import (CHAIR, MAX_RICH_CHARS, MAX_RICH_EMOJI, NAME_ROOM_PT, Person, day_emoji_id,
                                 desk_picture, desk_summary, month_legend, render_calendar, render_day, seat_badge)
from src.ui.rich.emoji import (DAY_EMOJI, DESK_ICON, DESK_ROW, LEGEND_EMOJI, LOOK, ROW_CORRIDOR, ROW_WINDOW, SEAT_BADGE,
                               SETTINGS_ICON, TODAY_ICON, WH_TODAY_IDS, emoji_strip)
from src.ui.rich.fit import fit_name, text_width
from src.ui.widgets.layout import BOSS_SEAT, OFFICE_LAYOUT, SEAT_NUMBERS, SEATS
from src.ui.widgets.state import DaySeats, QueueEntry, SeatHolder, build_day_state

NOV = date(2026, 11, 1)          # 30 дней, 1-е воскресенье: шесть пустых ячеек перед ним
TODAY = date(2026, 11, 22)       # воскресенье
BIG_ID = 10 ** 20 - 1            # длиннее любого user_id Telegram
LONG_NAME = "Константинопольская Александра"


def all_buttons(page: str):
    """(callback_data, подпись) всех кнопок callback_data, в том числе «Настройки» (SettingsCB)"""
    return [(html.unescape(d), label) for d, label in
            re.findall(r'<tg-button type="callback_data" data="([^"]*)"[^>]*>(.*?)</tg-button>', page)]


def buttons(page: str):
    """Кнопки Rich-календаря (RichCB)"""
    return [(d, label) for d, label in all_buttons(page) if d.startswith("r:")]


def bar(page: str) -> str:
    """Нижний ряд календаря: последний tg-button-row"""
    return re.findall(r"<tg-button-row[^>]*>.*?</tg-button-row>", page)[-1]


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

    def test_bottom_row(self):
        """Один ряд во всю ширину: «Сегодня» и «Настройки» иконками без стиля, «←» и «→» primary"""
        row = bar(self.page)
        self.assertTrue(row.startswith("<tg-button-row><tg-button"))      # align не задан
        self.assertTrue(self.page.endswith(row))
        cells = re.findall(r"<tg-button ([^>]*)>(.*?)</tg-button>", row)
        self.assertEqual([label for _, label in cells], [TODAY_ICON, SETTINGS_ICON, "←", "→"])
        self.assertNotIn("style", cells[0][0] + cells[1][0])
        self.assertTrue(all('style="primary"' in attrs for attrs, _ in cells[2:]))
        today = unpack(html.unescape(re.search(r'data="([^"]*)"', cells[0][0]).group(1)))
        self.assertEqual((today.cmd, today.day, today.target), ("today", TODAY.isoformat(), None))
        self.assertTrue(re.search(r'data="([^"]*)"', cells[1][0]).group(1).startswith("s:INIT_SETTINGS"))
        months = [unpack(d).day for d, _ in buttons(row) if unpack(d).cmd == "month"]
        self.assertEqual(months, ["2026-10-01", "2026-12-01"])
        self.assertNotIn("Октябрь", row)                                   # названий месяцев на кнопках нет
        self.assertNotIn("Декабрь", row)
        self.assertEqual(self.page.count("<tg-button-row"), 1)
        self.assertEqual(TODAY_ICON, '<tg-emoji emoji-id="5193122438803665781">🔄</tg-emoji>')
        self.assertEqual(SETTINGS_ICON, '<tg-emoji emoji-id="5192757126065336227">⚙</tg-emoji>')

    def test_month_arrows_at_range_edges(self):
        """Недоступный месяц: стрелка на месте неактивной кнопкой без стиля, ряд не прыгает"""
        def row(prev, nxt):
            return bar(render_calendar(NOV, self.codes, TODAY, prev, nxt))

        first = row(None, date(2026, 12, 1))
        self.assertIn('<tg-button type="disabled">←</tg-button>', first)
        self.assertIn('style="primary">→</tg-button>', first)
        last = row(date(2026, 10, 1), None)
        self.assertIn('style="primary">←</tg-button>', last)
        self.assertIn('<tg-button type="disabled">→</tg-button>', last)
        only = row(None, None)
        self.assertEqual(only.count('type="disabled"'), 2)
        for r in (first, last, only):
            self.assertEqual(r.count("<tg-button "), 4)

    def test_target_in_every_button(self):
        page = render_calendar(NOV, self.codes, TODAY, date(2026, 10, 1), date(2026, 12, 1), BIG_ID, LONG_NAME)
        self.assertTrue(page.startswith("<h5>Бронь за сотрудника: Александра К.</h5><h2>"))
        self.assertEqual({unpack(d).cmd for d, _ in buttons(bar(page))}, {"today", "month"})  # и «Сегодня»
        self.assertTrue(all(unpack(d).target == BIG_ID for d, _ in buttons(page)))
        self.assertNotIn("Бронь за сотрудника", render_calendar(NOV, self.codes, TODAY, None, None))


BOSS = Person(user_id=777, full_name="Андреева Анна")
# Демо из пробы: Стол 1: места 1, 2 (номера 1, 2), руководитель (3); Стол 2: места 3-10 (номера 4-11)
DEMO = {1: "Волков Сергей", 2: "Петров Дмитрий", 4: "Кузнецов Максим", 5: "Белова Анна", 7: "Козлов Дмитрий",
        8: "Константинопольский Максимилиан", 10: "Смирнов Александр"}


def day_page(holders=None, me=0, boss=BOSS, capacity=None, readonly=False, queue=(), target=None, target_name=None,
             cal_date=date(2026, 11, 26)):
    """Экран дня через build_day_state, как в WidgetUseCase.rich_day. holders: {seat_no: «Фамилия Имя»},
    user_id занявшего 100 + seat_no; me: user_id того, чей это день"""
    holders = holders or {}
    hs = [SeatHolder(user_id=100 + n, full_name=name, seat_no=n, confirmed=True) for n, name in holders.items()]
    day = DaySeats(cal_date=cal_date, capacity=capacity or len(SEATS), holders=hs,
                   queue=[QueueEntry(user_id=uid, full_name="Очередь Ольга") for uid in queue])
    state = json.loads(build_day_state(day, SEATS, me or 1, "Я Я", True, readonly, today=TODAY,
                                       extra_taken=1 if boss else 0))
    return render_day(cal_date, state, day, boss, target, target_name), state


def blocks(page: str):
    """[(открыт ли, заголовок, содержимое)] блоков столов"""
    return [(bool(o), summary, body) for o, summary, body in
            re.findall(r"<details( open)?><summary>(.*?)</summary>(.*?)</details>", page)]


def seat_buttons(page: str):
    """Кнопки мест по порядку схемы: (подпись, атрибуты) из рядов кнопок внутри блоков столов"""
    out = []
    for _, _, body in blocks(page):
        for row in re.findall(r"<tg-button-row>(.*?)</tg-button-row>", body):
            out += [(label, attrs) for attrs, label in re.findall(r"<tg-button ([^>]*)>(.*?)</tg-button>", row)]
    return out


def chair(n: int) -> str:
    return CHAIR + str(n).translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))


def badge(n: int) -> str:
    return f'<tg-emoji emoji-id="{SEAT_BADGE[n]}">📅</tg-emoji> '


def name_cells(body: str):
    """Ячейки таблицы имён (первая таблица блока) по порядку"""
    return re.findall(r'<td align="left" valign="top">(.*?)</td>', body.split("</table>")[0])


class DayTest(unittest.TestCase):
    D = date(2026, 11, 26)

    def test_seat_numbers_on_scheme(self):
        """Подряд вместе с руководителем, столы сверху вниз, ряд от окна к коридору"""
        self.assertEqual(SEAT_NUMBERS, {1: 1, 2: 2, BOSS_SEAT: 3, **{n: n + 1 for n in range(3, 11)}})

    def test_layout(self):
        page, state = day_page(DEMO, me=104)
        self.assertTrue(page.startswith("<h2>Чт, 26 ноября</h2><h6>Свободно 3 из 11</h6><details"))
        got = blocks(page)
        self.assertEqual(len(got), 2)
        desk1, desk2 = got
        self.assertEqual(desk1[1], emoji_strip(DESK_ICON["Стол 1"]) + " нет мест")       # 1, 2 и руководитель
        self.assertEqual(desk2[1], emoji_strip(DESK_ICON["Стол 2"]) + " свободно 3 из 8")
        self.assertEqual((desk1[0], desk2[0]), (False, True))   # своё место и свободные только на Столе 2
        for n, (_, _, body) in zip(("Стол 1", "Стол 2"), got):   # имена без рамки, ряд мест, строка стола, ряд мест
            parts = re.findall(r"<table compact>|<tg-button-row>", body)
            self.assertEqual(parts, ["<table compact>", "<tg-button-row>", "<table compact>", "<tg-button-row>"])
            self.assertNotIn("bordered", body)
            self.assertIn(f'<td align="left" valign="middle">{emoji_strip(ROW_WINDOW)}</td>'
                          f'<td align="center" valign="middle">{emoji_strip(DESK_ROW[n])}</td>', body)
            self.assertIn(f'<td align="right" valign="middle">{emoji_strip(ROW_CORRIDOR)}</td>', body)
        self.assertFalse(desk1[2].endswith("<hr/>"))
        self.assertTrue(desk2[2].endswith("<hr/>"))              # разделитель внутри блока последнего стола
        self.assertTrue(page.endswith("</details><tg-button-row>" + bar(page)[len("<tg-button-row>"):]))

    def test_names_table(self):
        page, _ = day_page(DEMO, me=104)
        desk1, desk2 = blocks(page)
        # Стол 1: верхний ряд целиком чужой и в таблицу не попадает; окно слева, коридор справа
        self.assertEqual(name_cells(desk1[2]), [
            f'<a href="tg://user?id=101">{badge(1)}Сергей В.</a>', f'<a href="tg://user?id=777">{badge(3)}Анна А.</a>',
            f'<a href="tg://user?id=102">{badge(2)}Дмитрий П.</a>', "—"])
        cells = name_cells(desk2[2])
        self.assertEqual(cells[:4], [
            f"{badge(4)}<i>Свободно</i>", f'<a href="tg://user?id=105">{badge(6)}Анна Б.</a>',
            f'<a href="tg://user?id=104">{badge(5)}<b>Максим К.</b></a>', f"{badge(7)}<i>Свободно</i>"])
        self.assertEqual(cells[7], f'<a href="tg://user?id=110">{badge(11)}Александр С.</a>')
        self.assertEqual(desk2[2].count("<b>"), 1)                                        # своё имя полужирным

    def test_names_table_without_filler(self):
        """Без невидимого заполнения (на iPhone «⠀» шире расчёта, строки скакали); ячейки по левому краю и по верху"""
        page, _ = day_page(DEMO, me=104)
        for _, _, body in blocks(page):
            names = body.split("</table>")[0]
            for ch in ("\u2800", "\u00a0", "\u2060"):
                self.assertNotIn(ch, names)
            self.assertNotIn('valign="middle"', names)
            self.assertEqual(names.count("<td "), names.count('<td align="left" valign="top">'))

    def test_seat_buttons(self):
        page, _ = day_page(DEMO, me=104)
        got = seat_buttons(page)
        self.assertEqual(len(got), 16)
        self.assertEqual(got[:4], [("—", 'type="disabled"')] * 4)                          # чужие места
        self.assertEqual(got[4:8], [(chair(1), 'type="disabled"'), (chair(2), 'type="disabled"'),
                                    (chair(3), 'type="disabled"'), ("—", 'type="disabled"')])   # руководитель
        self.assertEqual(got[8][0], chair(4))
        self.assertIn('style="success"', got[8][1])
        self.assertIn('style="primary"', got[9][1])                                        # своё место
        self.assertEqual(got[10], (chair(6), 'type="disabled"'))                           # занято
        cbs = {unpack(d).seat: unpack(d).cmd for d, _ in buttons(page) if unpack(d).cmd in ("seat", "name")}
        self.assertEqual(cbs, {"3": "seat", "6": "seat", "9": "seat", "4": "name"})       # seat_no из БД
        self.assertEqual(page.count('style="success"'), 3)

    def test_desk_without_free_seats_and_full_day(self):
        full = {n: f"Фамилия{n} Имя" for n in SEATS}
        page, state = day_page(full)
        self.assertEqual(state["h"], "Мест нет")
        self.assertEqual([o for o, _, _ in blocks(page)], [False, False])   # мест нет нигде: всё свёрнуто
        self.assertTrue(all(s.endswith(" нет мест") for _, s, _ in blocks(page)))
        self.assertNotIn('style="success"', page)
        self.assertIn("В очередь", page)
        queued, state = day_page(full, me=5000, queue=(5000,))
        self.assertEqual(state["h"], "Мест нет, вы №1 в очереди")
        self.assertIn("Выйти из очереди", queued)
        self.assertEqual([o for o, _, _ in blocks(queued)], [False, False])

    def test_open_desks_without_own_seat(self):
        """Без своего места раскрыты столы со свободными местами"""
        only_desk1_free = {n: f"Фамилия{n} Имя" for n in range(3, 11)}
        page, _ = day_page(only_desk1_free)
        self.assertEqual([o for o, _, _ in blocks(page)], [True, False])
        page, _ = day_page({1: "Волков Сергей", 2: "Петров Дмитрий"})
        self.assertEqual([o for o, _, _ in blocks(page)], [False, True])
        page, _ = day_page({})
        self.assertEqual([o for o, _, _ in blocks(page)], [True, True])

    def test_own_seat_opens_only_its_desk(self):
        """Стол со своим местом раскрыт и тогда, когда на нём нет свободных мест, а на другом есть; другой свёрнут"""
        busy = {n: f"Фамилия{n} Имя" for n in range(3, 11)}
        page, _ = day_page({**busy, 1: "Я Я"}, me=101)
        self.assertEqual([o for o, _, _ in blocks(page)], [True, False])
        page, _ = day_page({**busy, 1: "Волков Сергей"}, me=104)    # свой стол полный, на Столе 1 место 2 свободно
        self.assertEqual([o for o, _, _ in blocks(page)], [False, True])
        page, _ = day_page({1: "Я Я"}, me=101)                       # свободные есть на обоих столах
        self.assertEqual([o for o, _, _ in blocks(page)], [True, False])
        self.assertIn('<a href="tg://user?id=101">' + badge(1) + "<b>Я.</b>", page.replace("Я Я.", "Я."))

    def test_header_counts_boss(self):
        _, with_boss = day_page({1: "Волков Сергей"})
        self.assertEqual(with_boss["h"], "Свободно 9 из 11")
        page, without = day_page({1: "Волков Сергей"}, boss=None)
        self.assertEqual(without["h"], "Свободно 9 из 10")

    def test_past_day_counts_boss(self):
        """«Было N человек» с руководителем, как «занято N из Y» в заголовках столов; без руководителя без него"""
        past = date(2026, 11, 19)
        _, with_boss = day_page({1: "Волков Сергей", 4: "Я Я"}, readonly=True, cal_date=past)
        self.assertEqual(with_boss["h"], "Было 3 человека")
        _, without = day_page({1: "Волков Сергей", 4: "Я Я"}, boss=None, readonly=True, cal_date=past)
        self.assertEqual(without["h"], "Было 2 человека")
        _, nobody = day_page({}, readonly=True, cal_date=past)
        self.assertEqual(nobody["h"], "Был 1 человек")                     # только руководитель
        _, future = day_page({1: "Волков Сергей"}, readonly=True)
        self.assertEqual(future["h"], "Бронирование закрыто")

    def test_no_boss(self):
        """Руководитель не выбран: место без имени, неактивное, в «из Y» не входит"""
        page, _ = day_page({1: "Волков Сергей"}, boss=None)
        desk1 = blocks(page)[0]
        self.assertEqual(desk1[1], emoji_strip(DESK_ICON["Стол 1"]) + " свободно 1 из 2")
        self.assertEqual(name_cells(desk1[2])[1], badge(3) + "—")
        self.assertIn((chair(3), 'type="disabled"'), seat_buttons(page))
        self.assertNotIn("tg://user?id=777", page)

    def test_long_names_are_cut_to_column(self):
        """Имя укорачивается до NAME_ROOM_PT; так в одной строке помещаются два длинных имени"""
        page, _ = day_page({8: "Константинопольский Максимилиан", 9: "Ли Ян", 3: "Александрова Александра",
                            7: "Мононим", 10: "Х Константинопольская", 4: "Абдурахмангаджиев Христофорович"}, me=104)
        cells = " ".join(name_cells(blocks(page)[1][2]))
        self.assertIn(">" + badge(9) + "Максимилиан К.</a>", cells)       # помещаются целиком
        self.assertIn(">" + badge(4) + "Александра А.</a>", cells)
        self.assertIn(">" + badge(10) + "Ян Л.</a>", cells)
        self.assertIn(">" + badge(8) + "Мононим</a>", cells)
        self.assertIn(">" + badge(11) + "Константин… Х.</a>", cells)
        self.assertIn("<b>Христофо… А.</b>", cells)                         # полужирное шире
        for name, longer, bold in (("Константин… Х.", "Константино… Х.", False),
                                   ("Христофо… А.", "Христофор… А.", True)):
            self.assertLessEqual(text_width(name, bold), NAME_ROOM_PT)
            self.assertGreater(text_width(longer, bold), NAME_ROOM_PT)    # укорочено ровно до места
        self.assertEqual(fit_name("Максимилиан К.", 1), "Ма… К.")           # короче 2 букв не режет

    def test_names_are_escaped(self):
        page, _ = day_page({1: "<b>Хак</b> <i>"})
        self.assertNotIn("<b>Хак", page)
        self.assertIn("&lt;i&gt; &lt;", page)

    def test_readonly_day(self):
        """Закрытый день: все кнопки мест серые, своё primary; свободное «—»; раскрыт только стол со своим местом"""
        page, state = day_page({1: "Волков Сергей", 4: "Я Я"}, me=104, readonly=True, cal_date=date(2026, 11, 19))
        self.assertEqual(state["h"], "Было 3 человека")                    # двое и руководитель
        self.assertEqual(seat_buttons(page)[9], (chair(5), 'type="disabled" style="primary"'))
        self.assertNotIn('style="success"', page)
        self.assertNotIn("<i>Свободно</i>", page)
        self.assertEqual(name_cells(blocks(page)[1][2])[0], badge(4) + "—")
        desk1, desk2 = blocks(page)
        self.assertEqual((desk1[0], desk2[0]), (False, True))
        self.assertEqual(desk1[1], emoji_strip(DESK_ICON["Стол 1"]) + " занято 2 из 3")    # с руководителем
        self.assertEqual(desk2[1], emoji_strip(DESK_ICON["Стол 2"]) + " занято 1 из 8")
        self.assertEqual([unpack(d).cmd for d, _ in buttons(page)], ["month"])            # только «Назад»
        nobody, state = day_page({}, readonly=True)
        self.assertEqual(state["h"], "Бронирование закрыто")   # будущий закрытый день
        self.assertEqual([o for o, _, _ in blocks(nobody)], [False, False])

    def test_over_capacity_seats_closed(self):
        """Лимит дня выбран раньше, чем места на схеме: оставшиеся места неактивны, свободных нет"""
        page, state = day_page({1: "Волков Сергей", 2: "Петров Дмитрий"}, capacity=2)
        self.assertNotIn('style="success"', page)
        self.assertEqual(name_cells(blocks(page)[1][2])[0], badge(4) + "—")
        self.assertIn("В очередь", page)

    def test_actions(self):
        booked, _ = day_page({4: "Я Я"}, me=104)
        self.assertIn("Отменить бронь", booked)
        free, _ = day_page({})
        self.assertNotIn("Отменить", free)
        self.assertNotIn("В очередь", free)

    def test_target(self):
        """Бронь за сотрудника: его место своё, target во всех кнопках"""
        page, _ = day_page({4: "Кузнецов Максим"}, me=104, target=BIG_ID, target_name="Кузнецов Максим")
        self.assertTrue(page.startswith("<h5>Бронь за сотрудника: Максим К.</h5><h2>"))
        self.assertIn("<b>Максим К.</b>", page)
        self.assertTrue(all(unpack(d).target == BIG_ID for d, _ in buttons(page)))

    def test_back_returns_month_of_day(self):
        page, _ = day_page({})
        back = [unpack(d) for d, label in buttons(page) if label == "Назад"]
        self.assertEqual([(b.cmd, b.day) for b in back], [("month", "2026-11-01")])

    def test_layout_has_pictures(self):
        """Новый стол или место в OFFICE_LAYOUT: нужны картинки (src/ui/rich/emoji.py, раздел «Экран дня»)"""
        tables = {item[1] for item in OFFICE_LAYOUT if not isinstance(item, str)}
        self.assertTrue(tables <= set(DESK_ICON), "нет пиктограммы стола: DESK_ICON")
        self.assertTrue(tables <= set(DESK_ROW), "нет крупной картинки стола: DESK_ROW")
        self.assertTrue(set(SEAT_NUMBERS.values()) <= set(SEAT_BADGE), "нет номера в рамке: SEAT_BADGE")

    def test_fallbacks_without_pictures(self):
        self.assertEqual(desk_picture("Стол 3"), "СТОЛ 3")
        self.assertEqual(seat_badge(13)[0], "13 ")
        self.assertEqual(desk_picture("Стол 1"), emoji_strip(DESK_ROW["Стол 1"]))
        self.assertEqual(desk_summary("Стол 3", [], False), "Стол 3: нет мест")


class LimitsTest(unittest.TestCase):
    def heaviest(self):
        cal = render_calendar(date(2026, 12, 1), "b" * 31, date(2026, 12, 31), date(2026, 11, 1), date(2027, 1, 1),
                              BIG_ID, LONG_NAME)
        cal = max(cal, render_calendar(date(2026, 12, 1), "bvqn" * 7 + "bvq", date(2026, 12, 31),
                                       date(2026, 11, 1), date(2027, 1, 1), BIG_ID, LONG_NAME), key=len)
        hs = [SeatHolder(user_id=BIG_ID - n, full_name=LONG_NAME, seat_no=n, confirmed=True) for n in SEATS]
        day = DaySeats(cal_date=date(2026, 12, 3), capacity=len(SEATS), holders=hs,
                       queue=[QueueEntry(user_id=2000 + i, full_name=LONG_NAME) for i in range(8)])
        state = json.loads(build_day_state(day, SEATS, BIG_ID - 4, LONG_NAME, False, False, today=TODAY,
                                           extra_taken=1))
        page = render_day(date(2026, 12, 3), state, day, Person(BIG_ID, LONG_NAME), BIG_ID, LONG_NAME)
        return cal, page

    def test_callback_data_fits_64_bytes(self):
        cal, day = self.heaviest()
        found = all_buttons(cal) + all_buttons(day)
        self.assertTrue(found)
        for data, _ in found:
            self.assertLessEqual(len(data.encode()), 64, data)          # и «Настройки» (SettingsCB)
        for data, _ in buttons(cal) + buttons(day):
            self.assertEqual(unpack(data).target, BIG_ID)

    def test_size_within_rich_limit(self):
        for page in self.heaviest():
            self.assertLess(len(page), MAX_RICH_CHARS // 2, len(page))

    def test_custom_emoji_within_limit(self):
        """Сверх ~92 эмодзи сервер заменяет новые id подписью, missing_emoji увёл бы в базовый сценарий"""
        for page in self.heaviest():
            self.assertLess(page.count("<tg-emoji"), MAX_RICH_EMOJI)

    def test_unique_idk_per_button(self):
        cal, _ = self.heaviest()
        idks = [unpack(d).idk for d, _ in buttons(cal)]
        self.assertGreater(len(set(idks)), len(idks) - 3)        # 4 символа из 62: совпадения редки


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



class RichBot:
    """Bot API для show_rich: sendRichMessage отвечает сообщением с эмодзи из HTML, deleteMessage записывается"""
    def __init__(self):
        self.calls, self.deleted = [], []

    async def __call__(self, method):
        self.calls.append(method)
        ids = sorted(emoji_ids(method.rich_message.html))
        return Message.model_validate({
            "message_id": 500 + len(self.calls), "date": 0, "chat": {"id": 5, "type": "private"},
            "rich_message": {"blocks": [{"type": "paragraph", "text": [
                {"type": "custom_emoji", "custom_emoji_id": i, "alternative_text": "📅"} for i in ids] + [" x"]}]},
        })

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


class FreshDayWindowTest(unittest.IsolatedAsyncioTestCase):
    """Экран дня из календаря новым сообщением без звука: клиент не помнит раскрытые в другом дне блоки"""
    async def asyncSetUp(self):
        self.bot = RichBot()
        self.widgets = WidgetUseCase(self.bot, None, TechService(FakeStore(), None), None, None)
        self.page, _ = day_page(DEMO, me=104)

    async def test_new_silent_message_replaces_tapped_window(self):
        await self.widgets.tech.set_booking_widget(5, 100, None, rich_view="m2026-11-01")
        await self.widgets.show_rich(5, self.page, "d2026-11-26", None, None, silent=True, tapped=100)
        sent = self.bot.calls[0]
        self.assertIsInstance(sent, SendRichMessage)
        self.assertTrue(sent.disable_notification)
        self.assertEqual(self.bot.deleted, [100])                                  # нажатое окно и есть прежнее
        pointer = await self.widgets.tech.get_booking_widget(5)
        self.assertEqual((pointer.message_id, pointer.view), (501, "d2026-11-26"))

    async def test_tapped_old_window_removed_too(self):
        """Нажали в старом окне, а в указателе другое: удаляются оба"""
        await self.widgets.tech.set_booking_widget(5, 200, None, rich_view="m2026-11-01")
        await self.widgets.show_rich(5, self.page, "d2026-11-26", None, None, silent=True, tapped=100)
        self.assertEqual(sorted(self.bot.deleted), [100, 200])

    async def test_plain_send_is_not_silent(self):
        await self.widgets.show_rich(5, self.page, "d2026-11-26")
        self.assertIsNone(self.bot.calls[0].disable_notification)
        self.assertEqual(self.bot.deleted, [])


if __name__ == "__main__":
    unittest.main()
