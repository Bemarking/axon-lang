"""RBAC ORM models.

Replaces the in-memory scaffolding from v1.0.0 with real persistent
tables. The schema layout:

    permissions           global catalog (no RLS — read-only by design)
    roles                 tenant-scoped, hierarchy via parent_role_id
    role_permissions      M2M (role_id, permission_id) + denormalised
                          tenant_id for direct RLS on the join table
    user_roles            user ↔ role binding inside a tenant

Hierarchy semantics
-------------------
A role ``developer`` can set ``parent_role_id`` pointing to
``viewer``; calling ``effective_permissions(developer)`` therefore
returns viewer's permissions UNION developer's own. Cycles are
prevented by ``RbacService.create_role`` / ``set_parent`` which walk
upward before accepting the change, and by the recursive CTE using
``UNION`` (deduplicates) so even a smuggled cycle can't loop.

Denormalised tenant_id
----------------------
``role_permissions`` and ``user_roles`` carry ``tenant_id`` even
though it could be derived from ``roles.tenant_id`` via join. The
redundancy enables a direct RLS policy on each table without the
policy needing a JOIN (which risks recursive RLS evaluation and
hurts plan stability).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from axon_enterprise.db.base import Base, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    pass


# ── permissions ──────────────────────────────────────────────────────


class Permission(TimestampMixin, Base):
    """Global catalog entry — ``(resource, action)`` is unique."""

    __tablename__ = "permissions"

    permission_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_system: Mapped[bool] = mapped_column(
        nullable=False, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permissions_resource_action"),
    )

    @property
    def key(self) -> str:
        return f"{self.resource}:{self.action}"


# ── roles ────────────────────────────────────────────────────────────


class Role(TimestampMixin, Base):
    """A tenant-scoped role. Carries optional ``parent_role_id`` hierarchy."""

    __tablename__ = "roles"

    role_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    is_built_in: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    parent_role_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.roles.role_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
        Index("ix_roles_parent_role_id", "parent_role_id"),
    )

    parent: Mapped[Role | None] = relationship(
        "Role",
        remote_side=[role_id],
        foreign_keys=[parent_role_id],
    )


# ── role_permissions (M2M) ───────────────────────────────────────────


class RolePermission(Base):
    """Grant of a permission to a role. Tenant denormalised for RLS."""

    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.roles.role_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.permissions.permission_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    granted_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_role_permissions_tenant_id", "tenant_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )


# ── user_roles ──────────────────────────────────────────────────────


class UserRole(Base):
    """Assignment of a ``(role, tenant)`` pair to a user."""

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.roles.role_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    assigned_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_user_roles_tenant_id_user_id", "tenant_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
    )
