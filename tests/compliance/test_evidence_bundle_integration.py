"""Integration — EvidenceBundleService produces a SOC 2 evidence bundle."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.evidence import EvidenceBundleService
from axon_enterprise.compliance.local_blob_store import LocalBlobStore
from axon_enterprise.config import ComplianceSettings

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


def _service(tmp_path: Path) -> EvidenceBundleService:
    settings = ComplianceSettings(blob_local_path=tmp_path)
    return EvidenceBundleService.default(
        blob=LocalBlobStore(settings=settings)
    )


@pytest.mark.asyncio
async def test_evidence_bundle_contains_expected_members(
    session, tmp_path: Path
) -> None:
    # Seed an audit event so the bundle is non-empty for the period.
    audit = AuditService()
    await audit.record(
        session,
        AuditWriteRequest(
            tenant_id="alpha",
            event_type=AuditEventType.CONFIG_CHANGED,
            resource_type="tenant",
            resource_id="alpha",
            action="config_update",
            details={"seeded_for_evidence": True},
        ),
    )
    await session.commit()

    svc = _service(tmp_path)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1)
    result = await svc.generate(
        session,
        tenant_id="alpha",
        period_start=start,
        period_end=end,
    )
    assert result.size_bytes > 0

    path = Path(result.uri.removeprefix("file:///"))
    raw = path.read_bytes()
    decompressed = gzip.decompress(raw)
    with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:") as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert "audit_events.jsonl" in names
        assert "rbac_snapshot.json" in names
        assert "sso_configurations.json" in names
        assert "legal_holds.jsonl" in names
        assert "compliance_requests.jsonl" in names

        manifest_member = tar.extractfile("manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read())
        assert manifest["tenant_id"] == "alpha"
        assert "audit_chain" in manifest
        assert manifest["counts"]["audit_events"] >= 1
