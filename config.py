import logging
import sys

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",
                                      frozen=True,
                                      extra='ignore')

    TOKEN: str = "TOKEN"
    BOT_USERNAME: str = "BOT_USERNAME"
    TG_CHAT_ID: int = -681141068

    REDIS_URL: str = "redis://localhost:6379/0"

    POSTGRES_URL: str = "postgresql+asyncpg://localhost:5432/bot_db_v5"
    POSTGRES_POOL_SIZE: int = 4
    POSTGRES_MAX_OVERFLOW: int = 4
    POSTGRES_POOL_TIMEOUT: int = 15
    POSTGRES_POOL_RECYCLE: int = 1800
    POSTGRES_ECHO: bool = False
    POSTGRES_POOL_PRE_PING: bool = True

    MSC_TZ: str = "Europe/Moscow"

    GOOGLE_SHEET_URL: str = "https://script.google.com/macros/s/abcd/exec"
    GOOGLE_SHEET_TOKEN: str = "TOKEN"
    GOOGLE_SHEET_USER_URL: str = "https://docs.google.com/spreadsheets"

    WORK_END_HOUR: int = 12             # Время, до которого можно бронировать место для текущего дня
    WORK_END_MINUTES: int = 00

    BOOKING_SESSION_SEC: int = 300      # Время сессии бронирования при нажатии кнопки "Забронировать место"
    PAGINATION_LIMIT_WEEKS: int = 4     # Сколько недель можно глянуть в "Забронировать место"

    REMIND_JOB_HOUR: int = 16           # Ежедневный дайджест в чате (часы запуска)
    REMIND_JOB_MINUTES: int = 00        # Ежедневный дайджест в чате (минуты запуска)

    FRIDAY_JOB_HOUR: int = 17           # Пятничное подведение итогов (часы запуска)
    FRIDAY_JOB_MINUTES: int = 45        # Пятничное подведение итогов (минуты запуска)

    CONFIRM_REMIND_JOB_HOUR: int = 18           # Напоминание о подтверждении брони (часы запуска)
    CONFIRM_REMIND_JOB_MINUTES: int = 30        # Напоминание о подтверждении брони (минуты запуска)

    CONFIRM_REMIND_REPEAT_JOB_HOUR: int = 21    # Финальное напоминание о подтверждении брони (часы запуска)
    CONFIRM_REMIND_REPEAT_JOB_MINUTES: int = 00 # Финальное напоминание о подтверждении брони (минуты запуска)

    CANCEL_BOOKING_JOB_HOUR: int = 21           # Отмена не подтвержденных броней (часы запуска)
    CANCEL_BOOKING_JOB_MINUTES: int = 30        # Отмена не подтвержденных броней (минуты запуска)


settings = Config()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout
    )
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    # logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    # logging.getLogger("sqlalchemy.pool").setLevel(logging.INFO)