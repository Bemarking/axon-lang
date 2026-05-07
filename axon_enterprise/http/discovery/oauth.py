"""OAuth 2.0 Authorization Server Metadata endpoint — RFC 8414.

``GET /.well-known/oauth-authorization-server``. Public, unauthenticated.

Lets OAuth clients (M2M, machine-to-machine, non-OIDC consumers)
discover the integration parameters of this axon-enterprise installation
via the standard published in RFC 8414. Many fields overlap with the
OIDC Connect Discovery 1.0 doc at ``/.well-known/openid-configuration``;
both are exposed so clients can consume whichever standard their library
expects. The two documents must remain consistent on shared fields —
the drift gate (sub-fase 21.g) will enforce that.

Cache-Control matches the OIDC discovery doc (``jwks_cache_control_seconds``,
default 600 s). ETag is a strong hash of the canonical JSON body.
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

OAUTH_METADATA_SCHEMA_VERSION = "1.0"


def build_oauth_authorization_server_metadata() -> dict[str, Any]:
    """Build the RFC 8414 OAuth 2.0 Authorization Server Metadata document."""
    s = get_settings()
    issuer = s.jwt.issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/api/v1/sso/oidc/initiate",
        "token_endpoint": f"{issuer}/api/v1/auth/login",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "revocation_endpoint": f"{issuer}/api/v1/auth/logout",
        "response_types_supported": ["code", "id_token"],
        "response_modes_supported": ["query"],
        "grant_types_supported": [
            "password",
            "refresh_token",
            "authorization_code",
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "token_endpoint_auth_signing_alg_values_supported": [s.jwt.algorithm],
        "revocation_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "scopes_supported": ["openid", "profile", "email", "tenant"],
        "service_documentation": f"{issuer}/docs",
        "axon_enterprise_version": axon_enterprise_version(),
        "axon_oauth_metadata_schema_version": OAUTH_METADATA_SCHEMA_VERSION,
    }


async def oauth_authorization_server_endpoint(request: Request) -> Response:
    """``GET /.well-known/oauth-authorization-server`` — RFC 8414."""
    s = get_settings()
    cache_seconds = s.jwt.jwks_cache_control_seconds

    body = serialize_canonical(build_oauth_authorization_server_metadata())
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
