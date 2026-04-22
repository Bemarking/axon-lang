"""CognitiveStateService — envelope-encrypted persist / restore.

The envelope AAD binds every ciphertext to its owning row — a
tampered ``state_id`` or ``tenant_id`` invalidates the tag. Restore
thus fails fast on any row-level swap attempt even before decryption
produces plaintext.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.cognitive_states.errors import (
    CognitiveStateExpired,
    CognitiveStateNotFound,
)
from axon_enterprise.cognitive_states.models import CognitiveStateSnapshot
from axon_enterprise.crypto.envelope import EnvelopeEncryption, get_envelope

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.cognitive_states.service"
)


@dataclass
class CognitiveStateService:
    """Persist + restore + evict a session's cognitive state.

    Wraps an :class:`EnvelopeEncryption` so the row never carries
    plaintext. Emits audit events for every boundary crossing
    (persist / restore / evict / reconnect_denied).
    """

    audit: AuditService
    envelope: EnvelopeEncryption

    @classmethod
    def default(cls) -> "CognitiveStateService":
        return cls(audit=AuditService(), envelope=get_envelope())

    # ── Persist ───────────────────────────────────────────────────

    async def persist(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        session_id: str,
        flow_id: str,
        state_bytes: bytes,
        ttl: timedelta,
        subject_user_id: Optional[UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
        actor_user_id: Optional[UUID] = None,
    ) -> CognitiveStateSnapshot:
        """Encrypt + upsert the snapshot, emit ``pem:state_persisted``.

        ``state_bytes`` is the output of
        :meth:`axon.runtime.pem.CognitiveState.encode` (Python) or
        the equivalent from axon-rs. The service does not parse the
        payload — it's opaque envelope input.
        """
        aad = _aad(
            tenant_id=tenant_id,
            session_id=session_id,
            flow_id=flow_id,
            subject_user_id=subject_user_id,
        )
        ciphertext = self.envelope.encrypt(state_bytes, aad)
        expires_at = datetime.now(timezone.utc) + ttl

        existing = await db.scalar(
            select(CognitiveStateSnapshot).where(
                CognitiveStateSnapshot.tenant_id == tenant_id,
                CognitiveStateSnapshot.session_id == session_id,
            )
        )
        if existing is not None:
            existing.state_ciphertext = ciphertext
            existing.state_size_bytes = len(state_bytes)
            existing.expires_at = expires_at
            existing.flow_id = flow_id
            existing.subject_user_id = subject_user_id
            existing.metadata_json = dict(metadata or {})
            snapshot = existing
        else:
            snapshot = CognitiveStateSnapshot(
                tenant_id=tenant_id,
                session_id=session_id,
                flow_id=flow_id,
                subject_user_id=subject_user_id,
                state_ciphertext=ciphertext,
                state_size_bytes=len(state_bytes),
                expires_at=expires_at,
                metadata_json=dict(metadata or {}),
            )
            db.add(snapshot)
        await db.flush()

        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.PEM_STATE_PERSISTED,
                resource_type="cognitive_state",
                resource_id=str(snapshot.state_id),
                action="persisted",
                actor_user_id=actor_user_id,
                details={
                    "session_id": session_id,
                    "flow_id": flow_id,
                    "state_size_bytes": len(state_bytes),
                    "ttl_seconds": int(ttl.total_seconds()),
                },
            ),
        )
        return snapshot

    # ── Restore ───────────────────────────────────────────────────

    async def restore(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        session_id: str,
        actor_user_id: Optional[UUID] = None,
    ) -> tuple[CognitiveStateSnapshot, bytes]:
        """Decrypt + return raw bytes plus the ORM row.

        Emits ``pem:state_restored`` + bumps ``restore_count`` so
        operators can see reconnection rates per tenant. Raises
        :class:`CognitiveStateNotFound` /
        :class:`CognitiveStateExpired` on the obvious failure paths.
        """
        row = await db.scalar(
            select(CognitiveStateSnapshot).where(
                CognitiveStateSnapshot.tenant_id == tenant_id,
                CognitiveStateSnapshot.session_id == session_id,
            )
        )
        if row is None:
            raise CognitiveStateNotFound(session_id)
        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            raise CognitiveStateExpired(
                f"session {session_id!r} expired at {row.expires_at.isoformat()}"
            )

        aad = _aad(
            tenant_id=tenant_id,
            session_id=session_id,
            flow_id=row.flow_id,
            subject_user_id=row.subject_user_id,
        )
        plaintext = self.envelope.decrypt(row.state_ciphertext, aad)

        row.last_restored_at = now
        row.restore_count += 1
        await db.flush()

        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.PEM_STATE_RESTORED,
                resource_type="cognitive_state",
                resource_id=str(row.state_id),
                action="restored",
                actor_user_id=actor_user_id,
                details={
                    "session_id": session_id,
                    "flow_id": row.flow_id,
                    "restore_count": row.restore_count,
                },
            ),
        )
        return row, plaintext

    # ── Evict ─────────────────────────────────────────────────────

    async def evict(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        session_id: str,
        actor_user_id: Optional[UUID] = None,
        reason: str = "manual",
    ) -> bool:
        """Delete the snapshot (cryptoshredding is implicit — rows
        are gone). Idempotent. Returns True iff a row was removed.
        Emits ``pem:state_evicted``."""
        row = await db.scalar(
            select(CognitiveStateSnapshot).where(
                CognitiveStateSnapshot.tenant_id == tenant_id,
                CognitiveStateSnapshot.session_id == session_id,
            )
        )
        if row is None:
            return False
        state_id = row.state_id
        await db.execute(
            delete(CognitiveStateSnapshot).where(
                CognitiveStateSnapshot.state_id == state_id
            )
        )
        await db.flush()
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.PEM_STATE_EVICTED,
                resource_type="cognitive_state",
                resource_id=str(state_id),
                action="evicted",
                actor_user_id=actor_user_id,
                details={"session_id": session_id, "reason": reason},
            ),
        )
        return True

    async def record_reconnect_denied(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        session_id: str,
        reason: str,
        actor_user_id: Optional[UUID] = None,
    ) -> None:
        """Emit ``pem:reconnect_denied`` without deleting anything.
        Called by the transport layer when a continuity-token verify
        fails (forged / expired / session-binding mismatch)."""
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.PEM_RECONNECT_DENIED,
                resource_type="cognitive_state",
                resource_id=session_id,
                action="reconnect_denied",
                actor_user_id=actor_user_id,
                status="denied",
                details={"session_id": session_id, "reason": reason},
            ),
        )

    # ── Eviction sweep (worker-driven) ─────────────────────────────

    async def evict_expired(
        self, db: AsyncSession, *, before: Optional[datetime] = None
    ) -> int:
        """Delete every snapshot whose TTL lapsed at or before
        ``before`` (defaults to now). Used by the eviction worker;
        mirrors the compliance worker pattern from §10.l."""
        cutoff = before or datetime.now(timezone.utc)
        result = await db.execute(
            delete(CognitiveStateSnapshot).where(
                CognitiveStateSnapshot.expires_at <= cutoff
            )
        )
        await db.flush()
        count = result.rowcount or 0
        if count > 0:
            _logger.info(
                "cognitive_state_eviction_swept", removed=count
            )
        return int(count)


# ── AAD construction ──────────────────────────────────────────────────


def _aad(
    *,
    tenant_id: str,
    session_id: str,
    flow_id: str,
    subject_user_id: Optional[UUID],
) -> dict[str, str]:
    """AAD binding the ciphertext to the owning row. Order-stable
    because the envelope layer canonicalises keys before folding
    into HKDF info / AES-GCM AAD."""
    aad: dict[str, str] = {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "flow_id": flow_id,
    }
    if subject_user_id is not None:
        aad["subject_user_id"] = str(subject_user_id)
    return aad


__all__ = ["CognitiveStateService"]
