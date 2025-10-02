import datetime

from src.dto.booking_dto import WeekVisitsDTO


def pluralize_person(count: int) -> str:

    if 11 <= count % 100 <= 14:
        return "человек"
    last_digit = count % 10
    if last_digit == 1:
        return "человек"
    if 2 <= last_digit <= 4:
        return "человека"
    return "человек"


def week_summary_mess(week_data: list[WeekVisitsDTO]) -> str:
    weekdays_ru = {
        0: "Понедельник",
        1: "Вторник",
        2: "Среда",
        3: "Четверг",
        4: "Пятница",
        5: "Суббота",
        6: "Воскресенье"
    }

    if not week_data:
        return "<b>✨ Итоги недели</b>\n<blockquote>Нет данных</blockquote>"

    sorted_data = sorted(week_data, key=lambda x: x.cal_date)

    week_start = sorted_data[0].cal_date
    week_end = sorted_data[-1].cal_date

    lines = []
    for item in sorted_data:
        weekday_index = item.cal_date.weekday()
        visits = item.visits
        word = pluralize_person(visits)
        lines.append(f"• {weekdays_ru[weekday_index]} – {visits} {word}")

    result = (
        f"<b>✨ Итоги недели ({week_start:%d.%m}–{week_end:%d.%m})</b>\n"
        f"<blockquote>{chr(10).join(lines)}</blockquote>\n\n"
        f"<b>Всем хороших выходных! 🫶</b>"
    )
    return result
