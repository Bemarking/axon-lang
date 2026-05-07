"""OIDC Connect Discovery 1.0 endpoint — ``/.well-known/openid-configuration``.

Public, unauthenticated. Lets any OIDC-compliant client discover the
issuer, jwks_uri, supported algorithms, scopes, claims and audience of
this axon-enterprise installation. Removes the need for out-of-band
handover of those values to integrating consumers.

The document is derived entirely from ``get_settings()``; nothing
per-tenant lives here. Per-tenant introspection (rate limits, allowed
primitives, audit retention) lives in sub-fase 21.c at
``/api/v1/tenant/me/integration-context``.

Cache-Control: ``public, max-age=<jwt.jwks_cache_control_seconds>`` —
aligned with the JWKS endpoint lifespan so a single round-trip
populates both for a freshly-booted client. ETag is the SHA-256 of the
canonical JSON body; ``If-None-Match`` returns 304 with no payload.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from axon_enterprise.config import get_settings
from axon_enterprise.http.discovery._helpers import (
    axon_enterprise_version,
    serialize_canonical,
    strong_etag,
)

DISCOVERY_SCHEMA_VERSION = "1.0"


def build_openid_configuration() -> dict[str, Any]:
    """Build the OIDC Connect Discovery 1.0 document."""
    s = get_settings()
    issuer = s.jwt.issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/api/v1/sso/oidc/initiate",
        "token_endpoint": f"{issuer}/api/v1/auth/login",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["id_token", "code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [s.jwt.algorithm],
        "scopes_supported": ["openid", "profile", "email", "tenant"],
        "claims_supported": [
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "tenant_id",
            "email",
            "user_id",
            "roles",
            "plan",
        ],
        "audience_supported": [s.jwt.audience],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "axon_enterprise_version": axon_enterprise_version(),
        "axon_discovery_schema_version": DISCOVERY_SCHEMA_VERSION,
    }


async def openid_configuration_endpoint(request: Request) -> Response:
    """``GET /.well-known/openid-configuration`` — OIDC Connect Discovery 1.0."""
    s = get_settings()
    cache_seconds = s.jwt.jwks_cache_control_seconds

    body = serialize_canonical(build_openid_configuration())
    etag = strong_etag(body)

    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"public, max-age={cache_seconds}",
            },
        )

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Cache-Control": f"public, max-age={cache_seconds}",
            "ETag": etag,
        },
    )
