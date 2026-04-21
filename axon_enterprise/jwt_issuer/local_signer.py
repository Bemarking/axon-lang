"""In-process RSA signer for dev/test.

Rejected by the settings validator when ``env=production``.

The private key is loaded from ``AXON_JWT_LOCAL_PRIVATE_KEY_PEM``
and held in memory for the lifetime of the process. A deterministic
``kid`` is derived from the SHA-256 of the DER-encoded public key —
so the same key always advertises the same ``kid`` across restarts
(which keeps the JWKS stable and avoids cache flushes at startup).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.jwt_issuer.errors import JwtSigningFailed
from axon_enterprise.jwt_issuer.signer import SignerInfo


def _pkcs1_hash(alg: str):
    return {
        "RS256": hashes.SHA256(),
        "RS384": hashes.SHA384(),
        "RS512": hashes.SHA512(),
    }[alg]


def _derive_kid(public_pem: str) -> str:
    """SHA-256 of the DER SPKI bytes, truncated to 16 hex chars."""
    pub = serialization.load_pem_public_key(public_pem.encode("ascii"))
    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:16]


@dataclass
class LocalSigner:
    """RSA signer backed by a private key held in process memory."""

    _private_key: rsa.RSAPrivateKey
    _info: SignerInfo

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_pem(
        cls, private_pem: str, *, algorithm: str = "RS256", kid: str | None = None
    ) -> LocalSigner:
        priv = serialization.load_pem_private_key(
            private_pem.encode("utf-8"), password=None
        )
        if not isinstance(priv, rsa.RSAPrivateKey):
            raise JwtSigningFailed(
                "LocalSigner requires an RSA private key; got "
                f"{type(priv).__name__}"
            )
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        resolved_kid = kid or _derive_kid(pub_pem)
        return cls(
            _private_key=priv,
            _info=SignerInfo(
                kid=resolved_kid,
                algorithm=algorithm,
                public_key_pem=pub_pem,
            ),
        )

    @classmethod
    def from_settings(cls, settings: JwtSettings | None = None) -> LocalSigner:
        s = settings or get_settings().jwt
        if s.local_private_key_pem is None:
            raise JwtSigningFailed(
                "jwt.local_private_key_pem is unset; cannot build LocalSigner"
            )
        return cls.from_pem(
            s.local_private_key_pem.get_secret_value(),
            algorithm=s.algorithm,
        )

    @classmethod
    def generate(
        cls, *, algorithm: str = "RS256", kid: str | None = None
    ) -> LocalSigner:
        """Mint a fresh RSA key. Intended for tests + operator bootstrap."""
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        return cls.from_pem(pem, algorithm=algorithm, kid=kid)

    # ── Signer protocol ───────────────────────────────────────────────

    @property
    def info(self) -> SignerInfo:
        return self._info

    def sign(self, message: bytes) -> bytes:
        try:
            return self._private_key.sign(
                message,
                padding.PKCS1v15(),
                _pkcs1_hash(self._info.algorithm),
            )
        except Exception as exc:  # noqa: BLE001
            raise JwtSigningFailed(f"LocalSigner.sign failed: {exc}") from exc

    # Handy for operator key-export commands.
    def export_private_key_pem(self) -> bytes:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


def pem_to_base64_jwk_bytes(pem: str) -> bytes:
    """Round-trip a PEM public key to DER bytes (shared by jwks.py)."""
    pub = serialization.load_pem_public_key(pem.encode("ascii"))
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
