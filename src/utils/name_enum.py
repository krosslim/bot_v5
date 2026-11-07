from enum import StrEnum


class NameEnum(StrEnum):
    """StrEnum, где auto() даёт имя члена как есть: BOOKED = auto() → "BOOKED".

    Замена пакета strenum. У enum.StrEnum auto() даёт имя в нижнем регистре ("booked"), а эти значения
    лежат в БД (bookings.status, индекс ux_bookings_date_seat_booked) и в callback_data уже отправленных кнопок.
    """

    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list) -> str:
        return name
