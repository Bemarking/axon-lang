"""Audit-layer error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class AuditError(IdentityError):
    """Base class for audit errors."""

    code = "audit.error"


class AuditEventMalformed(AuditError):
    """Caller supplied an event that fails basic validation."""

    code = "audit.event_malformed"
    reveal_to_client = False


class AuditSequenceConflict(AuditError):
    """Two writers raced for the same ``(tenant_id, sequence_number)``.

    The advisory-lock path should prevent this in practice; if it
    raises we have a bug in the lock key derivation or a malfunctioning
    pg_advisory.
    """

    code = "audit.sequence_conflict"
    reveal_to_client = False


class AuditChainBroken(AuditError):
    """The chain verifier found a divergence.

    Either a row's ``event_hash`` does not match the recomputed value,
    or ``prev_hash`` does not point to the predecessor's ``event_hash``.
    """

    code = "audit.chain_broken"
    reveal_to_client = False

    def __init__(self, tenant_id: str, sequence_number: int, reason: str) -> None:
        self.tenant_id = tenant_id
        self.sequence_number = sequence_number
        self.reason = reason
        super().__init__(
            f"audit chain broken at tenant={tenant_id!r} seq={sequence_number}: {reason}"
        )


class AuditAppendOnlyViolation(AuditError):
    """Trigger-level rejection of an UPDATE/DELETE hit application code."""

    code = "audit.append_only_violation"
    reveal_to_client = False
