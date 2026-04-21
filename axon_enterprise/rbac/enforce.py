"""Enforcement — decorator + helper that read from ``CURRENT_PRINCIPAL``.

Handler code composes like this::

    from axon_enterprise.rbac.enforce import require_permission

    @require_permission("secret:write")
    async def create_secret(db: TenantSession, request: Request) -> Response:
        ...

The decorator:

    1. Resolves the active ``PrincipalContext`` (raises if unset).
    2. Locates a DB session argument by type annotation (``AsyncSession``
       or one of the typed ``TenantSession`` / ``AdminSession`` aliases).
    3. Calls ``RbacService.require`` — raises ``PermissionDenied`` on
       deny. Handlers catch in a generic error middleware and return 403.

A standalone helper ``require_permission_active`` is exposed for
cases where a decorator does not fit (workers, background jobs).
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.identity.principal import (
    PrincipalContext,
    require_principal,
)
from axon_enterprise.rbac.errors import PermissionDenied  # noqa: F401 (re-export)
from axon_enterprise.rbac.permissions import parse_permission
from axon_enterprise.rbac.service import RbacService

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def require_permission(permission: str) -> Callable[[F], F]:
    """Decorator asserting the principal holds ``permission``.

    The permission string is parsed at decoration time so typos fail
    fast at import rather than at request time.
    """
    parse_permission(permission)  # validates against catalog
    rbac = RbacService()

    def wrap(fn: F) -> F:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = require_principal()
            db = _extract_session(fn, sig, args, kwargs)
            await rbac.require(
                db,
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                permission=permission,
            )
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return wrap


async def require_permission_active(
    db: AsyncSession,
    permission: str,
    *,
    principal: PrincipalContext | None = None,
) -> None:
    """Imperative variant — use outside decoratable contexts.

    ``principal`` defaults to the active ``CURRENT_PRINCIPAL`` ContextVar
    value; pass explicitly in background workers where the ContextVar
    may not be set by middleware.
    """
    principal = principal or require_principal()
    await RbacService().require(
        db,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        permission=permission,
    )


async def check_permission(
    db: AsyncSession,
    permission: str,
    *,
    principal: PrincipalContext | None = None,
) -> bool:
    """Boolean variant of ``require_permission_active``. No exception."""
    principal = principal or require_principal()
    return await RbacService().check(
        db,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        permission=permission,
    )


# ── Internals ─────────────────────────────────────────────────────────


def _extract_session(
    fn: Callable[..., Any],
    sig: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> AsyncSession:
    """Find the ``AsyncSession`` parameter among the wrapped function's args.

    The decorator must locate the DB session without requiring the
    handler to conform to a specific positional layout. We pick the
    first parameter whose annotation is ``AsyncSession`` (or a typed
    alias thereof).
    """
    bound = sig.bind_partial(*args, **kwargs)
    for name, param in sig.parameters.items():
        ann = param.annotation
        if ann is inspect.Parameter.empty:
            continue
        if _is_async_session_annotation(ann):
            if name in bound.arguments:
                value = bound.arguments[name]
                if isinstance(value, AsyncSession):
                    return value
    raise TypeError(
        f"@require_permission: function {fn.__qualname__} must accept an "
        "AsyncSession parameter (or a typed alias) so RBAC can resolve "
        "the permission check."
    )


def _is_async_session_annotation(annotation: Any) -> bool:
    """True when the annotation *is* ``AsyncSession`` or ``NewType`` of it."""
    if annotation is AsyncSession:
        return True
    # Typed aliases from db.session: TenantSession / AdminSession —
    # NewType wraps AsyncSession, so inspect its supertype.
    supertype = getattr(annotation, "__supertype__", None)
    if supertype is AsyncSession:
        return True
    # String-form annotations: PEP 563 / postponed evaluation.
    if isinstance(annotation, str):
        return "AsyncSession" in annotation or "TenantSession" in annotation
    return False
