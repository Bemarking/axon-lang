"""SsoConfigurationService — envelope-encrypted CRUD for per-tenant IdP configs.

The ``config_encrypted`` column is the single point where sensitive
IdP material lives at rest. The AAD binds the ciphertext to
``{tenant_id, provider_type, purpose="sso_config"}`` so a ciphertext
from tenant A cannot be reused for tenant B, and a row's OIDC
ciphertext cannot be smuggled into the SAML slot.

Config shapes
-------------
OIDC::
    {
        "issuer": "https://accounts.google.com",
        "client_id": "...",
        "client_secret": "...",
        "scopes": ["openid", "email", "profile"],
        "redirect_uri": "https://auth.bemarking.com/sso/{tenant}/oidc/callback"
    }

SAML::
    {
        "idp_entity_id": "https://idp.example.com",
        "idp_sso_url": "https://idp.example.com/sso",
        "idp_slo_url": "https://idp.example.com/slo",
        "idp_x509_cert": "-----BEGIN CERTIFICATE-----...",
        "sp_entity_id": "https://auth.bemarking.com/sso/{tenant}/saml/metadata",
        "sp_acs_url":   "https://auth.bemarking.com/sso/{tenant}/saml/acs",
        "sp_private_key": "-----BEGIN PRIVATE KEY-----...",
        "sp_x509_cert":   "-----BEGIN CERTIFICATE-----..."
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.crypto import AAD, EnvelopeEncryption, get_envelope
from axon_enterprise.sso.errors import (
    SsoConfigurationInvalid,
    SsoConfigurationNotFound,
    SsoProviderDisabled,
)
from axon_enterprise.sso.models import SsoConfiguration, SsoProviderType

_PURPOSE: Final[str] = "sso_config"


@dataclass(frozen=True)
class ResolvedSsoConfiguration:
    """Decrypted + parsed SSO configuration ready to hand to a provider."""

    config_id: Any  # UUID — kept generic to avoid import cycles
    tenant_id: str
    provider_type: SsoProviderType
    payload: dict[str, Any]
    attribute_map: dict[str, str]
    role_map: dict[str, str]
    auto_provision: bool
    default_role_id: Any | None
    enabled: bool


@dataclass(frozen=True)
class SsoConfigurationService:
    """CRUD with transparent envelope encryption.

    Writes validate the payload shape against the provider; reads
    return the decrypted ``ResolvedSsoConfiguration`` or raise.
    """

    envelope: EnvelopeEncryption

    @classmethod
    def default(cls) -> SsoConfigurationService:
        return cls(envelope=get_envelope())

    # ── AAD helper ────────────────────────────────────────────────────

    def _aad(self, tenant_id: str, provider_type: SsoProviderType) -> AAD:
        return {
            "tenant_id": tenant_id,
            "provider_type": provider_type.value,
            "purpose": _PURPOSE,
        }

    # ── Upsert ────────────────────────────────────────────────────────

    async def upsert(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_type: SsoProviderType,
        payload: dict[str, Any],
        attribute_map: dict[str, str] | None = None,
        role_map: dict[str, str] | None = None,
        auto_provision: bool = False,
        default_role_id: Any | None = None,
        enabled: bool = True,
    ) -> SsoConfiguration:
        """Create or replace the configuration for (tenant_id, provider_type).

        Raises ``SsoConfigurationInvalid`` if ``payload`` is missing
        required fields for the selected provider.
        """
        self._validate_payload(provider_type, payload)

        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        ciphertext = self.envelope.encrypt(
            encoded, self._aad(tenant_id, provider_type)
        )

        row = await db.scalar(
            select(SsoConfiguration).where(
                SsoConfiguration.tenant_id == tenant_id,
                SsoConfiguration.provider_type == provider_type.value,
            )
        )
        if row is None:
            row = SsoConfiguration(
                tenant_id=tenant_id,
                provider_type=provider_type.value,
                config_encrypted=ciphertext,
                attribute_map=attribute_map or {},
                role_map=role_map or {},
                auto_provision=auto_provision,
                default_role_id=default_role_id,
                enabled=enabled,
            )
            db.add(row)
        else:
            row.config_encrypted = ciphertext
            row.attribute_map = attribute_map or {}
            row.role_map = role_map or {}
            row.auto_provision = auto_provision
            row.default_role_id = default_role_id
            row.enabled = enabled
        await db.flush()
        return row

    # ── Load ──────────────────────────────────────────────────────────

    async def get(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_type: SsoProviderType,
    ) -> ResolvedSsoConfiguration:
        row = await db.scalar(
            select(SsoConfiguration).where(
                SsoConfiguration.tenant_id == tenant_id,
                SsoConfiguration.provider_type == provider_type.value,
            )
        )
        if row is None:
            raise SsoConfigurationNotFound(
                f"{tenant_id}/{provider_type.value}"
            )
        if not row.enabled:
            raise SsoProviderDisabled(
                f"{tenant_id}/{provider_type.value}"
            )
        plaintext = self.envelope.decrypt(
            row.config_encrypted, self._aad(tenant_id, provider_type)
        )
        payload = json.loads(plaintext.decode("utf-8"))
        return ResolvedSsoConfiguration(
            config_id=row.sso_config_id,
            tenant_id=tenant_id,
            provider_type=provider_type,
            payload=payload,
            attribute_map=dict(row.attribute_map),
            role_map=dict(row.role_map),
            auto_provision=row.auto_provision,
            default_role_id=row.default_role_id,
            enabled=row.enabled,
        )

    # ── Delete ────────────────────────────────────────────────────────

    async def delete(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_type: SsoProviderType,
    ) -> None:
        row = await db.scalar(
            select(SsoConfiguration).where(
                SsoConfiguration.tenant_id == tenant_id,
                SsoConfiguration.provider_type == provider_type.value,
            )
        )
        if row is not None:
            await db.delete(row)
            await db.flush()

    # ── Validation ────────────────────────────────────────────────────

    @staticmethod
    def _validate_payload(
        provider_type: SsoProviderType, payload: dict[str, Any]
    ) -> None:
        """Minimal shape validation.

        Deliberately conservative — only fields we read later are
        required. Operators can extend the payload with extra fields
        and the service does not reject them.
        """
        if provider_type is SsoProviderType.OIDC:
            required = {"issuer", "client_id", "client_secret", "redirect_uri"}
        elif provider_type is SsoProviderType.SAML:
            required = {
                "idp_entity_id",
                "idp_sso_url",
                "idp_x509_cert",
                "sp_entity_id",
                "sp_acs_url",
            }
        else:  # pragma: no cover - enum guarantees coverage
            raise SsoConfigurationInvalid(f"unknown provider {provider_type}")

        missing = required.difference(payload.keys())
        if missing:
            raise SsoConfigurationInvalid(
                f"missing required fields for {provider_type.value}: "
                f"{sorted(missing)}"
            )
