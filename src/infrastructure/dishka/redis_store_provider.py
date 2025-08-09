from dishka import Provider, provide, Scope
from redis.asyncio import Redis

from src.storage.redis.store import RedisStore


class RedisStoreProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_redis_store(self, redis: Redis) -> RedisStore:
        return RedisStore(redis)