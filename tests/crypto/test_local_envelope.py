"""Unit tests for ``LocalEnvelopeEncryption``.

No Docker needed — pure cryptography.
"""

from __future__ import annotations

import base64
import os

import pytest

from axon_enterprise.crypto import (
    EnvelopeError,
    IntegrityError,
    LocalEnvelopeEncryption,
    VersionUnsupported,
)
from axon_enterprise.crypto.envelope import serialise_aad


@pytest.fixture
def envelope() -> LocalEnvelopeEncryption:
    raw = os.urandom(32)
    key_b64 = base64.urlsafe_b64encode(raw).decode("ascii")
    return LocalEnvelopeEncryption.from_base64(key_b64)


def test_encrypt_decrypt_roundtrip(envelope: LocalEnvelopeEncryption) -> None:
    aad = {"user_id": "abc", "purpose": "test"}
    ct = envelope.encrypt(b"hello world", aad)
    assert envelope.decrypt(ct, aad) == b"hello world"


def test_version_byte_is_01(envelope: LocalEnvelopeEncryption) -> None:
    ct = envelope.encrypt(b"x", {"purpose": "t"})
    assert ct[0] == 0x01


def test_two_encrypts_produce_different_ciphertexts(
    envelope: LocalEnvelopeEncryption,
) -> None:
    aad = {"purpose": "t"}
    a = envelope.encrypt(b"same", aad)
    b = envelope.encrypt(b"same", aad)
    assert a != b, "fresh salt + nonce must make each ciphertext unique"


def test_aad_mismatch_is_rejected(envelope: LocalEnvelopeEncryption) -> None:
    ct = envelope.encrypt(b"secret", {"user_id": "alice"})
    with pytest.raises(IntegrityError):
        envelope.decrypt(ct, {"user_id": "bob"})


def test_tampered_ciphertext_is_rejected(envelope: LocalEnvelopeEncryption) -> None:
    ct = bytearray(envelope.encrypt(b"secret", {"purpose": "t"}))
    ct[-1] ^= 0x01
    with pytest.raises(IntegrityError):
        envelope.decrypt(bytes(ct), {"purpose": "t"})


def test_unknown_version_byte_is_rejected(
    envelope: LocalEnvelopeEncryption,
) -> None:
    with pytest.raises(VersionUnsupported):
        envelope.decrypt(b"\xff" + b"\x00" * 64, {"purpose": "t"})


def test_truncated_envelope_is_rejected(envelope: LocalEnvelopeEncryption) -> None:
    ct = envelope.encrypt(b"secret", {"purpose": "t"})
    with pytest.raises(IntegrityError):
        envelope.decrypt(ct[:10], {"purpose": "t"})


def test_wrong_length_key_rejected() -> None:
    with pytest.raises(EnvelopeError):
        LocalEnvelopeEncryption(master_key=b"short")


def test_invalid_base64_key_rejected() -> None:
    with pytest.raises(EnvelopeError):
        LocalEnvelopeEncryption.from_base64("not!valid!base64?%%")


def test_aad_with_control_chars_rejected(envelope: LocalEnvelopeEncryption) -> None:
    with pytest.raises(EnvelopeError):
        envelope.encrypt(b"x", {"k\x1ey": "v"})


def test_serialise_aad_is_order_independent() -> None:
    assert serialise_aad({"a": "1", "b": "2"}) == serialise_aad({"b": "2", "a": "1"})
