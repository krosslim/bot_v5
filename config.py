from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Config(BaseSettings):
    TOKEN: str = "TOKEN"

    REDIS_URL: str = "redis://localhost:6379/0"

    POSTGRES_URL: str = "postgresql+asyncpg://localhost:5432/bot_db_v5"
    POSTGRES_POOL_SIZE: int = 4
    POSTGRES_MAX_OVERFLOW: int = 4
    POSTGRES_POOL_TIMEOUT: int = 15
    POSTGRES_POOL_RECYCLE: int = 1800
    POSTGRES_ECHO: bool = False
    POSTGRES_POOL_PRE_PING: bool = True

    class ConfigSettings:
        env_file = ".env"

c = Config()
print(c.POSTGRES_URL)