"""Capability advertisement endpoint — ``/.well-known/axon-capabilities.json``.

axon-namespaced extension to the standard discovery surface. Where OIDC
discovery (21.a) and OAuth metadata (21.b) describe the *authentication*
surface, this doc describes the *language and runtime* surface this
installation supports — which Shield strategies are registered, which
Shield categories the registry knows about, which SSO providers are
configured, and which discovery endpoints are exposed.

SDKs and adopter tooling consume this to adapt behaviour to the actual
server capabilities (e.g., a client library can refuse to construct a
Flow that uses a Shield strategy this installation doesn't support).

Public, unauthenticated. Cache-Control mirrors the OIDC discovery doc
(``jwt.jwks_cache_control_seconds``, default 600 s). ETag derives from
the canonical JSON body; ``If-None-Match`` returns 304.

**Honesty discipline**: every advertised value is introspected from a
real source — Shield strategies/categories from the runtime registry,
SSO providers from the ``SsoProviderType`` enum, axon-lang version
from ``importlib.metadata``. Fields whose data sources don't exist yet
in v1.4.0 (per-tenant rate limits, vertical pack subscription state,
audit retention defaults) are NOT advertised. When those data models
land, they get added with a schema-version bump.
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

CAPABILITIES_SCHEMA_VERSION = "1.0"


def build_capabilities() -> dict[str, Any]:
    """Build the axon-capabilities document by introspecting live state."""
    return {
        "axon_enterprise_version": axon_enterprise_version(),
        "axon_lang_installed_version": _axon_lang_installed_version(),
        "sso_providers_supported": _sso_providers_supported(),
        "shield_strategies_supported": _shield_strategies_supported(),
        "shield_categories_supported": _shield_categories_supported(),
        "discovery_endpoints": {
            "openid_configuration": "/.well-known/openid-configuration",
            "oauth_authorization_server": "/.well-known/oauth-authorization-server",
            "jwks": "/.well-known/jwks.json",
            "capabilities": "/.well-known/axon-capabilities.json",
        },
        "axon_capabilities_schema_version": CAPABILITIES_SCHEMA_VERSION,
    }


# ── Introspection probes ─────────────────────────────────────────────


def _axon_lang_installed_version() -> str | None:
    """Resolve the installed ``axon-lang`` distribution version, or None
    if the package is not installed (defensive — pyproject declares it
    as a hard dep, but never assume installation in advertised metadata).
    """
    try:
        import importlib.metadata

        return importlib.metadata.version("axon-lang")
    except Exception:
        return None


def _sso_providers_supported() -> list[str]:
    """Enumerate the SSO providers the platform implements.

    Source of truth: ``SsoProviderType`` enum (axon_enterprise/sso/models.py).
    """
    try:
        from axon_enterprise.sso.models import SsoProviderType

        return sorted(p.value for p in SsoProviderType)
    except Exception:
        return []


def _shield_registry_known() -> dict[str, list[str]] | None:
    """Return the Shield registry's ``known()`` map, or None if axon-lang
    isn't importable. Cached at import time would couple lifetime to
    process start; we re-query each request so adopter-registered
    scanners (Fase 20 plugin pattern) appear without restart."""
    try:
        from axon.runtime.shield_scanners import default_registry  # type: ignore[import-not-found]

        return default_registry.known()
    except Exception:
        return None


def _shield_categories_supported() -> list[str] | None:
    known = _shield_registry_known()
    if known is None:
        return None
    return sorted(known.keys())


def _shield_strategies_supported() -> list[str] | None:
    """Union of all strategies registered across categories."""
    known = _shield_registry_known()
    if known is None:
        return None
    return sorted({strategy for strategies in known.values() for strategy in strategies})


# ── ASGI handler ─────────────────────────────────────────────────────


async def capabilities_endpoint(request: Request) -> Response:
    """``GET /.well-known/axon-capabilities.json``."""
    s = get_settings()
    cache_seconds = s.jwt.jwks_cache_control_seconds

    body = serialize_canonical(build_capabilities())
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
