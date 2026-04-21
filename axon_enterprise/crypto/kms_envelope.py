"""AWS KMS envelope encryption.

Each ``encrypt`` call:

    1. Requests a new 256-bit DEK from KMS via ``GenerateDataKey``.
       The AAD is passed as ``EncryptionContext`` — a KMS-level
       authenticated binding on the DEK.
    2. Wraps the plaintext with AES-256-GCM using the DEK, a fresh
       12-byte nonce, and the same AAD.
    3. Returns: 0x02 | dek_wrap_len(2) | wrapped_dek | nonce(12) |
       ciphertext_with_tag.

``decrypt`` reverses the flow: parses the wrapped DEK, calls
``kms:Decrypt`` with the same EncryptionContext (which must match or
KMS itself refuses), then AES-256-GCM-opens the ciphertext.

``boto3`` is a soft dependency — the module imports lazily so unit
tests that don't touch KMS don't need the SDK installed.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from axon_enterprise.config import EnvelopeSettings
from axon_enterprise.crypto.envelope import (
    AAD,
    FORMAT_VERSION_KMS,
    EnvelopeError,
    IntegrityError,
    VersionUnsupported,
    serialise_aad,
)

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_kms import KMSClient

_NONCE_LEN = 12
_DEK_LEN = 32  # AES-256
_DEK_LEN_HDR = 2  # uint16 big-endian


@dataclass(frozen=True)
class KmsEnvelopeEncryption:
    """AWS KMS-backed envelope encryption."""

    kms_key_id: str
    _client: Any  # boto3 KMS client — Any to avoid hard boto3 import at type time

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: EnvelopeSettings) -> KmsEnvelopeEncryption:
        if not settings.kms_key_id:
            raise EnvelopeError("envelope.kms_key_id is required when backend='kms'")

        # Lazy import so unit tests without boto3 installed still pass.
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise EnvelopeError(
                "boto3 is required for KMS envelope encryption. Install "
                "with `pip install 'axon-enterprise[aws]'`."
            ) from exc

        kwargs: dict[str, Any] = {}
        if settings.kms_region:
            kwargs["region_name"] = settings.kms_region
        client = boto3.client("kms", **kwargs)
        return cls(kms_key_id=settings.kms_key_id, _client=client)

    @classmethod
    def for_testing(cls, kms_key_id: str, client: Any) -> KmsEnvelopeEncryption:
        """Constructor for tests with a stubbed/moto client."""
        return cls(kms_key_id=kms_key_id, _client=client)

    # ── Encrypt ───────────────────────────────────────────────────────

    def encrypt(self, plaintext: bytes, aad: AAD) -> bytes:
        ctx = _encryption_context(aad)

        # KMS-level GenerateDataKey: we get (plaintext_DEK, wrapped_DEK)
        resp = self._client.generate_data_key(
            KeyId=self.kms_key_id,
            KeySpec="AES_256",
            EncryptionContext=ctx,
        )
        dek: bytes = resp["Plaintext"]
        dek_wrapped: bytes = resp["CiphertextBlob"]

        if len(dek) != _DEK_LEN:
            raise EnvelopeError("unexpected DEK length from KMS")

        nonce = os.urandom(_NONCE_LEN)
        aad_bytes = serialise_aad(aad)
        try:
            ct_with_tag = AESGCM(dek).encrypt(nonce, plaintext, aad_bytes)
        finally:
            # Best-effort zero. Python can't guarantee immediate GC of bytes,
            # but clearing our reference is all we can do in-process.
            del dek

        if len(dek_wrapped) > 0xFFFF:
            raise EnvelopeError("wrapped DEK unexpectedly large (>65535 bytes)")

        return (
            bytes([FORMAT_VERSION_KMS])
            + struct.pack(">H", len(dek_wrapped))
            + dek_wrapped
            + nonce
            + ct_with_tag
        )

    # ── Decrypt ───────────────────────────────────────────────────────

    def decrypt(self, envelope: bytes, aad: AAD) -> bytes:
        if not envelope:
            raise IntegrityError("envelope is empty")
        version = envelope[0]
        if version != FORMAT_VERSION_KMS:
            raise VersionUnsupported(
                f"KmsEnvelopeEncryption cannot decrypt version 0x{version:02x}"
            )
        if len(envelope) < 1 + _DEK_LEN_HDR + _NONCE_LEN:
            raise IntegrityError("envelope too short")

        dek_wrap_len = struct.unpack(">H", envelope[1 : 1 + _DEK_LEN_HDR])[0]
        header_end = 1 + _DEK_LEN_HDR + dek_wrap_len
        nonce_end = header_end + _NONCE_LEN
        if len(envelope) < nonce_end + 16:  # + AES-GCM tag
            raise IntegrityError("envelope truncated")

        dek_wrapped = envelope[1 + _DEK_LEN_HDR : header_end]
        nonce = envelope[header_end:nonce_end]
        ct_with_tag = envelope[nonce_end:]

        ctx = _encryption_context(aad)

        # KMS verifies the EncryptionContext: swapping aad breaks here.
        resp = self._client.decrypt(
            CiphertextBlob=dek_wrapped,
            EncryptionContext=ctx,
            # KeyId is optional on decrypt; passing it narrows the trust
            # decision to the configured key.
            KeyId=self.kms_key_id,
        )
        dek: bytes = resp["Plaintext"]

        try:
            try:
                return AESGCM(dek).decrypt(nonce, ct_with_tag, serialise_aad(aad))
            except InvalidTag as exc:
                raise IntegrityError(
                    "AES-GCM authentication failed (AAD mismatch or tampered data)"
                ) from exc
        finally:
            del dek


def _encryption_context(aad: AAD) -> dict[str, str]:
    """KMS EncryptionContext requires a flat ``{str: str}`` dict.

    We pass the AAD verbatim — both KMS and AES-GCM will fail if the
    caller supplies different values at decrypt time.
    """
    return {str(k): str(v) for k, v in aad.items()}
