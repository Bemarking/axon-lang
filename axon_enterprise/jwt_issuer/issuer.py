"""JwtIssuer — mint signed access tokens with the currently active key.

The issuer builds the header + claims from a ``PrincipalContext``
(tenant_id + roles) plus lifetime settings, computes the signing
input (``b64url(header).b64url(claims)``), hands the bytes to the
active ``Signer`` (either KMS or local), and emits the canonical
three-part JWT string.

Token shape
-----------

    Header:  {"alg": "RS256", "typ": "JWT", "kid": "<active-kid>"}
    Claims:  {
      "iss": "https://auth.bemarking.com",
      "sub": "user:<uuid>",
      "aud": "axon-api",
      "tenant_id": "<tenant>",
      "plan": "<plan>",
      "roles": ["admin", "developer"],
      "exp": <unix ts>,
      "iat": <unix ts>,
      "nbf": <unix ts>,
      "jti": "<uuid>"
    }

Claims are ordered by the JSON encoder (sort_keys=True) so two calls
with the same inputs produce byte-identical output before signing —
useful for reproducible test fixtures.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.identity.principal import PrincipalContext
from axon_enterprise.jwt_issuer.key_management import (
    KeyManagementService,
    load_signer_for_row,
)
from axon_enterprise.jwt_issuer.local_signer import b64url_no_pad
from axon_enterprise.jwt_issuer.signer import Signer

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.jwt_issuer.issuer"
)


@dataclass(frozen=True)
class IssuedJwt:
    """What ``JwtIssuer.mint`` returns — the token plus its metadata."""

    token: str
    jti: UUID
    kid: str
    expires_at: datetime


@dataclass
class JwtIssuer:
    """Produces signed JWTs for authenticated principals."""

    key_management: KeyManagementService
    settings: JwtSettings

    @classmethod
    def default(cls) -> JwtIssuer:
        return cls(
            key_management=KeyManagementService(),
            settings=get_settings().jwt,
        )

    # ── Mint ──────────────────────────────────────────────────────────

    async def mint(
        self,
        db: AsyncSession,
        *,
        principal: PrincipalContext,
        plan: str | None = None,
        ttl_seconds: int | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> IssuedJwt:
        """Emit a JWT for ``principal``.

        ``extra_claims`` is passed through unchanged; reserved names
        (iss/sub/aud/exp/iat/nbf/jti/tenant_id/roles/plan) are
        overwritten by the issuer even if the caller supplies them,
        so callers can't silently impersonate a tenant.
        """
        row = await self.key_management.get_active(db)
        signer: Signer = await load_signer_for_row(row, settings=self.settings)

        now = int(time.time())
        ttl = ttl_seconds or self.settings.access_token_ttl_seconds
        exp = now + ttl
        jti = uuid.uuid4()

        header = {"alg": signer.info.algorithm, "typ": "JWT", "kid": signer.info.kid}
        claims: dict[str, Any] = dict(extra_claims or {})
        claims.update(
            {
                "iss": self.settings.issuer,
                "sub": f"user:{principal.user_id}",
                "aud": self.settings.audience,
                "tenant_id": principal.tenant_id,
                "plan": plan or "enterprise",
                "roles": sorted(principal.role_names),
                "iat": now,
                "nbf": now,
                "exp": exp,
                "jti": str(jti),
            }
        )

        signing_input = (
            _b64url_json(header).encode("ascii")
            + b"."
            + _b64url_json(claims).encode("ascii")
        )
        signature = signer.sign(signing_input)
        token = signing_input.decode("ascii") + "." + b64url_no_pad(signature)

        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        _logger.info(
            "jwt_minted",
            kid=signer.info.kid,
            sub=f"user:{principal.user_id}",
            tenant_id=principal.tenant_id,
            jti=str(jti),
            exp=exp,
        )
        return IssuedJwt(token=token, jti=jti, kid=signer.info.kid, expires_at=expires_at)


def _b64url_json(obj: dict[str, Any]) -> str:
    """Canonical JSON → urlsafe-base64 without padding."""
    raw = json.dumps(
        obj,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
