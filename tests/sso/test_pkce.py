"""Unit tests for RFC 7636 PKCE helpers."""

from __future__ import annotations

import base64
import hashlib

import pytest

from axon_enterprise.sso.errors import OidcPkceMismatch
from axon_enterprise.sso.oidc_pkce import (
    compute_code_challenge,
    generate_code_verifier,
    verify_pair,
)


def test_verifier_has_expected_shape() -> None:
    v = generate_code_verifier()
    assert 43 <= len(v) <= 128
    # URL-safe base64 chars
    for ch in v:
        assert ch.isalnum() or ch in "-_"


def test_verifier_is_unique_across_calls() -> None:
    vs = {generate_code_verifier() for _ in range(16)}
    assert len(vs) == 16


def test_challenge_matches_rfc_example() -> None:
    # RFC 7636 §4.2 example
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert compute_code_challenge(verifier) == expected


def test_verify_pair_accepts_matching() -> None:
    v = generate_code_verifier()
    c = compute_code_challenge(v)
    verify_pair(v, c)  # does not raise


def test_verify_pair_rejects_mismatched() -> None:
    v1 = generate_code_verifier()
    v2 = generate_code_verifier()
    with pytest.raises(OidcPkceMismatch):
        verify_pair(v1, compute_code_challenge(v2))


def test_challenge_is_url_safe_base64_no_padding() -> None:
    c = compute_code_challenge("any-verifier")
    assert "=" not in c
    # Round-trip to bytes
    padded = c + "=" * (-len(c) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 32
    assert raw == hashlib.sha256(b"any-verifier").digest()
