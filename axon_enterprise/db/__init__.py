"""Database foundation — async engine, session factory, declarative base.

Fase 10.a building blocks. Higher-level sub-fases (identity, RBAC, audit,
metering, secrets) declare their ORM models on top of ``Base`` and write
migrations through Alembic against ``METADATA``.
"""

from axon_enterprise.db.base import (
    Base,
    METADATA,
    NAMING_CONVENTION,
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
)
from axon_enterprise.db.engine import (
    create_primary_engine,
    create_read_engine,
    dispose_all_engines,
    get_primary_engine,
    get_read_engine,
)
from axon_enterprise.db.rls_policies import (
    admin_bypass_policy_sql,
    enable_rls_sql,
    tenant_isolation_policy_sql,
)
from axon_enterprise.db.session import (
    AdminSession,
    TenantSession,
    admin_session,
    read_session,
    tenant_session,
)

__all__ = [
    "AdminSession",
    "Base",
    "METADATA",
    "NAMING_CONVENTION",
    "SoftDeleteMixin",
    "TenantScopedMixin",
    "TenantSession",
    "TimestampMixin",
    "admin_bypass_policy_sql",
    "admin_session",
    "create_primary_engine",
    "create_read_engine",
    "dispose_all_engines",
    "enable_rls_sql",
    "get_primary_engine",
    "get_read_engine",
    "read_session",
    "tenant_isolation_policy_sql",
    "tenant_session",
]
