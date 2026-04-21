"""JWT issuance + JWKS rotation + revocation.

Closes the gap left by ``axon-rs/src/tenant.rs`` where JWTs were
extracted without signature verification. Python emits RS256-signed
JWTs (optionally via AWS KMS so private keys never leave the HSM);
Rust verifies those JWTs against the JWKS served from this module.

Public surface
--------------
    JwtIssuer          — mint access tokens
    JwksDocumentBuilder — materialise the public JWKS document
    KeyManagementService — register / rotate / retire signing keys
    JtiRevocationService — blacklist management

    Signer               Protocol (ABC) for sign(message) + public_key_pem
    KmsSigner            production — kms:Sign
    LocalSigner          dev/test — RSA private key in-process

    JwtSigningKey / JwtRevokedJti — ORM

Every piece is composable and side-effect-free until a caller passes
an ``AsyncSession`` and an outbound backend. Tests swap signers
freely; production wires one concrete set of services at startup.
"""

from axon_enterprise.jwt_issuer.errors import (
    JwtBackendError,
    JwtIssuerError,
    JwtKeyNotFound,
    JwtRevoked,
    JwtSigningFailed,
    NoActiveSigningKey,
)
from axon_enterprise.jwt_issuer.issuer import IssuedJwt, JwtIssuer
from axon_enterprise.jwt_issuer.jwks import JwksDocumentBuilder
from axon_enterprise.jwt_issuer.key_management import KeyManagementService
from axon_enterprise.jwt_issuer.local_signer import LocalSigner
from axon_enterprise.jwt_issuer.models import (
    JwtRevokedJti,
    JwtSigningKey,
    SigningKeyStatus,
)
from axon_enterprise.jwt_issuer.revocation import JtiRevocationService
from axon_enterprise.jwt_issuer.signer import Signer, SignerInfo, build_default_signer

try:  # KMS is optional in dev
    from axon_enterprise.jwt_issuer.kms_signer import KmsSigner
except ImportError:  # pragma: no cover
    KmsSigner = None  # type: ignore[misc,assignment]

__all__ = [
    "IssuedJwt",
    "JtiRevocationService",
    "JwksDocumentBuilder",
    "JwtBackendError",
    "JwtIssuer",
    "JwtIssuerError",
    "JwtKeyNotFound",
    "JwtRevoked",
    "JwtRevokedJti",
    "JwtSigningFailed",
    "JwtSigningKey",
    "KeyManagementService",
    "KmsSigner",
    "LocalSigner",
    "NoActiveSigningKey",
    "Signer",
    "SignerInfo",
    "SigningKeyStatus",
    "build_default_signer",
]
