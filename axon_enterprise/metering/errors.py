"""Metering error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class MeteringError(IdentityError):
    """Base class for metering errors."""

    code = "metering.error"


class RateLimited(MeteringError):
    """Per-minute rate limit hit. Client receives 429.

    ``retry_after_seconds`` tells the client when the window resets.
    """

    code = "metering.rate_limited"
    reveal_to_client = True

    def __init__(self, *, metric: str, retry_after_seconds: int) -> None:
        self.metric = metric
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"rate limit exceeded for {metric}; retry in {retry_after_seconds}s"
        )


class QuotaExceeded(MeteringError):
    """Monthly quota exhausted on a ``hard_cap`` plan. Client receives 402."""

    code = "metering.quota_exceeded"
    reveal_to_client = True

    def __init__(
        self,
        *,
        metric: str,
        quantity: float,
        limit: float,
    ) -> None:
        self.metric = metric
        self.quantity = quantity
        self.limit = limit
        super().__init__(
            f"quota exceeded for {metric}: requested {quantity}, limit {limit}"
        )


class PlanNotFound(MeteringError):
    code = "metering.plan_not_found"
    reveal_to_client = True


class UsageRecordInvalid(MeteringError):
    code = "metering.usage_invalid"
    reveal_to_client = False


class InvoiceAlreadyIssued(MeteringError):
    """Caller tried to generate an invoice that already exists for the period."""

    code = "metering.invoice_already_issued"
    reveal_to_client = True


class StripeIntegrationError(MeteringError):
    """Stripe API returned an error during invoice issuance / sync."""

    code = "metering.stripe_error"
    reveal_to_client = False


class MeteringBackendError(MeteringError):
    """Opaque backend failure — Redis down, Stripe 5xx, etc."""

    code = "metering.backend_error"
    reveal_to_client = False
