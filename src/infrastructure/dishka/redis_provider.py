from typing import AsyncGenerator

from dishka import Provider, provide, Scope
from redis.asyncio import Redis

from config import Config


class RedisProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_redis(self, cfg: Config) -> AsyncGenerator[Redis, None]:
        redis = Redis.from_url(cfg.REDIS_URL, decode_responses=True)
        yield redis
        await redis.close()
