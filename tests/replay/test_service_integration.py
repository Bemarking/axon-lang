"""Integration tests — ReplayService persistence + audit anchoring.

Covers:
    - record persists + anchors to audit chain (REPLAY_TOKEN_EMITTED)
    - inputs/outputs hash mismatch → ReplayTokenMalformed
    - get_by_token_hash returns the row tenant-scoped
    - tokens_for_flow ordered by recorded_at ascending
    - record_divergence + record_replay emit the expected events
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.models import AuditEvent
from axon_enterprise.replay.errors import (
    ReplayTokenMalformed,
    ReplayTokenNotFound,
)
from axon_enterprise.replay.models import ReplayTokenRecord
from axon_enterprise.replay.service import ReplayService, ReplayTokenPayload

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


def _canonical_hash_hex(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _payload(
    *,
    flow_id: str = "flow-1",
    effect: str = "call_tool:db_read",
    legal_basis: str | None = None,
    seq: int = 0,
) -> ReplayTokenPayload:
    inputs = {"flow_id": flow_id, "seq": seq}
    outputs = {"ok": True}
    return ReplayTokenPayload(
        effect_name=effect,
        inputs=inputs,
        inputs_hash_hex=_canonical_hash_hex(inputs),
        outputs=outputs,
        outputs_hash_hex=_canonical_hash_hex(outputs),
        model_version="axon.builtin.v1",
        sampling={},
        timestamp=datetime(2026, 4, 22, 12, 0, seq, tzinfo=timezone.utc),
        nonce_hex="0" * 32,
        token_hash_hex=f"deadbeef{seq:060x}",
        flow_id=flow_id,
        legal_basis=legal_basis,
    )


@pytest.mark.asyncio
async def test_record_persists_and_emits_audit_event(session) -> None:
    svc = ReplayService.default()
    payload = _payload(legal_basis="HIPAA.164_502")
    row = await svc.record(session, tenant_id="alpha", payload=payload)
    await session.commit()

    # Row persisted with audit anchor.
    assert row.token_hash_hex == payload.token_hash_hex
    assert row.legal_basis == "HIPAA.164_502"
    assert row.audit_event_id is not None

    # Matching audit_events row.
    event = await session.get(AuditEvent, row.audit_event_id)
    assert event is not None
    assert event.event_type == AuditEventType.REPLAY_TOKEN_EMITTED.value
    assert event.details["token_hash_hex"] == payload.token_hash_hex
    assert event.details["legal_basis"] == "HIPAA.164_502"


@pytest.mark.asyncio
async def test_record_rejects_tampered_inputs_hash(session) -> None:
    svc = ReplayService.default()
    payload = _payload()
    # Replace inputs_hash_hex with a wrong value.
    tampered = payload._replace(inputs_hash_hex="0" * 64)

    with pytest.raises(ReplayTokenMalformed, match="inputs_hash_hex"):
        await svc.record(session, tenant_id="alpha", payload=tampered)


@pytest.mark.asyncio
async def test_record_rejects_tampered_outputs_hash(session) -> None:
    svc = ReplayService.default()
    payload = _payload()
    tampered = payload._replace(outputs_hash_hex="1" * 64)

    with pytest.raises(ReplayTokenMalformed, match="outputs_hash_hex"):
        await svc.record(session, tenant_id="alpha", payload=tampered)


@pytest.mark.asyncio
async def test_get_by_token_hash_tenant_scoped(session) -> None:
    svc = ReplayService.default()
    payload = _payload(seq=7)
    await svc.record(session, tenant_id="alpha", payload=payload)
    await session.commit()

    row = await svc.get_by_token_hash(
        session,
        tenant_id="alpha",
        token_hash_hex=payload.token_hash_hex,
    )
    assert row.token_hash_hex == payload.token_hash_hex

    # Wrong tenant → not found, not leaked.
    with pytest.raises(ReplayTokenNotFound):
        await svc.get_by_token_hash(
            session,
            tenant_id="beta",
            token_hash_hex=payload.token_hash_hex,
        )


@pytest.mark.asyncio
async def test_tokens_for_flow_ordered(session) -> None:
    svc = ReplayService.default()
    for seq in [2, 0, 1]:  # insert out of order
        await svc.record(
            session,
            tenant_id="alpha",
            payload=_payload(flow_id="ordered-flow", seq=seq),
        )
    await session.commit()
    rows = await svc.tokens_for_flow(
        session, tenant_id="alpha", flow_id="ordered-flow"
    )
    seqs = [r.inputs["seq"] for r in rows]
    assert seqs == [0, 1, 2]


@pytest.mark.asyncio
async def test_record_divergence_emits_failure_audit(session) -> None:
    svc = ReplayService.default()
    row = await svc.record(
        session, tenant_id="alpha", payload=_payload(seq=100)
    )
    await session.commit()

    await svc.record_divergence(
        session,
        tenant_id="alpha",
        token=row,
        expected_outputs_hash_hex="expected-abc",
        actual_outputs_hash_hex="actual-def",
    )
    await session.commit()

    events = (
        await session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == "alpha",
                AuditEvent.event_type
                == AuditEventType.REPLAY_DIVERGENCE_DETECTED.value,
            )
            .order_by(AuditEvent.sequence_number.desc())
            .limit(1)
        )
    ).scalars()
    last = next(iter(events))
    assert last.status == "failure"
    assert last.details["token_hash_hex"] == row.token_hash_hex


@pytest.mark.asyncio
async def test_append_only_trigger_blocks_delete(session) -> None:
    """The migration installs BEFORE UPDATE/DELETE/TRUNCATE triggers.
    Direct tampering via SQL must raise SQLSTATE 42501."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    svc = ReplayService.default()
    row = await svc.record(
        session, tenant_id="alpha", payload=_payload(seq=200)
    )
    await session.commit()

    with pytest.raises(ProgrammingError) as exc_info:
        await session.execute(
            text(
                "DELETE FROM axon_control.replay_tokens "
                "WHERE token_id = :tid"
            ),
            {"tid": row.token_id},
        )
        await session.commit()
    assert "42501" in str(exc_info.value)
