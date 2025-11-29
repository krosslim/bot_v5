from datetime import date


WEEKDAYS_RU = {
    0: "ПН", 1: "ВТ", 2: "СР",
    3: "ЧТ", 4: "ПТ", 5: "СБ", 6: "ВС",
}


def build_promote_message(cal_date: date) -> str:

    weekday = WEEKDAYS_RU[cal_date.weekday()]

    formatted_date = cal_date.strftime("%d.%m")

    return (
        f"<b>🗓️ {weekday} {formatted_date} → Забронировано</b>\n\n"
        "Ты просил(а) занять место, если освободится. Ждём в офисе)\n"
        "<blockquote>Дополнительное подтверждение записи в чате <b>не требуется</b></blockquote>"
    )