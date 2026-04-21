"""Admin API router — mounted under ``/admin`` by the app factory.

Every handler is @require_permission'd via the 10.c decorator so
tenant admins cannot accidentally hit an operator-only endpoint.
The handler layer does nothing more than: parse inputs →
delegate to the service → serialise outputs. All business logic
lives in the respective service modules.
"""

from starlette.routing import Mount, Route

from axon_enterprise.http.admin import audit, keys, tenants, users


def build_admin_router() -> list[Route | Mount]:
    """Return the route list that the app factory mounts under ``/admin``."""
    return [
        Mount("/tenants", routes=tenants.routes()),
        Mount("/users", routes=users.routes()),
        Mount("/keys", routes=keys.routes()),
        Mount("/audit", routes=audit.routes()),
    ]


__all__ = ["build_admin_router"]
