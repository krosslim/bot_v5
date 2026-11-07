"""Шаблон листа месяца и решения по листам без Google: python -m unittest discover -s tests -t ."""
import re
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.clients.google_sheets_client import GoogleSheetsError, SheetInfo
from src.dto.calendar_dates_dto import CalendarDatesDTO, CalendarSource
from src.dto.office_capacity_dto import OfficeCapacityDTO
from src.use_cases import sheet_template_use_case as module
from src.use_cases.sheet_template_use_case import Action, SheetTemplateUseCase
from src.utils.sheet_template import (TEMPLATE_MARKER_KEY, TemplateDay, build_create_requests, build_values,
                                      col_letter, has_body_data, header_matches, is_blank, sheet_serial,
                                      stale_days)
from src.utils.work_calendar import holidays_year, parse_isdayoff_year
from tests.test_work_calendar import ISDAYOFF_2025, ISDAYOFF_2026


def month_days(flags, year, month):
    return [TemplateDay(d.cal_date, d.is_workday) for d in flags if (d.cal_date.year, d.cal_date.month) == (year, month)]


NOV_2025 = month_days(parse_isdayoff_year(2025, ISDAYOFF_2025), 2025, 11)   # 01.11 — рабочая суббота


class BuilderTest(unittest.TestCase):
    def test_col_letters(self):
        self.assertEqual([col_letter(n) for n in (1, 26, 27, 52, 53)], ["A", "Z", "AA", "AZ", "BA"])

    def test_values_layout(self):
        data = {d["range"]: d["values"] for d in build_values("ноябрь 2025", NOV_2025, "07.11.2026 04:30")}
        self.assertEqual(data["'ноябрь 2025'!A1"], [["Обновлено 07.11.2026 04:30"]])
        self.assertEqual(data["'ноябрь 2025'!A2:C2"], [["Продукт", "Должность", "ФИО"]])   # как ждёт Apps Script
        self.assertEqual(data["'ноябрь 2025'!D2:AG2"][0][:2], [45962, 45963])            # 01.11.2025 и 02.11.2025
        self.assertEqual(data["'ноябрь 2025'!D3:AG3"][0][:3], ["Сб", "Вс", "Пн"])
        row4 = data["'ноябрь 2025'!D4:AG4"][0]
        self.assertEqual(row4[0], "=СЧЁТЕСЛИ(D5:D100; ИСТИНА())")     # рабочая суббота — с формулой
        self.assertEqual(row4[1:4], ["", "", ""])                      # вс, 03.11 перенос, 04.11 праздник
        totals = data["'ноябрь 2025'!AH5:AH100"]
        self.assertEqual((len(totals), totals[0]), (96, ["=СЧЁТЕСЛИ(D5:AG5; ИСТИНА())"]))
        self.assertEqual(data["'ноябрь 2025'!AH1"], [["Факт."]])

    def test_sheet_serial_matches_google(self):
        self.assertEqual(sheet_serial(date(2025, 12, 1)), 45992)      # так Google хранит 01.12.2025

    def test_create_requests(self):
        requests = build_create_requests(42, "ноябрь 2025", NOV_2025, capacity=10)
        self.assertEqual(requests[0]["addSheet"]["properties"]["title"], "ноябрь 2025")
        self.assertEqual(requests[0]["addSheet"]["properties"]["sheetId"], 42)
        gray = [r["repeatCell"]["range"] for r in requests
                if "repeatCell" in r and "backgroundColor" in r["repeatCell"]["cell"]["userEnteredFormat"]
                and r["repeatCell"]["range"]["endRowIndex"] == 4 and r["repeatCell"]["range"]["startColumnIndex"] > 0]
        first_gray = (gray[0]["startColumnIndex"], gray[0]["endColumnIndex"])
        self.assertEqual(first_gray, (4, 7))                           # 02–04.11 (E:G) одним отрезком, 01.11 (D) не серый
        gradient = next(r for r in requests if "addConditionalFormatRule" in r)["addConditionalFormatRule"]["rule"]
        points = gradient["gradientRule"]
        self.assertEqual((points["midpoint"]["value"], points["maxpoint"]["value"]), ("7", "10"))
        validation = next(r for r in requests if "setDataValidation" in r)["setDataValidation"]["range"]
        self.assertEqual((validation["startRowIndex"], validation["endRowIndex"]), (4, 100))
        self.assertEqual((validation["startColumnIndex"], validation["endColumnIndex"]), (3, 33))

    def test_layout_matches_prod_sheet(self):
        """Раскладка прод-листа: Apps Script объединяет A1:C1 — это возможно, только если закреплены 3 колонки"""
        requests = build_create_requests(42, "декабрь 2026", NOV_2025, capacity=12)
        frozen = next(r for r in requests if "updateSheetProperties" in r)["updateSheetProperties"]
        self.assertEqual(frozen["properties"]["gridProperties"], {"frozenRowCount": 4, "frozenColumnCount": 3})
        merges = sorted((m["startRowIndex"], m["endRowIndex"], m["startColumnIndex"], m["endColumnIndex"])
                        for m in (r["mergeCells"]["range"] for r in requests if "mergeCells" in r))
        self.assertEqual(merges, [(0, 1, 0, 3), (0, 4, 33, 34), (1, 4, 0, 1), (1, 4, 1, 2), (1, 4, 2, 3)])
        self.assertEqual(requests[0]["addSheet"]["properties"]["gridProperties"]["columnCount"], 35)

    def test_gradient_follows_small_capacity(self):
        rule = next(r for r in build_create_requests(1, "t", NOV_2025, capacity=5)
                    if "addConditionalFormatRule" in r)["addConditionalFormatRule"]["rule"]["gradientRule"]
        self.assertEqual((rule["midpoint"]["value"], rule["maxpoint"]["value"]), ("4", "5"))

    def test_header_matches_dates_shown_by_sheet(self):
        self.assertTrue(header_matches(NOV_2025, [[f"{d:02d}.11.2025" for d in range(1, 31)]]))
        self.assertTrue(header_matches(NOV_2025, [[f"{d:02d}.11" for d in range(1, 31)]]))
        self.assertFalse(header_matches(NOV_2025, [[f"{d:02d}.12" for d in range(1, 31)]]))
        self.assertFalse(header_matches(NOV_2025, [["01.11", "02.11"]]))
        self.assertFalse(header_matches(NOV_2025, []))

    def test_stale_days_and_body_data(self):
        row4 = ["=СЧЁТЕСЛИ(...)" if d.is_workday else "" for d in NOV_2025]
        self.assertEqual(stale_days(NOV_2025, [[], [], row4]), [])
        row4[0] = ""                                                   # старый лист не знал рабочую субботу
        self.assertEqual(stale_days(NOV_2025, [[], [], row4]), [date(2025, 11, 1)])
        self.assertFalse(has_body_data([["", "FALSE"], ["ЛОЖЬ"]]))
        self.assertTrue(has_body_data([["Иванов Иван"]]))
        self.assertTrue(has_body_data([["", "TRUE"]]))
        self.assertTrue(is_blank([[], ["", " "]]))
        self.assertFalse(is_blank([[], ["", "", "ФИО"]]))


# ---------------------------------------------------------------------------#
#  Use case на подставном клиенте Google
# ---------------------------------------------------------------------------#
class FakeSheetsClient:
    def __init__(self, sheets=None, fail=None):
        self.data = dict(sheets or {})     # title → {"id", "meta", "rows": {2: [...], 3, 4}, "body": [[...]]}
        self.fail = fail
        self.calls = []

    def sheets(self):
        if self.fail == "sheets":
            raise GoogleSheetsError("Google Sheets API 403: Forbidden", 403)
        return [SheetInfo(s["id"], t, dict(s["meta"])) for t, s in self.data.items()]

    def _title(self, sheet_id):
        return next(t for t, s in self.data.items() if s["id"] == sheet_id)

    def batch_update(self, requests):
        for r in requests:
            kind = next(iter(r))
            self.calls.append(kind)
            if kind == "addSheet":
                p = r["addSheet"]["properties"]
                self.data[p["title"]] = {"id": p["sheetId"], "meta": {}, "rows": {}, "body": []}
            elif kind == "createDeveloperMetadata":
                m = r[kind]["developerMetadata"]
                self.data[self._title(m["location"]["sheetId"])]["meta"][m["metadataKey"]] = m["metadataValue"]
            elif kind == "deleteSheet":
                del self.data[self._title(r[kind]["sheetId"])]

    def write_values(self, data):
        self.calls.append("write_values")
        if self.fail == "write_values":
            raise GoogleSheetsError("timeout")
        for d in data:
            title, a1 = re.match(r"'(.+)'!(.+)", d["range"]).groups()
            row = re.match(r"D(\d):", a1)
            if row:
                self.data[title]["rows"][int(row.group(1))] = d["values"][0]

    def read_values(self, a1_range, formulas=False):
        title, a1 = re.match(r"'(.+)'!(.+)", a1_range).groups()
        sheet = self.data[title]
        if a1.startswith("D2:"):
            return [sheet["rows"].get(i, []) for i in (2, 3, 4)]
        if a1.startswith("A1:"):
            return sheet.get("head", [sheet["rows"].get(i, []) for i in (1, 2, 3, 4)])
        return sheet["body"]


class FakeCalendar:
    def __init__(self, rows):
        self.rows = rows

    async def days_by_range(self, start, end):
        return [r for r in self.rows if start <= r.cal_date <= end]


class FakeCapacity:
    async def get_office_capacity(self):
        return [OfficeCapacityDTO(weekday=i, short_name="x", capacity=10) for i in range(1, 8)]


class FakeAlerts:
    def __init__(self):
        self.sent = []

    async def notify(self, alert):
        self.sent.append(alert)
        return 1


class FakeSession:
    @asynccontextmanager
    async def begin(self):
        yield


def calendar_rows():
    def dto(flags):
        return CalendarDatesDTO(cal_date=flags.cal_date, is_holiday=flags.is_holiday, is_weekend=flags.is_weekend,
                                is_workday=flags.is_workday, visit_count=0, source=flags.source,
                                updated_at=datetime(2026, 1, 1))
    # 2026 — из isdayoff.ru, 2027 — пока только holidays (постановления «ещё нет»)
    return [dto(f) for f in parse_isdayoff_year(2026, ISDAYOFF_2026)] + [dto(f) for f in holidays_year(2027)]


def labels(year, month, days, fmt="{d:02d}.{m:02d}.{y}"):
    return [fmt.format(d=d, m=month, y=year) for d in range(1, days + 1)]


class SheetTemplateUseCaseTest(unittest.IsolatedAsyncioTestCase):
    async def run_uc(self, client, today=date(2026, 11, 7), creds="{}", rows=None):
        self.alerts = FakeAlerts()
        cfg = SimpleNamespace(GOOGLE_SHEET_CREDENTIALS=creds, GOOGLE_SHEET_KEY="sheet-id", MSC_TZ="Europe/Moscow")
        uc = SheetTemplateUseCase(FakeSession(), FakeCalendar(rows if rows is not None else calendar_rows()),
                                  FakeCapacity(), self.alerts, cfg, client_factory=lambda: client)
        with patch.object(module, "d_tz", return_value=today):
            return {r.title: (r.action, r.note) for r in await uc.run()}

    def titles(self):
        return [a.title for a in self.alerts.sent]

    async def test_empty_spreadsheet_creates_ready_months_and_waits_for_final_calendar(self):
        client = FakeSheetsClient()
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.CREATE)
        self.assertEqual(res["декабрь 2026"][0], Action.CREATE)
        self.assertEqual(res["январь 2027"], (None, "ждём календарь isdayoff.ru"))
        self.assertEqual(self.titles(), ["Создан лист «ноябрь 2026»", "Создан лист «декабрь 2026»"])
        self.assertTrue(all(TEMPLATE_MARKER_KEY in client.data[t]["meta"] for t in ("ноябрь 2026", "декабрь 2026")))
        # порядок: лист и оформление, значения, метка — последней
        steps = [c for c in client.calls if c in ("addSheet", "write_values", "createDeveloperMetadata")]
        self.assertEqual(steps[:3], ["addSheet", "write_values", "createDeveloperMetadata"])

    async def test_second_run_changes_nothing(self):
        client = FakeSheetsClient()
        await self.run_uc(client)
        calls = len(client.calls)
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.READY)
        self.assertEqual(len(client.calls), calls)
        self.assertEqual(self.alerts.sent, [])

    async def test_old_script_sheet_is_adopted_not_recreated(self):
        nov = [d for d in calendar_rows() if (d.cal_date.year, d.cal_date.month) == (2026, 11)]
        row4 = ["=СЧЁТЕСЛИ(D5:D100; ИСТИНА())" if d.is_workday else "" for d in nov]
        client = FakeSheetsClient({"ноябрь 2026": {"id": 7, "meta": {}, "body": [["Иванов Иван", "TRUE"]],
                                                   "rows": {2: labels(2026, 11, 30), 4: row4}}})
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.ADOPT)
        self.assertEqual(client.data["ноябрь 2026"]["id"], 7)                     # тот же лист
        self.assertIn(TEMPLATE_MARKER_KEY, client.data["ноябрь 2026"]["meta"])
        self.assertNotIn("deleteSheet", client.calls)
        self.assertIn("Листы посещений взяты под присмотр бота", self.titles())

    async def test_half_created_empty_sheet_is_recreated(self):
        client = FakeSheetsClient({"ноябрь 2026": {"id": 7, "meta": {}, "rows": {}, "body": []}})
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.REPAIR)
        self.assertNotEqual(client.data["ноябрь 2026"]["id"], 7)
        self.assertIn("Пересоздан лист «ноябрь 2026»", self.titles())

    async def test_unknown_sheet_with_data_is_left_alone(self):
        client = FakeSheetsClient({"ноябрь 2026": {"id": 7, "meta": {}, "rows": {2: ["что-то своё"]},
                                                   "body": [["Иванов Иван"]]}})
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.FOREIGN)
        self.assertEqual(client.data["ноябрь 2026"]["id"], 7)
        self.assertNotIn("deleteSheet", client.calls)
        self.assertIn("Лист «ноябрь 2026» не похож на шаблон бота", self.titles())

    async def test_empty_sheet_with_other_layout_is_not_deleted(self):
        """Пустой лист без метки, но с шапкой — сделан руками или старым скриптом другой раскладки
        (даты с B, одна колонка «ФИО»): не удаляем, только алерт"""
        head = [["Обновлено 03.11.2026"], ["ФИО"] + labels(2026, 11, 30, "{d:02d}.{m:02d}"), [], []]
        client = FakeSheetsClient({"ноябрь 2026": {"id": 7, "meta": {}, "head": head, "body": [],
                                                   "rows": {2: labels(2026, 11, 30)[2:]}}})
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.FOREIGN)
        self.assertNotIn("deleteSheet", client.calls)

    async def test_calendar_change_after_creation_is_reported_not_fixed(self):
        client = FakeSheetsClient()
        await self.run_uc(client)
        rows = calendar_rows()
        rows = [r.model_copy(update={"is_workday": False, "is_holiday": True}) if r.cal_date == date(2026, 12, 30)
                else r for r in rows]                                           # вышло постановление
        await self.run_uc(client, rows=rows)
        self.assertEqual(self.titles(), ["Лист «декабрь 2026» расходится с производственным календарём"])
        self.assertIn("30.12 (ср): теперь выходной", self.alerts.sent[0].text)

    async def test_month_about_to_start_is_created_from_holidays_with_warning(self):
        client = FakeSheetsClient()
        res = await self.run_uc(client, today=date(2026, 12, 28))
        self.assertEqual(res["январь 2027"][0], Action.CREATE)
        self.assertEqual(res["февраль 2027"], (None, "ждём календарь isdayoff.ru"))
        jan = next(a for a in self.alerts.sent if a.title == "Создан лист «январь 2027»")
        self.assertIn("библиотеки holidays", jan.text)

    async def test_no_access_alerts_once_and_stops(self):
        res = await self.run_uc(FakeSheetsClient(fail="sheets"))
        self.assertEqual(res, {})
        self.assertEqual([a.key for a in self.alerts.sent], ["sheet_template:access"])

    async def test_interrupted_creation_is_repaired_next_run(self):
        client = FakeSheetsClient(fail="write_values")
        await self.run_uc(client)                                               # лист есть, значений и метки нет
        self.assertNotIn(TEMPLATE_MARKER_KEY, client.data["ноябрь 2026"]["meta"])
        client.fail = None
        res = await self.run_uc(client)
        self.assertEqual(res["ноябрь 2026"][0], Action.REPAIR)
        self.assertIn(TEMPLATE_MARKER_KEY, client.data["ноябрь 2026"]["meta"])

    async def test_not_configured_does_nothing(self):
        client = FakeSheetsClient()
        self.assertEqual(await self.run_uc(client, creds=""), {})
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
