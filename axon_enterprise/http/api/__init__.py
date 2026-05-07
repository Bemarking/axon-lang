"""Tenant-facing API — mounted under ``/api/v1``.

Serves the portal (tenant admins) + M2M integrations. Every route
is JWT-authenticated via the ``AuthMiddleware`` from 10.j + scoped
to the principal's tenant. No ``_require_admin`` coarse gate here —
tenant admins operate within their own tenant freely.
"""

from starlette.routing import Mount, Route

from axon_enterprise.http.api import (
    api_keys,
    auth,
    compliance,
    integration_context,
    primitives,
    sso_routes,
    tenant_users,
    usage,
)


def build_api_router() -> list[Route | Mount]:
    """Return the route tree the app factory mounts under ``/api/v1``."""
    return [
        Mount("/auth", routes=auth.routes()),
        Mount("/sso", routes=sso_routes.routes()),
        Mount("/tenant/users", routes=tenant_users.routes()),
        Mount("/tenant/api-keys", routes=api_keys.routes()),
        Mount("/tenant/usage", routes=usage.routes()),
        Mount("/tenant/compliance", routes=compliance.routes()),
        # Fase 21.c — tenant introspection of integration context.
        # Auth-required, RLS by construction (uses principal.tenant_id).
        Mount(
            "/tenant/me/integration-context",
            routes=integration_context.routes(),
        ),
        # §v1.2.1 — public primitives discovery endpoint. Enumerates
        # every closed catalogue (trust / backpressure / legal /
        # OTS) + the seeded BufferKind registry so clients can
        # discover the language surface programmatically.
        Mount("/primitives", routes=primitives.routes()),
    ]


__all__ = ["build_api_router"]
