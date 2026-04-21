"""AWS KMS-backed RSA signer.

Uses ``kms:Sign`` so the private key never leaves the HSM. Public
key material is fetched once via ``kms:GetPublicKey`` and held
in-process (stable per KMS key unless the key is rotated at the AWS
level — KMS key IDs are stable across AWS-managed rotations).

The ``kid`` is derived as ``SHA-256(SPKI DER)[:16]``, matching the
scheme used by ``LocalSigner`` so JWKS tokens remain compatible when
operators migrate a tenant from local to KMS.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.jwt_issuer.errors import JwtSigningFailed
from axon_enterprise.jwt_issuer.signer import SignerInfo

_ALG_TO_KMS: dict[str, str] = {
    "RS256": "RSASSA_PKCS1_V1_5_SHA_256",
    "RS384": "RSASSA_PKCS1_V1_5_SHA_384",
    "RS512": "RSASSA_PKCS1_V1_5_SHA_512",
}


@dataclass
class KmsSigner:
    """Signs JWTs by calling ``kms:Sign``."""

    kms_key_id: str
    _client: Any
    _info: SignerInfo

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def for_testing(
        cls,
        *,
        kms_key_id: str,
        client: Any,
        public_key_pem: str,
        algorithm: str = "RS256",
        kid: str | None = None,
    ) -> KmsSigner:
        """Stub-client constructor for tests (moto / custom mock)."""
        resolved_kid = kid or _derive_kid(public_key_pem)
        return cls(
            kms_key_id=kms_key_id,
            _client=client,
            _info=SignerInfo(
                kid=resolved_kid,
                algorithm=algorithm,
                public_key_pem=public_key_pem,
            ),
        )

    @classmethod
    def from_settings(cls, settings: JwtSettings | None = None) -> KmsSigner:
        s = settings or get_settings().jwt
        # Delegate to KeyManagementService which knows which row is
        # currently 'active' (the signer rebinds on rotation).
        from axon_enterprise.jwt_issuer.key_management import (
            resolve_active_kms_signer,
        )

        return resolve_active_kms_signer(s)

    @classmethod
    def from_kms_arn(
        cls,
        kms_key_id: str,
        *,
        algorithm: str = "RS256",
        region: str | None = None,
        kid: str | None = None,
    ) -> KmsSigner:
        """Initialise by fetching the public key from KMS directly."""
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise JwtSigningFailed(
                "boto3 required for KmsSigner — install axon-enterprise[aws]"
            ) from exc
        kwargs: dict[str, Any] = {}
        if region:
            kwargs["region_name"] = region
        client = boto3.client("kms", **kwargs)
        resp = client.get_public_key(KeyId=kms_key_id)
        pub_der = resp["PublicKey"]
        pub_pem = serialization.load_der_public_key(pub_der).public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        resolved_kid = kid or _derive_kid(pub_pem)
        return cls(
            kms_key_id=kms_key_id,
            _client=client,
            _info=SignerInfo(
                kid=resolved_kid,
                algorithm=algorithm,
                public_key_pem=pub_pem,
            ),
        )

    # ── Signer protocol ───────────────────────────────────────────────

    @property
    def info(self) -> SignerInfo:
        return self._info

    def sign(self, message: bytes) -> bytes:
        kms_alg = _ALG_TO_KMS.get(self._info.algorithm)
        if kms_alg is None:
            raise JwtSigningFailed(
                f"KmsSigner does not support algorithm {self._info.algorithm!r}"
            )
        try:
            resp = self._client.sign(
                KeyId=self.kms_key_id,
                Message=message,
                MessageType="RAW",
                SigningAlgorithm=kms_alg,
            )
        except Exception as exc:  # noqa: BLE001
            raise JwtSigningFailed(f"kms:Sign failed: {exc}") from exc
        return resp["Signature"]


def _derive_kid(public_pem: str) -> str:
    pub = serialization.load_pem_public_key(public_pem.encode("ascii"))
    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:16]
