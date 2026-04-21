"""TOTP (RFC 6238) with envelope-encrypted secrets at rest.

Secrets are 160-bit base32-encoded (standard compatible with Google
Authenticator, Authy, 1Password). They are encrypted with the
application envelope backend before being persisted; the plaintext
secret only exists:

    - During enrolment (shown to the user as a QR provisioning URI)
    - At verification time (decrypt → HOTP compare → discard)

The AAD used for envelope binding includes the ``user_id`` and a
constant purpose tag, so ciphertexts cannot be smuggled between
users or between TOTP and other field-level secrets.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import pyotp

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.crypto import AAD, EnvelopeEncryption, get_envelope
from axon_enterprise.identity.errors import TotpNotEnabledError, TotpVerificationError

_PURPOSE: Final[str] = "identity.totp"
_SECRET_BYTES: Final[int] = 20  # 160 bits


@dataclass(frozen=True)
class TotpEnrolment:
    """Result of ``TotpService.generate``: what the UI needs to show."""

    secret: str            # base32, to let the user type it in manually
    provisioning_uri: str  # otpauth:// URL for QR-code libs
    ciphertext: bytes      # encrypted secret the caller persists

    def qr_payload(self) -> str:
        """Alias — makes the caller side of the API read naturally."""
        return self.provisioning_uri


@dataclass(frozen=True)
class TotpService:
    """Generate + verify TOTP codes backed by envelope-encrypted secrets."""

    envelope: EnvelopeEncryption
    settings: IdentitySettings

    @classmethod
    def default(cls) -> TotpService:
        return cls(envelope=get_envelope(), settings=get_settings().identity)

    # ── Enrolment ─────────────────────────────────────────────────────

    def generate(self, user_id: UUID, email: str) -> TotpEnrolment:
        """Generate a fresh secret + provisioning URI + encrypted form."""
        raw = secrets.token_bytes(_SECRET_BYTES)
        secret_b32 = _b32nopad(raw)

        otp = self._totp(secret_b32)
        uri = otp.provisioning_uri(
            name=email,
            issuer_name=self.settings.totp_issuer,
        )
        ct = self.envelope.encrypt(raw, self._aad(user_id))
        return TotpEnrolment(secret=secret_b32, provisioning_uri=uri, ciphertext=ct)

    # ── Verification ──────────────────────────────────────────────────

    def verify(
        self,
        *,
        user_id: UUID,
        ciphertext: bytes | None,
        code: str,
    ) -> None:
        """Validate a TOTP ``code`` for ``user_id``.

        Raises:
            TotpNotEnabledError: when ``ciphertext`` is None.
            TotpVerificationError: when decryption or code match fails.
        """
        if ciphertext is None:
            raise TotpNotEnabledError()

        try:
            raw = self.envelope.decrypt(ciphertext, self._aad(user_id))
        except Exception as exc:  # noqa: BLE001
            raise TotpVerificationError() from exc

        secret_b32 = _b32nopad(raw)
        otp = self._totp(secret_b32)
        if not otp.verify(code, valid_window=self.settings.totp_verification_window):
            raise TotpVerificationError()

    # ── Helpers ───────────────────────────────────────────────────────

    def _totp(self, secret_b32: str) -> pyotp.TOTP:
        return pyotp.TOTP(
            secret_b32,
            digits=self.settings.totp_digits,
            interval=self.settings.totp_interval_seconds,
        )

    def _aad(self, user_id: UUID) -> AAD:
        return {"user_id": str(user_id), "purpose": _PURPOSE}


def _b32nopad(raw: bytes) -> str:
    """Base32 without padding, matching the format pyotp expects."""
    import base64

    return base64.b32encode(raw).decode("ascii").rstrip("=")
