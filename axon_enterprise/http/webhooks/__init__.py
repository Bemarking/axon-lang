"""Inbound webhooks — Fase 10.k.

Currently covers Stripe billing events. Future integrations (GitHub
OAuth app state, Slack app events, audit sink adapters) land in the
same router. Webhook routes are PUBLIC at the ``AuthMiddleware``
layer — each handler re-authenticates the caller via provider-
specific signature verification (Stripe-Signature HMAC, GitHub's
X-Hub-Signature-256, etc.).
"""

from starlette.routing import Mount, Route

from axon_enterprise.http.webhooks import stripe_webhook


def build_webhook_router() -> list[Route | Mount]:
    """Return the webhook route tree mounted under ``/webhooks``."""
    return [
        Mount("/stripe", routes=stripe_webhook.routes()),
    ]


__all__ = ["build_webhook_router"]
