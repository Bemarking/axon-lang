"""Signer abstraction shared by KMS and Local backends.

The JwtIssuer does not know whether it's talking to an HSM or an
in-process key — it just sees ``Signer.sign(message) -> bytes`` and
``Signer.public_key_pem`` which is enough to build a JWT and the
JWKS response.

Each signer also reports ``kid`` + ``algorithm`` for header emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SignerInfo:
    """Metadata returned by a signer — what JwtIssuer embeds in the header."""

    kid: str
    algorithm: str
    public_key_pem: str


@runtime_checkable
class Signer(Protocol):
    """Producer of RSA signatures over arbitrary byte messages."""

    @property
    def info(self) -> SignerInfo: ...

    def sign(self, message: bytes) -> bytes:
        """Return the raw signature bytes (not base64)."""
        ...


def build_default_signer() -> Signer:
    """Wire the production signer from settings.

    Kept as a free function (rather than a classmethod on Signer)
    because the two implementations live in separate files and
    circular imports would force another indirection layer.
    """
    from axon_enterprise.config import get_settings

    s = get_settings()
    if s.jwt.signer_backend == "kms":
        from axon_enterprise.jwt_issuer.kms_signer import KmsSigner

        return KmsSigner.from_settings()
    from axon_enterprise.jwt_issuer.local_signer import LocalSigner

    return LocalSigner.from_settings()
