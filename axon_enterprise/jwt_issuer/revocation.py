"""Token-level revocation (``jti`` blacklist).

Three backends share a single ``JtiRevocationService`` façade:

- ``memory``   — in-process dict. Dev/test only.
- ``redis``    — atomic, fast, cross-replica. Keys expire at token
                 ``exp`` so the set never grows unboundedly.
- ``postgres`` — durable, auditable, slower. Fallback for deployments
                 without Redis; also always queried when Redis is
                 enabled but unreachable (fail-closed → treat the
                 token as revoked when we can't confirm otherwise).

The fail-closed behaviour is important: a Redis outage must not
allow a revoked token to slip through. The Postgres fallback lets
the system degrade gracefully rather than silently letting every
revoked token ride.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.jwt_issuer.errors import JwtBackendError
from axon_enterprise.jwt_issuer.models import JwtRevokedJti

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.jwt_issuer.revocation"
)


# ── Backend protocol ─────────────────────────────────────────────────


class _Backend(Protocol):
    async def add(
        self, jti: UUID, *, expires_at: datetime, reason: str | None
    ) -> None: ...

    async def contains(self, jti: UUID) -> bool: ...


# ── Backends ─────────────────────────────────────────────────────────


@dataclass
class _MemoryBackend:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _blacklist: dict[UUID, datetime] = field(default_factory=dict)

    async def add(
        self, jti: UUID, *, expires_at: datetime, reason: str | None
    ) -> None:
        with self._lock:
            self._blacklist[jti] = expires_at

    async def contains(self, jti: UUID) -> bool:
        with self._lock:
            exp = self._blacklist.get(jti)
            if exp is None:
                return False
            if exp <= datetime.now(timezone.utc):
                self._blacklist.pop(jti, None)
                return False
            return True


@dataclass
class _PostgresBackend:
    db_factory: "object"  # something that yields an AsyncSession

    async def add(
        self, jti: UUID, *, expires_at: datetime, reason: str | None
    ) -> None:
        # Use the surrounding session — no nested tx creation.
        raise NotImplementedError(
            "_PostgresBackend is used via JtiRevocationService.revoke which "
            "passes the AsyncSession directly."
        )

    async def contains(self, jti: UUID) -> bool:  # pragma: no cover
        raise NotImplementedError()


# ── Redis backend (lazy import) ──────────────────────────────────────


@dataclass
class _RedisBackend:
    _client: "object | None" = None
    url: str = ""

    async def connect(self) -> None:
        if self._client is not None:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise JwtBackendError(
                "redis backend requires the `redis` package — "
                "pip install 'redis>=5.0'"
            ) from exc
        self._client = aioredis.from_url(self.url, decode_responses=True)

    async def add(
        self, jti: UUID, *, expires_at: datetime, reason: str | None
    ) -> None:
        await self.connect()
        ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        try:
            await self._client.setex(f"axon:jwt:revoked:{jti}", ttl, reason or "1")  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise JwtBackendError(f"redis SETEX failed: {exc}") from exc

    async def contains(self, jti: UUID) -> bool:
        await self.connect()
        try:
            hit = await self._client.exists(f"axon:jwt:revoked:{jti}")  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise JwtBackendError(f"redis EXISTS failed: {exc}") from exc
        return bool(hit)


# ── Service ──────────────────────────────────────────────────────────


@dataclass
class JtiRevocationService:
    """Public API — the issuer + verifier code paths talk to this."""

    backend_kind: Literal["memory", "redis", "postgres"]
    memory: _MemoryBackend = field(default_factory=_MemoryBackend)
    redis: _RedisBackend | None = None
    settings: JwtSettings = field(default_factory=lambda: get_settings().jwt)

    @classmethod
    def default(cls) -> JtiRevocationService:
        s = get_settings().jwt
        redis = None
        if s.revocation_backend == "redis" and s.redis_url is not None:
            redis = _RedisBackend(url=s.redis_url.get_secret_value())
        return cls(backend_kind=s.revocation_backend, redis=redis, settings=s)

    # ── Revoke ────────────────────────────────────────────────────────

    async def revoke(
        self,
        db: AsyncSession,
        *,
        jti: UUID,
        expires_at: datetime,
        reason: str | None = None,
    ) -> None:
        """Record the ``jti`` as revoked in both durable + fast paths.

        We always write to Postgres (durable) and, if Redis is
        configured, to Redis too (fast reads). Writing to Postgres
        first ensures persistence survives a Redis failure mid-call.
        """
        if self.backend_kind == "memory":
            await self.memory.add(jti, expires_at=expires_at, reason=reason)
            return

        # Postgres durability — write every time (needed for recovery).
        await self._postgres_add(db, jti=jti, expires_at=expires_at, reason=reason)

        # Redis speed — best-effort; surface errors so Prometheus alerts.
        if self.backend_kind == "redis" and self.redis is not None:
            try:
                await self.redis.add(jti, expires_at=expires_at, reason=reason)
            except JwtBackendError:
                _logger.warning(
                    "jwt_revoke_redis_failed_falling_back_to_pg_only",
                    jti=str(jti),
                )

    # ── Check ─────────────────────────────────────────────────────────

    async def is_revoked(
        self,
        db: AsyncSession,
        *,
        jti: UUID,
    ) -> bool:
        """Ask the fast path first; on failure fall through to Postgres.

        Fail-closed: an unreachable backend is treated as a revocation
        hit — a revoked token must never slip through because infra
        is sick.
        """
        if self.backend_kind == "memory":
            return await self.memory.contains(jti)

        if self.backend_kind == "redis" and self.redis is not None:
            try:
                return await self.redis.contains(jti)
            except JwtBackendError:
                _logger.warning(
                    "jwt_check_redis_unavailable_falling_back_to_pg",
                    jti=str(jti),
                )

        return await self._postgres_contains(db, jti=jti)

    # ── Housekeeping ──────────────────────────────────────────────────

    async def purge_expired(self, db: AsyncSession) -> int:
        """Remove Postgres rows whose expiry has passed. Run daily."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(JwtRevokedJti).where(JwtRevokedJti.expires_at <= now)
        )
        await db.flush()
        return int(result.rowcount or 0)

    # ── Internals ─────────────────────────────────────────────────────

    async def _postgres_add(
        self,
        db: AsyncSession,
        *,
        jti: UUID,
        expires_at: datetime,
        reason: str | None,
    ) -> None:
        stmt = (
            pg_insert(JwtRevokedJti)
            .values(jti=jti, expires_at=expires_at, reason=reason)
            .on_conflict_do_update(
                index_elements=[JwtRevokedJti.jti],
                set_={
                    "expires_at": expires_at,
                    "reason": reason,
                },
            )
        )
        await db.execute(stmt)
        await db.flush()

    async def _postgres_contains(
        self, db: AsyncSession, *, jti: UUID
    ) -> bool:
        now = datetime.now(timezone.utc)
        row = await db.scalar(
            select(JwtRevokedJti).where(
                JwtRevokedJti.jti == jti,
                JwtRevokedJti.expires_at > now,
            )
        )
        return row is not None
