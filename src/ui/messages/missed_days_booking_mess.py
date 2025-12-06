from datetime import date
from typing import List


def render_missed_booking_mess(choosen_dates: List[date], is_confirmation: bool = False) -> str:
    if len(choosen_dates) == 0:
        return (
            "🗓 <b>Выбор дат</b>\n\n"
            "Выберите доступные даты из календаря ниже, нажимая на нужные числа."
        )

    sorted_dates = sorted(choosen_dates)

    formatted_dates = [d.strftime("%d.%m") for d in sorted_dates]
    dates_text = "\n".join(f"• {date_str}" for date_str in formatted_dates)

    base = (f"🗓 <b>Выбранные даты</b>\n"
            f"<blockquote>{dates_text}</blockquote>\n\n")

    if is_confirmation:
        footer = "Для выхода в меню: /menu"
    else:
        footer = "Нажмите на кнопку <b>«Подтвердить»</b>, чтобы сохранить изменения ⤵︎"

    return base + footer