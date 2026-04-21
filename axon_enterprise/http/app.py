"""App factory — builds the Starlette ASGI application.

Responsibilities:

1. Wire middleware in the correct order.
2. Mount the Admin API router under ``/admin`` (10.j).
3. Mount the Portal API router under ``/api/v1`` (10.k).
4. Mount inbound webhook routes under ``/webhooks`` (10.k).
5. Mount the health + readiness + metrics + JWKS endpoints.
6. Install typed-error handlers.
7. Return a ``Starlette`` app ready for ``uvicorn`` / ``gunicorn``.

The factory is deliberately parameterless — every dependency comes
from ``get_settings()``. Tests that need to swap components monkey-
patch the settings cache and rebuild.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from axon_enterprise.compliance import DataResidencyMiddleware
from axon_enterprise.config import get_settings
from axon_enterprise.db.session import admin_session
from axon_enterprise.http.admin import build_admin_router
from axon_enterprise.http.api import build_api_router
from axon_enterprise.http.auth_middleware import AuthMiddleware
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.http.webhooks import build_webhook_router
from axon_enterprise.jwt_issuer import JwksDocumentBuilder
from axon_enterprise.observability import (
    ObservabilityMiddleware,
    build_healthz_asgi_app,
    build_metrics_asgi_app,
    build_readyz_asgi_app,
    configure_logging,
    configure_tracing,
)


_PORTAL_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        # Plumbing — AuthMiddleware replaces its default set when we
        # pass public_paths, so list every public route explicitly.
        "/healthz",
        "/readyz",
        "/.well-known/jwks.json",
        # Public Portal routes (no bearer required):
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/invite/accept",
        # OIDC entry points — interactive flows start before the
        # user has a bearer.
        "/api/v1/sso/oidc/initiate",
        "/api/v1/sso/oidc/callback",
    }
)

# Prefix matches — SAML ACS/metadata carry the tenant id in the
# path, webhook routes re-authenticate via provider signatures.
_PORTAL_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/v1/sso/saml/",
    "/webhooks/",
)


async def _jwks_endpoint(request: Request) -> JSONResponse:
    """Serve the JWKS document at /.well-known/jwks.json."""
    builder = JwksDocumentBuilder()
    async with admin_session() as db:
        doc = await builder.build(db)
    settings = get_settings()
    cache_seconds = settings.jwt.jwks_cache_control_seconds
    return JSONResponse(
        doc,
        headers={
            "Cache-Control": f"public, max-age={cache_seconds}",
            "Content-Type": "application/json",
        },
    )


def build_app() -> Starlette:
    """Return a fully-wired Starlette app."""
    configure_logging()
    configure_tracing()

    settings = get_settings()

    routes = [
        # Public plumbing
        Route("/.well-known/jwks.json", _jwks_endpoint, methods=["GET"]),
        Mount("/healthz", build_healthz_asgi_app()),
        Mount("/readyz", build_readyz_asgi_app()),
        Mount(settings.observability.metrics_path, build_metrics_asgi_app()),
        # Admin API — require the admin JWT audience (enforced per-
        # handler via @require_permission decorators from 10.c).
        Mount("/admin", routes=build_admin_router()),
        # Portal API — tenant-admin + M2M self-service.
        Mount("/api/v1", routes=build_api_router()),
        # Inbound webhooks (Stripe, etc.). Auth is re-implemented
        # via provider signatures; AuthMiddleware skips these paths.
        Mount("/webhooks", routes=build_webhook_router()),
    ]

    app = Starlette(routes=routes)

    # Middleware chain — outermost first. ``add_middleware`` in
    # Starlette prepends, so the LAST call wraps OUTSIDE the earlier
    # ones. We want:
    #   ObservabilityMiddleware    (outermost — always records)
    #     AuthMiddleware           (verifies JWT, sets principal)
    #       DataResidencyMiddleware (308-redirects mis-routed tenants)
    #         Route handler
    # Thus we add innermost first.
    app.add_middleware(DataResidencyMiddleware)
    app.add_middleware(
        AuthMiddleware,
        public_paths=_PORTAL_PUBLIC_PATHS,
        public_prefixes=_PORTAL_PUBLIC_PREFIXES,
    )
    app.add_middleware(ObservabilityMiddleware)

    install_error_handlers(app)
    return app
