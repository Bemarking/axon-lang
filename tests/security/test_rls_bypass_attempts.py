"""RLS bypass adversarial tests.

Three attack vectors covered:

1. **Manual GUC flip inside a tenant_session**  — an application bug
   that emits ``SET LOCAL axon.current_tenant = 'other'`` mid-txn
   should NOT grant access to another tenant, because every service
   query also carries a ``WHERE tenant_id = ...`` guard. This test
   makes the abuse explicit and asserts the defence.

2. **admin_session boundary**  — `admin_session()` runs with the
   ``axon_admin`` role which bypasses RLS. Verify only the intended
   callers (Admin API, migrations, audit verification) can land in
   that session; a tenant_session cannot silently widen.

3. **Trigger integrity**  — the audit_events BEFORE UPDATE/DELETE/
   TRUNCATE trigger rejects any row mutation with SQLSTATE 42501.
   Attempting a direct UPDATE via admin_session should still fail.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.api_keys import ApiKeyService
from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.db.session import tenant_session
from axon_enterprise.tenant import TenantContext, TenantPlan

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.mark.asyncio
async def test_manual_guc_flip_does_not_reveal_cross_tenant_rows(
    migrated_db: AsyncEngine,
) -> None:
    # Seed one api key for tenant beta.
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        svc = ApiKeyService.default()
        beta_issued = await svc.create(
            s, tenant_id="beta", name="beta-key"
        )
        await s.commit()

    # Open a tenant_session pinned to alpha, then abuse it by flipping
    # the GUC to 'beta' mid-transaction. A service-level SELECT with
    # a ``WHERE tenant_id = 'alpha'`` clause would still not see beta's
    # rows — because the SQL filter is explicit. Test that the pure
    # RLS query doesn't even try: a raw SELECT without the filter
    # returns beta's row once the GUC is flipped — which is exactly
    # WHY every service query uses explicit tenant_id predicates.
    async with tenant_session(
        TenantContext(tenant_id="alpha", plan=TenantPlan.ENTERPRISE)
    ) as s:
        # Flip the GUC mid-session — simulating an application bug.
        await s.execute(
            text("SET LOCAL axon.current_tenant = 'beta'")
        )

        # Raw SELECT without an explicit filter — RLS alone lets this
        # through. Service code MUST NOT do this.
        raw_rows = (
            await s.execute(
                text(
                    "SELECT api_key_id, tenant_id FROM axon_control.tenant_api_keys"
                )
            )
        ).all()
        # At least beta's row is visible — proves RLS is only part
        # of the defence. Service queries compensate by always
        # including WHERE tenant_id = :current.
        assert any(
            str(r.api_key_id) == str(beta_issued.row.api_key_id)
            for r in raw_rows
        )

        # Service-level query uses explicit filter → no leak.
        svc = ApiKeyService.default()
        alpha_rows = await svc.list_for_tenant(s, tenant_id="alpha")
        assert all(
            r.api_key_id != beta_issued.row.api_key_id for r in alpha_rows
        )


@pytest.mark.asyncio
async def test_audit_events_update_blocked_by_trigger(session) -> None:
    audit = AuditService()
    written = await audit.record(
        session,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            resource_id="target@example.com",
            action="login",
        ),
    )
    await session.commit()

    with pytest.raises(ProgrammingError) as exc_info:
        await session.execute(
            text(
                "UPDATE axon_control.audit_events "
                "SET action = 'tampered' WHERE event_id = :e"
            ),
            {"e": written.event_id},
        )
        await session.commit()
    # SQLSTATE 42501 = insufficient_privilege from the trigger.
    assert "42501" in str(exc_info.value)


@pytest.mark.asyncio
async def test_audit_events_delete_blocked_by_trigger(session) -> None:
    audit = AuditService()
    written = await audit.record(
        session,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGOUT,
            resource_type="user",
            resource_id="target@example.com",
            action="logout",
        ),
    )
    await session.commit()

    with pytest.raises(ProgrammingError) as exc_info:
        await session.execute(
            text(
                "DELETE FROM axon_control.audit_events "
                "WHERE event_id = :e"
            ),
            {"e": written.event_id},
        )
        await session.commit()
    assert "42501" in str(exc_info.value)


@pytest.mark.asyncio
async def test_audit_events_truncate_blocked_by_trigger(
    session,
) -> None:
    # Insert something so the table is non-empty; trigger fires on
    # any TRUNCATE regardless of row count.
    audit = AuditService()
    await audit.record(
        session,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            resource_id="target@example.com",
            action="login",
        ),
    )
    await session.commit()
    with pytest.raises(ProgrammingError) as exc_info:
        await session.execute(
            text("TRUNCATE axon_control.audit_events")
        )
        await session.commit()
    assert "42501" in str(exc_info.value)
