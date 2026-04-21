"""rbac_production

Creates the RBAC subsystem tables and seeds the permission catalog.

    axon_control.permissions          global (no RLS — read-only catalog)
    axon_control.roles                tenant-scoped, self-FK parent_role_id
    axon_control.role_permissions     M2M + denormalised tenant_id
    axon_control.user_roles           user ↔ role ↔ tenant binding

The permission catalog is seeded from ``rbac.permissions.SYSTEM_PERMISSIONS``
using INSERT ... ON CONFLICT DO NOTHING so re-running the migration
against a populated catalog is a no-op.

Built-in roles (``owner`` / ``admin`` / ``developer`` / ``viewer``)
are NOT seeded here. They are created per-tenant by
``rbac.seed.seed_builtin_roles`` during tenant provisioning (Fase
10.j Admin API), so this migration stays idempotent even when the
fleet of tenants grows.

Revision ID: 003
Revises: 002
Create Date: 2026-04-21 02:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql
from axon_enterprise.rbac.permissions import SYSTEM_PERMISSIONS

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── permissions (global catalog — no RLS) ─────────────────────────
    op.create_table(
        "permissions",
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "resource", "action", name="uq_permissions_resource_action"
        ),
        schema="axon_control",
    )

    # Seed the catalog. Sorted by (resource, action) so the INSERT is
    # deterministic across reviewers.
    sorted_perms = sorted(
        SYSTEM_PERMISSIONS, key=lambda p: (p.resource, p.action)
    )
    if sorted_perms:
        values_sql = ",\n    ".join(
            f"('{p.resource}', '{p.action}', $${p.description}$$)"
            for p in sorted_perms
        )
        op.execute(
            sa.text(
                f"""
                INSERT INTO axon_control.permissions (resource, action, description)
                VALUES
                    {values_sql}
                ON CONFLICT (resource, action) DO NOTHING;
                """
            )
        )

    # ── roles ─────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_roles_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "is_built_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "parent_role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.roles.role_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_roles_parent_role_id_roles",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
        schema="axon_control",
    )
    op.create_index(
        "ix_roles_tenant_id", "roles", ["tenant_id"], schema="axon_control"
    )
    op.create_index(
        "ix_roles_parent_role_id",
        "roles",
        ["parent_role_id"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="roles", schema="axon_control"):
        op.execute(stmt)

    # ── role_permissions ──────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.roles.role_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_role_permissions_role_id_roles",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.permissions.permission_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_role_permissions_permission_id_permissions",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_role_permissions_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column(
            "granted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_role_permissions_granted_by_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_role_permissions_tenant_id",
        "role_permissions",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_role_permissions_permission_id",
        "role_permissions",
        ["permission_id"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="role_permissions", schema="axon_control"
    ):
        op.execute(stmt)

    # ── user_roles ────────────────────────────────────────────────────
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_user_roles_user_id_users",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.roles.role_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_user_roles_role_id_roles",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_user_roles_tenant_id_tenants",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_user_roles_assigned_by_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_user_roles_tenant_id_user_id",
        "user_roles",
        ["tenant_id", "user_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_user_roles_role_id",
        "user_roles",
        ["role_id"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="user_roles", schema="axon_control"):
        op.execute(stmt)


def downgrade() -> None:
    # Drop in reverse FK order.
    op.drop_table("user_roles", schema="axon_control")
    op.drop_table("role_permissions", schema="axon_control")
    op.drop_table("roles", schema="axon_control")
    op.drop_table("permissions", schema="axon_control")
