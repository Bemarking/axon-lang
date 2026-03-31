"""
AXON Runtime — Redis State Backend
=====================================
Production-grade CPS persistence using Redis.

Stores serialized ExecutionState in Redis keys, enabling daemon
hibernate/resume cycles to survive server restarts and even
migrate across AxonServer instances.

Key format: ``axon:state:{continuation_id}``

Dependency: redis[hiredis]>=5.2  (installed via ``pip install axon-lang[redis]``)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "axon:state:"


class RedisStateBackend:
    """
    Redis-backed state backend for production CPS persistence.

    All operations are async-safe via the redis.asyncio client.
    Uses hiredis C extension for maximum throughput.

    Usage:
        backend = RedisStateBackend(redis_url="redis://localhost:6379/0")
        await backend.connect()
        await backend.save_state("cont_123", state_bytes)
        data = await backend.load_state("cont_123")
        await backend.close()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = _KEY_PREFIX,
        ttl_seconds: int = 86400 * 7,   # 7 days default TTL
    ) -> None:
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._ttl = ttl_seconds
        self._client: Any = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        try:
            from redis.asyncio import from_url
        except ImportError as exc:
            raise ImportError(
                "redis is required for RedisStateBackend. "
                "Install it with: pip install axon-lang[redis]"
            ) from exc

        self._client = from_url(self._redis_url, decode_responses=False)
        # Verify connection
        await self._client.ping()
        logger.info("RedisStateBackend connected to %s", self._redis_url)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _key(self, continuation_id: str) -> str:
        """Build the Redis key for a continuation ID."""
        return f"{self._key_prefix}{continuation_id}"

    async def save_state(self, continuation_id: str, state: bytes) -> None:
        """Persist a serialized execution state to Redis."""
        if not self._client:
            raise RuntimeError("RedisStateBackend not connected.")
        await self._client.set(self._key(continuation_id), state, ex=self._ttl)

    async def load_state(self, continuation_id: str) -> bytes | None:
        """Load a previously saved state. Returns None if not found."""
        if not self._client:
            raise RuntimeError("RedisStateBackend not connected.")
        return await self._client.get(self._key(continuation_id))

    async def delete_state(self, continuation_id: str) -> None:
        """Remove a state after successful resume."""
        if not self._client:
            raise RuntimeError("RedisStateBackend not connected.")
        await self._client.delete(self._key(continuation_id))

    async def list_pending(self) -> list[str]:
        """List all continuation IDs with pending states."""
        if not self._client:
            raise RuntimeError("RedisStateBackend not connected.")
        keys: list[bytes] = []
        async for key in self._client.scan_iter(
            match=f"{self._key_prefix}*",
            count=100,
        ):
            keys.append(key)
        prefix_len = len(self._key_prefix)
        return [
            k.decode("utf-8")[prefix_len:] if isinstance(k, bytes)
            else k[prefix_len:]
            for k in keys
        ]
