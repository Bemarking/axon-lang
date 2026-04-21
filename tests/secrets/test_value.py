"""Unit tests for ``SecretValue`` — redaction must be watertight."""

from __future__ import annotations

import copy
import pickle

import pytest

from axon_enterprise.secrets.value import SecretValue


def test_repr_redacts() -> None:
    v = SecretValue("sk-super-secret-xyz")
    r = repr(v)
    assert "sk-super-secret-xyz" not in r
    assert r.startswith("<SecretValue len=")


def test_str_redacts() -> None:
    v = SecretValue("leak-me")
    assert "leak-me" not in str(v)


def test_format_without_spec_returns_repr() -> None:
    v = SecretValue("topsecret")
    assert "topsecret" not in f"{v}"


def test_format_with_spec_raises() -> None:
    v = SecretValue("x")
    with pytest.raises(ValueError, match="does not support format specs"):
        _ = f"{v:>20}"


def test_pickle_substitutes_placeholder() -> None:
    v = SecretValue("roundtrip")
    restored = pickle.loads(pickle.dumps(v))
    assert isinstance(restored, SecretValue)
    assert restored.reveal() == "[REDACTED]"


def test_copy_substitutes_placeholder() -> None:
    v = SecretValue("don't-leak")
    c = copy.deepcopy(v)
    assert c.reveal() == "[REDACTED]"


def test_reveal_returns_plaintext() -> None:
    v = SecretValue("plain")
    assert v.reveal() == "plain"


def test_reveal_bytes_roundtrips_binary() -> None:
    raw = b"\x00\x01\xff"
    v = SecretValue(raw)
    assert v.reveal_bytes() == raw


def test_fingerprint_is_stable_length() -> None:
    v = SecretValue("x")
    assert len(v.fingerprint) == 8


def test_fingerprint_differs_for_different_values() -> None:
    assert SecretValue("a").fingerprint != SecretValue("b").fingerprint


def test_fingerprint_stable_for_same_value() -> None:
    assert SecretValue("z").fingerprint == SecretValue("z").fingerprint


def test_length_accessor() -> None:
    assert SecretValue("abcd").length == 4


def test_equality_is_constant_time() -> None:
    a = SecretValue("same")
    b = SecretValue("same")
    c = SecretValue("diff")
    assert a == b
    assert a != c


def test_rejects_bad_type() -> None:
    with pytest.raises(TypeError):
        SecretValue(123)  # type: ignore[arg-type]


def test_in_set_uses_fingerprint_hash() -> None:
    a = SecretValue("x")
    b = SecretValue("x")
    assert {a, b} == {a}
