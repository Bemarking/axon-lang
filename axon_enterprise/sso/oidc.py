"""OIDC provider — orchestrates discovery, PKCE, state, token exchange,
and ID token validation.

Public surface
--------------
    OidcProvider.initiate(tenant_id, return_url)  → (authorization_url, stored_state)
    OidcProvider.complete(tenant_id, state, code) → ValidatedIdToken

Replaces the v1.0.0 scaffolding (every method a ``TODO``) with a
signature-verifying implementation. Token exchange uses ``httpx``;
signature verification uses ``PyJWT`` against the live JWKS via
``JwksClient``; replay defence is enforced in ``SsoStateService``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.configurations import (
    ResolvedSsoConfiguration,
    SsoConfigurationService,
)
from axon_enterprise.sso.errors import (
    OidcTokenExchangeError,
    SsoConfigurationInvalid,
)
from axon_enterprise.sso.models import SsoProviderType
from axon_enterprise.sso.oidc_discovery import OidcDiscoverer, OidcMetadata
from axon_enterprise.sso.oidc_id_token import IdTokenValidator, ValidatedIdToken
from axon_enterprise.sso.oidc_jwks import JwksClient
from axon_enterprise.sso.oidc_pkce import (
    compute_code_challenge,
    generate_code_verifier,
)
from axon_enterprise.sso.state import SsoStateService, StoredState

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.sso.oidc")


@dataclass(frozen=True)
class InitiateResult:
    """Outcome of ``OidcProvider.initiate`` — what handlers return to the browser."""

    authorization_url: str
    state_id: str
    expires_at_seconds: int  # TTL the caller can mirror into a cookie


@dataclass
class OidcProvider:
    """OIDC orchestrator bound to a discovery + JWKS cache pair."""

    discoverer: OidcDiscoverer
    jwks: JwksClient
    validator: IdTokenValidator
    config_store: SsoConfigurationService
    state_service: SsoStateService
    http_client: httpx.AsyncClient
    settings: SsoSettings

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def build(cls) -> OidcProvider:
        settings = get_settings().sso
        discoverer = OidcDiscoverer.build(settings=settings)
        jwks = JwksClient.build(settings=settings)
        validator = IdTokenValidator(jwks=jwks, settings=settings)
        http_client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "axon-enterprise"},
        )
        return cls(
            discoverer=discoverer,
            jwks=jwks,
            validator=validator,
            config_store=SsoConfigurationService.default(),
            state_service=SsoStateService(settings=settings),
            http_client=http_client,
            settings=settings,
        )

    async def aclose(self) -> None:
        await self.http_client.aclose()
        await self.discoverer.aclose()
        await self.jwks.aclose()

    # ── Initiate ──────────────────────────────────────────────────────

    async def initiate(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        return_url: str | None = None,
    ) -> InitiateResult:
        """Build the authorization URL and persist the state record."""
        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.OIDC
        )
        metadata = await self.discoverer.metadata(config.payload["issuer"])

        nonce = secrets.token_urlsafe(32)
        verifier = generate_code_verifier()
        challenge = compute_code_challenge(verifier)

        stored = await self.state_service.create(
            db,
            tenant_id=tenant_id,
            provider_type=SsoProviderType.OIDC,
            nonce=nonce,
            code_verifier=verifier,
            return_url=return_url,
            issuer=metadata.issuer,
        )

        scopes = config.payload.get("scopes") or ["openid", "email", "profile"]
        params: dict[str, Any] = {
            "response_type": "code",
            "client_id": config.payload["client_id"],
            "redirect_uri": config.payload["redirect_uri"],
            "scope": " ".join(scopes),
            "state": stored.state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        url = f"{metadata.authorization_endpoint}?{urlencode(params)}"
        return InitiateResult(
            authorization_url=url,
            state_id=str(stored.state_id),
            expires_at_seconds=self.settings.state_ttl_seconds,
        )

    # ── Complete ──────────────────────────────────────────────────────

    async def complete(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        state: str,
        code: str,
    ) -> ValidatedIdToken:
        """Exchange ``code`` for tokens, validate the ID token, return claims."""
        stored: StoredState = await self.state_service.consume(
            db, tenant_id=tenant_id, state=state
        )
        if stored.provider_type is not SsoProviderType.OIDC:
            raise SsoConfigurationInvalid(
                f"state {state} was created for {stored.provider_type.value}, not oidc"
            )

        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.OIDC
        )
        metadata = await self.discoverer.metadata(config.payload["issuer"])
        tokens = await self._exchange(
            metadata=metadata,
            config=config,
            code=code,
            code_verifier=stored.code_verifier or "",
        )
        id_token = tokens.get("id_token")
        if not id_token:
            raise OidcTokenExchangeError("token response missing id_token")

        validated = await self.validator.validate(
            id_token=id_token,
            issuer=metadata.issuer,
            audience=config.payload["client_id"],
            jwks_uri=metadata.jwks_uri,
            expected_nonce=stored.nonce,
        )
        _logger.info(
            "oidc_login_success",
            tenant_id=tenant_id,
            issuer=metadata.issuer,
            subject=validated.subject,
        )
        return validated

    # ── Internals ─────────────────────────────────────────────────────

    async def _exchange(
        self,
        *,
        metadata: OidcMetadata,
        config: ResolvedSsoConfiguration,
        code: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.payload["redirect_uri"],
            "client_id": config.payload["client_id"],
            "code_verifier": code_verifier,
        }
        # ``client_secret`` — public OIDC clients can skip this;
        # confidential clients require it.
        if config.payload.get("client_secret"):
            data["client_secret"] = config.payload["client_secret"]

        try:
            resp = await self.http_client.post(
                metadata.token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OidcTokenExchangeError(f"network error: {exc}") from exc

        if resp.status_code != 200:
            raise OidcTokenExchangeError(
                f"token endpoint returned HTTP {resp.status_code}: "
                f"{resp.text[:200]!r}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise OidcTokenExchangeError("token response not JSON") from exc
        return payload
