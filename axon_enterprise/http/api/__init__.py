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
    ]


__all__ = ["build_api_router"]
