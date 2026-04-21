"""Compliance error hierarchy.

Typed so the Admin/Portal API's error handler can translate each
case to the correct HTTP status without the handler having to
switch on string codes.
"""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class ComplianceError(IdentityError):
    """Base for every compliance-subsystem error."""

    code = "compliance.error"


class ComplianceRequestNotFound(ComplianceError):
    code = "compliance.request_not_found"
    reveal_to_client = True


class ComplianceRequestInvalidState(ComplianceError):
    """Caller tried to act on a request whose status forbids it."""

    code = "compliance.invalid_state"
    reveal_to_client = True


class LegalHoldActive(ComplianceError):
    """Erasure blocked because the subject has an active legal hold."""

    code = "compliance.legal_hold_active"
    reveal_to_client = True


class DataResidencyViolation(ComplianceError):
    """Tenant's declared region does not match the server region."""

    code = "compliance.residency_violation"
    reveal_to_client = True


class ComplianceBackendError(ComplianceError):
    """Opaque backend failure (blob store, worker crash)."""

    code = "compliance.backend_error"
    reveal_to_client = False
