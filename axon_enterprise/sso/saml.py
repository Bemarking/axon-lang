"""SAML 2.0 provider — thin wrapper over ``python3-saml``.

Replaces the v1.0.0 scaffolding (``return None`` for every method).

Responsibilities
----------------
- Build a per-tenant ``python3-saml`` settings dict from a
  ``ResolvedSsoConfiguration`` payload.
- Expose ``initiate`` / ``complete`` with the same shape as
  ``OidcProvider`` so ``SsoService`` can treat both uniformly.
- Defend against assertion replay via ``SsoAssertionSeen``.

The heavy lifting (XML signature verification, NotBefore/NotOnOrAfter,
Audience / Destination / InResponseTo checks) is delegated to
``python3-saml``; this module wires configuration + state + replay.

Import discipline
-----------------
``python3-saml`` is imported lazily so the rest of the SSO module
(OIDC + tests) works on environments where ``xmlsec`` / ``libxml2``
are not installed. Importing ``SamlProvider`` from this module does
NOT trigger the underlying import; that happens only when a caller
invokes ``build()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import structlog
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.configurations import (
    ResolvedSsoConfiguration,
    SsoConfigurationService,
)
from axon_enterprise.sso.errors import (
    SamlAssertionReplay,
    SamlResponseInvalid,
    SsoConfigurationInvalid,
)
from axon_enterprise.sso.models import (
    SsoAssertionSeen,
    SsoProviderType,
)
from axon_enterprise.sso.state import SsoStateService, StoredState

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.sso.saml")


@dataclass(frozen=True)
class SamlInitiateResult:
    """Outcome of ``SamlProvider.initiate`` — redirect the browser to ``redirect_url``."""

    redirect_url: str
    state_id: str


@dataclass(frozen=True)
class SamlAssertion:
    """Validated SAML assertion attributes extracted from the IdP response."""

    subject_nameid: str
    attributes: dict[str, list[str]]

    @property
    def email(self) -> str:
        # SAML lets attribute names vary wildly by IdP; attribute_map
        # in the SsoConfiguration handles the translation. Here we
        # expose a convenience when the canonical ``email`` attribute
        # was populated by the mapper.
        vals = self.attributes.get("email") or self.attributes.get("emailaddress")
        if not vals:
            raise SamlResponseInvalid("no email attribute in SAML assertion")
        return vals[0].lower()

    def first(self, key: str) -> str | None:
        vals = self.attributes.get(key)
        return vals[0] if vals else None


@dataclass
class SamlProvider:
    """SAML 2.0 login orchestrator."""

    config_store: SsoConfigurationService
    state_service: SsoStateService
    settings: SsoSettings

    @classmethod
    def build(cls) -> SamlProvider:
        s = get_settings().sso
        return cls(
            config_store=SsoConfigurationService.default(),
            state_service=SsoStateService(settings=s),
            settings=s,
        )

    # ── Initiate ──────────────────────────────────────────────────────

    async def initiate(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        return_url: str | None = None,
    ) -> SamlInitiateResult:
        """Generate a signed AuthnRequest and return the redirect URL."""
        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.SAML
        )
        auth = self._build_auth(config, request_data=_fake_request_data(config))
        # Persist our own state so we can correlate the response.
        stored = await self.state_service.create(
            db,
            tenant_id=tenant_id,
            provider_type=SsoProviderType.SAML,
            return_url=return_url,
        )
        redirect_url = auth.login(
            return_to=stored.state,  # carried through RelayState
            set_nameid_policy=True,
        )
        return SamlInitiateResult(
            redirect_url=redirect_url, state_id=str(stored.state_id)
        )

    # ── Complete ──────────────────────────────────────────────────────

    async def complete(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        saml_response_b64: str,
        relay_state: str,
    ) -> SamlAssertion:
        """Process a SAML response POSTed to the ACS endpoint."""
        stored: StoredState = await self.state_service.consume(
            db, tenant_id=tenant_id, state=relay_state
        )
        if stored.provider_type is not SsoProviderType.SAML:
            raise SsoConfigurationInvalid(
                f"state {relay_state} belongs to {stored.provider_type.value}, not saml"
            )

        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.SAML
        )
        request_data = _fake_request_data(config, saml_response_b64=saml_response_b64)
        auth = self._build_auth(config, request_data=request_data)
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            reason = auth.get_last_error_reason() or "unknown SAML error"
            raise SamlResponseInvalid(f"{errors}: {reason}")
        if not auth.is_authenticated():
            raise SamlResponseInvalid("SAML response did not authenticate")

        assertion_id = auth.get_last_assertion_id()
        if not assertion_id:
            raise SamlResponseInvalid("SAML response missing assertion ID")

        await self._record_assertion_or_replay(
            db, tenant_id=tenant_id, assertion_id=assertion_id
        )

        return SamlAssertion(
            subject_nameid=str(auth.get_nameid() or ""),
            attributes={
                k: [str(v) for v in vs]
                for k, vs in (auth.get_attributes() or {}).items()
            },
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _build_auth(
        self,
        config: ResolvedSsoConfiguration,
        *,
        request_data: dict[str, Any],
    ):
        """Instantiate ``OneLogin_Saml2_Auth``. Lazy-imports python3-saml."""
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise SamlResponseInvalid(
                "python3-saml (+ xmlsec1 / libxml2) is required for SAML. "
                "Install via `pip install 'axon-enterprise[saml]'`"
            ) from exc

        return OneLogin_Saml2_Auth(request_data, _to_saml_settings(config))

    async def _record_assertion_or_replay(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        assertion_id: str,
    ) -> None:
        row = SsoAssertionSeen(
            tenant_id=tenant_id,
            assertion_id=assertion_id,
        )
        db.add(row)
        try:
            await db.flush()
        except SAIntegrityError as exc:
            await db.rollback()
            _logger.warning(
                "saml_assertion_replay",
                tenant_id=tenant_id,
                assertion_id=assertion_id,
            )
            raise SamlAssertionReplay(assertion_id) from exc


# ── Helpers ───────────────────────────────────────────────────────────


def _to_saml_settings(config: ResolvedSsoConfiguration) -> dict[str, Any]:
    """Convert a ``ResolvedSsoConfiguration`` to the python3-saml shape."""
    p = config.payload
    sp = {
        "entityId": p["sp_entity_id"],
        "assertionConsumerService": {
            "url": p["sp_acs_url"],
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        "NameIDFormat": p.get(
            "name_id_format",
            "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        ),
    }
    if p.get("sp_private_key"):
        sp["privateKey"] = p["sp_private_key"]
    if p.get("sp_x509_cert"):
        sp["x509cert"] = p["sp_x509_cert"]
    if p.get("sp_slo_url"):
        sp["singleLogoutService"] = {
            "url": p["sp_slo_url"],
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    idp = {
        "entityId": p["idp_entity_id"],
        "singleSignOnService": {
            "url": p["idp_sso_url"],
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        },
        "x509cert": p["idp_x509_cert"],
    }
    if p.get("idp_slo_url"):
        idp["singleLogoutService"] = {
            "url": p["idp_slo_url"],
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    security = {
        "authnRequestsSigned": bool(p.get("sp_private_key")),
        "wantAssertionsSigned": True,
        "wantMessagesSigned": p.get("want_messages_signed", False),
        "wantAssertionsEncrypted": p.get("want_assertions_encrypted", False),
        "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
    }

    return {"strict": True, "debug": False, "sp": sp, "idp": idp, "security": security}


def _fake_request_data(
    config: ResolvedSsoConfiguration,
    *,
    saml_response_b64: str | None = None,
) -> dict[str, Any]:
    """python3-saml expects the inbound request as a dict; we synthesize it."""
    parsed = urlsplit(config.payload["sp_acs_url"])
    request_data: dict[str, Any] = {
        "https": "on" if parsed.scheme == "https" else "off",
        "http_host": parsed.netloc,
        "script_name": parsed.path,
        "get_data": {},
        "post_data": {},
        "server_port": "443" if parsed.scheme == "https" else "80",
        # Used by python3-saml as the "received at" URL — must match ACS.
        "request_uri": parsed.path,
    }
    if saml_response_b64:
        request_data["post_data"]["SAMLResponse"] = saml_response_b64
    return request_data


# ── Audit hook for cleanup ────────────────────────────────────────────


async def purge_assertion_seen(
    db: AsyncSession, *, older_than_seconds: int = 48 * 3600
) -> int:
    """Delete ``SsoAssertionSeen`` rows older than the replay window.

    Call from a cron job. Default window is 48h — comfortably past the
    typical maximum SAML ``SessionNotOnOrAfter``.
    """
    from datetime import timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    res = await db.execute(
        delete(SsoAssertionSeen).where(SsoAssertionSeen.created_at < cutoff)
    )
    await db.flush()
    return int(res.rowcount or 0)
