from redis.asyncio import Redis
from typing import Optional

class RedisStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def set_nx_key_ttl(self, key: str, ttl: int) -> Optional[bool]:
        return await self.redis.set(key, "1", nx=True, ex=ttl)

    async def z_add(self, key: str, value: str, score: int) -> None:
        return await self.redis.zadd(f"{key}", {f"{value}": score})

    async def z_rem(self, key: str, value: str) -> int:
        return await self.redis.zrem(key, value)

    async def z_rem_multiple(self, key: str, *values: str) -> int:
        return await self.redis.zrem(key, *values)

    async def z_range_by_score(self, key: str, min_score: str | int, max_score: str | int, withscores: bool = True) -> list:
        return await self.redis.zrangebyscore(key, min_score, max_score, withscores=withscores)

