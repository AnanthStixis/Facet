"""Rate limiting.

Two backends behind one interface:

  * in-process  - a sliding window in a dict. Correct for a single worker,
                  which is how local development runs.
  * redis       - shared counters. Required as soon as more than one worker
                  serves traffic, because otherwise each worker enforces its
                  own private limit and the effective limit is N times higher.

Login limits are applied per IP *and* per account. Per-IP alone lets a
distributed attempt spread across addresses walk an account's password; per
account alone lets one attacker lock out every user they know the email of.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import settings
from app.core.errors import RateLimited


@dataclass(frozen=True, slots=True)
class Limit:
    times: int
    seconds: int

    @property
    def key_suffix(self) -> str:
        return f"{self.times}/{self.seconds}s"


# Tuned for a business tool, not a public API. Humans do not sign in eight
# times a minute; scripts do.
LOGIN_PER_IP = Limit(times=20, seconds=300)
LOGIN_PER_ACCOUNT = Limit(times=8, seconds=900)
REFRESH_PER_SESSION = Limit(times=60, seconds=60)
REGISTRATION_PER_IP = Limit(times=5, seconds=3600)
EXPORT_PER_USER = Limit(times=30, seconds=3600)
LOOKUP_PER_USER = Limit(times=300, seconds=60)


class RateLimiter:
    async def hit(self, key: str, limit: Limit) -> None:
        raise NotImplementedError

    async def reset(self, key: str) -> None:
        raise NotImplementedError


class InProcessRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, limit: Limit) -> None:
        bucket = self._events[f"{key}:{limit.key_suffix}"]
        now = time.monotonic()
        cutoff = now - limit.seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit.times:
            retry_after = int(bucket[0] + limit.seconds - now) + 1
            raise RateLimited(retry_after_seconds=retry_after)
        bucket.append(now)

    async def reset(self, key: str) -> None:
        for suffix in list(self._events):
            if suffix.startswith(f"{key}:"):
                self._events.pop(suffix, None)


class RedisRateLimiter(RateLimiter):
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(url, decode_responses=True)

    async def hit(self, key: str, limit: Limit) -> None:
        redis_key = f"rl:{key}:{limit.key_suffix}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            count, ttl = await pipe.execute()
        if ttl is None or ttl < 0:
            await self._redis.expire(redis_key, limit.seconds)
            ttl = limit.seconds
        if count > limit.times:
            raise RateLimited(retry_after_seconds=int(ttl))

    async def reset(self, key: str) -> None:
        async for found in self._redis.scan_iter(match=f"rl:{key}:*"):
            await self._redis.delete(found)


def build_limiter() -> RateLimiter:
    if settings.redis_url:
        return RedisRateLimiter(settings.redis_url)
    return InProcessRateLimiter()


limiter: RateLimiter = build_limiter()
