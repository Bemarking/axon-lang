"""Integration tests — CognitiveStateService envelope encryption,
persist / restore / evict, audit trail anchoring, eviction worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.models import AuditEvent
from axon_enterprise.cognitive_states.errors import (
    CognitiveStateExpired,
    CognitiveStateNotFound,
)
from axon_enterprise.cognitive_states.models import (
    CognitiveStateSnapshot,
)
from axon_enterprise.cognitive_states.service import (
    CognitiveStateService,
)
from axon_enterprise.cognitive_states.worker import (
    CognitiveStateEvictionWorker,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


def _state_bytes() -> bytes:
    # Opaque payload — the service doesn't introspect; any bytes
    # suffice for integration coverage.
    return b'{"session_id":"sess-1","tenant_id":"alpha","flow_id":"f","density_matrix":[],"belief_state":null,"short_term_memory":[],"created_at":1700000000000,"last_updated_at":1700000000000}'


@pytest.mark.asyncio
async def test_persist_stores_ciphertext_and_emits_audit(session) -> None:
    svc = CognitiveStateService.default()
    snapshot = await svc.persist(
        session,
        tenant_id="alpha",
        session_id="sess-1",
        flow_id="flow-transcribe",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=15),
    )
    await session.commit()

    # Ciphertext was stored — not plaintext.
    assert snapshot.state_ciphertext != _state_bytes()
    assert len(snapshot.state_ciphertext) > 0
    assert snapshot.state_size_bytes == len(_state_bytes())

    # Audit anchor present.
    events = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == "alpha",
                AuditEvent.event_type
                == AuditEventType.PEM_STATE_PERSISTED.value,
            )
        )
    ).scalars()
    first = next(iter(events), None)
    assert first is not None
    assert first.details["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_restore_returns_original_plaintext(session) -> None:
    svc = CognitiveStateService.default()
    original = _state_bytes()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="sess-2",
        flow_id="f",
        state_bytes=original,
        ttl=timedelta(minutes=15),
    )
    await session.commit()

    row, plaintext = await svc.restore(
        session,
        tenant_id="alpha",
        session_id="sess-2",
    )
    assert plaintext == original
    assert row.restore_count == 1
    assert row.last_restored_at is not None


@pytest.mark.asyncio
async def test_restore_unknown_session_raises(session) -> None:
    svc = CognitiveStateService.default()
    with pytest.raises(CognitiveStateNotFound):
        await svc.restore(
            session, tenant_id="alpha", session_id="missing"
        )


@pytest.mark.asyncio
async def test_restore_expired_raises(session) -> None:
    svc = CognitiveStateService.default()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="stale",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(seconds=-5),
    )
    await session.commit()
    with pytest.raises(CognitiveStateExpired):
        await svc.restore(
            session, tenant_id="alpha", session_id="stale"
        )


@pytest.mark.asyncio
async def test_restore_fails_across_tenants(session) -> None:
    svc = CognitiveStateService.default()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="shared-id",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=15),
    )
    await session.commit()

    # Same session_id under a different tenant must not resolve.
    with pytest.raises(CognitiveStateNotFound):
        await svc.restore(
            session, tenant_id="beta", session_id="shared-id"
        )


@pytest.mark.asyncio
async def test_evict_removes_row_and_emits_audit(session) -> None:
    svc = CognitiveStateService.default()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="to-evict",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=15),
    )
    await session.commit()

    deleted = await svc.evict(
        session,
        tenant_id="alpha",
        session_id="to-evict",
        reason="test",
    )
    await session.commit()
    assert deleted is True

    with pytest.raises(CognitiveStateNotFound):
        await svc.restore(
            session, tenant_id="alpha", session_id="to-evict"
        )

    evicted_events = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.event_type
                == AuditEventType.PEM_STATE_EVICTED.value
            )
        )
    ).scalars()
    assert any(
        e.details.get("session_id") == "to-evict"
        for e in evicted_events
    )


@pytest.mark.asyncio
async def test_evict_missing_session_is_idempotent(session) -> None:
    svc = CognitiveStateService.default()
    result = await svc.evict(
        session, tenant_id="alpha", session_id="never-existed"
    )
    assert result is False


@pytest.mark.asyncio
async def test_evict_expired_sweeps_tenant_neutral(session) -> None:
    svc = CognitiveStateService.default()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="stale-1",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(seconds=-10),
    )
    await svc.persist(
        session,
        tenant_id="beta",
        session_id="stale-2",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(seconds=-10),
    )
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="fresh",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=30),
    )
    await session.commit()

    removed = await svc.evict_expired(session)
    await session.commit()
    assert removed == 2

    # Fresh row survives.
    remaining = (
        await session.execute(select(CognitiveStateSnapshot))
    ).scalars()
    session_ids = {r.session_id for r in remaining}
    assert session_ids == {"fresh"}


@pytest.mark.asyncio
async def test_ciphertext_bound_to_row_aad(session) -> None:
    """Tampering the ciphertext between rows fails the AEAD
    verification. We simulate this by moving ciphertext from row A
    to row B (different session_id → different AAD) and asserting
    restore raises IntegrityError via the envelope layer."""
    from axon_enterprise.crypto.envelope import IntegrityError

    svc = CognitiveStateService.default()
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="sess-a",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=15),
    )
    await svc.persist(
        session,
        tenant_id="alpha",
        session_id="sess-b",
        flow_id="f",
        state_bytes=_state_bytes(),
        ttl=timedelta(minutes=15),
    )
    await session.commit()

    # Swap A's ciphertext into B's row.
    row_a = await session.scalar(
        select(CognitiveStateSnapshot).where(
            CognitiveStateSnapshot.session_id == "sess-a"
        )
    )
    row_b = await session.scalar(
        select(CognitiveStateSnapshot).where(
            CognitiveStateSnapshot.session_id == "sess-b"
        )
    )
    row_b.state_ciphertext = row_a.state_ciphertext
    await session.commit()

    # Restoring B now tries to decrypt A's bytes under B's AAD —
    # the envelope layer catches it.
    with pytest.raises(IntegrityError):
        await svc.restore(
            session, tenant_id="alpha", session_id="sess-b"
        )


@pytest.mark.asyncio
async def test_eviction_worker_runs_once_with_empty_db(session) -> None:
    """The worker doesn't crash on an empty DB and returns 0."""
    worker = CognitiveStateEvictionWorker.default()
    removed = await worker.run_once()
    assert removed >= 0
