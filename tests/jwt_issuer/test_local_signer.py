"""Unit tests for LocalSigner."""

from __future__ import annotations

import base64

import jwt
import pytest

from axon_enterprise.jwt_issuer.errors import JwtSigningFailed
from axon_enterprise.jwt_issuer.local_signer import (
    LocalSigner,
    _derive_kid,
    b64url_no_pad,
)


@pytest.fixture
def signer() -> LocalSigner:
    return LocalSigner.generate()


def test_generate_produces_usable_signer(signer: LocalSigner) -> None:
    assert signer.info.algorithm == "RS256"
    assert len(signer.info.kid) == 16
    assert "BEGIN PUBLIC KEY" in signer.info.public_key_pem


def test_kid_is_deterministic_across_instances(signer: LocalSigner) -> None:
    # Round-tripping the private PEM must yield the same kid.
    pem = signer.export_private_key_pem().decode("ascii")
    other = LocalSigner.from_pem(pem)
    assert other.info.kid == signer.info.kid


def test_sign_produces_verifiable_jwt(signer: LocalSigner) -> None:
    # Build a toy JWT manually (matches JwtIssuer shape) + verify via PyJWT.
    import json

    header = {"alg": "RS256", "typ": "JWT", "kid": signer.info.kid}
    claims = {"sub": "user:1", "iss": "t", "aud": "a"}
    signing_input = (
        b64url_no_pad(json.dumps(header, sort_keys=True).encode()).encode()
        + b"."
        + b64url_no_pad(json.dumps(claims, sort_keys=True).encode()).encode()
    )
    sig = signer.sign(signing_input)
    token = signing_input.decode() + "." + b64url_no_pad(sig)
    decoded = jwt.decode(
        token,
        signer.info.public_key_pem,
        algorithms=[signer.info.algorithm],
        audience="a",
        issuer="t",
    )
    assert decoded["sub"] == "user:1"


def test_non_rsa_key_rejected() -> None:
    # Feed an EC key PEM to from_pem → must reject.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_priv = ec.generate_private_key(ec.SECP256R1())
    pem = ec_priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    with pytest.raises(JwtSigningFailed, match="RSA"):
        LocalSigner.from_pem(pem)


def test_b64url_no_pad_strips_padding() -> None:
    assert b64url_no_pad(b"\x00") == "AA"
    assert b64url_no_pad(b"abc") == "YWJj"


def test_derive_kid_stable_across_calls() -> None:
    pem = LocalSigner.generate().info.public_key_pem
    assert _derive_kid(pem) == _derive_kid(pem)
    assert len(_derive_kid(pem)) == 16


def test_sign_raises_typed_error_on_failure() -> None:
    # Construct a signer whose private key we then break — simplest is
    # to patch the ``_private_key`` attribute to None and confirm error
    # propagation path.
    signer = LocalSigner.generate()
    signer.__dict__["_private_key"] = None  # type: ignore[assignment]
    with pytest.raises(JwtSigningFailed):
        signer.sign(b"hello")
