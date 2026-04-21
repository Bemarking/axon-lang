"""Declarative base, metadata, and reusable mixins.

Design notes
------------
- A deterministic ``NAMING_CONVENTION`` is set on ``MetaData`` so Alembic
  autogenerate produces stable constraint names across developers and
  platforms — critical to keep migrations byte-identical in review.
- All Python-owned tables live in the ``axon_control`` schema. The
  ``tenants`` table (and the rest of the Rust data plane) lives in
  ``public``; cross-schema foreign keys are used where we reference it.
- Mixins are composable: a table that wants all four characteristics
  (timestamps, tenant scope, soft delete, audit actor) inherits
  ``TimestampMixin, TenantScopedMixin, SoftDeleteMixin`` alongside
  ``Base``. The order doesn't matter because each mixin declares its own
  non-overlapping columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, MetaData, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from axon_enterprise.config import get_settings

# ── Naming convention ─────────────────────────────────────────────────
#
# Makes Alembic produce deterministic constraint names on autogenerate.
# The short prefix (ix / uq / ck / fk / pk) is the same convention
# SQLAlchemy recommends and that Rust's sqlx migrations also follow —
# consistency across both sides eases schema reviews.

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _default_schema() -> str:
    """Resolve the control-plane schema name from settings at import time."""
    try:
        return get_settings().db.control_schema
    except Exception:  # noqa: BLE001
        # Settings may be unavailable (e.g. during doc build).
        # ``axon_control`` is the documented default.
        return "axon_control"


METADATA = MetaData(
    naming_convention=NAMING_CONVENTION,
    schema=_default_schema(),
)


class Base(DeclarativeBase):
    """Root of the Python-owned ORM tree."""

    metadata = METADATA


# ── Mixins ────────────────────────────────────────────────────────────


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` managed server-side.

    ``server_default=func.now()`` ensures the value is set by Postgres,
    which is important when a row is inserted by a different service
    (e.g. a Rust job) that doesn't go through this ORM.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantScopedMixin:
    """Adds ``tenant_id`` with a cross-schema FK to ``public.tenants``.

    Any table inheriting this mixin MUST be covered by an RLS policy
    declared via ``rls_policies.tenant_isolation_policy_sql``. The helper
    ``__table_args__`` here also adds a composite index on
    ``(tenant_id, id)`` which is the most common query shape.
    """

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "public.tenants.tenant_id",
            # Rust owns the tenants table; we read it but don't cascade.
            # Deleting a tenant is a multi-step workflow (soft-delete first,
            # then purge), so a hard cascade would hide bugs.
            ondelete="RESTRICT",
            onupdate="CASCADE",
            name=None,  # name auto-generated via NAMING_CONVENTION
        ),
        nullable=False,
        index=True,
    )

    @declared_attr.directive
    @classmethod
    def __table_args__(cls):  # type: ignore[override]
        # Subclasses that add more args should override explicitly.
        return (
            Index(
                f"ix_{cls.__tablename__}_tenant_id_created_at",  # type: ignore[attr-defined]
                "tenant_id",
                "created_at",
            ),
        )


class SoftDeleteMixin:
    """Adds ``deleted_at`` so rows can be soft-deleted.

    Production code must filter ``deleted_at IS NULL`` on read. Helpers
    to enforce this are added by the service layer; the mixin only
    provides the column.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# ── Session-level GUC helper ───────────────────────────────────────────
#
# Used by the session factory; exposed here so migrations and tests can
# apply the same ``SET LOCAL`` without importing session.


def set_tenant_guc_sql(guc_name: str, tenant_id: str) -> text:  # type: ignore[return-value]
    """Return a ``SET LOCAL`` statement scoping the given GUC for the current tx.

    We intentionally use ``SET LOCAL`` (not ``SET``) so the setting is
    discarded on transaction end; this guarantees a pool-recycled
    connection never carries a stale tenant into the next request.
    """
    # bindparam avoids quoting pitfalls on the value and leverages asyncpg's
    # native parameter binding.
    return text(f"SET LOCAL {guc_name} = :tenant_id").bindparams(tenant_id=tenant_id)
