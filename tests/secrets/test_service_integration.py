"""Integration tests for ``SecretsService`` — real DB + in-memory backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.config import SecretsSettings
from axon_enterprise.secrets import (
    InMemoryBackend,
    SecretAlreadyScheduledForDeletion,
    SecretKeyInvalid,
    SecretNotFound,
    SecretStatus,
    SecretValue,
    SecretsPolicy,
    SecretsService,
)
from axon_enterprise.secrets.service import LoggingAuditEmitter
from axon_enterprise.secrets.models import TenantSecret

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_secrets(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("TRUNCATE axon_control.tenant_secrets CASCADE")
            )


def _service() -> SecretsService:
    settings = SecretsSettings(
        backend="memory",
        path_prefix="axon/tenants",
        deletion_recovery_window_days=7,
        audit_on_read=True,
    )
    return SecretsService(
        backend=InMemoryBackend(),
        policy=SecretsPolicy.from_settings(settings),
        audit=LoggingAuditEmitter(),
        settings=settings,
    )


class _RecordingAudit:
    """Captures every emit() call for assertion."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(
        self, *, tenant_id, user_id, event_type, key, fingerprint=None, details=None
    ) -> None:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "user_id": str(user_id) if user_id else None,
                "event_type": event_type,
                "key": key,
                "fingerprint": fingerprint,
                "details": details or {},
            }
        )


# ── Happy paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_creates_metadata_row_without_value(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    row = await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        value=SecretValue("sk-test-1"),
        description="for dev flows",
    )
    # Metadata row exists and contains NO plaintext.
    assert row.key == "openai_api_key"
    assert row.storage_path == "axon/tenants/alpha/openai_api_key"
    assert row.status == SecretStatus.ACTIVE.value

    # Raw row bytes in DB must not contain the value.
    rowbytes = await admin_db.execute(
        text(
            "SELECT description || storage_path || current_version "
            "FROM axon_control.tenant_secrets "
            "WHERE tenant_id = :t AND key = :k"
        ),
        {"t": "alpha", "k": "openai_api_key"},
    )
    combined = rowbytes.scalar_one()
    assert "sk-test-1" not in combined


@pytest.mark.asyncio
async def test_reveal_returns_value_and_bumps_access_counter(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        value=SecretValue("sk-42"),
    )
    r1 = await svc.reveal_secret(admin_db, tenant_id="alpha", key="openai_api_key")
    assert r1.value.reveal() == "sk-42"

    r2 = await svc.reveal_secret(admin_db, tenant_id="alpha", key="openai_api_key")
    assert r2.value.reveal() == "sk-42"

    row = await admin_db.get(TenantSecret, ("alpha", "openai_api_key"))
    assert row is not None
    assert row.accessed_count == 2
    assert row.last_accessed_at is not None


@pytest.mark.asyncio
async def test_rotate_replaces_version(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    first = await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        value=SecretValue("v1"),
    )
    rotated = await svc.rotate_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        new_value=SecretValue("v2"),
    )
    assert rotated.current_version != first.current_version

    revealed = await svc.reveal_secret(
        admin_db, tenant_id="alpha", key="openai_api_key"
    )
    assert revealed.value.reveal() == "v2"


@pytest.mark.asyncio
async def test_list_secrets_returns_metadata_only(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        value=SecretValue("v"),
    )
    await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="anthropic_api_key",
        value=SecretValue("v"),
    )
    items = await svc.list_secrets(admin_db, tenant_id="alpha")
    assert [i.key for i in items] == ["anthropic_api_key", "openai_api_key"]
    # No field leaks the value.
    for item in items:
        for attr in ("description", "version_id"):
            assert "v" != getattr(item, attr) or attr != "version_id"


@pytest.mark.asyncio
async def test_schedule_deletion_flags_row(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    await svc.put_secret(
        admin_db, tenant_id="alpha", key="k", value=SecretValue("v")
    )
    await svc.schedule_deletion(admin_db, tenant_id="alpha", key="k")
    row = await admin_db.get(TenantSecret, ("alpha", "k"))
    assert row is not None
    assert row.status == SecretStatus.DELETED_PENDING.value
    assert row.deleted_pending_until is not None


# ── Error paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reveal_unknown_key_raises_not_found(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    with pytest.raises(SecretNotFound):
        await svc.reveal_secret(admin_db, tenant_id="alpha", key="missing")


@pytest.mark.asyncio
async def test_put_rejects_invalid_key(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    with pytest.raises(SecretKeyInvalid):
        await svc.put_secret(
            admin_db,
            tenant_id="alpha",
            key="has space",
            value=SecretValue("v"),
        )


@pytest.mark.asyncio
async def test_put_on_deleted_pending_raises(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    await svc.put_secret(
        admin_db, tenant_id="alpha", key="k", value=SecretValue("v")
    )
    await svc.schedule_deletion(admin_db, tenant_id="alpha", key="k")
    with pytest.raises(SecretAlreadyScheduledForDeletion):
        await svc.put_secret(
            admin_db, tenant_id="alpha", key="k", value=SecretValue("v2")
        )


# ── Audit emission ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_emits_on_every_mutation_and_read(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    rec = _RecordingAudit()
    settings = SecretsSettings(backend="memory", audit_on_read=True)
    svc = SecretsService(
        backend=InMemoryBackend(),
        policy=SecretsPolicy.from_settings(settings),
        audit=rec,
        settings=settings,
    )
    uid = uuid4()
    await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="k",
        value=SecretValue("v"),
        user_id=uid,
    )
    await svc.reveal_secret(admin_db, tenant_id="alpha", key="k", user_id=uid)
    await svc.rotate_secret(
        admin_db,
        tenant_id="alpha",
        key="k",
        new_value=SecretValue("v2"),
        user_id=uid,
    )
    await svc.schedule_deletion(
        admin_db, tenant_id="alpha", key="k", user_id=uid
    )

    event_types = [e["event_type"] for e in rec.events]
    assert event_types == [
        "secret:create",
        "secret:read",
        "secret:rotate",
        "secret:delete_scheduled",
    ]
    for e in rec.events:
        # No event body carries the plaintext value — only fingerprints.
        assert "v" != e.get("fingerprint")
        assert "v2" != e.get("fingerprint")


@pytest.mark.asyncio
async def test_audit_on_read_can_be_disabled(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    rec = _RecordingAudit()
    settings = SecretsSettings(backend="memory", audit_on_read=False)
    svc = SecretsService(
        backend=InMemoryBackend(),
        policy=SecretsPolicy.from_settings(settings),
        audit=rec,
        settings=settings,
    )
    await svc.put_secret(
        admin_db, tenant_id="alpha", key="k", value=SecretValue("v")
    )
    rec.events.clear()  # discard create event
    await svc.reveal_secret(admin_db, tenant_id="alpha", key="k")
    assert rec.events == []


# ── Tenant RLS isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rls_hides_secret_metadata_from_other_tenants(
    admin_db: AsyncSession, _clean_secrets: None
) -> None:
    svc = _service()
    await svc.put_secret(
        admin_db,
        tenant_id="alpha",
        key="openai_api_key",
        value=SecretValue("v"),
    )

    async with admin_db.begin_nested():
        await admin_db.execute(
            text("SELECT set_config('axon.current_tenant', 'beta', true)")
        )
        count = (
            await admin_db.execute(
                text(
                    "SELECT COUNT(*) FROM axon_control.tenant_secrets "
                    "WHERE key = 'openai_api_key'"
                )
            )
        ).scalar_one()
        assert count == 0
