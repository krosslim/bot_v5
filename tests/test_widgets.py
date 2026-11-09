"""Проверки виджетов без БД и Telegram: python -m unittest discover -s tests"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
from src.utils.today import confirm_deadline, widget_data_expiry

from src.handlers.widget.widget_query_handler import DigestRequest, parse_digest, parse_private
from src.ui.widgets.layout import OFFICE_LAYOUT, SEATS
from src.ui.widgets import render as render_module
from src.ui.widgets.render import (MAX_ZLIB_BYTES, _merge_foreign, render_booking_widget, render_digest_widget,
                                   widget_layout, widget_size)
from src.ui.widgets.state import (MAX_DATA_BYTES, CalendarDay, DaySeats, QueueEntry, SeatHolder, build_calendar_data,
                                  build_day_state, build_digest_data, data_size, day_code, people,
                                  shift_month, short_name, was_people)

LONG_NAME = "Константинопольская Александра"   # «Александра К.» — самое длинное, что влезает


def _full_day(cal_date: date, confirmed: bool = False) -> DaySeats:
    holders = [SeatHolder(user_id=1000 + n, full_name=LONG_NAME, seat_no=n, confirmed=confirmed) for n in SEATS]
    queue = [QueueEntry(user_id=2000 + i, full_name=LONG_NAME) for i in range(8)]
    return DaySeats(cal_date=cal_date, capacity=len(SEATS), holders=holders, queue=queue)


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
        self.assertIn('data-e="1">\'+(pd==\'e\'?SP:\'Выйти\')+\'</button>', html)
        self.assertIn("rq('x','e')", html)

    def test_back_button_at_bottom(self):
        html = render_booking_widget()
        self.assertIn('<div class="ft"><button class="bt" data-k="1">Назад</button>\'+q+\'</div>', html)
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
        """«Свободно» в легенде нет: у дней нет обводки, свободный день — обычное число без точки"""
        html = render_booking_widget()
        self.assertIn("'bБронь|vБыл(а)|qОчередь|nМест нет'", html)
        self.assertIn("if(k.indexOf(x[0])>=0)", html)
        self.assertNotIn("box-shadow:inset", html.split("</style>")[0].split(".mp{")[0])

    def test_calendar_header_and_day_colors(self):
        """Месяц слева, стрелки справа (рамка на CSS: SVG стоит ~100 Б после zlib). Шапка капсом, СБ и ВС красные.
        Красное число — нерабочий день по is_workday (коды w и h), рабочая суббота приходит обычным кодом"""
        html = render_booking_widget()
        self.assertIn("<div class=\"hd\"><div data-g=\"1\"'+(M!=(C.c||0)?' class=\"ac\"':'')+'><b>", html)
        self.assertIn(".ac b{color:var(--ac)}", html)
        self.assertIn("'ПН ВТ СР ЧТ ПТ СБ ВС'", html)
        self.assertIn(".gr small:nth-child(n+6){color:var(--r)}", html)
        self.assertIn(".w,.h{color:var(--r)}", html)
        self.assertNotIn("<svg", html)

    def test_calendar_hints_and_back_to_current_month(self):
        """Нерабочий и ещё не открытый день («Бронь не открыта») — подсказка на месте легенды, без запроса к боту.
        Нажатие на название месяца возвращает к текущему месяцу"""
        html = render_booking_widget()
        self.assertIn("data-'+(/[whx]/.test(c)?'h=\"'+c:'d=\"')+s", html)
        self.assertIn("flash(['',t.h[0]=='x'?'Бронь не открыта':'Нерабочий день',t.h.slice(1)])", html)
        # Нажатый день — серая подложка цветом (не opacity): пока грузится схема и пока видна подсказка
        self.assertIn("(s==pd||fl&&fl[2]==s?' sel':'')", html)
        self.assertIn(".sel,.c:active{background:var(--sf)}", html)
        self.assertIn("(fl?'<div class=\"lg '+fl[0]+'\">'+esc(fl[1])+'</div>'", html)
        self.assertIn("else if(t.g){if(M!=(C.c||0)){M=C.c||0;", html)
        self.assertEqual(html.count("selectionChanged"), 3)

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
        self.assertLessEqual(huge, MAX_ZLIB_BYTES - 5)

    def test_stale_window_offers_reopen(self):
        html = render_booking_widget()
        self.assertIn("C.x||old()?xp()", html)
        self.assertIn("if(t.o)return rq('o','o')", html)
        self.assertIn("Обновить", html)

    def test_cancel_by_button_not_by_seat(self):
        html = render_booking_widget()
        self.assertIn("D.st=='B'?b('lv','c','Отменить бронь')", html)
        self.assertNotIn("rq('c:'", html)

    def test_no_mass_opacity(self):
        """Не больше 16 элементов с opacity < 1 одновременно, иначе «Paint limit exceeded». Нажатую кнопку
        затемняет UA-стиль клиента (--tg-button-pressed-opacity), нажатое место — своё правило :active (тоже одно).
        Ещё opacity у подложки красных кнопок под схемой (одна на экране)"""
        css = {k: html.split("</style>")[0] for k, html in
               (("booking", render_booking_widget()), ("digest", render_digest_widget()))}
        self.assertEqual(re.findall(r"([^{}]+)\{[^}]*opacity", css["booking"]),
                         ["[data-n]:active,[data-s]:active", ".lv:before"])
        self.assertEqual(re.findall(r"([^{}]+)\{[^}]*opacity", css["digest"]),
                         ["[data-n]:active,[data-s]:active,[data-u]:active", ".lv:before"])

    def test_seats_are_divs(self):
        """Места — <div>, не <button>: кнопки клиент рисует сам и скругляет одним радиусом, «стулья» пропадают
        (scripts/widget_css_probe.py, раунд 2). Нажатия ловит общий обработчик по data-атрибутам"""
        for html in (render_booking_widget(), render_digest_widget("Дмитрий К.")):
            js = html.split("<script>")[1]
            self.assertNotIn('<button class="s', js)
        self.assertIn("return'<div'+(n?' data-n=\"'+n+'\"':'')+' class=\"s '+c+'\">", render_booking_widget())

    def test_buttons_use_client_style(self):
        """Начертание шрифта, скругление и отступы кнопок — из токенов клиента --tg-button-*. Размер шрифта 1em: клиентский
        не следует настройке размера текста. Фон и цвет текста свои:
        клиенты передают в --tg-button-bg цвет основной кнопки, и «Назад» выглядел бы как главное действие"""
        for html in (render_booking_widget(), render_digest_widget()):
            css = html.split("</style>")[0]
            self.assertNotRegex(css, r"[>}]button[{:]")                 # нет общего сброса всех кнопок
            self.assertNotIn("font:14px", css)
            self.assertNotRegex(css, r"var\(--tg-theme-[a-z-]+,")      # палитру рендерер задаёт всегда
            self.assertNotIn("\n", css.split("<style>")[1])               # переносы в CSS убираются при сборке
        html = render_booking_widget()
        # Фон вторичных кнопок — цвет темы secondary_bg, текст — акцент. Красные (отмена, выход из очереди) — свой тон:
        # полупрозрачный слой цвета текста поверх кнопки (как раньше), на secondary_bg красный читается хуже
        # Скругление и отступы остаются клиентскими
        self.assertIn(".bt{flex:1;background:var(--tg-theme-secondary-bg-color);color:var(--ac);font-size:1em}", html)
        self.assertIn(".bt{flex:1;background:var(--tg-theme-secondary-bg-color);color:var(--ac)}", render_digest_widget())
        for h in (html, render_digest_widget()):
            self.assertNotIn(".bt:before", h)
            self.assertIn(".lv{position:relative;color:var(--r);background:none}", h)
            self.assertIn("border-radius:var(--tg-button-radius,8px);background:currentColor;opacity:.12}", h)

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
        self.assertIn("if(c=='b')return B?nm(B,'bs',tp):'<div class=\"s o\"></div>'", digest)   # нажатие → gn
        self.assertIn('B=""', render_digest_widget())

    def test_digest_header_and_status(self):
        """Дайджест v2: под датой «Свободно f из c» / «Все места заняты», в закрытом дне — текст из данных
        («Было 5 человек»). Результат нажатия и полное имя заменяют эту строку на 3 секунды: успех зелёным,
        ошибка красным, имя серым. Вибрация — только на результат действия"""
        html = render_digest_widget()
        self.assertIn("esc(fl?fl[1]:C.x||(C.f?'Свободно '+C.f+' из '+C.c:'Все места заняты'))", html)
        self.assertIn("flash(j.er?['er',j.er]:j.ok?['ok',j.ok]:j.n?['',j.n]:['er',F])", html)
        self.assertIn("(j.ok||j.er)&&H&&H.notificationOccurred(j.er?'error':'success')", html)
        self.assertEqual(html.count("notificationOccurred"), 1)
        self.assertIn("},3000)", html)
        # Цвет результата перебивает серый .hd small: селектор специфичнее (0,2,0 против 0,1,1)
        self.assertIn(".hd .ok{color:var(--g)}.hd .er{color:var(--r)}", html)
        self.assertIn(".hd small{display:block;font-size:14px;line-height:19px;color:var(--hn)}", html)
        self.assertNotIn("Бронирование закрыто", html)
        self.assertIn(".tk,.bs,.me{background:var(--bg);color:var(--hn)}", html)

    def test_digest_timer_and_hint(self):
        """W: таймер до отмены справа от даты, подсказка без времени. Дедлайн приходит в chat_data (e), не в HTML.
        Раз в секунду обновляется только узел таймера, не весь виджет"""
        html = render_digest_widget()
        self.assertIn('<div class="nt"><i></i>Подтвердите, иначе бронь отменится</div>', html)
        self.assertNotIn("DL", html.split("<script>")[1])
        self.assertIn("(S=='W'&&C.e?'<span id=\"tm\" class=\"tm'+(rm()<900?' u':'')+'\">'+fm()+'</span>':'')", html)
        self.assertIn("setInterval(function(){var n=document.getElementById('tm')", html)
        self.assertEqual(html.count("setInterval"), 1)
        self.assertRegex(html, r"\.tm\{[^}]*font-variant-numeric:tabular-nums")

    def test_digest_worst_case_size(self):
        """Цель ТЗ — не больше 3900 Б после zlib; всё, что меняется при отправке (руководитель), в худшем значении"""
        packed = widget_size(render_digest_widget(short_name("Константинопольский Александр")))[1]
        self.assertLessEqual(packed, MAX_ZLIB_BYTES - 80)
        self.assertLessEqual(packed, 3900)

    def test_digest_commands(self):
        """Каждое действие — явная команда g*: сервер не угадывает намерение по месту"""
        html = render_digest_widget()
        for cmd in ("rq('gn'+d+':'+t.n,'n')", "rq('gu'+d+':'+t.u,'n')", "rq('gb'+d+':'+t.s,'s'+t.s)",
                    "rq('g'+t.r+d,t.r)"):
            self.assertIn(cmd, html)
        self.assertNotIn("'s:'", html)

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

    def test_digest(self):
        d = date(2026, 11, 12)
        self.assertEqual(parse_digest("gn:2026-11-12:7"), DigestRequest("n", d, seat=7))
        self.assertEqual(parse_digest("gn:2026-11-12:b"), DigestRequest("n", d, seat="b"))
        self.assertEqual(parse_digest("gu:2026-11-12:1234567890"), DigestRequest("u", d, user_id=1234567890))
        self.assertEqual(parse_digest("gb:2026-11-12:10"), DigestRequest("b", d, seat=10))
        for cmd in "cxql":
            self.assertEqual(parse_digest(f"g{cmd}:2026-11-12"), DigestRequest(cmd, d))
        for bad in ("", "g", "gb:2026-11-12", "gb:2026-11-12:b", "gb:2026-11-12:1234", "gn:2026-11-12",
                    "gn:2026-11-12:bb", "gu:2026-11-12", "gu:2026-11-12:b", "gu:2026-11-12:123456789012345678901",
                    "gc:2026-11-12:1", "gx:2026-11-12:b", "gz:2026-11-12", "gn:2026-13-40:1", "gc:2026-11-12 ",
                    "gx:2026-11-12@1", "s:2026-11-12:1", "Gc:2026-11-12", "gc:2026-11-12\n"):
            self.assertIsNone(parse_digest(bad), bad)
        longest = "gu:2026-11-12:" + "9" * 20
        self.assertIsNotNone(parse_digest(longest))
        self.assertLessEqual(len(longest.encode()), 64)


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

def _worst_digest_day(queue: int = 8) -> DaySeats:
    """Худший случай из ТЗ: 10 мест с длинными именами и 10-значными id, очередь"""
    holders = [SeatHolder(1_000_000_000 + n, LONG_NAME, n, False) for n in SEATS]
    q = [QueueEntry(2_000_000_000 + i, LONG_NAME) for i in range(queue)]
    return DaySeats(date(2026, 11, 12), len(SEATS), holders, q)


class DigestDataTest(unittest.TestCase):
    def test_worst_case_fits_without_shortening(self):
        out = build_digest_data(_worst_digest_day(), SEATS, closed=True)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        data = json.loads(out)
        self.assertEqual(data["s"][0], ["Александра К.", 0, 1_000_000_001])
        self.assertEqual(data["q"][0], ["Александра К.", 2_000_000_000])
        self.assertEqual(len(data["q"]), 8)

    def test_long_queue_keeps_ids_only(self):
        """Не влезает даже с именами по 6 символов — в q остаются только id, по порядку"""
        out = build_digest_data(_worst_digest_day(queue=40), SEATS, closed=False)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        data = json.loads(out)
        self.assertEqual(data["q"], [2_000_000_000 + i for i in range(40)])
        self.assertEqual(len(data["s"][0][0]), 6)
        self.assertEqual(data["s"][0][2], 1_000_000_001)

    def test_format(self):
        d = date(2026, 11, 12)
        holders = [SeatHolder(11, "Смирнов Алексей", 1, True), SeatHolder(12, "Кузнецова Мария", 3, False)]
        data = json.loads(build_digest_data(DaySeats(d, 10, holders), SEATS, closed=False))
        self.assertEqual((data["d"], data["t"]), ("2026-11-12", "Чт, 12 ноября"))
        self.assertEqual(data["s"][:4], [["Алексей С.", 1, 11], 0, ["Мария К.", 0, 12], 0])
        self.assertNotIn("q", data)
        self.assertNotIn("x", data)
        # Лимит дня выбран: остальные стулья недоступны
        limited = json.loads(build_digest_data(DaySeats(d, 2, holders), SEATS, closed=False))
        self.assertEqual((limited["f"], limited["c"]), (0, 2))
        self.assertEqual([v for i, v in enumerate(limited["s"]) if i not in (0, 2)], ["u"] * 8)
        # Закрытый день: строка под датой — сколько было людей, как в личном виджете
        self.assertEqual(json.loads(build_digest_data(DaySeats(d, 10, holders), SEATS, closed=True))["x"],
                         "Было 2 человека")
        self.assertEqual(json.loads(build_digest_data(DaySeats(d, 10), SEATS, closed=True))["x"], "Никого не было")

    def test_deadline_only_in_open_day(self):
        d = date(2026, 11, 12)
        self.assertEqual(json.loads(build_digest_data(DaySeats(d, 10), SEATS, closed=False, deadline=1794342600))["e"],
                         1794342600)
        self.assertNotIn("e", json.loads(build_digest_data(DaySeats(d, 10), SEATS, closed=True, deadline=1794342600)))
        self.assertNotIn("e", json.loads(build_digest_data(DaySeats(d, 10), SEATS, closed=False)))
        out = build_digest_data(_worst_digest_day(), SEATS, closed=False, deadline=1794342600)
        self.assertLessEqual(data_size(out), MAX_DATA_BYTES)
        self.assertEqual(json.loads(out)["s"][0][0], "Александра К.")

    def test_queue_order_and_names(self):
        d = date(2026, 11, 12)
        q = [QueueEntry(31, "Лебедев Никита"), QueueEntry(32, "Фёдорова Дарья")]
        data = json.loads(build_digest_data(DaySeats(d, 0, [], q), SEATS, closed=False))
        self.assertEqual(data["q"], [["Никита Л.", 31], ["Дарья Ф.", 32]])

    def test_confirm_deadline(self):
        """Подтвердить можно до снятия неподтверждённых броней: накануне в CANCEL_BOOKING_JOB_HOUR:MINUTES"""
        tz = ZoneInfo(settings.MSC_TZ)
        self.assertEqual(confirm_deadline(date(2026, 11, 12)),
                         datetime(2026, 11, 11, settings.CANCEL_BOOKING_JOB_HOUR,
                                  settings.CANCEL_BOOKING_JOB_MINUTES, tzinfo=tz))


# Шаблон дайджеста запускается в Node с заглушкой TelegramWidget: data-* в разметке — то, что можно нажать
_HARNESS = r"""
const {html, cases} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const js = html.split('<script>')[1].split('</script>')[0];
const tick = () => new Promise(r => setTimeout(r, 0));
function snap(r, A, store) {
  const h = A.innerHTML, all = re => [...h.matchAll(re)].map(m => m[1]);
  return {state: r.st(), buttons: all(/data-r="(\w)"/g), free: all(/data-s="(\d+)"/g), names: all(/data-n="(\w+)"/g),
    queue: all(/data-u="(\d+)"/g), link: h.includes('data-l="1"'), hint: h.includes('иначе бронь отменится'),
    timer: (m => m && {cls: m[1], text: m[2]})(h.match(/id="tm" class="([^"]*)">([^<]*)</)),
    sub: (h.match(/<small[^>]*>([^<]*)/) || [])[1], cls: (h.match(/<small class="(\w*)"/) || [])[1] ?? null,
    qline: ((h.match(/Очередь: (.*?)<\/div>/) || [])[1] || '').replace(/<[^>]+>/g, ''),
    qbold: [...((h.match(/Очередь: (.*?)<\/div>/) || [])[1] || '').matchAll(/<b>([^<]*)<\/b>/g)].map(m => m[1]),
    take: h.includes('>занять<'), move: h.includes('>пересесть<'), mine: all(/data-n="(\d+)" class="s me/g),
    unconfirmed: all(/data-n="(\d+)" class="s \w+ r"/g), stored: store.u ?? null};
}
(async () => {
  const out = [];
  for (const c of cases) {
    const A = {innerHTML: ''}, store = c.ur ? {u: '1'} : {}, sent = [], hap = [], opened = [];
    const T = {chatData: JSON.stringify(c.data), viewer: c.viewer, onEvent() {}, ready() {},
      HapticFeedback: {notificationOccurred: k => hap.push(k)}, openTelegramLink: u => opened.push(u),
      request: s => { sent.push(s); return Promise.resolve({result: c.answer == null ? null : JSON.stringify(c.answer)}); }};
    const clock = {t: c.now == null ? Date.now() : c.now * 1000}, intervals = [], tm = {textContent: '', className: 'tm'};
    const doc = {getElementById: id => id == 'a' ? A : id == 'tm' && c.advance != null ? tm : null, documentElement: {}};
    const ls = {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }};
    const r = new Function('window', 'document', 'localStorage', 'Date', 'setInterval', js + ';return {st: st};')(
      {TelegramWidget: T}, doc, ls, {now: () => clock.t}, f => intervals.push(f));
    const res = snap(r, A, store);
    if (c.advance != null) {
      clock.t += c.advance * 1000;
      intervals.forEach(f => f());
      res.tick = {text: tm.textContent, cls: tm.className};
    }
    if (c.click) {
      doc.onclick({target: {dataset: c.click, parentNode: A}});
      await tick(); await tick();
      res.after = {...snap(r, A, store), sent, hap, opened};
    }
    out.push(res);
  }
  process.stdout.write(JSON.stringify(out), () => process.exit(0));
})();
"""
ME = 111
D = "2026-11-12"


def _digest(me=None, full=False, queue=(), closed=False, capacity=10, deadline=None) -> dict:
    """Схема дня через build_digest_data: заняты 1, 3 (не подтверждено), 5, 7, 9, 10; me — бронь зрителя на месте 4
    (True — подтверждена, False — нет); full — заняты и 2, 6, 8, а место 4 — чужое, если брони зрителя нет"""
    holders = [SeatHolder(200 + n, f"Сотрудник{n} Иван", n, n != 3) for n in (1, 3, 5, 7, 9, 10)]
    if me is not None:
        holders.append(SeatHolder(ME, "Иванов Иван", 4, me))
    if full:
        holders += [SeatHolder(200 + n, f"Сотрудник{n} Пётр", n, True) for n in (2, 6, 8)]
        if me is None:
            holders.append(SeatHolder(204, "Сотрудник4 Пётр", 4, True))
    q = [QueueEntry(uid, name) for uid, name in queue]
    return json.loads(build_digest_data(DaySeats(date(2026, 11, 12), capacity, holders, q), SEATS, closed, deadline))


QUEUE = ((351, "Лебедев Никита"), (352, "Фёдорова Дарья"))


@unittest.skipUnless(shutil.which("node"), "нужен Node.js")
class DigestStatesTest(unittest.TestCase):
    """Раздел 7 ТЗ: что видит и может нажать каждый зритель"""

    @staticmethod
    def run_cases(*cases):
        html = render_digest_widget("Дмитрий К.")
        res = subprocess.run([shutil.which("node"), "-e", _HARNESS], input=json.dumps({"html": html, "cases": cases}),
                             capture_output=True, text=True, timeout=30)
        if res.returncode:
            raise AssertionError(res.stderr)
        return json.loads(res.stdout)

    def case(self, data, viewer=ME, **kw):
        return {"data": data, "viewer": {"id": viewer, "first_name": "Иван"} if viewer else None, **kw}

    def test_states(self):
        x, v, u, w, b, f, n, q0, q = self.run_cases(
            self.case(_digest(me=True, closed=True)),
            self.case(_digest(full=True, queue=QUEUE), viewer=None),
            self.case(_digest(), ur=1),
            self.case(_digest(me=False)),
            self.case(_digest(me=True)),
            self.case(_digest(me=True, full=True, queue=QUEUE)),
            self.case(_digest()),
            self.case(_digest(full=True, queue=QUEUE)),
            self.case(_digest(full=True, queue=QUEUE[:1] + ((ME, "Иванов Иван"),) + QUEUE[1:])),
        )
        self.assertEqual([s["state"] for s in (x, v, u, w, b, f, n, q0, q)], ["X", "V", "U", "W", "B", "F", "N", "Q0", "Q"])
        # X: свободные места не нажимаются, кнопок нет, имена нажимаются; под датой — сколько было людей
        self.assertEqual((x["buttons"], x["free"], x["sub"]), ([], [], "Было 7 человек"))
        self.assertIn("1", x["names"])
        # V: не нажимается ничего, даже имена в очереди, и нет ссылки на регистрацию
        self.assertEqual((v["buttons"], v["free"], v["names"], v["queue"], v["link"]), ([], [], [], [], False))
        self.assertEqual(v["qline"], "Никита Л., Дарья Ф.")
        # U: только ссылка на бота, места не занимаются, имена нажимаются
        self.assertEqual((u["buttons"], u["free"], u["link"]), ([], [], True))
        self.assertIn("b", u["names"])
        # W: подтвердить или отменить, подсказка с дедлайном, свободные места пустые
        self.assertEqual((w["buttons"], w["free"], w["hint"], w["take"]), (["x", "c"], [], True, False))
        self.assertEqual(w["mine"], ["4"])
        self.assertIn("4", w["unconfirmed"])
        # B: пересесть одним нажатием, отменить кнопкой
        self.assertEqual((b["buttons"], b["free"], b["move"]), (["x"], ["2", "6", "8"], True))
        self.assertEqual((b["sub"], b["mine"]), ("Свободно 3 из 10", ["4"]))
        # F: только отмена
        self.assertEqual((f["buttons"], f["free"], f["sub"]), (["x"], [], "Все места заняты"))
        self.assertEqual(f["queue"], ["351", "352"])
        # N: занять одним нажатием, кнопок нет
        self.assertEqual((n["buttons"], n["free"], n["take"], n["link"]), ([], ["2", "4", "6", "8"], True, False))
        # Q0 и Q: встать или выйти; сам зритель в очереди — своё короткое имя полужирным, не нажимается
        self.assertEqual((q0["buttons"], q0["free"], q0["qbold"]), (["q"], [], []))
        self.assertEqual((q["buttons"], q["qline"], q["queue"]), (["l"], "Никита Л., Иван И., Дарья Ф.", ["351", "352"]))
        self.assertEqual(q["qbold"], ["Иван И."])
        # Неподтверждённые места помечены у всех
        for s in (x, u, w, b, n):
            self.assertIn("3", s["unconfirmed"])
        self.assertTrue(all(not s["hint"] for s in (x, v, u, b, f, n, q0, q)))

    def test_timer(self):
        """Таймер только в W: часы и минуты, в последний час минуты и секунды, за 15 минут красный, ниже нуля 0:00.
        Часы телефона — только для показа: состояние и кнопки по-прежнему из данных"""
        e = 1794342600
        w = lambda rem, **kw: self.case(_digest(me=False, deadline=e), now=e - rem, **kw)
        long, hour, urgent, over, booked, no_deadline, ticking = self.run_cases(
            w(19800), w(2820), w(540), w(-5),
            self.case(_digest(me=True, deadline=e), now=e - 600),
            self.case(_digest(me=False), now=e - 600),
            w(3605, advance=10),
        )
        self.assertEqual(long["timer"], {"cls": "tm", "text": "5 ч 30 мин"})
        self.assertEqual(hour["timer"], {"cls": "tm", "text": "47:00"})
        self.assertEqual(urgent["timer"], {"cls": "tm u", "text": "9:00"})
        self.assertEqual(over["timer"], {"cls": "tm u", "text": "0:00"})
        self.assertEqual((over["state"], over["buttons"]), ("W", ["x", "c"]))   # кнопки решает сервер, не часы
        self.assertIsNone(booked["timer"])
        self.assertIsNone(no_deadline["timer"])
        self.assertEqual(ticking["timer"]["text"], "1 ч 0 мин")
        self.assertEqual(ticking["tick"], {"text": "59:55", "cls": "tm"})
        (late,) = self.run_cases(w(905, advance=10))
        self.assertEqual(late["tick"], {"text": "14:55", "cls": "tm u"})

    def test_data_overrides_unregistered_mark(self):
        """Бронь или место в очереди значат, что зритель зарегистрирован: отметка U не мешает"""
        booked, queued = self.run_cases(self.case(_digest(me=True), ur=1),
                                        self.case(_digest(full=True, queue=((ME, "Иванов Иван"),)), ur=1))
        self.assertEqual((booked["state"], queued["state"]), ("B", "Q"))

    def test_ids_only_queue(self):
        data = _digest(full=True)
        data["q"] = [351, ME, 352]
        (res,) = self.run_cases(self.case(data))
        self.assertEqual((res["state"], res["qline"], res["queue"]), ("Q", "3 человека, вы №2", []))

    def test_requests_and_answers(self):
        take, unreg, link, confirm, cancel, join, leave, name, queue_name, silent = self.run_cases(
            self.case(_digest(), click={"s": "2"}, answer={"ok": "Место забронировано"}),
            self.case(_digest(), click={"s": "2"}, answer={"er": "Вы не зарегистрированы", "u": 1}),
            self.case(_digest(), ur=1, click={"l": "1"}),
            self.case(_digest(me=False), click={"r": "c"}, answer={"ok": "Бронь подтверждена"}),
            self.case(_digest(me=True), click={"r": "x"}, answer={"er": "Бронирование на этот день закрыто"}),
            self.case(_digest(full=True), click={"r": "q"}, answer={"ok": "Вы в очереди"}),
            self.case(_digest(full=True, queue=((ME, "Иванов Иван"),)), click={"r": "l"}, answer={"ok": "Вы вышли из очереди"}),
            self.case(_digest(), click={"n": "1"}, answer={"n": "Сотрудник1 Иван"}),
            self.case(_digest(full=True, queue=QUEUE), click={"u": "351"}, answer={"n": "Лебедев Никита"}),
            self.case(_digest(), click={"n": "1"}, answer=None),
        )
        a = take["after"]
        self.assertEqual((a["sent"], a["sub"], a["cls"], a["hap"]), ([f"gb:{D}:2"], "Место забронировано", "ok", ["success"]))
        a = unreg["after"]
        self.assertEqual((a["state"], a["stored"], a["cls"], a["hap"]), ("U", "1", "er", ["error"]))
        a = link["after"]
        self.assertEqual((a["state"], a["stored"], a["sent"]), ("N", None, []))
        self.assertEqual(a["opened"], [f"https://t.me/{settings.BOT_USERNAME}?start="])
        self.assertEqual(confirm["after"]["sent"], [f"gc:{D}"])
        self.assertEqual((cancel["after"]["sent"], cancel["after"]["cls"]), ([f"gx:{D}"], "er"))
        self.assertEqual(join["after"]["sent"], [f"gq:{D}"])
        self.assertEqual(leave["after"]["sent"], [f"gl:{D}"])
        a = name["after"]
        self.assertEqual((a["sent"], a["sub"], a["cls"], a["hap"]), ([f"gn:{D}:1"], "Сотрудник1 Иван", "", []))
        self.assertEqual(queue_name["after"]["sent"], [f"gu:{D}:351"])
        a = silent["after"]
        self.assertEqual((a["sub"], a["cls"]), ("Попробуйте ещё раз", "er"))


if __name__ == "__main__":
    unittest.main()
