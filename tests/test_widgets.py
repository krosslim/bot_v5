"""Проверки виджетов без БД и Telegram: python -m unittest discover -s tests"""
import json
import re
import unittest
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
from src.utils.today import widget_data_expiry

from src.handlers.widget.widget_query_handler import parse_group, parse_private
from src.ui.widgets.layout import OFFICE_LAYOUT, SEATS
from src.ui.widgets import render as render_module
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
        boss = short_name(LONG_NAME)
        for html in (render_booking_widget(), render_booking_widget(1234567890123, LONG_NAME, boss),
                     render_digest_widget(), render_digest_widget(boss)):
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
            # В местах (flex) спиннер центрирует align-self: margin:auto у flex-элемента клиент не учитывает
            self.assertRegex(html, r"\.sp\{[^}]*align-self:center")

    def test_day_hint_without_color_dot(self):
        """Под датой только текст («Свободно 5 из 10», ФИО, сообщение), без цветной точки"""
        html = render_booking_widget()
        self.assertNotIn('class="dt', html)
        self.assertIn("+'>'+esc(fl?fl[1]:D.h)+'</small>", html)

    def test_long_admin_name_does_not_grow_html(self):
        """Подпись «Бронь за сотрудника» — короткое имя: длина ФИО не приближает виджет к лимиту 4 КБ"""
        boss = short_name("Константинопольский Александр")    # руководитель на схеме — тоже в худшем значении
        short = widget_size(render_booking_widget(1, "Иванов Иван", boss))[1]
        huge = widget_size(render_booking_widget(1234567890123, "Константинопольская-Длинноименная " * 3, boss))[1]
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
        """Не больше 16 элементов с opacity < 1 одновременно, иначе «Paint limit exceeded». Нажатую кнопку
        затемняет UA-стиль клиента (--tg-button-pressed-opacity), нажатое место — своё правило :active (тоже одно).
        Ещё opacity у подложки кнопок действий под схемой (их не больше двух)"""
        css = {k: html.split("</style>")[0] for k, html in
               (("booking", render_booking_widget()), ("digest", render_digest_widget()))}
        self.assertEqual(re.findall(r"([^{}]+)\{[^}]*opacity", css["booking"]),
                         ["[data-n]:active,[data-s]:active", ".bt:before"])
        self.assertEqual(re.findall(r"([^{}]+)\{[^}]*opacity", css["digest"]), ["[data-s]:active"])

    def test_seats_are_divs(self):
        """Места — <div>, не <button>: кнопки клиент рисует сам и скругляет одним радиусом, «стулья» пропадают
        (scripts/widget_css_probe.py, раунд 2). Нажатия ловит общий обработчик по data-атрибутам"""
        for html in (render_booking_widget(), render_digest_widget("Дмитрий К.")):
            js = html.split("<script>")[1]
            self.assertNotIn('<button class="s', js)
        self.assertIn("return'<div'+(n?' data-n=\"'+n+'\"':'')+' class=\"s '+c+'\">", render_booking_widget())

    def test_buttons_use_client_style(self):
        """Шрифт, скругление и отступы кнопок — из токенов клиента --tg-button-*. Фон и цвет текста свои:
        клиенты передают в --tg-button-bg цвет основной кнопки, и «Назад» выглядел бы как главное действие"""
        for html in (render_booking_widget(), render_digest_widget()):
            css = html.split("</style>")[0]
            self.assertNotRegex(css, r"[>}]button[{:]")                 # нет общего сброса всех кнопок
            self.assertNotIn("font:14px", css)
            self.assertNotRegex(css, r"var\(--tg-theme-[a-z-]+,")      # палитру рендерер задаёт всегда
            self.assertNotIn("\n", css.split("<style>")[1])               # переносы в CSS убираются при сборке
        html = render_booking_widget()
        # Подложка — полупрозрачный слой цвета текста (акцент или красный) поверх кнопки: текст того же цвета
        # под ней не меняется, поэтому z-index не нужен
        self.assertIn(".bt{flex:1;position:relative;background:none;color:var(--ac)}", html)
        self.assertIn("background:currentColor;opacity:.12}", html)
        # Скругление подложки — явным токеном: border-radius:inherit клиент не поддерживает (квадратные кнопки)
        self.assertIn("border-radius:var(--tg-button-radius,8px);background:currentColor", html)
        self.assertNotIn("inherit;background:currentColor", html)

    def test_templates_join_safely(self):
        """Переносы в <script> убираются при сборке: строки должны заканчиваться на ; { } , или + и не начинаться
        с ( [ / + - ` — иначе склейка поменяет разбор (автоподстановка точки с запятой)"""
        for name in ("booking", "digest"):
            js = (Path(render_module.__file__).parent / f"{name}.html").read_text(encoding="utf-8")
            lines = [l.strip() for l in js.split("<script>")[1].split("</script>")[0].split("\n") if l.strip()]
            for a, b in zip(lines, lines[1:]):
                self.assertIn(a[-1], ";{},+", (name, a[-40:]))
                self.assertNotIn(b[0], "([/+-`", (name, b[:40]))

    def test_chair_corners_use_longhands(self):
        """Скругление «стульев»: фон с разными углами клиент рисует (scripts/widget_css_probe.py), а обрезку
        overflow:hidden — по одному радиусу, и углы снова одинаковые. Поэтому у мест нет overflow:hidden:
        длинное имя обрезает сам <em> (max-width и многоточие)"""
        for html in (render_booking_widget(), render_digest_widget()):
            css = html.split("</style>")[0]
            seat = re.search(r"\}\.s\{([^}]*)\}", css).group(1)
            self.assertNotIn("overflow", seat)
            self.assertIn(".s em{max-width:100%;", css)
            self.assertIn("border-bottom-left-radius:4px", css)
            self.assertIn(".tb+.rw .s{border-radius:12px;border-top-left-radius:4px;border-top-right-radius:4px}", css)

    def test_boss_seat(self):
        """Место руководителя: подпись из админки и полное имя по нажатию; не выбран — штриховка"""
        html = render_booking_widget(None, None, "Дмитрий К.")
        self.assertIn('B="Дмитрий К."', html)
        self.assertIn("if(c=='b')return B?nm(B,'bs','b'):'<div class=\"s o\"></div>'", html)
        self.assertIn('B=""', render_booking_widget())
        digest = render_digest_widget("Дмитрий К.")
        self.assertIn('B="Дмитрий К."', digest)
        self.assertIn('data-s="b"', digest)
        self.assertIn('B=""', render_digest_widget())

    def test_digest_header_and_status(self):
        """Дайджест (вариант B): под датой «Свободно f из c» / «Все места заняты», ФИО или результат нажатия одной
        строкой — успех зелёным, ошибка и «нужен бот» красным; нижняя строка — подсказка дня, следующий шаг (h)
        или ссылка на бота (b). Результат 3 секунды, со ссылкой — 6. Лоадер только на свободном месте"""
        html = render_digest_widget()
        self.assertIn("'Свободно '+C.f+' из '+C.c:'Все места заняты'", html)
        self.assertIn("esc(ts?ts.m:nv||(C.x?'Бронирование закрыто'", html)
        self.assertIn("(ts?' class=\"'+(ts.ok?'ok':'er')+'\"':'')", html)
        self.assertIn("(v?nm(v[0]):busy==c?'<i class=\"sp\"></i>'", html)       # занятое место — без лоадера
        self.assertIn("if(j.n)fio(j.n);", html)
        self.assertIn("j.b?6e3:3e3", html)
        self.assertIn("(ts.b==2?'Зарегистрироваться':'Встать в очередь')+' в боте ›</button>'", html)
        self.assertIn("ts&&ts.h?esc(ts.h)", html)
        self.assertIn("'<i></i>Нажмите на своё место, чтобы подтвердить'", html)
        self.assertIn("'Встать в очередь можно <button data-l=\"1\">в боте ›</button>'", html)
        self.assertRegex(html, r"\.nt\{[^}]*height:19px")                       # нижняя часть — одна строка
        self.assertNotIn("занято '", html)
        self.assertIn(".tk,.bs{background:var(--bg);color:var(--hn)}", html)
        self.assertNotIn("--nm", html)

    def test_full_name_on_tap(self):
        """Места с именами — кнопки: запрос n:<дата>:<место>, ответ {"n": ФИО} серым вместо подсказки дня"""
        html = render_booking_widget()
        self.assertIn("return v?nm(v,c==D.m?'me':'tk',c)", html)
        self.assertIn("else if(t.n)rq('n:'+D.d+':'+t.n,'n')", html)
        self.assertIn("j.n?['',j.n]", html)

    def test_haptics_only_for_action_results(self):
        """Вибрация — только на результат действия (ok / er): открытие дня в календаре и ФИО — без неё"""
        html = render_booking_widget()
        self.assertIn("(j.ok||j.er)&&H&&H.notificationOccurred(j.er?'error':'success')", html)
        self.assertEqual(html.count("notificationOccurred"), 1)

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
        r = parse_private("n:2026-11-12:b@42")
        self.assertEqual((r.cmd, r.seat, r.target), ("n", "b", 42))
        self.assertEqual(parse_private("n:2026-11-12:7").seat, 7)
        for bad in ("x:2026-11-12", "b:2026-13-40:1", "b:2026-11-12:1@", "", "d:2026-11-12;drop", "n:2026-11-12:bb"):
            self.assertIsNone(parse_private(bad), bad)
        self.assertLessEqual(len("lq:2026-11-12:10@12345678901234567890".encode()), 64)

    def test_group(self):
        self.assertEqual(parse_group("s:2026-11-10:5"), (date(2026, 11, 10), 5))
        self.assertIsNone(parse_group("b:2026-11-10:5"))
        self.assertEqual(parse_group("s:2026-11-10:b"), (date(2026, 11, 10), "b"))
        self.assertIsNone(parse_group("s:2026-11-10:x"))


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

    def test_digest_free_and_total(self):
        """«Свободно f из c» под датой — как в личном виджете: места сверх лимита дня не считаются"""
        d = date(2026, 11, 12)
        holders = [SeatHolder(1, "Смирнов Алексей", 1, True), SeatHolder(2, "Кузнецова Мария", 3, False)]
        data = json.loads(build_digest_data(DaySeats(d, 10, holders), SEATS, closed=False))
        self.assertEqual((data["f"], data["c"]), (8, 10))
        limited = json.loads(build_digest_data(DaySeats(d, 4, holders), SEATS, closed=False))
        self.assertEqual((limited["f"], limited["c"]), (2, 4))
        full = json.loads(build_digest_data(_full_day(d), SEATS, closed=False))
        self.assertEqual((full["f"], full["c"]), (0, len(SEATS)))

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

    def test_calendar_future_months(self):
        """Вперёд — future_months месяцев после текущего («Месяцы вперёд» в админке); дни после горизонта бронирования серые (x)"""
        today, horizon = date(2026, 11, 9), date(2026, 11, 29)
        days = [CalendarDay(date(2026, 12, 7), False, False, True, 0, 10, None),
                CalendarDay(date(2026, 12, 12), True, False, False, 0, 10, None),
                CalendarDay(date(2027, 1, 1), False, True, False, 0, 10, None)]
        data = json.loads(build_calendar_data(days, today, today, horizon, future_months=2))
        self.assertEqual([m[0] for m in data["m"]], ["2026-11", "2026-12", "2027-01"])
        self.assertEqual(data["c"], 0)
        dec, jan = data["m"][1][2], data["m"][2][2]
        self.assertEqual((dec[6], dec[11], jan[0]), ("x", "w", "h"))
        # 0 — как раньше: до месяца горизонта, а горизонт дальше future_months не обрезается
        self.assertEqual([m[0] for m in json.loads(build_calendar_data([], today, today, horizon))["m"]], ["2026-11"])
        self.assertEqual([m[0] for m in json.loads(build_calendar_data([], today, today, date(2026, 12, 6),
                                                                       future_months=0))["m"]], ["2026-11", "2026-12"])

    def test_calendar_future_fits_chat_data(self):
        """Не влезает в chat_data — отбрасываются самые далёкие от сегодня месяцы с обеих сторон,
        текущий месяц и месяцы до горизонта бронирования остаются"""
        today, horizon = date(2026, 11, 9), date(2026, 12, 6)
        out = build_calendar_data([], today, today, horizon, history_months=12, future_months=12)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        data = json.loads(out)
        keys = [m[0] for m in data["m"]]
        self.assertEqual(keys[data["c"]], "2026-11")
        self.assertIn("2026-12", keys)
        back, ahead = data["c"], len(keys) - 1 - data["c"]
        self.assertLessEqual(abs(back - ahead), 1)
        self.assertGreater(back, 3)
        out = build_calendar_data([], today, today, horizon, future_months=36)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        only_future = json.loads(out)
        self.assertEqual([m[0] for m in only_future["m"]][:2], ["2026-11", "2026-12"])

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
