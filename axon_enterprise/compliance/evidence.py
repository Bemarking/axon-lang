"""SOC 2 evidence bundle generator.

Produces a tar.gz per (tenant, period) that auditors can consume
without direct DB access. Contents:

    manifest.json            — tenant id, period, generator version,
                               audit chain verification report
    audit_events.jsonl       — every audit event in the period
    rbac_snapshot.json       — roles, permissions, user_roles as-of
                               the end of the period
    sso_configurations.json  — current SSO provider config (public
                               portions only)
    legal_holds.json         — all holds active at any point in the
                               period
    compliance_requests.json — all SAR / erasure requests filed in
                               the period + their outcomes

The bundle is written via the same ``BlobStore`` used for SAR
exports; an audit event ``compliance:evidence_bundle_generated``
records who produced it + the artefact URI.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.models import AuditEvent
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.blob_store import BlobPutResult, BlobStore
from axon_enterprise.compliance.exporter import _build_tar_gz  # reused
from axon_enterprise.compliance.models import (
    ComplianceRequest,
    LegalHold,
)
from axon_enterprise.config import ComplianceSettings, get_settings

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.evidence"
)


@dataclass
class EvidenceBundleService:
    """Produce + upload a SOC 2 evidence bundle for a single period."""

    blob: BlobStore
    settings: ComplianceSettings
    audit: AuditService

    @classmethod
    def default(cls, blob: BlobStore) -> EvidenceBundleService:
        return cls(
            blob=blob,
            settings=get_settings().compliance,
            audit=AuditService(),
        )

    async def generate(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
        requested_by: UUID | None = None,
    ) -> BlobPutResult:
        audit_rows = await self._fetch_audit_events(
            db, tenant_id=tenant_id, start=period_start, end=period_end
        )
        chain_report = await self.audit.verify_chain(
            db, tenant_id=tenant_id
        )
        rbac = await self._fetch_rbac_snapshot(db, tenant_id=tenant_id)
        sso = await self._fetch_sso_snapshot(db, tenant_id=tenant_id)
        legal = await self._fetch_legal_holds(
            db, tenant_id=tenant_id, start=period_start, end=period_end
        )
        compliance = await self._fetch_compliance_requests(
            db, tenant_id=tenant_id, start=period_start, end=period_end
        )

        manifest = {
            "version": 1,
            "tenant_id": tenant_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": {
                "service": "axon-enterprise",
                "phase": "10.l",
            },
            "audit_chain": {
                "ok": chain_report.ok,
                "checked": chain_report.checked,
                "broken_at": chain_report.broken_at,
            },
            "counts": {
                "audit_events": len(audit_rows),
                "legal_holds": len(legal),
                "compliance_requests": len(compliance),
                "rbac_roles": len(rbac.get("roles", [])),
                "rbac_user_roles": len(rbac.get("user_roles", [])),
            },
        }

        tables = [
            (
                "audit_events.jsonl",
                [_audit_to_dict(a) for a in audit_rows],
            ),
            ("legal_holds.jsonl", [_legal_to_dict(h) for h in legal]),
            (
                "compliance_requests.jsonl",
                [_compliance_to_dict(c) for c in compliance],
            ),
        ]
        payload = _build_tar_gz(manifest=manifest, tables=tables)
        # Two additional non-JSONL members merged in: rbac + sso.
        payload = _merge_extras(
            payload,
            extras={
                "rbac_snapshot.json": json.dumps(
                    rbac, indent=2, default=_json_default
                ).encode(),
                "sso_configurations.json": json.dumps(
                    sso, indent=2, default=_json_default
                ).encode(),
            },
        )

        async def _single_chunk() -> AsyncIterator[bytes]:
            yield payload

        now = datetime.now(timezone.utc)
        key = (
            f"evidence/{tenant_id}/{period_start.date()}_"
            f"{period_end.date()}/{now.strftime('%Y%m%dT%H%M%S')}.tar.gz"
        )
        result = await self.blob.put(
            key=key, body=_single_chunk(), content_type="application/gzip"
        )

        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.COMPLIANCE_EVIDENCE_BUNDLE_GENERATED,
                resource_type="tenant",
                resource_id=tenant_id,
                action="evidence_bundle",
                actor_user_id=requested_by,
                details={
                    "bundle_uri": result.uri,
                    "bundle_sha256": result.sha256_hex,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "audit_chain_ok": chain_report.ok,
                },
            ),
        )
        _logger.info(
            "compliance_evidence_bundle_generated",
            tenant_id=tenant_id,
            bundle_uri=result.uri,
            size_bytes=result.size_bytes,
        )
        return result

    # ── Fetchers ─────────────────────────────────────────────────────

    async def _fetch_audit_events(
        self, db, *, tenant_id: str, start: datetime, end: datetime
    ) -> list[AuditEvent]:
        res = await db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.created_at >= start,
                AuditEvent.created_at <= end,
            )
            .order_by(AuditEvent.sequence_number.asc())
        )
        return list(res.scalars())

    async def _fetch_rbac_snapshot(
        self, db: AsyncSession, *, tenant_id: str
    ) -> dict:
        roles = [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT role_id, tenant_id, name, description, "
                        "is_builtin FROM axon_control.roles "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tenant_id},
                )
            )
            .mappings()
            .all()
        ]
        user_roles = [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT user_id, role_id, tenant_id, assigned_by, "
                        "assigned_at FROM axon_control.user_roles "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tenant_id},
                )
            )
            .mappings()
            .all()
        ]
        role_permissions = [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT rp.role_id, rp.permission_id "
                        "FROM axon_control.role_permissions rp "
                        "JOIN axon_control.roles r ON r.role_id = rp.role_id "
                        "WHERE r.tenant_id = :t"
                    ),
                    {"t": tenant_id},
                )
            )
            .mappings()
            .all()
        ]
        return {
            "roles": roles,
            "user_roles": user_roles,
            "role_permissions": role_permissions,
        }

    async def _fetch_sso_snapshot(
        self, db: AsyncSession, *, tenant_id: str
    ) -> dict:
        rows = [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT provider_type, created_at, updated_at, "
                        "enabled FROM axon_control.sso_configurations "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tenant_id},
                )
            )
            .mappings()
            .all()
        ]
        return {"tenant_id": tenant_id, "configurations": rows}

    async def _fetch_legal_holds(
        self, db: AsyncSession, *, tenant_id: str, start, end
    ) -> list[LegalHold]:
        res = await db.execute(
            select(LegalHold).where(
                LegalHold.tenant_id == tenant_id,
                LegalHold.applied_at <= end,
            )
        )
        # Include holds active at any point in the period: either
        # still active, or released after the period started.
        rows = [
            r
            for r in res.scalars()
            if r.released_at is None or r.released_at >= start
        ]
        return rows

    async def _fetch_compliance_requests(
        self, db: AsyncSession, *, tenant_id: str, start, end
    ) -> list[ComplianceRequest]:
        res = await db.execute(
            select(ComplianceRequest).where(
                ComplianceRequest.tenant_id == tenant_id,
                ComplianceRequest.created_at >= start,
                ComplianceRequest.created_at <= end,
            )
        )
        return list(res.scalars())


# ── Helpers ─────────────────────────────────────────────────────────


def _audit_to_dict(a: AuditEvent) -> dict:
    return {
        "event_id": a.event_id,
        "sequence_number": a.sequence_number,
        "event_type": a.event_type,
        "actor_user_id": a.actor_user_id,
        "actor_email": a.actor_email,
        "resource_type": a.resource_type,
        "resource_id": a.resource_id,
        "action": a.action,
        "status": a.status,
        "details": a.details,
        "event_hash_hex": bytes(a.event_hash).hex(),
        "prev_hash_hex": bytes(a.prev_hash).hex(),
        "created_at": a.created_at,
    }


def _legal_to_dict(h: LegalHold) -> dict:
    return {
        "hold_id": h.hold_id,
        "tenant_id": h.tenant_id,
        "subject_email": h.subject_email,
        "matter": h.matter,
        "applied_by": h.applied_by,
        "applied_at": h.applied_at,
        "released_by": h.released_by,
        "released_at": h.released_at,
        "released_reason": h.released_reason,
    }


def _compliance_to_dict(c: ComplianceRequest) -> dict:
    return {
        "request_id": c.request_id,
        "kind": c.kind,
        "status": c.status,
        "subject_email": c.subject_email,
        "reason": c.reason,
        "scheduled_for": c.scheduled_for,
        "completed_at": c.completed_at,
        "artefact_uri": c.artefact_uri,
        "artefact_sha256": c.artefact_sha256,
        "created_at": c.created_at,
    }


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(type(value).__name__)


def _merge_extras(tar_gz_payload: bytes, *, extras: dict[str, bytes]) -> bytes:
    """Unpack + re-pack adding the extras members."""
    decompressed = gzip.decompress(tar_gz_payload)
    raw_out = io.BytesIO()
    with gzip.GzipFile(fileobj=raw_out, mode="wb", mtime=0) as gz:
        with tarfile.open(
            fileobj=io.BytesIO(decompressed), mode="r:"
        ) as src:
            with tarfile.open(fileobj=gz, mode="w|") as dst:
                for member in src.getmembers():
                    body = src.extractfile(member)
                    if body is None:
                        continue
                    info = tarfile.TarInfo(name=member.name)
                    data = body.read()
                    info.size = len(data)
                    info.mtime = 0
                    info.mode = 0o644
                    dst.addfile(info, io.BytesIO(data))
                for name, body_bytes in extras.items():
                    info = tarfile.TarInfo(name=name)
                    info.size = len(body_bytes)
                    info.mtime = 0
                    info.mode = 0o644
                    dst.addfile(info, io.BytesIO(body_bytes))
    return raw_out.getvalue()
