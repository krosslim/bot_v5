def render_help_booking_mess(has_holiday: bool, has_available: bool) -> str:

    message = ("⚪️ — Места еще есть\n\n"
               "🟢 — Ты уже забронировал\n")

    if not has_available:
        message +=("───────────\n"
                "🔴 — Мест нет\nДля записи в очередь, нажми кнопку c ⏳\n\n"
                "🟡️ — Ты в очереди\nДля выхода из очереди, нажми кнопку с 🚪\n")
    if has_holiday:
        message +=("───────────\n"
                  "🌴 — Праздничный день")

    return message
