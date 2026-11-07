import html
from datetime import date
from typing import List

from src.dto.user_dto import UserDTO, UserStatisticsDTO
from src.services.feature_flags import MODE_TITLES, WidgetsSetting, digest_title, months_title


def render_auto_confirm_mess() -> str:
    return ("<b>Автоподтверждение бронирования</b>\n\n"
            "<blockquote><b>Что это значит?</b>\n"
            "✅ Включено – бронь подтверждается автоматически, напоминание не приходит\n"
            "❌ Выключено – за день до визита нужно вручную подтвердить бронь, иначе она отменится\n\n"
            "Включите, если уверены, что точно придёте.</blockquote>")


def render_employee_group_mess(employees: List[UserDTO], group_id: int) -> str:
    if len(employees) == 0:
        return "Сотрудники не найдены"

    header = f"<b>Кол-во требуемых визитов в неделю: {group_id}</b>"
    filtered_employees = [u for u in employees if u.week_visit_plan == group_id]
    employee_group_mess: list[str] = []

    for idx, u in enumerate(filtered_employees, start=1):
        employee_group_mess.append(f'{idx}. <a href="tg://user?id={u.user_id}">{u.full_name}</a>')

    if not employee_group_mess:
        employee_group_mess.append("В данной группе нет сотрудников")

    footer = "Чтобы добавить сотрудника в группу, нажмите на его имя в списке ниже ⤵︎"

    msg = f"{header}\n" + "<blockquote>" + "\n".join(employee_group_mess) + "</blockquote>\n\n" + footer
    return msg


def visit_plan_report_mess(
        employees: List[UserStatisticsDTO],
        start_date: date,
        end_date: date,
        only_no_count: bool = True,
) -> str:
    """
    Формирует HTML-строку с отчетом по посещаемости.

    Args:
        employees: Итерируемый объект с данными о посещаемости
        start_date: Начальная дата периода
        end_date: Конечная дата периода
        only_no_count: Если указан, то для блока no_plan возвращается только количество пользователей

    Returns:
        HTML-строка с отчетом или сообщение об отсутствии данных
    """

    header = f'<b>Посещаемость {start_date:%d.%m} - {end_date:%d.%m}</b>\n'

    if not employees:
        return header + "\n" + "Нет данных за выбранный период"

    # Категоризация пользователей
    no_plan = []
    no_plan_title = "<blockquote><b>ℹ️ План не задан</b></blockquote>"
    no_plan_cnt = 0
    done = []
    done_title = "<blockquote><b>✅ По плану</b></blockquote>"
    partial = []
    partial_title = "<blockquote><b>⚠️ С отклонениями</b></blockquote>"
    none = []
    none_title = "<blockquote><b>❌ Вне плана</b></blockquote>"

    for u in employees:
        visit_count = getattr(u, "visit_count", 0) or 0
        week_visit_plan = getattr(u, "week_visit_plan", 0) or 0

        # Формируем строку один раз
        user_info = f"[{visit_count}/{week_visit_plan}]"

        if week_visit_plan == 0 and only_no_count:
            # Нет данных по плану
            no_plan_cnt += 1
            continue
        if week_visit_plan == 0 and not only_no_count:
            # Нет данных по плану
            no_plan.append(
                f'• <a href="tg://user?id={u.user_id}">{u.full_name}</a> - {visit_count} посещ.'
            )
            continue
        if visit_count >= week_visit_plan:
            # План выполнен
            done.append(f"• {u.full_name} {user_info}")
        elif 0 < visit_count < week_visit_plan:
            # Частично выполнен - со ссылкой
            partial.append(
                f'• <a href="tg://user?id={u.user_id}">{u.full_name}</a> {user_info}'
            )
        else:
            # Не посещал - со ссылкой
            none.append(
                f'• <a href="tg://user?id={u.user_id}">{u.full_name}</a> {user_info}'
            )

    sections = [header]

    # Секция "План выполнен"
    if done:
        done_block = f"{done_title}\n" + "\n".join(done)
        sections += [done_block, ""]

    # Секция "Пропущены дни"
    if partial:
        partial_block = f"{partial_title}\n" + "\n".join(partial)
        sections += [partial_block, ""]

    # Секция "Ни разу не посетили"
    if none:
        none_block = f"{none_title}\n" + "\n".join(none)
        sections += [none_block, ""]

    # Секция "Нет данных", где нужно только количество пользователей
    if only_no_count:
        no_plan.append(f"• Количество сотрудников: {no_plan_cnt}")
        no_plan_block = f"{no_plan_title}\n" + "\n".join(no_plan)
        sections += [no_plan_block]

    # Секция "Нет данных"
    if not only_no_count:
        no_plan_block = f"{no_plan_title}\n" + "\n".join(no_plan)
        sections += [no_plan_block]

    message = "\n".join(part for part in sections if part is not None)
    return message.strip()


def render_widgets_settings_mess(setting: WidgetsSetting, api_supported: bool) -> str:
    changed = ""
    if setting.changed_at:
        who = f", {html.escape(setting.changed_by)}" if setting.changed_by else ""
        changed = f"\nИзменено: {setting.changed_at:%d.%m.%Y %H:%M}{who}"
    api = ("✅ Bot API поддерживает виджеты" if api_supported else
           "⚠️ Bot API по этому адресу не знает виджеты — включить не получится. "
           "Нужен TG_API_BASE=https://api.telegram.org/beta в .env и перезапуск бота")
    return (f"<b>🧩 Виджеты</b>\n\n"
            f"Бронирование в личке: <b>{MODE_TITLES[setting.mode]}</b>\n"
            f"Дайджест в группе: <b>{digest_title(setting.digest)}</b>\n"
            f"Календарь: назад <b>{months_title(setting.history_months)}</b>, "
            f"вперёд <b>{months_title(setting.future_months)}</b>{changed}\n{api}\n\n"
            "<blockquote expandable><b>Бронирование в личке</b>\n"
            "• Выключены — у всех прежние экраны: недельное расписание и «Мои брони»\n"
            "• Только админам — виджет у админов, у остальных прежние экраны. Удобно проверить на проде\n"
            "• Всем — «Забронировать место» открывает календарь со схемой зала, «Мои брони» скрыта\n"
            "Окна, уже открытые в чатах, при выключении не пропадают: любое нажатие в них заменит окно меню.\n\n"
            "<b>Дайджест в группе</b> — виджетом со схемой зала или текстом, как раньше. Telegram пока не пускает "
            "виджеты ботов в группы: если не пустит, дайджест уйдёт текстом, а в чат алертов придёт ошибка.\n\n"
            "<b>Календарь</b> — сколько прошлых месяцев можно посмотреть и на сколько месяцев вперёд листать. "
            "Бронь всё равно только в пределах горизонта бронирования. Если месяцев слишком много для лимита "
            "Telegram, самые дальние отбрасываются.</blockquote>")


def render_widgets_months_mess(field: str, current: int) -> str:
    what = ("Сколько прошлых месяцев можно посмотреть в календаре (только просмотр)" if field == "history" else
            "На сколько месяцев после текущего можно листать календарь вперёд. Бронь — только в пределах горизонта")
    return f"<b>🧩 Виджеты → календарь</b>\n\n{what}.\nСейчас: <b>{months_title(current)}</b>"
