"""Stripe integration — lazy import, optional.

When ``metering.stripe_enabled=false`` the service still produces
``Invoice`` rows in ``draft`` status — operators review and push
into Stripe manually. When enabled, ``StripeClient.issue_invoice``
pushes the finalised invoice (line items + customer id) through
the Stripe API and records the Stripe invoice id on the row.

Webhook verification
--------------------
``verify_webhook(payload, signature)`` wraps
``stripe.Webhook.construct_event`` with our configured secret.
Callers (Fase 10.j HTTP handler) hand the raw body + the
``Stripe-Signature`` header; we return the parsed ``Event`` or raise
``StripeIntegrationError`` on signature mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from axon_enterprise.config import MeteringSettings, get_settings
from axon_enterprise.metering.errors import StripeIntegrationError
from axon_enterprise.metering.invoicing import LineItem

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.metering.stripe"
)


@dataclass
class StripeClient:
    """Thin wrapper around the official stripe-python SDK."""

    settings: MeteringSettings

    @classmethod
    def from_settings(cls) -> StripeClient:
        return cls(settings=get_settings().metering)

    @property
    def enabled(self) -> bool:
        return self.settings.stripe_enabled and self.settings.stripe_api_key is not None

    # ── Invoicing ─────────────────────────────────────────────────────

    def issue_invoice(
        self,
        *,
        customer_id: str,
        currency: str,
        description: str,
        line_items: list[LineItem],
        due_days: int,
    ) -> str:
        """Create + finalise an invoice in Stripe, return its id.

        Raises ``StripeIntegrationError`` when the integration is
        disabled (caller should inspect ``enabled`` first), or when
        the Stripe API returns an error.
        """
        if not self.enabled:
            raise StripeIntegrationError(
                "Stripe integration is disabled. Enable it by setting "
                "AXON_METERING_STRIPE_ENABLED=true + providing "
                "AXON_METERING_STRIPE_API_KEY."
            )
        stripe = self._import()
        stripe.api_key = self.settings.stripe_api_key.get_secret_value()  # type: ignore[union-attr]

        try:
            for item in line_items:
                stripe.InvoiceItem.create(
                    customer=customer_id,
                    amount=item.amount_cents,
                    currency=currency.lower(),
                    description=item.description,
                )
            invoice = stripe.Invoice.create(
                customer=customer_id,
                description=description,
                collection_method="send_invoice",
                days_until_due=due_days,
            )
            invoice.finalize_invoice()
        except Exception as exc:  # noqa: BLE001
            raise StripeIntegrationError(f"Stripe API: {exc}") from exc

        _logger.info(
            "stripe_invoice_issued",
            stripe_invoice_id=invoice.id,
            customer_id=customer_id,
            amount=sum(i.amount_cents for i in line_items),
        )
        return str(invoice.id)

    # ── Webhook ──────────────────────────────────────────────────────

    def verify_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str,
    ) -> dict[str, Any]:
        """Verify the signature + return the parsed event dict.

        Raises ``StripeIntegrationError`` on signature mismatch. The
        caller (10.j HTTP handler) routes on ``event["type"]``.
        """
        if self.settings.stripe_webhook_secret is None:
            raise StripeIntegrationError(
                "metering.stripe_webhook_secret is unset — refusing to "
                "process webhook"
            )
        stripe = self._import()
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature_header,
                secret=self.settings.stripe_webhook_secret.get_secret_value(),
                api_version=self.settings.stripe_api_version,
            )
        except Exception as exc:  # noqa: BLE001
            raise StripeIntegrationError(
                f"webhook signature verification failed: {exc}"
            ) from exc
        return dict(event)

    # ── Internals ─────────────────────────────────────────────────────

    def _import(self):
        try:
            import stripe  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise StripeIntegrationError(
                "stripe>=9.0 required; install via "
                "`pip install 'axon-enterprise[stripe]'`"
            ) from exc
        return stripe
