"""ID token validation against a stubbed JWKS.

Uses a locally-generated RSA key to sign fixture ID tokens; a fake
``JwksClient`` returns the matching public key. No network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from axon_enterprise.config import SsoSettings
from axon_enterprise.sso.errors import (
    OidcEmailNotVerified,
    OidcIdTokenInvalid,
    OidcNonceMismatch,
)
from axon_enterprise.sso.oidc_id_token import IdTokenValidator
from axon_enterprise.sso.oidc_jwks import PublicKeyEntry


@dataclass
class _StubJwks:
    kid: str
    public_key: object

    async def get_key(self, *, jwks_uri: str, kid: str) -> PublicKeyEntry:
        if kid != self.kid:
            raise AssertionError(f"test only knows kid={self.kid!r}, got {kid!r}")
        return PublicKeyEntry(kid=kid, alg="RS256", key=self.public_key)


@pytest.fixture(scope="module")
def rsa_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture
def validator(rsa_keys) -> IdTokenValidator:
    _, pub = rsa_keys
    return IdTokenValidator(
        jwks=_StubJwks(kid="k1", public_key=pub),  # type: ignore[arg-type]
        settings=SsoSettings(clock_skew_seconds=30),
    )


def _sign(rsa_keys, claims: dict, *, kid: str = "k1", alg: str = "RS256") -> str:
    priv, _ = rsa_keys
    return jwt.encode(claims, priv, algorithm=alg, headers={"kid": kid})


def _base_claims(**over) -> dict:
    now = int(time.time())
    base = {
        "iss": "https://idp.test",
        "aud": "client-abc",
        "sub": "user-42",
        "email": "alice@example.com",
        "email_verified": True,
        "nonce": "nonce-xyz",
        "iat": now,
        "exp": now + 300,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_happy_path(rsa_keys, validator: IdTokenValidator) -> None:
    token = _sign(rsa_keys, _base_claims())
    result = await validator.validate(
        id_token=token,
        issuer="https://idp.test",
        audience="client-abc",
        jwks_uri="https://idp.test/jwks",
        expected_nonce="nonce-xyz",
    )
    assert result.email == "alice@example.com"
    assert result.email_verified


@pytest.mark.asyncio
async def test_wrong_issuer_rejected(rsa_keys, validator) -> None:
    token = _sign(rsa_keys, _base_claims(iss="https://attacker.test"))
    with pytest.raises(OidcIdTokenInvalid):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_wrong_audience_rejected(rsa_keys, validator) -> None:
    token = _sign(rsa_keys, _base_claims(aud="client-hacker"))
    with pytest.raises(OidcIdTokenInvalid):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_expired_rejected(rsa_keys, validator) -> None:
    now = int(time.time())
    token = _sign(rsa_keys, _base_claims(exp=now - 1000, iat=now - 2000))
    with pytest.raises(OidcIdTokenInvalid):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_nonce_mismatch_rejected(rsa_keys, validator) -> None:
    token = _sign(rsa_keys, _base_claims(nonce="attacker-nonce"))
    with pytest.raises(OidcNonceMismatch):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_email_not_verified_rejected(rsa_keys, validator) -> None:
    token = _sign(rsa_keys, _base_claims(email_verified=False))
    with pytest.raises(OidcEmailNotVerified):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_alg_none_rejected(rsa_keys, validator) -> None:
    # Forge a token with alg=none (unsigned) — the classic attack.
    import base64
    import json

    header = {"alg": "none", "kid": "k1", "typ": "JWT"}
    claims = _base_claims()

    def _b64(obj) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(obj).encode())
            .rstrip(b"=")
            .decode()
        )

    token = f"{_b64(header)}.{_b64(claims)}."
    with pytest.raises(OidcIdTokenInvalid):
        await validator.validate(
            id_token=token,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )


@pytest.mark.asyncio
async def test_tampered_signature_rejected(rsa_keys, validator) -> None:
    token = _sign(rsa_keys, _base_claims())
    parts = token.split(".")
    # Flip one byte in the signature.
    tampered = ".".join(parts[:-1] + [parts[-1][:-2] + "AA"])
    with pytest.raises(OidcIdTokenInvalid):
        await validator.validate(
            id_token=tampered,
            issuer="https://idp.test",
            audience="client-abc",
            jwks_uri="https://idp.test/jwks",
            expected_nonce="nonce-xyz",
        )
