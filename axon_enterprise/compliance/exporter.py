"""SarExporter — GDPR Art. 15 Subject Access Request execution.

Architecture
------------
Given a tenant_id + a subject email/user_id, produce a ``.tar.gz``
bundle with one ``<table>.jsonl`` per row source and a top-level
``manifest.json`` describing what was included + the tenant's
audit chain head at export time.

The bundle builds in an in-memory BytesIO and is pushed to
``BlobStore.put`` in a single chunk. Per-subject bundles are
bounded (typically < 10 MiB after gzip) so full in-memory is
tolerable; tenant-wide exports (all users) would need per-table
streaming — out of scope for 10.l.

Tables exported (subject-owned rows only):

    users                       — PII of the subject
    tenant_memberships          — membership lifecycle
    sessions                    — auth sessions tied to the subject
    user_roles                  — role assignments
    tenant_api_keys             — keys created by the subject
    audit_events                — events where actor_user_id == subject
    usage_events                — metering rows the subject generated
    compliance_requests         — prior tickets filed for this subject

Tables explicitly EXCLUDED (listed in manifest.excluded with reason):

    tenant_secrets              — tenant-scoped, never subject-owned
    jwt_signing_keys            — tenant-global cryptographic material
    sso_configurations          — tenant-global configuration
    sso_assertion_seen          — only stores hashes of replayed assertions
    pricing_plans / permissions — global catalogues
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.api_keys.models import TenantApiKey
from axon_enterprise.audit.models import AuditEvent
from axon_enterprise.audit.service import AuditService
from axon_enterprise.compliance.blob_store import BlobPutResult, BlobStore
from axon_enterprise.compliance.models import ComplianceRequest
from axon_enterprise.config import ComplianceSettings, get_settings
from axon_enterprise.identity.models import (
    Session,
    TenantMembership,
    User,
)
from axon_enterprise.metering.models import UsageEvent

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.exporter"
)


_EXCLUDED = (
    ("tenant_secrets", "tenant-scoped, never subject-owned"),
    ("jwt_signing_keys", "tenant-global cryptographic material"),
    ("sso_configurations", "tenant-global configuration"),
    ("sso_assertion_seen", "only hashes of replayed assertions"),
    ("pricing_plans", "global catalogue"),
    ("permissions", "global catalogue"),
)


@dataclass
class SarExporter:
    """Run a SAR export end-to-end and hand off the artefact to a BlobStore."""

    blob: BlobStore
    settings: ComplianceSettings

    @classmethod
    def default(cls, blob: BlobStore) -> SarExporter:
        return cls(blob=blob, settings=get_settings().compliance)

    async def export(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        subject_user_id: UUID | None,
        request_id: UUID,
    ) -> BlobPutResult:
        """Build the bundle, stream it into the blob store, return metadata."""
        subject_email = subject_email.strip().lower()
        resolved_uid = subject_user_id or await self._resolve_user_id(
            db, email=subject_email
        )

        tables = await self._collect_tables(
            db,
            tenant_id=tenant_id,
            subject_email=subject_email,
            subject_user_id=resolved_uid,
        )

        manifest = await self._build_manifest(
            db,
            tenant_id=tenant_id,
            subject_email=subject_email,
            subject_user_id=resolved_uid,
            request_id=request_id,
            tables=tables,
        )

        payload = _build_tar_gz(manifest=manifest, tables=tables)

        async def _single_chunk() -> AsyncIterator[bytes]:
            yield payload

        key = self._object_key(tenant_id=tenant_id, request_id=request_id)
        result = await self.blob.put(
            key=key, body=_single_chunk(), content_type="application/gzip"
        )
        _logger.info(
            "compliance_sar_export_completed",
            tenant_id=tenant_id,
            request_id=str(request_id),
            bundle_uri=result.uri,
            size_bytes=result.size_bytes,
        )
        return result

    # ── Internals ────────────────────────────────────────────────────

    def _object_key(self, *, tenant_id: str, request_id: UUID) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        return f"sar/{tenant_id}/{ts}/{request_id}.tar.gz"

    async def _resolve_user_id(
        self, db: AsyncSession, *, email: str
    ) -> UUID | None:
        return await db.scalar(
            select(User.user_id).where(User.email == email)
        )

    async def _collect_tables(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        subject_user_id: UUID | None,
    ) -> list[tuple[str, list[dict]]]:
        users = list(
            (
                await db.execute(
                    select(User).where(User.email == subject_email)
                )
            ).scalars()
        )
        out: list[tuple[str, list[dict]]] = [
            ("users.jsonl", [_user_to_dict(u) for u in users]),
        ]

        if subject_user_id is None:
            for name in (
                "tenant_memberships.jsonl",
                "sessions.jsonl",
                "user_roles.jsonl",
                "tenant_api_keys.jsonl",
                "audit_events.jsonl",
                "usage_events.jsonl",
                "compliance_requests.jsonl",
            ):
                out.append((name, []))
            return out

        memberships = list(
            (
                await db.execute(
                    select(TenantMembership).where(
                        TenantMembership.tenant_id == tenant_id,
                        TenantMembership.user_id == subject_user_id,
                    )
                )
            ).scalars()
        )
        out.append(
            (
                "tenant_memberships.jsonl",
                [_membership_to_dict(m) for m in memberships],
            )
        )

        sessions = list(
            (
                await db.execute(
                    select(Session).where(
                        Session.tenant_id == tenant_id,
                        Session.user_id == subject_user_id,
                    )
                )
            ).scalars()
        )
        out.append(
            ("sessions.jsonl", [_session_to_dict(s) for s in sessions])
        )

        role_rows = (
            (
                await db.execute(
                    text(
                        "SELECT user_id, role_id, tenant_id, assigned_by, "
                        "assigned_at FROM axon_control.user_roles "
                        "WHERE tenant_id = :t AND user_id = :u"
                    ),
                    {"t": tenant_id, "u": subject_user_id},
                )
            )
            .mappings()
            .all()
        )
        out.append(
            ("user_roles.jsonl", [dict(r) for r in role_rows])
        )

        api_keys = list(
            (
                await db.execute(
                    select(TenantApiKey).where(
                        TenantApiKey.tenant_id == tenant_id,
                        TenantApiKey.created_by == subject_user_id,
                    )
                )
            ).scalars()
        )
        out.append(
            ("tenant_api_keys.jsonl", [_api_key_to_dict(k) for k in api_keys])
        )

        audit_rows = list(
            (
                await db.execute(
                    select(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.actor_user_id == subject_user_id,
                    )
                    .order_by(AuditEvent.sequence_number.asc())
                )
            ).scalars()
        )
        out.append(
            ("audit_events.jsonl", [_audit_to_dict(a) for a in audit_rows])
        )

        usage_rows = list(
            (
                await db.execute(
                    select(UsageEvent).where(
                        UsageEvent.tenant_id == tenant_id,
                        UsageEvent.actor_user_id == subject_user_id,
                    )
                )
            ).scalars()
        )
        out.append(
            ("usage_events.jsonl", [_usage_to_dict(u) for u in usage_rows])
        )

        compliance_rows = list(
            (
                await db.execute(
                    select(ComplianceRequest).where(
                        ComplianceRequest.tenant_id == tenant_id,
                        ComplianceRequest.subject_email == subject_email,
                    )
                )
            ).scalars()
        )
        out.append(
            (
                "compliance_requests.jsonl",
                [_compliance_request_to_dict(c) for c in compliance_rows],
            )
        )

        # §Fase 11.d — cognitive_states snapshots tied to this
        # subject. We include the metadata + expires_at but NOT the
        # encrypted payload; the SAR bundle is decryptable per
        # GDPR Art 15 only when the subject still holds the session
        # key, which they do not (the session terminated when the
        # tenant admin filed the export). Surfacing the ciphertext
        # without a key is worse than useless — it's a distraction.
        from axon_enterprise.cognitive_states.models import (
            CognitiveStateSnapshot,
        )

        cog_rows = list(
            (
                await db.execute(
                    select(CognitiveStateSnapshot).where(
                        CognitiveStateSnapshot.tenant_id == tenant_id,
                        CognitiveStateSnapshot.subject_user_id
                        == subject_user_id,
                    )
                )
            ).scalars()
        )
        out.append(
            (
                "cognitive_states.jsonl",
                [_cognitive_state_to_dict(c) for c in cog_rows],
            )
        )
        return out

    async def _build_manifest(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        subject_user_id: UUID | None,
        request_id: UUID,
        tables: list[tuple[str, list[dict]]],
    ) -> dict:
        audit = AuditService()
        report = await audit.verify_chain(db, tenant_id=tenant_id)
        chain_head = await db.scalar(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.sequence_number.desc())
            .limit(1)
        )
        return {
            "version": 1,
            "tenant_id": tenant_id,
            "request_id": str(request_id),
            "subject_email": subject_email,
            "subject_user_id": str(subject_user_id)
            if subject_user_id
            else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "included": [
                {"table": name.removesuffix(".jsonl"), "rows": len(rows)}
                for name, rows in tables
            ],
            "excluded": [
                {"table": t, "reason": r} for t, r in _EXCLUDED
            ],
            "audit_chain": {
                "ok": report.ok,
                "checked": report.checked,
                "head_sequence": chain_head.sequence_number
                if chain_head
                else 0,
                "head_event_hash": bytes(chain_head.event_hash).hex()
                if chain_head is not None
                else None,
            },
        }


# ── tar.gz builder (pure, testable) ─────────────────────────────────


def _build_tar_gz(
    *, manifest: dict, tables: Iterable[tuple[str, list[dict]]]
) -> bytes:
    """Construct the ``.tar.gz`` payload deterministically."""
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|") as tar:
            _add_member(tar, "README.md", _README.encode())
            manifest_bytes = json.dumps(
                manifest, indent=2, sort_keys=True
            ).encode()
            _add_member(tar, "manifest.json", manifest_bytes)
            for name, rows in tables:
                body = _jsonl_bytes(rows)
                _add_member(tar, name, body)
    return raw.getvalue()


def _add_member(tar: tarfile.TarFile, name: str, body: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(body)
    info.mtime = 0
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(body))


def _jsonl_bytes(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    for row in rows:
        buf.write(json.dumps(row, default=_json_default).encode())
        buf.write(b"\n")
    return buf.getvalue()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"not JSON-serialisable: {type(value).__name__}")


_README = (
    "# Axon Enterprise — GDPR SAR Bundle\n"
    "\n"
    "This archive carries every piece of personal data we store for\n"
    "the subject whose details appear in `manifest.json`. One JSONL\n"
    "file per source table; excluded tables and the reason they were\n"
    "skipped are enumerated in `manifest.excluded`.\n"
    "\n"
    "The `audit_chain` section of the manifest records the head of\n"
    "the tenant's hash-chained audit log at the moment of export so\n"
    "the bundle can be independently verified.\n"
)


# ── Row serialisers ──────────────────────────────────────────────────


def _user_to_dict(u: User) -> dict:
    return {
        "user_id": u.user_id,
        "email": u.email,
        "display_name": u.display_name,
        "status": getattr(u, "status", None),
        "totp_enrolled_at": getattr(u, "totp_enrolled_at", None),
        "created_at": u.created_at,
        "updated_at": u.updated_at,
        "password_hash": "[redacted]",
    }


def _membership_to_dict(m: TenantMembership) -> dict:
    return {
        "tenant_id": m.tenant_id,
        "user_id": m.user_id,
        "status": m.status,
        "invited_by": m.invited_by,
        "joined_at": m.joined_at,
        "invitation_expires_at": m.invitation_expires_at,
    }


def _session_to_dict(s: Session) -> dict:
    return {
        "session_id": s.session_id,
        "tenant_id": s.tenant_id,
        "user_id": s.user_id,
        "user_agent": s.user_agent,
        "ip_address": s.ip_address,
        "created_at": s.created_at,
        "expires_at": s.expires_at,
        "revoked_at": s.revoked_at,
        "refresh_token_hash": "[redacted]",
    }


def _api_key_to_dict(k: TenantApiKey) -> dict:
    return {
        "api_key_id": k.api_key_id,
        "tenant_id": k.tenant_id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "created_by": k.created_by,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "expires_at": k.expires_at,
        "revoked_at": k.revoked_at,
        "key_hash": "[redacted]",
    }


def _audit_to_dict(a: AuditEvent) -> dict:
    return {
        "event_id": a.event_id,
        "tenant_id": a.tenant_id,
        "sequence_number": a.sequence_number,
        "event_type": a.event_type,
        "actor_user_id": a.actor_user_id,
        "actor_email": a.actor_email,
        "resource_type": a.resource_type,
        "resource_id": a.resource_id,
        "action": a.action,
        "status": a.status,
        "ip_address": a.ip_address,
        "user_agent": a.user_agent,
        "details": a.details,
        "event_hash_hex": bytes(a.event_hash).hex(),
        "prev_hash_hex": bytes(a.prev_hash).hex(),
        "created_at": a.created_at,
    }


def _usage_to_dict(u: UsageEvent) -> dict:
    return {
        "usage_id": u.usage_id,
        "tenant_id": u.tenant_id,
        "metric_type": u.metric_type,
        "unit": u.unit,
        "quantity": u.quantity,
        "actor_user_id": u.actor_user_id,
        "flow_id": u.flow_id,
        "provider": u.provider,
        "details": u.details,
        "recorded_at": u.recorded_at,
    }


def _compliance_request_to_dict(c: ComplianceRequest) -> dict:
    return {
        "request_id": c.request_id,
        "tenant_id": c.tenant_id,
        "kind": c.kind,
        "status": c.status,
        "subject_email": c.subject_email,
        "reason": c.reason,
        "details": c.details,
        "scheduled_for": c.scheduled_for,
        "completed_at": c.completed_at,
        "created_at": c.created_at,
    }


def _cognitive_state_to_dict(c) -> dict:
    """Shape for the SAR bundle — metadata only, never the
    encrypted payload. Rationale in `exporter._collect_tables`."""
    return {
        "state_id": c.state_id,
        "tenant_id": c.tenant_id,
        "session_id": c.session_id,
        "flow_id": c.flow_id,
        "subject_user_id": c.subject_user_id,
        "state_format_version": c.state_format_version,
        "state_size_bytes": c.state_size_bytes,
        "expires_at": c.expires_at,
        "last_restored_at": c.last_restored_at,
        "restore_count": c.restore_count,
        "metadata_json": c.metadata_json,
        "state_ciphertext": "[redacted — encrypted at rest]",
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }
