"""``GET /api/v1/tenant/me/integration-context`` (Fase 21.c).

Authenticated tenant introspection — returns the integration parameters
visible to a tenant from its own perspective. Lets adopters build
internal dashboards showing "what is configured for me" without
contacting the platform team.

Auth: bearer JWT verified by ``AuthMiddleware``; the handler reads the
resolved ``PrincipalContext`` to derive the tenant identity. RLS by
construction — the response only ever surfaces the principal's own
tenant_id; cross-tenant introspection is impossible because we never
query "give me data for tenant X" with X coming from the request.

Cache-Control: ``private, max-age=N`` (intermediaries must NOT cache
across tenants). ETag derives from the canonical JSON body so
``If-None-Match`` returns 304 and saves bandwidth on repeated polls.

v1 scope (this slice): static integration surface — tenant_id, plan,
auth params, discovery URLs, server version. Per-tenant fields that
require new data models (rate_limits, feature_flags, vertical_packs,
shield category enforcement) land in follow-on slices when those
models exist; we do NOT fabricate values for them.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from axon_enterprise.config import get_settings
from axon_enterprise.http.discovery._helpers import (
    axon_enterprise_version,
    serialize_canonical,
    strong_etag,
)
from axon_enterprise.http.discovery.observability import (
    with_integration_context_observability,
)
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.tenant import current_tenant_or_none

INTEGRATION_CONTEXT_SCHEMA_VERSION = "1.0"


def build_integration_context(*, tenant_id: str, plan: str) -> dict[str, Any]:
    """Build the integration-context document for a given principal.

    Pure function — receives the tenant identity explicitly so callers
    (handler, tests, future SDK helpers) can drive it without a request.
    """
    s = get_settings()
    issuer = s.jwt.issuer.rstrip("/")
    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "auth": {
            "issuer": issuer,
            "audience": s.jwt.audience,
            "expected_signing_alg": s.jwt.algorithm,
            "access_token_ttl_seconds": s.jwt.access_token_ttl_seconds,
        },
        "discovery": {
            "openid_configuration": f"{issuer}/.well-known/openid-configuration",
            "oauth_authorization_server": (
                f"{issuer}/.well-known/oauth-authorization-server"
            ),
            "jwks": f"{issuer}/.well-known/jwks.json",
        },
        "axon_enterprise_version": axon_enterprise_version(),
        "axon_integration_context_schema_version": INTEGRATION_CONTEXT_SCHEMA_VERSION,
    }


async def integration_context_endpoint(request: Request) -> Response:
    """Resolve the principal's tenant + plan and serve its integration context."""
    principal = require_principal()
    tenant_ctx = current_tenant_or_none()
    plan = tenant_ctx.plan.value if tenant_ctx is not None else "enterprise"

    body = serialize_canonical(
        build_integration_context(tenant_id=principal.tenant_id, plan=plan)
    )
    etag = strong_etag(body)
    cache_seconds = get_settings().jwt.jwks_cache_control_seconds

    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"private, max-age={cache_seconds}",
            },
        )

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Cache-Control": f"private, max-age={cache_seconds}",
            "ETag": etag,
        },
    )


def routes() -> list[Route]:
    # Fase 21.h — wrap the handler at mount time so each fetch emits a
    # ``tenant.integration_context.fetched`` structured event + bumps
    # the per-tenant Prometheus counter.
    return [
        Route(
            "/",
            with_integration_context_observability(integration_context_endpoint),
            methods=["GET"],
        )
    ]
