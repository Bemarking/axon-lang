"""
Unit tests — §λ-L-E Fase 11.a trust catalogue + Python verifiers.

Mirrors ``axon-rs/tests/fase_11a_refinement_and_stream.rs`` on the
Python reference side. Parity is asserted by
``tests/parity/test_fase_11a_catalogue_parity.py`` — this file is
focused on behavior of the verifiers themselves.
"""

from __future__ import annotations

import hashlib
import hmac as stdlib_hmac

import pytest

from axon.runtime.trust import (
    TRUST_CATALOG,
    Trusted,
    TrustError,
    TrustProof,
    Untrusted,
    VerifiedPayload,
    assert_trusted,
    is_trust_proof,
    verify_ed25519,
    verify_hmac_sha256,
    verify_hmac_sha256_hex,
)


# ── Catalogue invariants ──────────────────────────────────────────────


def test_catalog_contains_exactly_the_four_proofs() -> None:
    assert set(TRUST_CATALOG) == {
        "hmac",
        "jwt_sig",
        "oauth_code_exchange",
        "ed25519",
    }
    # Order is stable; Rust mirror depends on it.
    assert TRUST_CATALOG == (
        "hmac",
        "jwt_sig",
        "oauth_code_exchange",
        "ed25519",
    )


def test_is_trust_proof_accepts_only_catalogue_slugs() -> None:
    for slug in TRUST_CATALOG:
        assert is_trust_proof(slug)
    assert not is_trust_proof("HMAC")  # case-sensitive
    assert not is_trust_proof("crc32")
    assert not is_trust_proof("")


def test_trust_proof_enum_covers_every_slug() -> None:
    enum_values = {member.value for member in TrustProof}
    assert enum_values == set(TRUST_CATALOG)


# ── Untrusted / Trusted wrappers ─────────────────────────────────────


def test_untrusted_exposes_inner_value() -> None:
    u: Untrusted[bytes] = Untrusted(b"payload")
    assert u.value == b"payload"


def test_assert_trusted_accepts_trusted_instance() -> None:
    payload = b"hello"
    t = Trusted(
        payload,
        VerifiedPayload(proof=TrustProof.HMAC, key_id="k1"),
    )
    # Should not raise.
    assert_trusted(t)


def test_assert_trusted_rejects_untrusted_instance() -> None:
    u: Untrusted[bytes] = Untrusted(b"payload")
    with pytest.raises(TrustError):
        assert_trusted(u)


def test_assert_trusted_rejects_raw_value() -> None:
    with pytest.raises(TrustError) as excinfo:
        assert_trusted(b"raw bytes")
    # The message enumerates the catalogue so the operator gets the
    # complete list of acceptable verifier entry points.
    msg = str(excinfo.value)
    for slug in TRUST_CATALOG:
        assert slug in msg


# ── HMAC-SHA256 ──────────────────────────────────────────────────────


def _hmac_tag(payload: bytes, key: bytes) -> bytes:
    return stdlib_hmac.new(key, payload, hashlib.sha256).digest()


def test_hmac_roundtrip_returns_trusted() -> None:
    payload = b"order#42"
    key = b"shared-secret"
    tag = _hmac_tag(payload, key)

    trusted = verify_hmac_sha256(payload, tag, key, key_id="v1")
    assert isinstance(trusted, Trusted)
    assert trusted.value == payload
    assert trusted.proof.proof is TrustProof.HMAC
    assert trusted.proof.key_id == "v1"


def test_hmac_rejects_tampered_payload() -> None:
    key = b"k"
    tag = _hmac_tag(b"original", key)
    with pytest.raises(TrustError, match="mismatch"):
        verify_hmac_sha256(b"tampered", tag, key, key_id="v1")


def test_hmac_rejects_wrong_length_tag() -> None:
    with pytest.raises(TrustError, match="32 bytes"):
        verify_hmac_sha256(b"payload", b"\x00" * 16, b"k", key_id="v1")


def test_hmac_hex_decode_roundtrip() -> None:
    payload = b"hello"
    key = b"k"
    tag_hex = _hmac_tag(payload, key).hex()

    # Plain hex.
    trusted = verify_hmac_sha256_hex(payload, tag_hex, key, key_id="v1")
    assert trusted.proof.proof is TrustProof.HMAC

    # GitHub ``X-Hub-Signature-256`` convention is also accepted.
    trusted2 = verify_hmac_sha256_hex(
        payload, f"sha256={tag_hex}", key, key_id="v1"
    )
    assert trusted2.proof.proof is TrustProof.HMAC


def test_hmac_hex_rejects_malformed_hex() -> None:
    with pytest.raises(TrustError, match="decode"):
        verify_hmac_sha256_hex(b"x", "zz", b"k", key_id="v1")


# ── Ed25519 (guarded by cryptography availability) ──────────────────


def _cryptography_available() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _cryptography_available(),
    reason="cryptography adopter dep not installed in this env",
)
def test_ed25519_roundtrip() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives import serialization

    sk = Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = b"sigstore-attestation"
    sig = sk.sign(payload)

    trusted = verify_ed25519(
        payload, sig, pk_bytes, key_id="sigstore-key-1"
    )
    assert trusted.proof.proof is TrustProof.ED25519
    assert trusted.proof.key_id == "sigstore-key-1"


@pytest.mark.skipif(
    not _cryptography_available(),
    reason="cryptography adopter dep not installed in this env",
)
def test_ed25519_rejects_tampered_payload() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives import serialization

    sk = Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    sig = sk.sign(b"original")
    with pytest.raises(TrustError, match="mismatch"):
        verify_ed25519(
            b"tampered", sig, pk_bytes, key_id="sigstore-key-1"
        )


def test_ed25519_rejects_wrong_key_size_without_cryptography_dep() -> None:
    # Runs with or without cryptography — size check is pre-FFI.
    with pytest.raises(TrustError, match="32 bytes"):
        verify_ed25519(b"x", b"\x00" * 64, b"too_short", key_id="k")
