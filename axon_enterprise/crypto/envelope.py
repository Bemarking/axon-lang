"""Envelope encryption interface + backend factory.

The ``EnvelopeEncryption`` protocol is implemented by two classes:

    - ``LocalEnvelopeEncryption`` (``crypto.local_envelope``)
      Fernet-based. A single master key lives in the process; every
      encryption derives a per-record subkey via HKDF with the AAD
      folded into the info parameter.

    - ``KmsEnvelopeEncryption`` (``crypto.kms_envelope``) — production.
      Each encrypt requests a new DEK from KMS with the AAD set as the
      encryption context; the DEK is wrapped by KMS and returned
      encrypted. Plaintext is AES-256-GCM-sealed with the DEK and the
      wrapped DEK is stored alongside the ciphertext.

Both backends produce envelopes in the same wire format so ciphertexts
written by one can be decrypted by another only when the master key
material is shared (intentionally impossible across backends).
"""

from __future__ import annotations

from typing import Mapping, Protocol, TypeAlias, runtime_checkable

# A mapping of non-sensitive string labels describing the record the
# ciphertext belongs to: {"user_id": "...", "purpose": "totp"} etc.
# The keys are sorted and serialised deterministically before being
# used as AAD — the ordering stability is part of the wire contract.
AAD: TypeAlias = Mapping[str, str]


# ── Wire format ────────────────────────────────────────────────────────
#
#   byte 0        : format version
#                     0x01 = LocalEnvelopeEncryption (Fernet-derived)
#                     0x02 = KmsEnvelopeEncryption (AES-GCM + wrapped DEK)
#   bytes 1..    : backend-specific payload

FORMAT_VERSION_LOCAL: int = 0x01
FORMAT_VERSION_KMS: int = 0x02


# ── Errors ────────────────────────────────────────────────────────────


class EnvelopeError(Exception):
    """Base class for envelope encryption errors."""


class IntegrityError(EnvelopeError):
    """Raised when a ciphertext fails authentication.

    Examples:
        - AAD mismatch (row-binding broken)
        - GCM tag verification failed
        - Version byte is known but payload is malformed
    """


class VersionUnsupported(EnvelopeError):
    """Raised when the leading version byte is not recognised.

    Triggers an alert in production because it usually means a rolling
    deploy landed a row written by a newer backend that an older reader
    can't handle.
    """


# ── Protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class EnvelopeEncryption(Protocol):
    """The single interface used by callers (identity, secrets, ...)."""

    def encrypt(self, plaintext: bytes, aad: AAD) -> bytes:
        """Encrypt ``plaintext`` binding it to ``aad``.

        Returns a byte string beginning with the format version byte.
        """
        ...

    def decrypt(self, envelope: bytes, aad: AAD) -> bytes:
        """Decrypt the envelope, verifying that ``aad`` matches.

        Raises:
            IntegrityError: when AAD or tag doesn't match.
            VersionUnsupported: when the version byte is unknown.
        """
        ...


# ── Factory ────────────────────────────────────────────────────────────


def get_envelope() -> EnvelopeEncryption:
    """Return the configured envelope backend based on current settings.

    Cached at module scope. Tests may re-import after monkey-patching
    settings.
    """
    from axon_enterprise.config import get_settings

    settings = get_settings()
    backend = settings.envelope.backend
    if backend == "local":
        from axon_enterprise.crypto.local_envelope import LocalEnvelopeEncryption

        return LocalEnvelopeEncryption.from_settings(settings.envelope)
    if backend == "kms":
        from axon_enterprise.crypto.kms_envelope import KmsEnvelopeEncryption

        return KmsEnvelopeEncryption.from_settings(settings.envelope)
    raise EnvelopeError(f"Unknown envelope backend: {backend!r}")


def serialise_aad(aad: AAD) -> bytes:
    """Canonical serialisation of AAD for the GCM authentication tag.

    Stable across backends so a ciphertext can in principle be verified
    by the other backend as long as the master key material is compatible.
    """
    if not aad:
        return b""
    # Sort by key so the AAD is encoding-independent.
    parts: list[str] = []
    for k in sorted(aad.keys()):
        v = aad[k]
        if "\x1e" in k or "\x1f" in k or "\x1e" in v or "\x1f" in v:
            # 0x1e/0x1f are our field/record separators; reject if present.
            raise EnvelopeError(
                "AAD keys and values must not contain 0x1e or 0x1f separators"
            )
        parts.append(f"{k}\x1f{v}")
    return "\x1e".join(parts).encode("utf-8")
