"""Compliance Tooling — Fase 10.l.

GDPR / CCPA / SOC 2 execution on top of the primitives shipped in
earlier phases:

- **SAR Export (Art. 15)** — ``SarExporter`` streams a tar.gz per
  subject containing one JSONL file per source table plus a
  ``manifest.json`` with the tenant's audit-chain head. Runs
  asynchronously via a worker so portal POSTs return 202 + ticket.

- **Right to Erasure (Art. 17)** — ``ErasureService`` is two-stage:
  soft-delete on file (sessions + API keys revoked, membership
  flipped) → park in ``AWAITING_PURGE`` for the configured window
  (default 7 days) → anonymize (PII scrubbed, purge report
  uploaded). Blocked when an active ``LegalHold`` exists.

- **Data residency** — ``DataResidencyMiddleware`` 308-redirects or
  421-rejects requests whose tenant's declared region doesn't match
  the server's ``compliance.server_region``.

- **SOC 2 evidence bundle** — ``EvidenceBundleService`` packages
  audit events for a period + RBAC snapshot + SSO configs + legal
  holds + compliance requests into a single tar.gz ready for auditors.

- **Queue + worker** — ``ComplianceWorker`` polls
  ``compliance_requests`` via ``FOR UPDATE SKIP LOCKED`` and
  dispatches jobs. Safe to run N replicas.
"""

from axon_enterprise.compliance.blob_store import (
    BlobPutResult,
    BlobStore,
)
from axon_enterprise.compliance.erasure import (
    ErasureService,
    ErasureSoftDeleted,
)
from axon_enterprise.compliance.errors import (
    ComplianceBackendError,
    ComplianceError,
    ComplianceRequestInvalidState,
    ComplianceRequestNotFound,
    DataResidencyViolation,
    LegalHoldActive,
)
from axon_enterprise.compliance.evidence import EvidenceBundleService
from axon_enterprise.compliance.exporter import SarExporter
from axon_enterprise.compliance.legal_holds import LegalHoldService
from axon_enterprise.compliance.local_blob_store import LocalBlobStore
from axon_enterprise.compliance.models import (
    ComplianceRequest,
    ComplianceRequestKind,
    ComplianceRequestStatus,
    LegalHold,
)
from axon_enterprise.compliance.residency import (
    DataResidencyMiddleware,
    TenantRegionCache,
)
from axon_enterprise.compliance.s3_blob_store import (
    S3BlobStore,
    build_blob_store,
)
from axon_enterprise.compliance.service import ComplianceService
from axon_enterprise.compliance.tickets import TicketIssued, TicketService
from axon_enterprise.compliance.worker import ComplianceWorker

__all__ = [
    "BlobPutResult",
    "BlobStore",
    "ComplianceBackendError",
    "ComplianceError",
    "ComplianceRequest",
    "ComplianceRequestInvalidState",
    "ComplianceRequestKind",
    "ComplianceRequestNotFound",
    "ComplianceRequestStatus",
    "ComplianceService",
    "ComplianceWorker",
    "DataResidencyMiddleware",
    "DataResidencyViolation",
    "ErasureService",
    "ErasureSoftDeleted",
    "EvidenceBundleService",
    "LegalHold",
    "LegalHoldActive",
    "LegalHoldService",
    "LocalBlobStore",
    "S3BlobStore",
    "SarExporter",
    "TenantRegionCache",
    "TicketIssued",
    "TicketService",
    "build_blob_store",
]
