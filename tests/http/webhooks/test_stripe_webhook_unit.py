"""Unit tests for the Stripe webhook handler.

Signature verification is handed off to the Stripe SDK —
``StripeClient.verify_webhook`` raises ``StripeIntegrationError`` on
any bad/absent signature. Here we monkey-patch ``verify_webhook`` to
exercise the routing logic directly, which is the code we own.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.http.webhooks import build_webhook_router
from axon_enterprise.metering.errors import StripeIntegrationError


def _build_app() -> Starlette:
    routes = [Mount("/webhooks", routes=build_webhook_router())]
    app = Starlette(routes=routes)
    install_error_handlers(app)
    return app


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(monkeypatch) -> None:
    from axon_enterprise.http.webhooks import stripe_webhook as mod

    def _fail(self, *, payload, signature_header):
        raise StripeIntegrationError("bad signature")

    monkeypatch.setattr(
        "axon_enterprise.metering.stripe_client.StripeClient.verify_webhook",
        _fail,
    )
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/webhooks/stripe/",
            content=b"{}",
            headers={"Stripe-Signature": "nope"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "webhook.signature"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_returns_204_for_unknown_event_types(
    migrated_db, monkeypatch
) -> None:
    def _ok(self, *, payload, signature_header):
        return {
            "id": "evt_test",
            "type": "customer.subscription.created",  # we don't handle this
            "data": {"object": {"id": "sub_123"}},
        }

    monkeypatch.setattr(
        "axon_enterprise.metering.stripe_client.StripeClient.verify_webhook",
        _ok,
    )
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/webhooks/stripe/",
            content=json.dumps({}).encode(),
            headers={"Stripe-Signature": "valid"},
        )
    assert resp.status_code == 204


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_invoice_event_without_matching_row_returns_204(
    migrated_db, monkeypatch
) -> None:
    def _ok(self, *, payload, signature_header):
        return {
            "id": "evt_unknown_inv",
            "type": "invoice.paid",
            "data": {"object": {"id": "in_does_not_exist"}},
        }

    monkeypatch.setattr(
        "axon_enterprise.metering.stripe_client.StripeClient.verify_webhook",
        _ok,
    )
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/webhooks/stripe/",
            content=b"{}",
            headers={"Stripe-Signature": "valid"},
        )
    # Unknown invoice → 204 (idempotent, Stripe stops retrying).
    assert resp.status_code == 204
