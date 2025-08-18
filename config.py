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

    REDIS_URL: str = "redis://localhost:6379/0"

    POSTGRES_URL: str = "postgresql+asyncpg://localhost:5432/bot_db_v5"
    POSTGRES_POOL_SIZE: int = 4
    POSTGRES_MAX_OVERFLOW: int = 4
    POSTGRES_POOL_TIMEOUT: int = 15
    POSTGRES_POOL_RECYCLE: int = 1800
    POSTGRES_ECHO: bool = False
    POSTGRES_POOL_PRE_PING: bool = True

    TG_CHAT_ID: int = -681141068


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