"""Integration — AuditService against a real Postgres with RLS + triggers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.audit import (
    AuditEvent,
    AuditEventType,
    AuditService,
    AuditWriteRequest,
    RbacAuditAdapter,
    SecretsAuditAdapter,
)
from axon_enterprise.audit.canonical import genesis_hash

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_audit(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            # TRUNCATE hits the trigger; the superuser who owns the
            # table is still blocked by our BEFORE TRUNCATE trigger.
            # Work around for test cleanup by disabling triggers
            # for the current session's session_replication_role.
            await session.execute(
                text("SET session_replication_role = 'replica'")
            )
            await session.execute(
                text("TRUNCATE axon_control.audit_events CASCADE")
            )
            await session.execute(
                text("SET session_replication_role = 'origin'")
            )


# ── Write + sequence + chain ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_event_uses_genesis_prev_hash(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    out = await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            action="login",
            actor_user_id=uuid4(),
        ),
    )
    assert out.sequence_number == 1
    assert out.prev_hash == genesis_hash("alpha")
    assert len(out.event_hash) == 32


@pytest.mark.asyncio
async def test_sequence_increments_monotonically_per_tenant(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    for i in range(5):
        out = await svc.record(
            admin_db,
            AuditWriteRequest(
                tenant_id="alpha",
                event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                resource_type="user",
                action="login",
            ),
        )
        assert out.sequence_number == i + 1


@pytest.mark.asyncio
async def test_sequences_are_independent_per_tenant(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    a = await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.TENANT_CREATED,
            resource_type="tenant",
            action="create",
        ),
    )
    b = await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="beta",
            event_type=AuditEventType.TENANT_CREATED,
            resource_type="tenant",
            action="create",
        ),
    )
    assert a.sequence_number == 1
    assert b.sequence_number == 1


# ── Append-only enforcement ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_blocked_by_trigger(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    out = await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            action="login",
        ),
    )
    with pytest.raises(DBAPIError):
        await admin_db.execute(
            text(
                "UPDATE axon_control.audit_events SET action = 'forged' "
                "WHERE event_id = :e"
            ),
            {"e": out.event_id},
        )


@pytest.mark.asyncio
async def test_delete_blocked_by_trigger(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    out = await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            action="login",
        ),
    )
    with pytest.raises(DBAPIError):
        await admin_db.execute(
            text("DELETE FROM axon_control.audit_events WHERE event_id = :e"),
            {"e": out.event_id},
        )


# ── Verifier ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_chain_reports_healthy_chain(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    for _ in range(5):
        await svc.record(
            admin_db,
            AuditWriteRequest(
                tenant_id="alpha",
                event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                resource_type="user",
                action="login",
            ),
        )
    report = await svc.verify_chain(admin_db, tenant_id="alpha")
    assert report.ok
    assert report.checked == 5
    assert report.broken_at is None


@pytest.mark.asyncio
async def test_verify_chain_detects_tampering(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    for _ in range(3):
        await svc.record(
            admin_db,
            AuditWriteRequest(
                tenant_id="alpha",
                event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                resource_type="user",
                action="login",
            ),
        )

    # Simulate a rogue admin who bypassed the triggers (e.g. by
    # dropping them) and rewrote the `action` of one row.
    # session_replication_role=replica disables our triggers so we
    # can inject the tamper; the verifier should still catch it.
    await admin_db.execute(text("SET session_replication_role = 'replica'"))
    await admin_db.execute(
        text(
            "UPDATE axon_control.audit_events SET action = 'tampered' "
            "WHERE tenant_id = 'alpha' AND sequence_number = 2"
        )
    )
    await admin_db.execute(text("SET session_replication_role = 'origin'"))

    report = await svc.verify_chain(admin_db, tenant_id="alpha")
    assert not report.ok
    assert report.broken_at == 2
    assert "event_hash" in (report.reason or "")


# ── Reader ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_events_filters_by_type_and_window(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            action="login",
        ),
    )
    await svc.record(
        admin_db,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.SECRET_CREATED,
            resource_type="secret",
            resource_id="openai_api_key",
            action="create",
        ),
    )

    events = await svc.list_events(
        admin_db,
        tenant_id="alpha",
        event_types=[AuditEventType.SECRET_CREATED],
    )
    assert len(events) == 1
    assert events[0].resource_id == "openai_api_key"

    since = datetime.now(timezone.utc) + timedelta(hours=1)
    future = await svc.list_events(
        admin_db, tenant_id="alpha", since=since
    )
    assert future == []


# ── Adapters ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secrets_adapter_maps_event_types(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    adapter = SecretsAuditAdapter(service=svc, db=admin_db)

    await adapter.emit(
        tenant_id="alpha",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        event_type="secret:create",
        key="openai_api_key",
        fingerprint="abcd1234",
        details={"version_id": "v1"},
    )
    await adapter.emit(
        tenant_id="alpha",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        event_type="secret:read",
        key="openai_api_key",
    )

    events = await svc.list_events(admin_db, tenant_id="alpha")
    types = [e.event_type for e in events]
    assert AuditEventType.SECRET_CREATED.value in types
    assert AuditEventType.SECRET_READ.value in types


@pytest.mark.asyncio
async def test_secrets_adapter_rejects_unmapped(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    adapter = SecretsAuditAdapter(service=svc, db=admin_db)
    with pytest.raises(ValueError, match="unmapped"):
        await adapter.emit(
            tenant_id="alpha",
            user_id=None,
            event_type="secret:teleport",
            key="k",
        )


@pytest.mark.asyncio
async def test_rbac_adapter_emits_permission_denied(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    svc = AuditService()
    adapter = RbacAuditAdapter(service=svc, db=admin_db)
    await adapter.emit_permission_denied(
        tenant_id="alpha",
        actor_user_id=UUID("00000000-0000-0000-0000-000000000001"),
        permission="tenant:delete",
    )
    events = await svc.list_events(admin_db, tenant_id="alpha")
    assert len(events) == 1
    assert events[0].event_type == AuditEventType.RBAC_PERMISSION_DENIED.value
    assert events[0].status == "denied"
    assert events[0].resource_id == "tenant:delete"


# ── Validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_rejects_bad_status(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    from axon_enterprise.audit.errors import AuditEventMalformed

    svc = AuditService()
    with pytest.raises(AuditEventMalformed):
        await svc.record(
            admin_db,
            AuditWriteRequest(
                tenant_id="alpha",
                event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                resource_type="user",
                action="login",
                status="maybe",  # not in the allowed set
            ),
        )


@pytest.mark.asyncio
async def test_record_rejects_missing_resource_type(
    admin_db: AsyncSession, _clean_audit: None
) -> None:
    from axon_enterprise.audit.errors import AuditEventMalformed

    svc = AuditService()
    with pytest.raises(AuditEventMalformed):
        await svc.record(
            admin_db,
            AuditWriteRequest(
                tenant_id="alpha",
                event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
                resource_type="",
                action="login",
            ),
        )
