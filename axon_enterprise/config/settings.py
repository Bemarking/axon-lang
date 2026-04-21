"""Typed, environment-driven configuration for Axon Enterprise.

All settings are loaded lazily via ``get_settings()`` which caches the
result. Unit tests can reset the cache via ``get_settings.cache_clear()``
to re-read the environment.

Conventions
-----------
- Env var prefix:                ``AXON_``
- Nested delimiter:               ``__`` (double underscore)
- Env file (optional):            ``.env`` at CWD
- Secrets wrapped in ``SecretStr`` so ``repr()`` and structlog never leak
- SSL enforcement is mandatory when ``env == "production"``
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment. Drives safety defaults."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


SSLMode = Literal[
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
]


class DatabaseSettings(BaseSettings):
    """Postgres connection + pool + observability configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AXON_DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Connection — url is mandatory in every environment
    url: SecretStr = Field(
        ...,
        description=(
            "SQLAlchemy URL, e.g. "
            "postgresql+asyncpg://user:pass@host:5432/axon_enterprise"
        ),
    )
    read_url: SecretStr | None = Field(
        default=None,
        description="Optional read-replica URL. Reads fall back to primary when unset.",
    )

    # Pool tuning — defaults target a single service instance; scale per container count
    pool_size: int = Field(default=10, ge=1, le=200)
    max_overflow: int = Field(default=20, ge=0, le=400)
    pool_timeout_seconds: float = Field(default=30.0, gt=0.0)
    pool_recycle_seconds: int = Field(
        default=1800,
        ge=60,
        description="Close and recycle connections after N seconds to dodge NAT idle timeouts.",
    )
    pool_pre_ping: bool = Field(
        default=True,
        description="Validate connections with SELECT 1 before handing them out.",
    )

    # Query-level safety
    statement_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        description="Postgres statement_timeout applied per session.",
    )
    idle_in_transaction_timeout_ms: int = Field(
        default=60_000,
        ge=1_000,
        description="Kill sessions that sit in an open transaction too long.",
    )
    lock_timeout_ms: int = Field(
        default=5_000,
        ge=0,
        description="Maximum wait for row/table locks before failing a statement.",
    )
    slow_query_ms: int = Field(
        default=1_000,
        ge=0,
        description="Log + emit a metric for queries slower than this.",
    )

    # SSL / TLS
    ssl_mode: SSLMode = "require"
    ssl_root_cert: Path | None = Field(
        default=None,
        description="PEM bundle for verify-ca / verify-full modes.",
    )

    # Observability hooks
    echo_sql: bool = Field(
        default=False,
        description="Emit every statement via logging. Never enable in production.",
    )
    echo_pool: bool = False
    application_name: str = Field(
        default="axon-enterprise",
        description="Postgres application_name. Shows in pg_stat_activity for debugging.",
    )

    # Schema layout
    control_schema: str = Field(
        default="axon_control",
        description=(
            "Schema owned by the Python control plane. Separate from the "
            "default `public` schema where the Rust data plane writes "
            "(tenants, flows, traces)."
        ),
    )


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_prefix="AXON_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Environment = Environment.PRODUCTION

    # Nested
    db: DatabaseSettings

    # Tenant defaults — the GUC name must match axon-rs (M2 migration 005)
    default_tenant_id: str = "default"
    rls_guc_name: str = Field(
        default="axon.current_tenant",
        description=(
            "Postgres GUC set via `SET LOCAL` to scope every RLS policy. "
            "MUST match the name used by axon-rs/src/db_pool.rs."
        ),
    )

    # Retrieved from the runtime environment for structured logs / JWT `iss`
    service_name: str = "axon-enterprise"
    service_version: str = "1.1.0-dev"

    @field_validator("rls_guc_name")
    @classmethod
    def _guc_must_be_qualified(cls, v: str) -> str:
        if "." not in v:
            raise ValueError(
                "rls_guc_name must be a qualified GUC name like 'axon.current_tenant'"
            )
        return v

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Settings:
        """Production must use TLS and must not echo SQL."""
        if self.env is Environment.PRODUCTION:
            if self.db.ssl_mode in ("disable", "allow", "prefer"):
                raise ValueError(
                    "db.ssl_mode must be 'require' or stronger in production"
                )
            if self.db.echo_sql:
                raise ValueError("db.echo_sql must be False in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once and cache. Tests call ``get_settings.cache_clear()``."""
    return Settings()  # type: ignore[call-arg]
