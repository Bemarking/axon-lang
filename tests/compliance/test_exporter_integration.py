"""Integration — SarExporter produces a valid tar.gz with the expected shape."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.exporter import SarExporter
from axon_enterprise.compliance.local_blob_store import LocalBlobStore
from axon_enterprise.config import ComplianceSettings
from axon_enterprise.identity.models import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


def _exporter(tmp_path: Path) -> SarExporter:
    settings = ComplianceSettings(blob_local_path=tmp_path)
    return SarExporter(blob=LocalBlobStore(settings=settings), settings=settings)


@pytest.mark.asyncio
async def test_export_produces_tar_gz_with_manifest(
    session, tmp_path: Path
) -> None:
    email = f"sar-{uuid4().hex[:6]}@example.com"
    user = User(email=email, display_name="SAR Subject")
    session.add(user)
    await session.flush()

    # A synthetic audit event so the bundle includes one row.
    audit = AuditService()
    await audit.record(
        session,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.AUTH_LOGIN_SUCCESS,
            resource_type="user",
            resource_id=email,
            action="login",
            actor_user_id=user.user_id,
        ),
    )
    await session.commit()

    exporter = _exporter(tmp_path)
    request_id = uuid4()
    result = await exporter.export(
        session,
        tenant_id="alpha",
        subject_email=email,
        subject_user_id=user.user_id,
        request_id=request_id,
    )
    assert result.size_bytes > 0

    # Reopen the tar.gz and assert the structure.
    path = Path(result.uri.removeprefix("file:///"))
    raw = path.read_bytes() if not path.is_absolute() else path.read_bytes()
    decompressed = gzip.decompress(raw)
    with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:") as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert "README.md" in names
        assert "users.jsonl" in names
        assert "audit_events.jsonl" in names

        manifest_member = tar.extractfile("manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read())
        assert manifest["tenant_id"] == "alpha"
        assert manifest["subject_email"] == email
        assert any(
            entry["table"] == "audit_events" and entry["rows"] >= 1
            for entry in manifest["included"]
        )
        assert any(
            ex["table"] == "tenant_secrets" for ex in manifest["excluded"]
        )
