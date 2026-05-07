"""OpenAPI 3.1.0 publication endpoint — ``/openapi.json``.

Hand-built spec (axon-enterprise uses pure Starlette, no FastAPI auto-
generation). Scope of this slice:

- **Full schemas** for endpoints Fase 21 owns end-to-end:
  ``/.well-known/openid-configuration``, ``/.well-known/oauth-authorization-server``,
  ``/.well-known/axon-capabilities.json``, ``/.well-known/jwks.json``,
  ``/api/v1/tenant/me/integration-context``.
- **Tag-only stubs** for other Portal API / Admin API / Webhook families
  (auth, sso, tenant/users, tenant/api-keys, tenant/usage, tenant/compliance,
  webhooks, admin). They appear as documented namespaces with descriptions
  pointing to the canonical doc; future fases extend by adding their own
  ``Path Item`` entries to the same builder.

Why hand-built and not a generator:
- pyproject doesn't ship FastAPI / starlette-apispec / apispec — adding any
  would be a meaningful new dep for what is, today, a small surface.
- The Fase 21 endpoints have fully known schemas; documenting them by hand
  is concrete and stable.
- When the Portal API surface starts mutating frequently, switching to a
  generator is a separate refactor — Fase 21 ships the surface contract
  first, and the schema discipline second.

The spec is built once per request (no caching beyond Cache-Control); cost
is < 1 ms because it's a few hundred-line dict construction. ETag enables
``If-None-Match`` → 304 for unchanged specs.
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

OPENAPI_VERSION = "3.1.0"


def build_openapi_spec() -> dict[str, Any]:
    """Build the OpenAPI 3.1.0 document for this axon-enterprise install."""
    s = get_settings()
    issuer = s.jwt.issuer.rstrip("/")
    return {
        "openapi": OPENAPI_VERSION,
        "info": _info_section(),
        "servers": [{"url": issuer, "description": "axon-enterprise issuer base"}],
        "tags": _tags(),
        "paths": _paths(),
        "components": {
            "securitySchemes": _security_schemes(),
            "schemas": _schemas(),
        },
        "externalDocs": {
            "description": "axon-enterprise Portal API guide",
            "url": f"{issuer}/docs",
        },
    }


# ── Info, tags, security ─────────────────────────────────────────────


def _info_section() -> dict[str, Any]:
    return {
        "title": "axon-enterprise Portal API",
        "version": axon_enterprise_version(),
        "description": (
            "Authenticated tenant-facing surface for axon-enterprise installations. "
            "OIDC discovery is published at /.well-known/openid-configuration; "
            "OAuth 2.0 server metadata at /.well-known/oauth-authorization-server; "
            "language and runtime capability advertisement at "
            "/.well-known/axon-capabilities.json. Use /docs for an interactive "
            "Swagger UI rendering of this document, or /redoc for ReDoc."
        ),
        "contact": {"name": "axon-enterprise team"},
        "license": {"name": "Commercial — see LICENSE"},
    }


def _tags() -> list[dict[str, Any]]:
    return [
        {
            "name": "Discovery",
            "description": (
                "Public, unauthenticated well-known endpoints for adopter "
                "self-service integration (Fase 21). Adopters consume these "
                "to discover issuer, jwks, supported algorithms, registered "
                "Shield strategies, and SSO providers."
            ),
        },
        {
            "name": "Tenant Introspection",
            "description": (
                "Authenticated tenant-scoped introspection — what is configured "
                "for the calling tenant. RLS by construction (handler keys "
                "off the JWT principal, never off request body)."
            ),
        },
        {
            "name": "Auth",
            "description": (
                "Password + refresh-token + invitation acceptance flows. "
                "Full reference in docs/PORTAL_API.md."
            ),
        },
        {
            "name": "SSO",
            "description": (
                "OIDC + SAML provider initiate / callback / metadata flows. "
                "Per-tenant IdP configuration. Full reference in docs/SSO.md."
            ),
        },
        {
            "name": "Tenant",
            "description": (
                "Tenant-admin operations — users, API keys, usage, compliance "
                "exports. Full reference in docs/PORTAL_API.md."
            ),
        },
        {
            "name": "Webhooks",
            "description": (
                "Inbound webhook receivers — Stripe billing events, etc. "
                "Auth via provider-specific signature schemes (not JWT). "
                "Full reference in docs/PORTAL_API.md."
            ),
        },
        {
            "name": "Admin",
            "description": (
                "Cross-tenant control-plane operations — restricted to admin "
                "principals. Mounted under /admin/*. Full reference in "
                "docs/ADMIN_API_AND_CLI.md."
            ),
        },
    ]


def _security_schemes() -> dict[str, Any]:
    return {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "RS256-signed JWT issued by the Portal API. Discover signing "
                "keys at /.well-known/jwks.json; discover issuer + audience at "
                "/.well-known/openid-configuration. Obtain a token via "
                "POST /api/v1/auth/login or the OIDC/SAML SSO flows."
            ),
        }
    }


# ── Schemas ──────────────────────────────────────────────────────────


def _schemas() -> dict[str, Any]:
    return {
        "OidcDiscoveryDocument": {
            "type": "object",
            "required": [
                "issuer",
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
                "response_types_supported",
                "subject_types_supported",
                "id_token_signing_alg_values_supported",
            ],
            "properties": {
                "issuer": {"type": "string", "format": "uri"},
                "authorization_endpoint": {"type": "string", "format": "uri"},
                "token_endpoint": {"type": "string", "format": "uri"},
                "jwks_uri": {"type": "string", "format": "uri"},
                "response_types_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "subject_types_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "id_token_signing_alg_values_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "scopes_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "claims_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "audience_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "axon_enterprise_version": {"type": "string"},
                "axon_discovery_schema_version": {"type": "string"},
            },
        },
        "OAuthServerMetadata": {
            "type": "object",
            "required": [
                "issuer",
                "response_types_supported",
                "token_endpoint",
                "grant_types_supported",
                "token_endpoint_auth_methods_supported",
            ],
            "properties": {
                "issuer": {"type": "string", "format": "uri"},
                "authorization_endpoint": {"type": "string", "format": "uri"},
                "token_endpoint": {"type": "string", "format": "uri"},
                "jwks_uri": {"type": "string", "format": "uri"},
                "revocation_endpoint": {"type": "string", "format": "uri"},
                "response_types_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "grant_types_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "token_endpoint_auth_methods_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "axon_enterprise_version": {"type": "string"},
                "axon_oauth_metadata_schema_version": {"type": "string"},
            },
        },
        "AxonCapabilities": {
            "type": "object",
            "required": [
                "axon_enterprise_version",
                "discovery_endpoints",
                "axon_capabilities_schema_version",
            ],
            "properties": {
                "axon_enterprise_version": {"type": "string"},
                "axon_lang_installed_version": {
                    "type": ["string", "null"],
                    "description": (
                        "Null when probe fails (axon-lang not importable)."
                    ),
                },
                "sso_providers_supported": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "shield_strategies_supported": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Null when Shield registry import fails."
                    ),
                },
                "shield_categories_supported": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "discovery_endpoints": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "axon_capabilities_schema_version": {"type": "string"},
            },
        },
        "JwksDocument": {
            "type": "object",
            "required": ["keys"],
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "RSA public keys per RFC 7517. The structure is "
                        "standard JWK; consumers typically use a JOSE library."
                    ),
                }
            },
        },
        "IntegrationContext": {
            "type": "object",
            "required": [
                "tenant_id",
                "plan",
                "auth",
                "discovery",
                "axon_enterprise_version",
                "axon_integration_context_schema_version",
            ],
            "properties": {
                "tenant_id": {"type": "string"},
                "plan": {"type": "string", "enum": ["starter", "pro", "enterprise"]},
                "auth": {
                    "type": "object",
                    "required": [
                        "issuer",
                        "audience",
                        "expected_signing_alg",
                        "access_token_ttl_seconds",
                    ],
                    "properties": {
                        "issuer": {"type": "string", "format": "uri"},
                        "audience": {"type": "string"},
                        "expected_signing_alg": {"type": "string"},
                        "access_token_ttl_seconds": {"type": "integer"},
                    },
                },
                "discovery": {
                    "type": "object",
                    "required": [
                        "openid_configuration",
                        "oauth_authorization_server",
                        "jwks",
                    ],
                    "properties": {
                        "openid_configuration": {"type": "string", "format": "uri"},
                        "oauth_authorization_server": {
                            "type": "string",
                            "format": "uri",
                        },
                        "jwks": {"type": "string", "format": "uri"},
                    },
                },
                "axon_enterprise_version": {"type": "string"},
                "axon_integration_context_schema_version": {"type": "string"},
            },
        },
        "Error": {
            "type": "object",
            "required": ["error"],
            "properties": {
                "error": {
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                }
            },
        },
    }


# ── Paths ────────────────────────────────────────────────────────────


_RESP_304 = {
    "304": {
        "description": (
            "Not Modified — the ETag matched the request's If-None-Match header. "
            "Body is empty; client should reuse its cached copy."
        )
    }
}


def _paths() -> dict[str, Any]:
    paths = {
        "/.well-known/openid-configuration": {
            "get": {
                "tags": ["Discovery"],
                "summary": "OIDC Connect Discovery 1.0 document",
                "description": (
                    "Returns the OIDC discovery document so any compliant "
                    "OIDC client can discover this installation's issuer, "
                    "jwks, supported algorithms, and supported claims. "
                    "No authentication required."
                ),
                "responses": {
                    "200": {
                        "description": "Discovery document",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/OidcDiscoveryDocument"
                                }
                            }
                        },
                    },
                    **_RESP_304,
                },
            }
        },
        "/.well-known/oauth-authorization-server": {
            "get": {
                "tags": ["Discovery"],
                "summary": "OAuth 2.0 Authorization Server Metadata (RFC 8414)",
                "description": (
                    "Returns the OAuth Authorization Server Metadata document "
                    "for non-OIDC OAuth clients. Many fields overlap with the "
                    "OIDC discovery doc; both are published so clients can "
                    "consume whichever standard their library expects."
                ),
                "responses": {
                    "200": {
                        "description": "OAuth metadata document",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/OAuthServerMetadata"
                                }
                            }
                        },
                    },
                    **_RESP_304,
                },
            }
        },
        "/.well-known/axon-capabilities.json": {
            "get": {
                "tags": ["Discovery"],
                "summary": "axon runtime capability advertisement",
                "description": (
                    "axon-namespaced extension to the standard discovery surface. "
                    "Lists registered Shield strategies and categories, supported "
                    "SSO providers, and installed axon-lang version. SDKs adapt "
                    "behaviour to the actual server capabilities."
                ),
                "responses": {
                    "200": {
                        "description": "Capability document",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/AxonCapabilities"
                                }
                            }
                        },
                    },
                    **_RESP_304,
                },
            }
        },
        "/.well-known/jwks.json": {
            "get": {
                "tags": ["Discovery"],
                "summary": "JSON Web Key Set (RFC 7517)",
                "description": (
                    "Public RSA signing keys used to verify tokens issued by "
                    "this server. Cache as instructed by Cache-Control headers."
                ),
                "responses": {
                    "200": {
                        "description": "JWKS document",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/JwksDocument"}
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/tenant/me/integration-context/": {
            "get": {
                "tags": ["Tenant Introspection"],
                "summary": "Tenant-scoped integration context",
                "description": (
                    "Returns the integration parameters visible to the calling "
                    "tenant — its own tenant_id, plan, expected JWT issuer / "
                    "audience / signing alg, and discovery URLs. RLS by "
                    "construction: the response only ever surfaces the "
                    "principal's tenant_id."
                ),
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "Integration context for the principal's tenant",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/IntegrationContext"
                                }
                            }
                        },
                    },
                    "401": {
                        "description": "Missing or invalid bearer token",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Error"}
                            }
                        },
                    },
                    **_RESP_304,
                },
            }
        },
    }
    paths.update(_stub_paths())
    return paths


def _stub_paths() -> dict[str, Any]:
    """Tag-only stubs for the broader API surface that future fases own.

    Each entry advertises the namespace exists, points to its canonical
    doc, and uses the appropriate tag — but does NOT enumerate request
    or response schemas. Schema-level documentation is the responsibility
    of whichever fase owns the route family. Documenting them here
    falsely as "fully specified" would be the OpenAPI equivalent of
    fabricating capability fields.
    """
    namespaces = [
        ("/api/v1/auth/login", "Auth", "POST", "Password + TOTP login → JWT"),
        ("/api/v1/auth/refresh", "Auth", "POST", "Rotate the refresh token"),
        ("/api/v1/auth/logout", "Auth", "POST", "Revoke the session chain"),
        ("/api/v1/auth/invite/accept", "Auth", "POST", "Accept a tenant invitation"),
        ("/api/v1/sso/oidc/initiate", "SSO", "GET", "Begin OIDC SSO"),
        ("/api/v1/sso/oidc/callback", "SSO", "GET", "OIDC callback"),
        ("/api/v1/tenant/users/", "Tenant", "GET", "List tenant users"),
        ("/api/v1/tenant/api-keys/", "Tenant", "GET", "List tenant API keys"),
        ("/api/v1/tenant/usage/", "Tenant", "GET", "Current period usage"),
        ("/api/v1/tenant/compliance/", "Tenant", "GET", "Compliance exports"),
        ("/api/v1/primitives/", "Discovery", "GET", "Closed catalogues + seeded registries"),
        ("/webhooks/stripe", "Webhooks", "POST", "Stripe billing events (HMAC-signed)"),
        ("/admin/", "Admin", "GET", "Admin control-plane (see ADMIN_API_AND_CLI.md)"),
    ]
    out: dict[str, Any] = {}
    for path, tag, method, summary in namespaces:
        out[path] = {
            method.lower(): {
                "tags": [tag],
                "summary": summary,
                "description": (
                    f"See docs/{'PORTAL_API' if tag != 'Admin' else 'ADMIN_API_AND_CLI'}.md "
                    "for the canonical request/response contract."
                ),
                "responses": {
                    "200": {"description": "See linked doc."},
                    "401": {"description": "Authentication required."},
                },
            }
        }
    return out


# ── ASGI handler ─────────────────────────────────────────────────────


async def openapi_endpoint(request: Request) -> Response:
    """``GET /openapi.json`` — OpenAPI 3.1.0 document."""
    s = get_settings()
    cache_seconds = s.jwt.jwks_cache_control_seconds

    body = serialize_canonical(build_openapi_spec())
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
