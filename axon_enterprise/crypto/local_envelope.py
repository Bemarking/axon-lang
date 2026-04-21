"""Local (non-KMS) envelope encryption.

Intended for development, tests, and single-node deployments without
access to an HSM. The master key is a 32-byte secret held in the
process (loaded from ``AXON_ENVELOPE_LOCAL_KEY``).

Design
------
- Every encrypt generates a fresh 16-byte salt.
- HKDF-SHA-256 derives a per-record AES-256 key from
  (master_key, salt, info=canonical_AAD).
- AES-256-GCM encrypts the plaintext with a fresh 12-byte nonce and
  authenticates the same AAD.
- Wire format::

      0x01 | salt(16) | nonce(12) | tag(16) | ciphertext(var)

- Swapping ciphertext across records fails on decrypt because HKDF's
  ``info`` and GCM's ``aad`` are both tied to the exact AAD.

This backend is acceptable for dev / test / starter-tier deployments.
Production MUST use ``KmsEnvelopeEncryption`` (enforced by settings
validator).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from axon_enterprise.config import EnvelopeSettings
from axon_enterprise.crypto.envelope import (
    AAD,
    FORMAT_VERSION_LOCAL,
    EnvelopeError,
    IntegrityError,
    VersionUnsupported,
    serialise_aad,
)

_SALT_LEN = 16
_NONCE_LEN = 12
_TAG_LEN = 16
_KEY_LEN = 32


@dataclass(frozen=True)
class LocalEnvelopeEncryption:
    """Fernet-derived local envelope. Master key is held in-process."""

    master_key: bytes  # 32 raw bytes

    def __post_init__(self) -> None:
        if len(self.master_key) != _KEY_LEN:
            raise EnvelopeError(
                f"master_key must be exactly {_KEY_LEN} bytes, got {len(self.master_key)}"
            )

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: EnvelopeSettings) -> LocalEnvelopeEncryption:
        if settings.local_key is None:
            raise EnvelopeError(
                "envelope.local_key is unset; generate one with "
                "`Fernet.generate_key()` and export it as AXON_ENVELOPE__LOCAL_KEY"
            )
        raw = _decode_key(settings.local_key.get_secret_value())
        return cls(master_key=raw)

    @classmethod
    def from_base64(cls, key_b64: str) -> LocalEnvelopeEncryption:
        return cls(master_key=_decode_key(key_b64))

    # ── EnvelopeEncryption protocol ───────────────────────────────────

    def encrypt(self, plaintext: bytes, aad: AAD) -> bytes:
        salt = os.urandom(_SALT_LEN)
        info = serialise_aad(aad)
        subkey = _hkdf(self.master_key, salt=salt, info=info)
        nonce = os.urandom(_NONCE_LEN)
        ct_with_tag = AESGCM(subkey).encrypt(nonce, plaintext, info)
        # AESGCM.encrypt returns ciphertext||tag; we keep that layout.
        return bytes([FORMAT_VERSION_LOCAL]) + salt + nonce + ct_with_tag

    def decrypt(self, envelope: bytes, aad: AAD) -> bytes:
        if not envelope:
            raise IntegrityError("envelope is empty")
        version = envelope[0]
        if version != FORMAT_VERSION_LOCAL:
            raise VersionUnsupported(
                f"LocalEnvelopeEncryption cannot decrypt version 0x{version:02x}"
            )
        if len(envelope) < 1 + _SALT_LEN + _NONCE_LEN + _TAG_LEN:
            raise IntegrityError("envelope too short")
        salt = envelope[1 : 1 + _SALT_LEN]
        nonce = envelope[1 + _SALT_LEN : 1 + _SALT_LEN + _NONCE_LEN]
        ct_with_tag = envelope[1 + _SALT_LEN + _NONCE_LEN :]
        info = serialise_aad(aad)
        subkey = _hkdf(self.master_key, salt=salt, info=info)
        try:
            return AESGCM(subkey).decrypt(nonce, ct_with_tag, info)
        except InvalidTag as exc:
            raise IntegrityError(
                "ciphertext authentication failed (AAD mismatch or tampered data)"
            ) from exc


# ── Helpers ────────────────────────────────────────────────────────────


def _hkdf(master: bytes, *, salt: bytes, info: bytes) -> bytes:
    """Derive a 256-bit AES key from the master secret + salt + AAD-as-info."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt,
        info=info,
    ).derive(master)


def _decode_key(key_str: str) -> bytes:
    """Accept either a Fernet-style (44-char base64) or 32-byte b64 raw key.

    Fernet-style keys are 32 raw bytes encoded as 44-char urlsafe-base64
    (the standard ``Fernet.generate_key()`` output). We also accept a
    bare 32-byte urlsafe-base64 so operators can generate one with
    ``python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"``.
    """
    key_str = key_str.strip()
    # Fernet.generate_key() → 44 chars urlsafe-base64 of 32 raw bytes
    try:
        raw = base64.urlsafe_b64decode(key_str)
    except Exception as exc:  # noqa: BLE001
        raise EnvelopeError(f"local_key is not valid urlsafe-base64: {exc}") from exc
    if len(raw) != _KEY_LEN:
        raise EnvelopeError(
            f"local_key decodes to {len(raw)} bytes; exactly {_KEY_LEN} required"
        )
    return raw
