from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.dto.booking_dto import BookingStatus
from src.ui.keyboard.actions import MyBookingCB, MyBookingStep
from src.utils.idk import gen_idk

def _ddmm(d) -> str:
    return f"{d.day:02d}.{d.month:02d}"

def render_my_booking_kb(data, back_btn, back_btn_text) -> InlineKeyboardMarkup:

    booked, waitlist = data

    builder = InlineKeyboardBuilder()

    # --- Есть оба списка: верхнее меню ---
    if booked and waitlist:
        builder.row(
            InlineKeyboardButton(
                text="🗓 Мои бронирования",
                callback_data=MyBookingCB(
                    step=MyBookingStep.BOOKINGS,
                    idk=gen_idk()
                ).pack(),
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="⏳Я в листе ожидания",
                callback_data=MyBookingCB(
                    step=MyBookingStep.WAITLIST,
                    idk=gen_idk()
                ).pack(),
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"{back_btn_text}",
                callback_data=MyBookingCB(
                    step=back_btn,
                    idk=gen_idk()
                ).pack(),
            ),
            # InlineKeyboardButton(
            #     text="ℹ️ Инструкция",
            #     callback_data=MyBookingCB(
            #         step=MyBookingStep.GET_INFO,
            #         idk=gen_idk()
            #     ).pack(),
            # ),
        )
        return builder.as_markup()

    # --- Только бронирования ---
    if booked and not waitlist:
        for b in sorted(booked, key=lambda x: x.cal_date):
            d = b.cal_date
            text = _ddmm(d)
            extra = f"{d.isoformat()}|{(getattr(b, 'sub_status', '') or '').upper()}"
            builder.button(
                text=text,
                callback_data=MyBookingCB(
                    step=MyBookingStep.BOOK_DAY,
                    extra=extra,
                    idk=gen_idk()
                ).pack(),
            )
        builder.adjust(5)

        # Последний ряд — назад
        builder.row(
            InlineKeyboardButton(
                text=f"{back_btn_text}",
                callback_data=MyBookingCB(
                    step=back_btn,
                    idk=gen_idk()
                ).pack(),
            )
        )
        return builder.as_markup()

    # --- Только лист ожидания ---
    if waitlist and not booked:
        for w in sorted(waitlist, key=lambda x: x.cal_date):
            d = w.cal_date
            builder.button(
                text=_ddmm(d),
                callback_data=MyBookingCB(
                    step=MyBookingStep.WAITLIST_DAY,
                    extra=d.isoformat(),
                    idk=gen_idk()
                ).pack(),
            )
        builder.adjust(5)

        builder.row(
            InlineKeyboardButton(
                text=f"{back_btn_text}",
                callback_data=MyBookingCB(
                    step=back_btn,
                    idk=gen_idk()
                ).pack(),
            )
        )
        return builder.as_markup()

    # --- Оба списка пустые ---
    builder.row(
        InlineKeyboardButton(
            text=f"{back_btn_text}",
            callback_data=MyBookingCB(
                step=back_btn,
                idk=gen_idk()
            ).pack(),
        )
    )
    return builder.as_markup()


def render_book_day_kb(date: str, sub_status: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    confirm_button = InlineKeyboardButton(
        text="✅ Подтвердить бронирование",
        callback_data=MyBookingCB(
            step=MyBookingStep.CONFIRM_BOOKING,
            extra=date,
            idk=gen_idk()
        ).pack()
    )
    cancel_button = InlineKeyboardButton(
        text="❌ Отменить бронирование",
        callback_data=MyBookingCB(
            step=MyBookingStep.CANCEL_BOOKING,
            extra=date,
            idk=gen_idk()
        ).pack()
    )
    cancel_waitlist_button = InlineKeyboardButton(
        text="🚪 Выйти из очереди",
        callback_data=MyBookingCB(
            step=MyBookingStep.LEAVE_QUEUE,
            extra=date,
            idk=gen_idk()
        ).pack()
    )

    back_button = InlineKeyboardButton(
        text="« Вернуться назад",
        callback_data=MyBookingCB(
            step=MyBookingStep.GET_BACK_MY_BOOKING_DAYS,
            idk=gen_idk()
        ).pack()
    )
    back_button_waitlist = InlineKeyboardButton(
        text="« Вернуться назад",
        callback_data=MyBookingCB(
            step=MyBookingStep.GET_BACK_MY_WAITLIST_DAYS,
            idk=gen_idk()
        ).pack()
    )

    if sub_status == BookingStatus.RESERVED:
        buttons = [confirm_button, cancel_button, back_button]
    elif sub_status == BookingStatus.CONFIRMED:
        buttons = [cancel_button, back_button]
    else:
        buttons = [cancel_waitlist_button, back_button_waitlist]

    return kb.row(*buttons, width=1).as_markup()