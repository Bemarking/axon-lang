"""Application-level cryptography: envelope encryption for field-level secrets.

Used by ``identity.totp`` (TOTP secrets) and — in later sub-fases —
``secrets`` service metadata, SSO provider configs, and refresh-token
fingerprints where extra protection beyond Postgres TDE is warranted.

Design
------
- Backend-agnostic interface: ``EnvelopeEncryption``
- Two implementations: local (Fernet-based) for dev/test, KMS for prod
- Every call carries an ``AAD`` (additional authenticated data) dict —
  typically ``{"user_id": ..., "purpose": "totp"}``. AAD is cryptographically
  bound to the ciphertext, so swapping a ciphertext between two records
  is detected and rejected on decrypt.
- Serialised ciphertexts embed a version byte so backends can evolve
  without rotating every row at once.
"""

from axon_enterprise.crypto.envelope import (
    AAD,
    EnvelopeEncryption,
    EnvelopeError,
    IntegrityError,
    VersionUnsupported,
    get_envelope,
)
from axon_enterprise.crypto.local_envelope import LocalEnvelopeEncryption

__all__ = [
    "AAD",
    "EnvelopeEncryption",
    "EnvelopeError",
    "IntegrityError",
    "LocalEnvelopeEncryption",
    "VersionUnsupported",
    "get_envelope",
]
