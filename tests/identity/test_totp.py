"""Unit tests for ``TotpService``. Envelope is local-fernet."""

from __future__ import annotations

import base64
import os
from uuid import uuid4

import pyotp
import pytest

from axon_enterprise.config import IdentitySettings
from axon_enterprise.crypto import LocalEnvelopeEncryption
from axon_enterprise.identity.errors import (
    TotpNotEnabledError,
    TotpVerificationError,
)
from axon_enterprise.identity.totp import TotpService


@pytest.fixture
def service() -> TotpService:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    envelope = LocalEnvelopeEncryption.from_base64(key)
    return TotpService(
        envelope=envelope,
        settings=IdentitySettings(totp_issuer="TestIssuer"),
    )


def test_generate_returns_valid_provisioning_uri(service: TotpService) -> None:
    uid = uuid4()
    enrolment = service.generate(uid, "alice@example.com")
    assert enrolment.provisioning_uri.startswith("otpauth://totp/")
    assert "TestIssuer" in enrolment.provisioning_uri
    assert "alice%40example.com" in enrolment.provisioning_uri
    # Secret is 20 bytes → 32 chars base32 without padding
    assert len(enrolment.secret) == 32


def test_verify_current_code_succeeds(service: TotpService) -> None:
    uid = uuid4()
    enrolment = service.generate(uid, "alice@example.com")
    current = pyotp.TOTP(enrolment.secret).now()
    service.verify(user_id=uid, ciphertext=enrolment.ciphertext, code=current)


def test_verify_wrong_code_raises(service: TotpService) -> None:
    uid = uuid4()
    enrolment = service.generate(uid, "alice@example.com")
    with pytest.raises(TotpVerificationError):
        service.verify(user_id=uid, ciphertext=enrolment.ciphertext, code="000000")


def test_verify_without_ciphertext_raises_not_enabled(service: TotpService) -> None:
    with pytest.raises(TotpNotEnabledError):
        service.verify(user_id=uuid4(), ciphertext=None, code="123456")


def test_ciphertext_bound_to_user_id(service: TotpService) -> None:
    uid_a = uuid4()
    uid_b = uuid4()
    enrolment = service.generate(uid_a, "alice@example.com")
    current = pyotp.TOTP(enrolment.secret).now()
    # Correct code, but AAD mismatch (different user_id) must fail.
    with pytest.raises(TotpVerificationError):
        service.verify(user_id=uid_b, ciphertext=enrolment.ciphertext, code=current)
