"""ID token signature + claims validation.

Separated from the OIDC provider orchestration so the check can be
unit-tested with a stubbed ``JwksClient``.

Steps
-----
1. Decode (without verifying) to read ``kid`` and the raw claims.
2. Fetch the matching key from JWKS.
3. Verify the signature against the declared ``alg``. We allow only
   RS256/384/512 and ES256/384/512 — ``alg=none`` is explicitly
   rejected (the `jwt` library does this, but we belt-and-suspenders
   anyway).
4. Verify claims:
    - ``iss``            matches the configured issuer
    - ``aud``            contains the configured client_id
    - ``exp``            in the future (with configurable clock skew)
    - ``nbf`` (optional) in the past (with skew)
    - ``iat``            within a sensible window (``iat <= now + skew``)
    - ``nonce``          matches the ``nonce`` we stored at initiate()
5. ``email_verified`` — OIDC providers may omit this; when absent we
   treat the email as unverified and raise ``OidcEmailNotVerified``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
import structlog
from jwt.exceptions import InvalidTokenError

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.errors import (
    OidcEmailNotVerified,
    OidcIdTokenInvalid,
    OidcNonceMismatch,
)
from axon_enterprise.sso.oidc_jwks import JwksClient

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.sso.oidc_id_token"
)

# Only RS* and ES* families allowed. HS256 and "none" are explicitly
# rejected; the first would require sharing a symmetric secret with
# every IdP (wrong for multi-tenant), the second is an outright attack.
ACCEPTED_ALGS: frozenset[str] = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
)


@dataclass(frozen=True)
class ValidatedIdToken:
    """Decoded + validated claims + ``email_verified`` already true."""

    subject: str           # ``sub`` claim
    email: str
    email_verified: bool
    claims: dict[str, Any]

    @property
    def display_name(self) -> str | None:
        return self.claims.get("name") or self.claims.get("preferred_username")


@dataclass
class IdTokenValidator:
    """Validates OIDC ID tokens against a configured issuer + audience."""

    jwks: JwksClient
    settings: SsoSettings

    @classmethod
    def build(cls, *, jwks: JwksClient | None = None) -> IdTokenValidator:
        return cls(jwks=jwks or JwksClient.build(), settings=get_settings().sso)

    async def validate(
        self,
        *,
        id_token: str,
        issuer: str,
        audience: str,
        jwks_uri: str,
        expected_nonce: str | None,
        allowed_algs: frozenset[str] | None = None,
    ) -> ValidatedIdToken:
        """Signature + claims + nonce + email_verified check."""
        allowed = allowed_algs or ACCEPTED_ALGS

        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except InvalidTokenError as exc:
            raise OidcIdTokenInvalid(f"malformed ID token header: {exc}") from exc

        alg = unverified_header.get("alg")
        kid = unverified_header.get("kid")
        if not alg or alg not in allowed:
            raise OidcIdTokenInvalid(
                f"unsupported alg={alg!r}; expected one of {sorted(allowed)}"
            )
        if not kid:
            raise OidcIdTokenInvalid("ID token header missing 'kid'")

        key_entry = await self.jwks.get_key(jwks_uri=jwks_uri, kid=kid)
        # Soft-assert the key alg matches the token alg. Some IdPs
        # publish unannotated keys (alg absent from JWK) — in that
        # case we trust the token alg alone.
        if key_entry.alg and key_entry.alg != alg:
            # This can happen when IdPs publish multi-alg keys; we
            # log but still trust the token alg as long as it's in
            # our allow-list. Additional defence against a downgrade
            # would require tenant-level alg pinning (future).
            _logger.info(
                "oidc_alg_key_mismatch",
                token_alg=alg,
                key_alg=key_entry.alg,
                kid=kid,
            )

        # Signature + expiry (jwt handles exp/nbf/iat with leeway).
        try:
            claims = jwt.decode(
                id_token,
                key_entry.key,
                algorithms=[alg],
                audience=audience,
                issuer=issuer,
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
                leeway=self.settings.clock_skew_seconds,
            )
        except InvalidTokenError as exc:
            raise OidcIdTokenInvalid(f"ID token invalid: {exc}") from exc

        # Nonce binding: if we set a nonce at initiate() time, it MUST
        # match. Unset = provider config did not request a nonce (rare
        # but allowed — 3-legged flows without implicit grant).
        if expected_nonce is not None:
            actual = claims.get("nonce")
            if actual != expected_nonce:
                raise OidcNonceMismatch(
                    f"expected nonce={expected_nonce!r}, got {actual!r}"
                )

        # Defensive `iat <= now + skew` — jwt doesn't fail on iat in
        # the future by default.
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat > time.time() + self.settings.clock_skew_seconds:
            raise OidcIdTokenInvalid(
                f"iat {iat} is in the future (clock skew > {self.settings.clock_skew_seconds}s)"
            )

        email = claims.get("email")
        if not email:
            raise OidcIdTokenInvalid("ID token missing 'email' claim")
        email_verified = bool(claims.get("email_verified"))
        if not email_verified:
            raise OidcEmailNotVerified(email)

        return ValidatedIdToken(
            subject=str(claims.get("sub")),
            email=str(email).lower(),
            email_verified=email_verified,
            claims=claims,
        )
