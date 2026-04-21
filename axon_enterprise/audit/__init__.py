"""Hash-chained, append-only audit log — Fase 10.g.

Replaces every ``LoggingAuditEmitter`` stub introduced in 10.b / 10.c
/ 10.d / 10.f with durable, tamper-evident audit persistence.

Anchors
-------
- **Append-only.** Postgres triggers raise on any UPDATE or DELETE
  against ``axon_control.audit_events``.
- **Per-tenant hash chain.** Every event embeds
  ``prev_hash = SHA-256(predecessor event_hash)`` plus its own
  ``event_hash``. Genesis is a deterministic SHA of
  ``b"AXON_AUDIT_GENESIS:" + tenant_id``.
- **ESK stitch.** Optional column holds the hash of an ESK
  ``provenance_chain`` entry so compliance auditors can cross-
  reference the audit log with the runtime provenance.
- **Canonical JSON encoder** matches axon-lang's ESK serialisation
  so hashes are byte-identical across the Python + Rust planes.

Public surface — see module docstrings for detail.
"""

from axon_enterprise.audit.adapters import (
    RbacAuditAdapter,
    SecretsAuditAdapter,
    SsoAuditAdapter,
)
from axon_enterprise.audit.canonical import (
    GENESIS_MAGIC,
    canonical_bytes_for_hash,
    compute_event_hash,
    genesis_hash,
)
from axon_enterprise.audit.errors import (
    AuditAppendOnlyViolation,
    AuditChainBroken,
    AuditError,
    AuditEventMalformed,
    AuditSequenceConflict,
)
from axon_enterprise.audit.events import AuditEventType, EventCategory
from axon_enterprise.audit.models import AuditEvent
from axon_enterprise.audit.service import (
    AuditChainReport,
    AuditService,
    AuditWriteRequest,
    WrittenAuditEvent,
)

__all__ = [
    "AuditAppendOnlyViolation",
    "AuditChainBroken",
    "AuditChainReport",
    "AuditError",
    "AuditEvent",
    "AuditEventMalformed",
    "AuditEventType",
    "AuditSequenceConflict",
    "AuditService",
    "AuditWriteRequest",
    "EventCategory",
    "GENESIS_MAGIC",
    "RbacAuditAdapter",
    "SecretsAuditAdapter",
    "SsoAuditAdapter",
    "WrittenAuditEvent",
    "canonical_bytes_for_hash",
    "compute_event_hash",
    "genesis_hash",
]
