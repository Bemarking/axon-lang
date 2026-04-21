"""JWKS document builder.

Emits the ``application/json`` payload served from
``/.well-known/jwks.json`` — a list of JWK entries for every
``active`` + ``grace`` signing key. The Rust runtime fetches this
document and verifies incoming JWTs against it.

Format (RFC 7517 §4 / §5):

    {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "aabbcc...",
                "n": "<big-endian modulus base64url>",
                "e": "<public exponent base64url>"
            },
            ...
        ]
    }

Only RSA keys are emitted (the signer registry only accepts RS256/
RS384/RS512); adding EC when we support ES* is a one-liner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.jwt_issuer.key_management import KeyManagementService
from axon_enterprise.jwt_issuer.local_signer import b64url_no_pad


@dataclass(frozen=True)
class JwksDocumentBuilder:
    """Turn ``jwt_signing_keys`` rows into a JWKS JSON dict."""

    async def build(self, db: AsyncSession) -> dict[str, Any]:
        keys = await KeyManagementService().list_verifiable(db)
        jwks_entries: list[dict[str, Any]] = []
        for row in keys:
            pub = serialization.load_pem_public_key(
                row.public_key_pem.encode("ascii")
            )
            if not isinstance(pub, RSAPublicKey):
                # Current issuer only emits RSA; surfacing a mismatch
                # here is easier than silently dropping the key.
                continue
            nums = pub.public_numbers()
            jwks_entries.append(
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": row.algorithm,
                    "kid": row.kid,
                    "n": _int_to_b64url(nums.n),
                    "e": _int_to_b64url(nums.e),
                }
            )
        # Stable ordering by kid so the wire bytes are deterministic —
        # helps clients that cache the raw document.
        jwks_entries.sort(key=lambda j: j["kid"])
        return {"keys": jwks_entries}


def _int_to_b64url(value: int) -> str:
    """Big-endian unsigned bytes → urlsafe-base64 without padding.

    Matches RFC 7518 §6.3.1 encoding for RSA ``n`` and ``e``.
    """
    byte_len = (value.bit_length() + 7) // 8
    return b64url_no_pad(value.to_bytes(byte_len, "big"))
