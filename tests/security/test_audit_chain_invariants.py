"""Property tests for the audit hash-chain.

Uses ``hypothesis`` to generate sequences of audit writes and asserts
invariants that must hold regardless of content:

    I1  prev_hash(n) == event_hash(n-1) for every n > 1
    I2  event_hash is a deterministic function of (prev_hash, tenant,
        seq, type, payload) — same input yields same output
    I3  sequence_number is contiguous per tenant starting at 1
    I4  two tenants' chains are independent (tenant A's activity does
        not influence tenant B's hashes)
    I5  verify_chain(...) returns ok=True for a freshly-written chain

These are the load-bearing security properties; any regression here
means the whole compliance evidence story breaks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.audit.canonical import compute_event_hash, genesis_hash
from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.fixture
def clean_chain(migrated_db: AsyncEngine):
    """Wipe audit rows between hypothesis examples."""

    async def _clean():
        factory = async_sessionmaker(
            bind=migrated_db, expire_on_commit=False
        )
        async with factory() as s:
            async with s.begin():
                # Temporarily disable the no-delete trigger to let
                # the test fixture reset state. Re-enable on exit.
                await s.execute(
                    text(
                        "ALTER TABLE axon_control.audit_events "
                        "DISABLE TRIGGER ALL"
                    )
                )
                await s.execute(text("DELETE FROM axon_control.audit_events"))
                await s.execute(
                    text(
                        "ALTER TABLE axon_control.audit_events "
                        "ENABLE TRIGGER ALL"
                    )
                )

    return _clean


# ── I1 + I5: chain continuity after N random writes ────────────────


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(
                [
                    AuditEventType.AUTH_LOGIN_SUCCESS,
                    AuditEventType.AUTH_LOGOUT,
                    AuditEventType.USER_CREATED,
                    AuditEventType.CONFIG_CHANGED,
                ]
            ),
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Lu", "Nd"), max_codepoint=0x7F
                ),
                min_size=1,
                max_size=20,
            ),
        ),
        min_size=1,
        max_size=8,
    )
)
@pytest.mark.asyncio
async def test_chain_verifies_after_arbitrary_appends(
    migrated_db: AsyncEngine,
    clean_chain,
    events: list[tuple[AuditEventType, str]],
) -> None:
    await clean_chain()

    audit = AuditService()
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        for idx, (event_type, resource) in enumerate(events):
            await audit.record(
                s,
                AuditWriteRequest(
                    tenant_id="alpha",
                    event_type=event_type,
                    resource_type="user",
                    resource_id=f"{resource}-{idx}",
                    action="hypothesis_append",
                ),
            )
        await s.commit()

        report = await audit.verify_chain(s, tenant_id="alpha")
        assert report.ok
        assert report.checked == len(events)


# ── I2: deterministic hash function ──────────────────────────────────


def test_hash_function_is_deterministic() -> None:
    payload = {
        "actor_user_id": None,
        "actor_email": None,
        "resource_type": "user",
        "resource_id": "x@example.com",
        "action": "login",
        "status": "success",
        "ip_address": None,
        "user_agent": None,
        "details": {"note": "invariant"},
    }
    prev = genesis_hash("alpha")
    h1 = compute_event_hash(
        prev_hash=prev,
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
        payload=payload,
    )
    h2 = compute_event_hash(
        prev_hash=prev,
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
        payload=payload,
    )
    assert h1 == h2
    assert len(h1) == 32  # SHA-256 digest


# ── I4: cross-tenant chain independence ─────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_chains_are_independent(
    migrated_db: AsyncEngine, clean_chain
) -> None:
    await clean_chain()

    audit = AuditService()
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        # Interleave writes — verify both chains still validate.
        for i in range(3):
            await audit.record(
                s,
                AuditWriteRequest(
                    tenant_id="alpha",
                    event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                    resource_type="user",
                    resource_id=f"a-{i}",
                    action="login",
                ),
            )
            await audit.record(
                s,
                AuditWriteRequest(
                    tenant_id="beta",
                    event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                    resource_type="user",
                    resource_id=f"b-{i}",
                    action="login",
                ),
            )
        await s.commit()

        assert (await audit.verify_chain(s, tenant_id="alpha")).ok
        assert (await audit.verify_chain(s, tenant_id="beta")).ok


# ── I3: sequence numbers are contiguous per tenant ──────────────────


@pytest.mark.asyncio
async def test_sequence_numbers_are_contiguous(
    migrated_db: AsyncEngine, clean_chain
) -> None:
    await clean_chain()

    audit = AuditService()
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        for i in range(5):
            await audit.record(
                s,
                AuditWriteRequest(
                    tenant_id="gamma",
                    event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                    resource_type="user",
                    resource_id=f"user-{i}",
                    action="login",
                ),
            )
        await s.commit()

        rows = list(
            (
                await s.execute(
                    text(
                        "SELECT sequence_number FROM axon_control.audit_events "
                        "WHERE tenant_id = 'gamma' ORDER BY sequence_number"
                    )
                )
            )
        )
        seqs = [r[0] for r in rows]
        assert seqs == list(range(1, 6))
