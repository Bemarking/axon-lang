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


EnvelopeBackend = Literal["local", "kms"]


class EnvelopeSettings(BaseSettings):
    """Application-level envelope encryption configuration.

    Two backends are supported:

    - ``local`` — Fernet-based, uses a 32-byte key loaded from
      ``AXON_ENVELOPE__LOCAL_KEY`` (base64-urlsafe). Intended for
      development, tests, and single-node deployments without KMS.

    - ``kms`` — AWS KMS envelope encryption. Each record gets its own
      DEK (data encryption key) generated and wrapped by KMS; the DEK
      never leaves the HSM. AAD (encryption context) binds ciphertexts
      to individual rows so they cannot be swapped across records.
    """

    model_config = SettingsConfigDict(
        env_prefix="AXON_ENVELOPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend: EnvelopeBackend = "local"
    # Local backend
    local_key: SecretStr | None = Field(
        default=None,
        description="Base64-urlsafe-encoded 32-byte key. Required when backend='local'.",
    )
    # KMS backend
    kms_key_id: str | None = Field(
        default=None,
        description="KMS key ARN or alias. Required when backend='kms'.",
    )
    kms_region: str | None = Field(
        default=None,
        description="AWS region for the KMS client.",
    )


class IdentitySettings(BaseSettings):
    """Authentication and session policy."""

    model_config = SettingsConfigDict(
        env_prefix="AXON_IDENTITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Argon2id parameters (OWASP 2024 recommendation)
    argon2_time_cost: int = Field(default=3, ge=2, le=10)
    argon2_memory_cost_kib: int = Field(
        default=65_536,  # 64 MiB
        ge=19_456,       # minimum OWASP recommends
        description="Argon2 memory cost in KiB. 64 MiB default, bump to 128 MiB on beefy servers.",
    )
    argon2_parallelism: int = Field(default=4, ge=1, le=16)
    argon2_hash_len: int = Field(default=32, ge=16, le=64)
    argon2_salt_len: int = Field(default=16, ge=8, le=32)

    # Password policy
    password_min_length: int = Field(default=12, ge=8)
    password_zxcvbn_min_score: int = Field(default=3, ge=0, le=4)
    password_check_hibp: bool = Field(
        default=True,
        description="Consult HaveIBeenPwned k-anonymity API to reject leaked passwords.",
    )
    hibp_api_url: str = "https://api.pwnedpasswords.com/range"
    hibp_timeout_seconds: float = Field(default=2.0, gt=0.0)

    # Lockout ladder — progressive, matches the document
    lockout_threshold_soft: int = Field(default=5, ge=1)
    lockout_duration_soft_minutes: int = Field(default=15, ge=1)
    lockout_threshold_hard: int = Field(default=10, ge=2)
    lockout_duration_hard_minutes: int = Field(default=60, ge=1)
    lockout_threshold_permanent: int = Field(default=20, ge=3)

    # TOTP
    totp_issuer: str = Field(default="Axon Enterprise")
    totp_digits: int = Field(default=6, ge=6, le=8)
    totp_interval_seconds: int = Field(default=30, ge=15)
    totp_verification_window: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Accept codes from N intervals before and after. 1 = ±30s tolerance.",
    )

    # Session policy
    session_inactivity_ttl_hours: int = Field(default=24, ge=1)
    session_absolute_ttl_days: int = Field(default=30, ge=1)
    session_refresh_token_bytes: int = Field(default=64, ge=32)


JwtSignerBackend = Literal["local", "kms"]


class JwtSettings(BaseSettings):
    """JWT issuance + JWKS rotation configuration.

    Two signing backends are supported:

    - ``local`` — an RSA private key loaded from
      ``AXON_JWT_LOCAL_PRIVATE_KEY_PEM``. Dev/test only.
    - ``kms`` — ``kms:Sign`` calls against a KMS key. Private material
      never leaves the HSM. Production.

    The ``iss`` claim is ``AXON_JWT_ISSUER`` — must match what the
    Rust runtime has configured in its JWT verifier.
    """

    model_config = SettingsConfigDict(
        env_prefix="AXON_JWT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Signer
    signer_backend: JwtSignerBackend = "kms"
    # ``kms`` backend
    kms_region: str | None = None
    # ``local`` backend
    local_private_key_pem: SecretStr | None = Field(
        default=None,
        description="PEM-encoded RSA private key. Required when signer_backend='local'.",
    )

    # Emission
    issuer: str = Field(
        default="https://auth.bemarking.com",
        description="Value of the `iss` claim. Must match what Rust verifies.",
    )
    audience: str = Field(
        default="axon-api",
        description="Value of the `aud` claim.",
    )
    access_token_ttl_seconds: int = Field(default=3600, ge=60)  # 1 hour
    algorithm: str = Field(
        default="RS256",
        pattern=r"^(RS256|RS384|RS512)$",
        description="Signing algorithm. HS* and ES* intentionally disallowed here.",
    )

    # Rotation policy
    rotation_grace_days: int = Field(
        default=7,
        ge=1,
        description="Overlap window where the previous key is still valid for verification.",
    )
    rotation_active_max_days: int = Field(
        default=90,
        ge=7,
        description="Maximum age of an active signing key before rotation is forced.",
    )

    # Revocation
    revocation_backend: Literal["memory", "redis", "postgres"] = "postgres"
    redis_url: SecretStr | None = Field(
        default=None,
        description="Required when revocation_backend='redis'.",
    )

    # JWKS endpoint behaviour
    jwks_cache_control_seconds: int = Field(default=600, ge=60)


class SsoSettings(BaseSettings):
    """SSO / identity federation configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AXON_SSO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Discovery + JWKS caching
    discovery_ttl_seconds: int = Field(default=3600, ge=60)
    jwks_ttl_seconds: int = Field(default=600, ge=60)
    jwks_force_refresh_on_kid_miss: bool = True

    # Flow timeouts
    state_ttl_seconds: int = Field(default=600, ge=30)
    clock_skew_seconds: int = Field(default=60, ge=0, le=300)

    # HTTP client
    http_timeout_seconds: float = Field(default=10.0, gt=0.0)
    http_retries: int = Field(default=2, ge=0, le=5)

    # Auto-provisioning
    auto_provision_default: bool = True
    auto_provision_rate_limit_per_minute: int = Field(
        default=30,
        ge=1,
        description="Max new-user provisions per minute per (tenant, provider).",
    )

    # Callback / redirect URI pattern used by metadata + AuthnRequest
    base_url: str = Field(
        default="https://auth.bemarking.com",
        description="External URL of the auth service, used to build "
        "redirect/ACS URIs. Must match what the IdP is configured with.",
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
    envelope: EnvelopeSettings = Field(default_factory=EnvelopeSettings)  # type: ignore[arg-type]
    identity: IdentitySettings = Field(default_factory=IdentitySettings)  # type: ignore[arg-type]
    sso: SsoSettings = Field(default_factory=SsoSettings)  # type: ignore[arg-type]
    jwt: JwtSettings = Field(default_factory=JwtSettings)  # type: ignore[arg-type]

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
        """Production-only safety gates."""
        if self.env is Environment.PRODUCTION:
            if self.db.ssl_mode in ("disable", "allow", "prefer"):
                raise ValueError(
                    "db.ssl_mode must be 'require' or stronger in production"
                )
            if self.db.echo_sql:
                raise ValueError("db.echo_sql must be False in production")
            if self.envelope.backend == "local":
                raise ValueError(
                    "envelope.backend='local' is not allowed in production; "
                    "use 'kms' for compliant at-rest encryption of TOTP secrets "
                    "and other sensitive fields."
                )
            if self.envelope.backend == "kms" and not self.envelope.kms_key_id:
                raise ValueError("envelope.kms_key_id required when backend='kms'")
        if self.envelope.backend == "local" and self.envelope.local_key is None:
            raise ValueError(
                "envelope.local_key required when backend='local'; "
                "generate one via `python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'`"
            )
        # JWT signer validation
        if self.env is Environment.PRODUCTION:
            if self.jwt.signer_backend == "local":
                raise ValueError(
                    "jwt.signer_backend='local' is not allowed in production; "
                    "use 'kms' so private keys never leave the HSM."
                )
            if self.jwt.revocation_backend == "memory":
                raise ValueError(
                    "jwt.revocation_backend='memory' is not durable and is "
                    "rejected in production. Use 'postgres' or 'redis'."
                )
        if self.jwt.signer_backend == "local" and self.jwt.local_private_key_pem is None:
            raise ValueError(
                "jwt.local_private_key_pem required when signer_backend='local'"
            )
        if self.jwt.revocation_backend == "redis" and self.jwt.redis_url is None:
            raise ValueError(
                "jwt.redis_url required when revocation_backend='redis'"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once and cache. Tests call ``get_settings.cache_clear()``."""
    return Settings()  # type: ignore[call-arg]
