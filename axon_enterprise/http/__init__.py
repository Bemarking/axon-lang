"""HTTP layer — Admin API + common plumbing.

Fase 10.j. Exposes every service built in 10.a–10.i behind an
ASGI app. Pure Starlette (no FastAPI) so the middleware chain
from 10.i composes cleanly and we keep the dependency surface
small.

Public surface
--------------
    build_app           app factory — wires every middleware +
                        mounts the Admin API router + healthz + metrics
    AuthMiddleware      JWT verification → PrincipalContext ContextVar
    PermissionMiddleware 403 for routes tagged with required permissions
    error_handlers      maps typed IdentityError → JSON responses
    CursorPage          paging shape for high-volume endpoints
    OffsetPage          paging shape for small-admin endpoints

Routes under ``/admin/*`` require admin-tier JWT scope; routes
under ``/api/v1/*`` accept any authenticated principal with the
matching per-operation permission. Routes under ``/healthz``,
``/readyz``, and the configured ``metrics_path`` are always public.
"""

from axon_enterprise.http.app import build_app
from axon_enterprise.http.auth_middleware import AuthMiddleware
from axon_enterprise.http.errors import (
    error_response_for,
    install_error_handlers,
    json_error,
)
from axon_enterprise.http.pagination import (
    CursorPage,
    OffsetPage,
    parse_cursor,
    parse_pagination_params,
)

__all__ = [
    "AuthMiddleware",
    "CursorPage",
    "OffsetPage",
    "build_app",
    "error_response_for",
    "install_error_handlers",
    "json_error",
    "parse_cursor",
    "parse_pagination_params",
]
