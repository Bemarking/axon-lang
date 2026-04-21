"""Rate limiter — sliding window per ``(tenant_id, metric_type)``.

Redis is the production backend (cross-replica, atomic). In-memory
is the dev / single-replica fallback — also used in tests so we
don't need Docker Compose just to verify the limiter's arithmetic.

The limiter does NOT enforce monthly quotas; that is the
``QuotaEnforcer``'s job and uses Postgres. The limiter is for hot-
path ``rpm`` / ``tpm`` decisions where a sub-millisecond response
matters.

Key shape: ``axon:rate:{tenant_id}:{metric}:{minute_bucket}``. TTL
set to 120 seconds so a minute's worth of counters survive a
restart without outliving relevance.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import structlog

from axon_enterprise.config import MeteringSettings, get_settings
from axon_enterprise.metering.errors import (
    MeteringBackendError,
    RateLimited,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.metering.limiter"
)


# ── Protocol ─────────────────────────────────────────────────────────


@runtime_checkable
class RateLimiter(Protocol):
    """Sliding-window counter with an atomic check-and-record path."""

    async def check_and_record(
        self,
        *,
        tenant_id: str,
        metric: str,
        quantity: int,
        limit_per_minute: int,
    ) -> None:
        """Raise :class:`RateLimited` when ``limit_per_minute`` would be exceeded."""
        ...


# ── In-memory ────────────────────────────────────────────────────────


@dataclass
class InMemoryRateLimiter:
    """Dev / test limiter. Thread-safe, single-process."""

    _buckets: dict[tuple[str, str], deque[tuple[float, int]]] = field(
        default_factory=lambda: defaultdict(deque)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    async def check_and_record(
        self,
        *,
        tenant_id: str,
        metric: str,
        quantity: int,
        limit_per_minute: int,
    ) -> None:
        now = time.monotonic()
        cutoff = now - 60.0
        key = (tenant_id, metric)
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0][0] < cutoff:
                bucket.popleft()
            current = sum(q for _, q in bucket)
            if current + quantity > limit_per_minute:
                retry_after = int(max(1, bucket[0][0] + 60 - now)) if bucket else 60
                raise RateLimited(
                    metric=metric, retry_after_seconds=retry_after
                )
            bucket.append((now, quantity))

    def _reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# ── Redis ────────────────────────────────────────────────────────────


@dataclass
class RedisRateLimiter:
    """Redis-backed sliding window.

    Uses ZADD with timestamped scores + ZRANGEBYSCORE to count
    entries inside the last 60 seconds. Atomic via a short Lua
    script so check-and-record is one round-trip.
    """

    url: str
    _client: "object | None" = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    _LUA_SCRIPT: str = (
        # KEYS[1] = sliding-window key
        # ARGV[1] = now (unix seconds)
        # ARGV[2] = window length (seconds)
        # ARGV[3] = quantity to add
        # ARGV[4] = limit per window
        # Return: 0 when allowed (and added), integer retry_after when blocked
        "redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - ARGV[2])\n"
        "local count = 0\n"
        "local members = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')\n"
        "for i = 2, #members, 2 do\n"
        "    count = count + tonumber(members[i - 1]:match('^(%d+):') or 0)\n"
        "end\n"
        "if count + tonumber(ARGV[3]) > tonumber(ARGV[4]) then\n"
        "    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')\n"
        "    if #oldest >= 2 then\n"
        "        local retry = math.ceil(tonumber(oldest[2]) + ARGV[2] - ARGV[1])\n"
        "        if retry < 1 then retry = 1 end\n"
        "        return retry\n"
        "    end\n"
        "    return tonumber(ARGV[2])\n"
        "end\n"
        "local member = tostring(ARGV[3]) .. ':' .. redis.call('INCR', KEYS[1] .. ':seq')\n"
        "redis.call('ZADD', KEYS[1], ARGV[1], member)\n"
        "redis.call('EXPIRE', KEYS[1], 120)\n"
        "return 0\n"
    )

    async def _connect(self) -> None:
        if self._client is not None:
            return
        async with self._lock:
            if self._client is not None:
                return
            try:
                import redis.asyncio as aioredis  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover
                raise MeteringBackendError(
                    "redis>=5.0 required for RedisRateLimiter — "
                    "pip install redis"
                ) from exc
            self._client = aioredis.from_url(self.url, decode_responses=True)

    async def check_and_record(
        self,
        *,
        tenant_id: str,
        metric: str,
        quantity: int,
        limit_per_minute: int,
    ) -> None:
        await self._connect()
        key = f"axon:rate:{tenant_id}:{metric}"
        now = int(time.time())
        try:
            retry = await self._client.eval(  # type: ignore[attr-defined]
                self._LUA_SCRIPT,
                1,
                key,
                str(now),
                "60",
                str(quantity),
                str(limit_per_minute),
            )
        except Exception as exc:  # noqa: BLE001
            raise MeteringBackendError(f"redis rate limiter: {exc}") from exc
        retry_int = int(retry or 0)
        if retry_int > 0:
            raise RateLimited(metric=metric, retry_after_seconds=retry_int)


# ── Factory ──────────────────────────────────────────────────────────


def build_rate_limiter(
    settings: MeteringSettings | None = None,
) -> RateLimiter:
    s = settings or get_settings().metering
    if s.rate_limit_backend == "redis":
        if s.rate_limit_redis_url is None:
            raise MeteringBackendError(
                "metering.rate_limit_redis_url is required when backend='redis'"
            )
        return RedisRateLimiter(url=s.rate_limit_redis_url.get_secret_value())
    return InMemoryRateLimiter()
