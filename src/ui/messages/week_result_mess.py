from src.dto.booking_dto import WeekVisitsDTO, UserBookingWeekResultDTO


def pluralize_person(count: int) -> str:

    if 11 <= count % 100 <= 14:
        return "человек"
    last_digit = count % 10
    if last_digit == 1:
        return "человек"
    if 2 <= last_digit <= 4:
        return "человека"
    return "человек"


def pluralize_visit(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "визит"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        return "визита"
    else:
        return "визитов"


def week_summary_mess(week_data: list[WeekVisitsDTO], max_visitors: list[UserBookingWeekResultDTO]) -> str:

    weekdays_ru = {
        0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг",
        4: "Пятница", 5: "Суббота", 6: "Воскресенье"
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

    winner_block = ""
    if max_visitors:
        booking_count = max_visitors[0].booking_count

        # чтоб не спамить: кол-во бронирований ОТ 3
        if booking_count > 2:

            visit_word = pluralize_visit(booking_count)

            names = [
                f'<a href="tg://user?id={user.user_id}">{user.full_name}</a>'
                for user in max_visitors
            ]
            names_str = ", ".join(names)

            if len(max_visitors) == 1:
                title = f"🏆 Победитель ({booking_count} {visit_word})"
            else:
                title = f"🏆 Победители (по {booking_count} {visit_word})"

            winner_block = (
                f"<b>{title}</b>\n"
                f"<tg-spoiler>{names_str}</tg-spoiler>\n\n"
            )

    result = (
        f"<b>✨ Итоги недели ({week_start:%d.%m}–{week_end:%d.%m})</b>\n"
        f"<blockquote>{chr(10).join(lines)}</blockquote>\n\n"
        f"{winner_block}"  
        f"<b>Всем хороших выходных! 🫶</b>"
    )
    return result

