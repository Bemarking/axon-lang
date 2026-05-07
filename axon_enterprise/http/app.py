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
from axon_enterprise.http.discovery import (
    capabilities_endpoint,
    oauth_authorization_server_endpoint,
    openapi_endpoint,
    openid_configuration_endpoint,
    redoc_endpoint,
    swagger_ui_endpoint,
    version_endpoint,
    with_discovery_observability,
)
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
        "/livez",
        "/readyz",
        "/version",
        "/.well-known/jwks.json",
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/.well-known/axon-capabilities.json",
        "/openapi.json",
        "/docs",
        "/redoc",
        # Public Portal routes (no bearer required):
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/invite/accept",
        # OIDC entry points — interactive flows start before the
        # user has a bearer.
        "/api/v1/sso/oidc/initiate",
        "/api/v1/sso/oidc/callback",
        # §v1.2.1 — catalog discovery is public. The slugs are
        # already in `docs/` and the axon-lang source; no secret
        # to protect by gating.
        "/api/v1/primitives",
        "/api/v1/primitives/",
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
        # Public plumbing — Fase 21 endpoints are wrapped with observability
        # (sub-fase 21.h) so each fetch emits a structured log event +
        # bumps Prometheus counters with privacy-anonymized fields.
        Route(
            "/.well-known/jwks.json",
            with_discovery_observability("jwks", _jwks_endpoint),
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration",
            with_discovery_observability(
                "openid-configuration", openid_configuration_endpoint
            ),
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            with_discovery_observability(
                "oauth-authorization-server", oauth_authorization_server_endpoint
            ),
            methods=["GET"],
        ),
        Route(
            "/.well-known/axon-capabilities.json",
            with_discovery_observability("axon-capabilities", capabilities_endpoint),
            methods=["GET"],
        ),
        # Fase 21.e — OpenAPI 3.1.0 spec + interactive renderers.
        Route(
            "/openapi.json",
            with_discovery_observability("openapi", openapi_endpoint),
            methods=["GET"],
        ),
        Route("/docs", swagger_ui_endpoint, methods=["GET"]),
        Route("/redoc", redoc_endpoint, methods=["GET"]),
        Mount("/healthz", build_healthz_asgi_app()),
        # Fase 21.f — k8s-modern liveness alias. ``/livez`` and ``/healthz``
        # are intentionally the same handler: pure liveness, always 200.
        # Keeping both lets adopters use whichever convention their
        # orchestrator (kubelet, ECS, Nomad) expects without us picking
        # a winner.
        Mount("/livez", build_healthz_asgi_app()),
        Mount("/readyz", build_readyz_asgi_app()),
        # Fase 21.f — server version + build metadata for orchestrators
        # and post-deploy verification.
        Route(
            "/version",
            with_discovery_observability("version", version_endpoint),
            methods=["GET"],
        ),
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
