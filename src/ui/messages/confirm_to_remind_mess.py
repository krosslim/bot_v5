from config import settings as s


def remind_mess(escalation: bool):
    if escalation:
        minutes_left = (
                (s.CANCEL_BOOKING_JOB_HOUR * 60 + s.CANCEL_BOOKING_JOB_MINUTES)
                - (s.CONFIRM_REMIND_REPEAT_JOB_HOUR * 60 + s.CONFIRM_REMIND_REPEAT_JOB_MINUTES)
        )

        return ("<b>❗️ Повторно напоминаем</b>\n\n"
                f"В течение <b>{minutes_left} минут</b> запись будет отменена, если не подтвердить")

    return ("<b>ℹ️ Напоминаем о брони на завтра</b>\n\n"
            f"Подтвердите визит до <b>{s.CANCEL_BOOKING_JOB_HOUR}:{s.CANCEL_BOOKING_JOB_MINUTES}.</b> "
            f"Иначе бронь отменится.\n\n"
            f"<blockquote>Автоподтверждение можно подключить через настройки:\n"
            f"/menu → Настройки → Автоподтверждение брони</blockquote>")