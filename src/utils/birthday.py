import re
from datetime import datetime, date

def validate_birthday(value: str) -> str | None:
    value = value.strip()

    if re.fullmatch(r"\d{2}\.\d{2}", value):
        day, month = map(int, value.split("."))
        try:
            date(2000, month, day)
            return value
        except ValueError:
            return None

    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
        try:
            birthday = datetime.strptime(value, "%d.%m.%Y").date()
            if birthday > date.today():
                return None
            return value
        except ValueError:
            return None

    return None


def birthday_str_to_date(value: str) -> date | None:
    try:
        value = value.strip()
        if re.fullmatch(r"\d{2}\.\d{2}", value):
            return datetime.strptime(f"{value}.1900", "%d.%m.%Y").date()

        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
            return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None