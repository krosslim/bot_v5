"""Шаблоны листов месяцев в Google-таблице посещений.

Бот (sheet_update_job → Apps Script) пишет отметки в листы текущего и соседних месяцев. Здесь листы
создаются заранее: на текущий и два следующих месяца, как только для месяца есть окончательный
производственный календарь. Существующие листы с данными бот никогда не перезаписывает:

    листа нет                                   → создать шаблон
    есть, с меткой бота                         → не трогать; сверить с календарём, при расхождении — алерт
    есть без метки, даты совпадают с месяцем    → лист старого скрипта: поставить метку («принять»)
    есть без метки, шапка и тело пустые         → создание оборвалось на полпути: удалить и создать заново
    есть без метки, даты не те, но что-то есть  → не трогать, алерт (лист другой раскладки или чужой)

Запускается при старте бота и ночным заданием sheet_template_job.
"""
import asyncio
import calendar
import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from src.clients.google_sheets_client import GoogleSheetsClient, GoogleSheetsError, SheetInfo
from src.dto.calendar_dates_dto import CalendarDatesDTO, CalendarSource
from src.services.alert_service import Alert, AlertService
from src.services.calendar_dates_service import CalendarDatesService
from src.services.office_capacity_service import OfficeCapacityService
from src.utils.sheet_name import month_title
from src.utils.sheet_template import (TEMPLATE_MARKER_KEY, TemplateDay, body_range, build_create_requests,
                                      build_values, has_body_data, head_range, header_matches, header_range,
                                      is_blank, marker_request, stale_days)
from src.utils.tz_day import d_tz

logger = logging.getLogger(__name__)

MONTHS_AHEAD = 2                 # текущий месяц и два следующих — то же окно, куда пишет sheet_update_job
FALLBACK_DAYS = 7                # если до месяца меньше недели, а календарь всё ещё не окончательный — создаём
ACCESS_ALERT_EVERY = 24 * 3600
STALE_ALERT_EVERY = 7 * 24 * 3600
FOREIGN_ALERT_EVERY = 24 * 3600
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

_lock = asyncio.Lock()           # запуск при старте и ночной не должны создавать листы одновременно


class Readiness(Enum):
    READY = "ready"              # все дни месяца из isdayoff.ru
    FALLBACK = "fallback"        # не все из isdayoff.ru, но месяц вот-вот начнётся — создаём по holidays
    WAIT = "wait"                # не все из isdayoff.ru, время ещё есть
    MISSING = "missing"          # в calendar_dates нет части дней месяца


class Action(Enum):
    CREATE = "create"
    READY = "ready"
    ADOPT = "adopt"
    REPAIR = "repair"
    FOREIGN = "foreign"


def month_readiness(rows: Sequence[CalendarDatesDTO], month_start: date, today: date) -> Readiness:
    if len(rows) != calendar.monthrange(month_start.year, month_start.month)[1]:
        return Readiness.MISSING
    if all(r.source == CalendarSource.ISDAYOFF for r in rows):
        return Readiness.READY
    return Readiness.FALLBACK if (month_start - today).days < FALLBACK_DAYS else Readiness.WAIT


def decide(info: Optional[SheetInfo], header_ok: bool = False, has_data: bool = False,
           head_blank: bool = False) -> Action:
    """Удалить лист можно, только если в нём нет вообще ничего: ни данных, ни шапки. Так выглядит лист,
    создание которого оборвалось до записи значений. Всё остальное без метки и с чужими датами — не трогаем"""
    if info is None:
        return Action.CREATE
    if TEMPLATE_MARKER_KEY in info.metadata:
        return Action.READY
    if header_ok:
        return Action.ADOPT
    return Action.REPAIR if head_blank and not has_data else Action.FOREIGN


def fmt_day(d: date) -> str:
    return f"{d:%d.%m} ({WEEKDAYS[d.weekday()]})"


@dataclass
class MonthResult:
    title: str
    action: Optional[Action]
    note: str = ""


class SheetTemplateUseCase:
    def __init__(
            self,
            session: AsyncSession,
            calendar_dates: CalendarDatesService,
            office_capacity: OfficeCapacityService,
            alerts: AlertService,
            cfg: Config,
            client_factory: Optional[Callable[[], GoogleSheetsClient]] = None,
    ):
        self.session = session
        self.calendar_dates = calendar_dates
        self.office_capacity = office_capacity
        self.alerts = alerts
        self.cfg = cfg
        self.client_factory = client_factory or (
            lambda: GoogleSheetsClient(cfg.GOOGLE_SHEET_CREDENTIALS, cfg.GOOGLE_SHEET_KEY))

    async def run(self) -> List[MonthResult]:
        if not (self.cfg.GOOGLE_SHEET_CREDENTIALS and self.cfg.GOOGLE_SHEET_KEY):
            logger.warning("sheet_template | GOOGLE_SHEET_CREDENTIALS или GOOGLE_SHEET_KEY не заданы — пропуск")
            return []
        async with _lock:
            today = d_tz()
            months = [date(today.year, today.month, 1) + relativedelta(months=k) for k in range(MONTHS_AHEAD + 1)]
            last = months[-1]
            async with self.session.begin():
                rows = await self.calendar_dates.days_by_range(
                    months[0], date(last.year, last.month, calendar.monthrange(last.year, last.month)[1]))
                capacities = await self.office_capacity.get_office_capacity()
            capacity = max((c.capacity for c in capacities), default=10)
            by_month: Dict[date, List[CalendarDatesDTO]] = {m: [] for m in months}
            for r in rows:
                by_month.setdefault(date(r.cal_date.year, r.cal_date.month, 1), []).append(r)

            try:
                client = await asyncio.to_thread(self.client_factory)
                sheets = {s.title: s for s in await asyncio.to_thread(client.sheets)}
                results = [await self._month(client, m, by_month[m], sheets, capacity, today) for m in months]
            except GoogleSheetsError as e:
                logger.warning("sheet_template | Google-таблица недоступна | %s", e)
                hint = ("\nПроверьте, что сервисному аккаунту из GOOGLE_SHEET_CREDENTIALS выдан доступ редактора "
                        "к таблице GOOGLE_SHEET_KEY." if e.status in (401, 403, 404) else
                        "\nБот повторит попытку при следующем запуске задачи.")
                await self.alerts.notify(Alert(
                    "Ошибка Google-таблицы посещений",
                    f"Шаблоны листов месяцев не созданы: {e}{hint}",
                    level=logging.ERROR, key="sheet_template:access", dedup_ttl=ACCESS_ALERT_EVERY,
                ))
                return []

        adopted = [r.title for r in results if r.action == Action.ADOPT]
        if adopted:
            await self.alerts.notify(Alert(
                "Листы посещений взяты под присмотр бота",
                "Эти листы созданы раньше скриптом. Бот поставил на них метку и дальше их не трогает, "
                "только сверяет с календарём:\n" + "\n".join(f"• {t}" for t in adopted),
                level=logging.INFO,
            ))
        logger.info("sheet_template | %s", ", ".join(f"{r.title}: {r.action.value if r.action else r.note}"
                                                      for r in results))
        return results

    async def _month(self, client: GoogleSheetsClient, month: date, rows: List[CalendarDatesDTO],
                     sheets: Dict[str, SheetInfo], capacity: int, today: date) -> MonthResult:
        title = month_title(month)
        readiness = month_readiness(rows, month, today)
        if readiness == Readiness.MISSING:
            logger.warning("sheet_template | %s | в calendar_dates нет всех дней месяца — пропуск", title)
            return MonthResult(title, None, "нет календаря")
        days = [TemplateDay(r.cal_date, r.is_workday) for r in sorted(rows, key=lambda r: r.cal_date)]
        info = sheets.get(title)

        action = decide(info)
        if action == Action.CREATE:
            if readiness == Readiness.WAIT:
                return MonthResult(title, None, "ждём календарь isdayoff.ru")
            await self._create(client, title, days, capacity, sheets, readiness)
            return MonthResult(title, Action.CREATE)
        if action == Action.READY:
            await self._check_stale(client, title, days)
            return MonthResult(title, Action.READY)

        header = await asyncio.to_thread(client.read_values, header_range(title, days))
        if header_matches(days, header):
            await asyncio.to_thread(client.batch_update, [marker_request(info.sheet_id)])
            await self._check_stale(client, title, days)
            return MonthResult(title, Action.ADOPT)

        body = await asyncio.to_thread(client.read_values, body_range(title, days))
        head = await asyncio.to_thread(client.read_values, head_range(title, days))
        if decide(info, has_data=has_body_data(body), head_blank=is_blank(head)) == Action.REPAIR:
            await asyncio.to_thread(client.batch_update, [{"deleteSheet": {"sheetId": info.sheet_id}}])
            await self._create(client, title, days, capacity, sheets, readiness, repaired=True)
            return MonthResult(title, Action.REPAIR)

        await self.alerts.notify(Alert(
            f"Лист «{title}» не похож на шаблон бота",
            "Даты в строке 2 (с колонки D) не совпадают с месяцем, а лист не пустой: другая раскладка "
            "или в нём есть данные. Бот его не трогает, но Apps Script, скорее всего, не сможет в него писать. "
            "Если лист не нужен, переименуйте или удалите его — бот создаст шаблон заново.",
            level=logging.WARNING, key=f"sheet_template:foreign:{title}", dedup_ttl=FOREIGN_ALERT_EVERY,
        ))
        return MonthResult(title, Action.FOREIGN)

    async def _create(self, client: GoogleSheetsClient, title: str, days: List[TemplateDay], capacity: int,
                      sheets: Dict[str, SheetInfo], readiness: Readiness, repaired: bool = False) -> None:
        taken = {s.sheet_id for s in sheets.values()}
        sheet_id = next(i for i in iter(lambda: random.randint(1, 2 ** 31 - 1), None) if i not in taken)
        stamp = datetime.now(ZoneInfo(self.cfg.MSC_TZ)).strftime("%d.%m.%Y %H:%M")
        # 1) лист и оформление — атомарно; 2) значения и формулы; 3) метка «готово» — последней
        await asyncio.to_thread(client.batch_update, build_create_requests(sheet_id, title, days, capacity))
        await asyncio.to_thread(client.write_values, build_values(title, days, stamp))
        await asyncio.to_thread(client.batch_update, [marker_request(sheet_id)])
        sheets[title] = SheetInfo(sheet_id, title, {TEMPLATE_MARKER_KEY: "created"})

        note = ""
        if readiness == Readiness.FALLBACK:
            note = ("\n\nisdayoff.ru ещё не знает этот месяц: выходные и праздники взяты из библиотеки holidays, "
                    "рабочие субботы не учтены. Если календарь потом изменится, придёт алерт о расхождении.")
        await self.alerts.notify(Alert(
            f"{'Пересоздан' if repaired else 'Создан'} лист «{title}»",
            ("Прошлое создание оборвалось на полпути, в листе не было данных — он создан заново."
             if repaired else "Шаблон месяца готов, бот будет записывать в него отметки.") + note,
            level=logging.WARNING if repaired or note else logging.INFO,
        ))

    async def _check_stale(self, client: GoogleSheetsClient, title: str, days: List[TemplateDay]) -> None:
        formulas = await asyncio.to_thread(client.read_values, header_range(title, days), True)
        stale = stale_days(days, formulas)
        if not stale:
            return
        workday = {d.cal_date: d.is_workday for d in days}
        lines = [f"• {fmt_day(d)}: теперь {'рабочий' if workday[d] else 'выходной'}" for d in stale]
        digest = hashlib.sha1(",".join(d.isoformat() for d in stale).encode()).hexdigest()[:12]
        await self.alerts.notify(Alert(
            f"Лист «{title}» расходится с производственным календарём",
            "Бот не меняет листы, в которые уже пишутся отметки. Поправьте вручную: серый цвет и формулу "
            "в строке 4.\n" + "\n".join(lines),
            level=logging.WARNING, key=f"sheet_template:stale:{title}:{digest}", dedup_ttl=STALE_ALERT_EVERY,
        ))
