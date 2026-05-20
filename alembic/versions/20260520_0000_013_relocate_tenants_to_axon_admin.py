"""relocate_tenants_to_axon_admin — §Fase 38.x.b (D3)

Atomic FK relocation: every enterprise table that references
``public.tenants.tenant_id`` gets its ForeignKey dropped and re-created
pointing at ``axon_admin.tenants.tenant_id``. CASCADE / RESTRICT
semantics preserved per original declaration.

Why this migration exists
-------------------------
v1.38.2 of axon-lang moved the M1 admin tenants table from the default
search-path schema (typically ``public``) into a dedicated
``axon_admin.tenants`` (see ``axon-rs/migrations/003_add_tenants.sql``).
That fixes the kivi 2026-05-20 smoke-16 collision against adopter-owned
``public.tenants``. v1.29.1 enterprise catches up by repointing every
SQLAlchemy ``ForeignKey`` to the new canonical home.

This migration handles EXISTING deployments: their alembic 001-012 ran
with the legacy source code that declared FKs against ``public.tenants``,
so the actual constraints in their database still point there. This
migration drops and recreates each, atomically.

Pre-conditions (asserted)
-------------------------
- axon-lang v1.38.2+ must have run ``003_add_tenants.sql`` so
  ``axon_admin.tenants`` exists.
- ``public.tenants`` may STILL EXIST — we don't touch it. The adopter
  may have RLS grants / app FKs / readers pointing at it. v1.38.2's M1
  is non-destructive by design.

Post-conditions
---------------
- All 18 enterprise FK constraints that previously pointed at
  ``public.tenants.tenant_id`` now point at
  ``axon_admin.tenants.tenant_id``.
- The CASCADE / RESTRICT semantics each FK declared (ondelete +
  onupdate) are preserved verbatim.
- The migration is idempotent: rerunning is a no-op (every
  ``DROP CONSTRAINT IF EXISTS`` + ``ADD CONSTRAINT`` is safe).

Atomicity
---------
Each FK drop+recreate is one ``ALTER TABLE`` pair inside ONE alembic
transaction. If any single recreation fails (e.g. orphan rows that
violate RESTRICT semantics post-relocation), the entire migration
rolls back — no partial state.

Naming convention
-----------------
Enterprise FKs follow the ``NAMING_CONVENTION`` in
``axon_enterprise/db/base.py``:
``fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s``.
So FK names are ``fk_<table>_tenant_id_tenants`` uniformly — the
``referred_table_name`` is the bare ``tenants`` (no schema prefix), so
constraint NAMES are unchanged across the relocation.

Revision ID: 013
Revises: 012
Create Date: 2026-05-20 00:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── §D3 — the 18-FK relocation catalog ────────────────────────────────
#
# Each entry: (table, ondelete, onupdate). The constraint name follows
# the NAMING_CONVENTION: `fk_<table>_tenant_id_tenants`.
# The enterprise control-plane schema is `axon_control` (per
# `axon_enterprise.db.base._default_schema`); all 18 tables live there.
#
# Sources of truth:
#   - 15 explicit FK declarations across 10 models
#   - 3 implicit FKs via TenantScopedMixin (RESTRICT/CASCADE):
#     identity.Session, sso.SsoConfiguration, sso.SsoState

_RELOCATIONS: list[tuple[str, str, str]] = [
    # (table_name,         ondelete,   onupdate)
    # Explicit declarations:
    ("tenant_memberships",  "RESTRICT", "CASCADE"),  # identity/models.py:186
    ("roles",               "CASCADE",  "CASCADE"),  # rbac/models.py:87
    ("role_permissions",    "CASCADE",  "CASCADE"),  # rbac/models.py:137
    ("user_roles",          "CASCADE",  "CASCADE"),  # rbac/models.py:190
    ("sso_assertion_seen",  "CASCADE",  "CASCADE"),  # sso/models.py:193
    ("tenant_secrets",      "RESTRICT", "CASCADE"),  # secrets/models.py:54
    ("audit_events",        "RESTRICT", "CASCADE"),  # audit/models.py:39
    ("tenant_subscriptions","CASCADE",  "CASCADE"),  # metering/models.py:119
    ("usage_events",        "RESTRICT", "CASCADE"),  # metering/models.py:164
    ("invoices",            "RESTRICT", "CASCADE"),  # metering/models.py:219
    ("tenant_api_keys",     "CASCADE",  "CASCADE"),  # api_keys/models.py:30
    ("compliance_requests", "RESTRICT", "CASCADE"),  # compliance/models.py:61
    ("legal_holds",         "RESTRICT", "CASCADE"),  # compliance/models.py:157
    ("replay_tokens",       "RESTRICT", "CASCADE"),  # replay/models.py:31
    ("cognitive_states",    "RESTRICT", "CASCADE"),  # cognitive_states/models.py
    # Implicit via TenantScopedMixin (RESTRICT/CASCADE):
    ("sessions",            "RESTRICT", "CASCADE"),  # identity/models.py:262
    ("sso_configurations",  "RESTRICT", "CASCADE"),  # sso/models.py:58
    ("sso_states",          "RESTRICT", "CASCADE"),  # sso/models.py:120
]

CONTROL_SCHEMA = "axon_control"

_ASSERT_AXON_ADMIN_TENANTS_EXISTS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'axon_admin' AND table_name = 'tenants'
    ) THEN
        RAISE EXCEPTION
            'Required table axon_admin.tenants is missing. Run the Rust data-plane migrations from axon-lang v1.38.2+ first: axon-rs/migrations/003_add_tenants.sql.';
    END IF;
END
$$;
"""


def upgrade() -> None:
    """§D3 — atomic FK swap to ``axon_admin.tenants``.

    For each enterprise table with an FK to tenants:
    1. DROP CONSTRAINT IF EXISTS (defensive — fresh installs from
       v1.29.1+ source already point at axon_admin via the model
       declarations, so the alembic 001-012 baseline never created
       a public.tenants-pointing constraint).
    2. ADD CONSTRAINT (the new FK, same name, pointed at
       axon_admin.tenants, same CASCADE/RESTRICT semantics).
    """
    op.execute(_ASSERT_AXON_ADMIN_TENANTS_EXISTS)

    for table, ondelete, onupdate in _RELOCATIONS:
        constraint_name = f"fk_{table}_tenant_id_tenants"
        op.execute(
            f'ALTER TABLE "{CONTROL_SCHEMA}"."{table}" '
            f'DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )
        op.execute(
            f'ALTER TABLE "{CONTROL_SCHEMA}"."{table}" '
            f'ADD CONSTRAINT "{constraint_name}" '
            f'FOREIGN KEY ("tenant_id") '
            f'REFERENCES "axon_admin"."tenants" ("tenant_id") '
            f'ON DELETE {ondelete} ON UPDATE {onupdate}'
        )


def downgrade() -> None:
    """Re-point every FK back at ``public.tenants``.

    Requires the legacy table to still exist (v1.38.2's M1 is
    non-destructive, so this is the common case for any deploy that
    upgraded from v1.29.0 or earlier).
    """
    for table, ondelete, onupdate in _RELOCATIONS:
        constraint_name = f"fk_{table}_tenant_id_tenants"
        op.execute(
            f'ALTER TABLE "{CONTROL_SCHEMA}"."{table}" '
            f'DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )
        op.execute(
            f'ALTER TABLE "{CONTROL_SCHEMA}"."{table}" '
            f'ADD CONSTRAINT "{constraint_name}" '
            f'FOREIGN KEY ("tenant_id") '
            f'REFERENCES "public"."tenants" ("tenant_id") '
            f'ON DELETE {ondelete} ON UPDATE {onupdate}'
        )
