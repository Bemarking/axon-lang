"""App factory — builds the Starlette ASGI application.

Responsibilities:

1. Wire middleware in the correct order.
2. Mount the Admin API router under ``/admin``.
3. Mount the health + readiness + metrics + JWKS endpoints.
4. Install typed-error handlers.
5. Return a ``Starlette`` app ready for ``uvicorn`` / ``gunicorn``.

The factory is deliberately parameterless — every dependency comes
from ``get_settings()``. Tests that need to swap components monkey-
patch the settings cache and rebuild.
"""

from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from axon_enterprise.config import get_settings
from axon_enterprise.db.session import admin_session
from axon_enterprise.http.admin import build_admin_router
from axon_enterprise.http.auth_middleware import AuthMiddleware
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.jwt_issuer import JwksDocumentBuilder
from axon_enterprise.observability import (
    ObservabilityMiddleware,
    build_healthz_asgi_app,
    build_metrics_asgi_app,
    build_readyz_asgi_app,
    configure_logging,
    configure_tracing,
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
        # Admin API (require admin JWT — enforced per-handler via
        # @require_permission decorators)
        Mount("/admin", routes=build_admin_router()),
    ]

    app = Starlette(routes=routes)

    # Middleware chain — outermost first. ``add_middleware`` in
    # Starlette prepends, so the LAST call wraps OUTSIDE the earlier
    # ones. We want:
    #   ObservabilityMiddleware (outermost)
    #     AuthMiddleware
    #       Route handler
    # Thus we add AuthMiddleware first, then Observability.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(ObservabilityMiddleware)

    install_error_handlers(app)
    return app
