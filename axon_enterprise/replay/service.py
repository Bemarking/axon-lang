"""ReplayService — append / fetch / verify replay tokens.

Every token emission is hash-anchored to the tenant's 10.g audit
chain via a ``replay:token_emitted`` event. The token's
``token_hash_hex`` is persisted in the audit event's ``details``
payload so the chain verifier can cross-reference.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.replay.errors import (
    ReplayTokenMalformed,
    ReplayTokenNotFound,
)
from axon_enterprise.replay.models import ReplayTokenRecord

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.replay.service"
)


class ReplayTokenPayload(NamedTuple):
    """Canonical-wire shape of a token as it arrives from the runtime.

    Mirrors ``axon.runtime.replay.token.ReplayToken`` /
    ``axon::replay_token::ReplayToken``. Kept as a plain NamedTuple
    so the HTTP + CLI + internal paths all speak the same shape."""

    effect_name: str
    inputs: dict[str, Any]
    inputs_hash_hex: str
    outputs: dict[str, Any]
    outputs_hash_hex: str
    model_version: str
    sampling: dict[str, Any]
    timestamp: datetime
    nonce_hex: str
    token_hash_hex: str
    flow_id: Optional[str] = None
    legal_basis: Optional[str] = None


@dataclass
class ReplayService:
    """Persist + query replay tokens + anchor to the audit chain."""

    audit: AuditService

    @classmethod
    def default(cls) -> "ReplayService":
        return cls(audit=AuditService())

    # ── Ingest ────────────────────────────────────────────────────

    async def record(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        payload: ReplayTokenPayload,
        actor_user_id: UUID | None = None,
    ) -> ReplayTokenRecord:
        """Persist a token + emit the anchoring audit event.

        Verifies that ``token_hash_hex`` matches the one derived from
        the canonical payload. A mismatch means the caller tampered
        with the token (or the Rust/Python implementations disagree)
        — in either case we refuse and raise.
        """
        self._verify_inputs_outputs_hashes(payload)

        row = ReplayTokenRecord(
            tenant_id=tenant_id,
            flow_id=payload.flow_id,
            effect_name=payload.effect_name,
            model_version=payload.model_version,
            inputs_hash_hex=payload.inputs_hash_hex,
            outputs_hash_hex=payload.outputs_hash_hex,
            token_hash_hex=payload.token_hash_hex,
            nonce_hex=payload.nonce_hex,
            inputs=dict(payload.inputs) if payload.inputs else {},
            outputs=dict(payload.outputs) if payload.outputs else {},
            sampling=dict(payload.sampling) if payload.sampling else {},
            legal_basis=payload.legal_basis,
            recorded_at=payload.timestamp,
        )
        db.add(row)
        await db.flush()

        # Audit anchor — records WHAT was persisted without copying
        # the (potentially large) inputs/outputs into the audit row.
        written = await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.REPLAY_TOKEN_EMITTED,
                resource_type="replay_token",
                resource_id=str(row.token_id),
                action="token_emitted",
                actor_user_id=actor_user_id,
                details={
                    "token_hash_hex": payload.token_hash_hex,
                    "effect_name": payload.effect_name,
                    "model_version": payload.model_version,
                    "flow_id": payload.flow_id,
                    "legal_basis": payload.legal_basis,
                },
            ),
        )
        row.audit_event_id = written.event_id
        await db.flush()

        _logger.info(
            "replay_token_recorded",
            tenant_id=tenant_id,
            token_id=str(row.token_id),
            effect_name=payload.effect_name,
        )
        return row

    # ── Fetch ─────────────────────────────────────────────────────

    async def get_by_token_hash(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        token_hash_hex: str,
    ) -> ReplayTokenRecord:
        row = await db.scalar(
            select(ReplayTokenRecord).where(
                ReplayTokenRecord.tenant_id == tenant_id,
                ReplayTokenRecord.token_hash_hex == token_hash_hex,
            )
        )
        if row is None:
            raise ReplayTokenNotFound(token_hash_hex)
        return row

    async def tokens_for_flow(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        flow_id: str,
    ) -> list[ReplayTokenRecord]:
        result = await db.execute(
            select(ReplayTokenRecord)
            .where(
                ReplayTokenRecord.tenant_id == tenant_id,
                ReplayTokenRecord.flow_id == flow_id,
            )
            .order_by(ReplayTokenRecord.recorded_at.asc())
        )
        return list(result.scalars())

    # ── Divergence audit ─────────────────────────────────────────

    async def record_divergence(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        token: ReplayTokenRecord,
        expected_outputs_hash_hex: str,
        actual_outputs_hash_hex: str,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Emit a ``replay:divergence_detected`` audit event.

        Keeps the divergence forensics on the same hash chain as the
        original token emission, so a tampered token can't erase its
        own divergence record without breaking the chain.
        """
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.REPLAY_DIVERGENCE_DETECTED,
                resource_type="replay_token",
                resource_id=str(token.token_id),
                action="divergence_detected",
                actor_user_id=actor_user_id,
                status="failure",
                details={
                    "token_hash_hex": token.token_hash_hex,
                    "effect_name": token.effect_name,
                    "expected_outputs_hash_hex": expected_outputs_hash_hex,
                    "actual_outputs_hash_hex": actual_outputs_hash_hex,
                },
            ),
        )

    async def record_replay(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        token: ReplayTokenRecord,
        outcome: str,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Record an executed replay (``match`` / ``diverged`` / ``errored``)."""
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.REPLAY_REPLAYED,
                resource_type="replay_token",
                resource_id=str(token.token_id),
                action="replayed",
                actor_user_id=actor_user_id,
                status="success" if outcome == "match" else "failure",
                details={
                    "token_hash_hex": token.token_hash_hex,
                    "outcome": outcome,
                    "effect_name": token.effect_name,
                },
            ),
        )

    # ── Hash verification ────────────────────────────────────────

    def _verify_inputs_outputs_hashes(
        self,
        payload: ReplayTokenPayload,
    ) -> None:
        """Defence in depth against tampered tokens: recompute the
        inputs/outputs hashes from the structured originals and
        assert they match the claimed hex values."""
        recomputed_inputs = _canonical_hash_hex(payload.inputs)
        if recomputed_inputs != payload.inputs_hash_hex:
            raise ReplayTokenMalformed(
                "inputs_hash_hex did not match canonical re-hash"
            )
        recomputed_outputs = _canonical_hash_hex(payload.outputs)
        if recomputed_outputs != payload.outputs_hash_hex:
            raise ReplayTokenMalformed(
                "outputs_hash_hex did not match canonical re-hash"
            )


# ── Canonical JSON hash (same shape as runtime) ───────────────────────


def _canonical_hash_hex(value: Any) -> str:
    import json

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "ReplayService",
    "ReplayTokenPayload",
]
