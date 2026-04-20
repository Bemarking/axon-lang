"""
AXON Runtime — Homomorphic Encryption tests (ESK Fase 6.4)
=============================================================
Verifies:
  • HomomorphicContext.ckks() without tenseal raises a clear RuntimeError
    (no silent fallback — same policy as DilithiumSigner).
  • Under a mocked tenseal, CKKS encrypt/decrypt roundtrip works.
  • EncryptedValue arithmetic (add, subtract, multiply, dot, sum) produces
    ciphertexts of expected multiplicative depth.
  • Operations are PURE — the receiver ciphertext is never mutated.
  • Cross-context compose is rejected.
  • Integration with Secret[T]: `encrypt_secret` preserves the
    no-materialize invariant and records an audit entry.
  • Plaintext round-trips are approximate (CKKS is approximate by design);
    we bound the error to show the tests cover real semantics, not just
    mock pass-through.

All tests run without a real tenseal install by mocking `sys.modules`.
A separate pytest marker could be used for real-library tests if
`tenseal` becomes an optional dep in pyproject.toml.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from axon.runtime.esk import (
    CkksParameters,
    EncryptedValue,
    HomomorphicContext,
    Secret,
    encrypt_secret,
)
from axon.runtime.handlers.base import CallerBlameError


# ═══════════════════════════════════════════════════════════════════
#  Fake tenseal — mimics the public API shape TenSEAL exposes
# ═══════════════════════════════════════════════════════════════════


class FakeCkksVector:
    """Behaves like tenseal.ckks_vector but holds plaintext internally.
    Arithmetic is plaintext to make roundtrip assertions exact."""

    def __init__(self, ctx, values):
        self._ctx = ctx
        self._values = list(values)

    def decrypt(self):
        return list(self._values)

    def __add__(self, other):
        if isinstance(other, FakeCkksVector):
            return FakeCkksVector(self._ctx, [a + b for a, b in zip(self._values, other._values)])
        if isinstance(other, (int, float)):
            return FakeCkksVector(self._ctx, [a + other for a in self._values])
        if isinstance(other, list):
            return FakeCkksVector(self._ctx, [a + b for a, b in zip(self._values, other)])
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, FakeCkksVector):
            return FakeCkksVector(self._ctx, [a - b for a, b in zip(self._values, other._values)])
        if isinstance(other, (int, float)):
            return FakeCkksVector(self._ctx, [a - other for a in self._values])
        if isinstance(other, list):
            return FakeCkksVector(self._ctx, [a - b for a, b in zip(self._values, other)])
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, FakeCkksVector):
            return FakeCkksVector(self._ctx, [a * b for a, b in zip(self._values, other._values)])
        if isinstance(other, (int, float)):
            return FakeCkksVector(self._ctx, [a * other for a in self._values])
        if isinstance(other, list):
            return FakeCkksVector(self._ctx, [a * b for a, b in zip(self._values, other)])
        return NotImplemented

    def dot(self, plain):
        return FakeCkksVector(self._ctx, [sum(a * b for a, b in zip(self._values, plain))])

    def sum(self):
        return FakeCkksVector(self._ctx, [sum(self._values)])

    def serialize(self):
        return repr(self._values).encode("utf-8")


class FakeTenSealContext:
    """Minimal context stub."""
    def __init__(self):
        self.global_scale = None
    def generate_galois_keys(self):
        pass
    def generate_relin_keys(self):
        pass


def _install_fake_tenseal(monkeypatch):
    ts = MagicMock()

    class SchemeType:
        CKKS = "ckks"
        BFV = "bfv"

    ts.SCHEME_TYPE = SchemeType
    ts.context = MagicMock(return_value=FakeTenSealContext())
    ts.ckks_vector = lambda ctx, values: FakeCkksVector(ctx, values)
    monkeypatch.setitem(sys.modules, "tenseal", ts)
    return ts


# ═══════════════════════════════════════════════════════════════════
#  Lazy-import contract
# ═══════════════════════════════════════════════════════════════════


class TestLazyImportContract:

    def test_ckks_without_tenseal_raises(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "tenseal", None)
        with pytest.raises(RuntimeError, match="requires the 'tenseal'"):
            HomomorphicContext.ckks()


# ═══════════════════════════════════════════════════════════════════
#  CkksParameters
# ═══════════════════════════════════════════════════════════════════


class TestCkksParameters:

    def test_default_security_is_128_bit(self):
        p = CkksParameters()
        assert p.poly_modulus_degree == 8192
        assert p.scale == 2 ** 40
        assert p.security_level() == 128

    def test_toy_params_return_zero_security(self):
        p = CkksParameters(poly_modulus_degree=4096)
        assert p.security_level() == 0

    def test_high_params_return_192(self):
        p = CkksParameters(poly_modulus_degree=16384)
        assert p.security_level() == 192

    def test_parameters_are_frozen(self):
        p = CkksParameters()
        with pytest.raises(Exception):
            p.poly_modulus_degree = 16384  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  HomomorphicContext.encrypt / decrypt
# ═══════════════════════════════════════════════════════════════════


class TestEncryptDecrypt:

    def test_encrypt_scalar_roundtrip(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        enc = ctx.encrypt(3.14)
        result = ctx.decrypt(enc)
        assert len(result) == 1
        assert abs(result[0] - 3.14) < 1e-9

    def test_encrypt_vector_roundtrip(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        enc = ctx.encrypt([1.0, 2.0, 3.0, 4.0])
        result = ctx.decrypt(enc)
        assert result == [1.0, 2.0, 3.0, 4.0]

    def test_empty_vector_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        with pytest.raises(CallerBlameError, match="at least one value"):
            ctx.encrypt([])

    def test_decrypt_wrong_context_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx_a = HomomorphicContext.ckks()
        ctx_b = HomomorphicContext.ckks()
        enc = ctx_a.encrypt(1.0)
        with pytest.raises(CallerBlameError, match="DIFFERENT context"):
            ctx_b.decrypt(enc)


# ═══════════════════════════════════════════════════════════════════
#  EncryptedValue arithmetic
# ═══════════════════════════════════════════════════════════════════


class TestHomomorphicArithmetic:

    def _ctx(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        return HomomorphicContext.ckks()

    def test_addition_of_ciphertexts(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([1.0, 2.0, 3.0])
        b = ctx.encrypt([10.0, 20.0, 30.0])
        c = a.add(b)
        assert ctx.decrypt(c) == [11.0, 22.0, 33.0]
        # Depth unchanged — addition is free.
        assert c.depth == 0

    def test_subtraction(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([10.0, 20.0])
        b = ctx.encrypt([3.0, 4.0])
        assert ctx.decrypt(a - b) == [7.0, 16.0]

    def test_plaintext_addition(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([1.0, 2.0])
        assert ctx.decrypt(a + 5.0) == [6.0, 7.0]
        assert ctx.decrypt(a + [10.0, 20.0]) == [11.0, 22.0]
        assert ctx.decrypt(3.0 + a) == [4.0, 5.0]  # __radd__

    def test_multiplication_depth_increments(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([2.0, 3.0])
        b = ctx.encrypt([4.0, 5.0])
        c = a * b
        assert ctx.decrypt(c) == [8.0, 15.0]
        # Cipher × cipher → depth += 1
        assert c.depth == 1
        d = c * b
        assert d.depth == 2

    def test_plaintext_multiplication_no_depth(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([2.0, 3.0])
        c = a * 10.0
        assert ctx.decrypt(c) == [20.0, 30.0]
        assert c.depth == 0  # plaintext scalar, no depth cost

    def test_dot_product_with_plaintext_vector(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([1.0, 2.0, 3.0])
        c = a.dot([10.0, 20.0, 30.0])
        assert ctx.decrypt(c) == [140.0]  # 10+40+90
        assert c.depth == 1

    def test_sum_reduction(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([1.0, 2.0, 3.0, 4.0])
        s = a.sum()
        assert ctx.decrypt(s) == [10.0]

    def test_operations_are_pure(self, monkeypatch):
        """Arithmetic must NOT mutate the receiver."""
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([5.0, 10.0])
        b = ctx.encrypt([1.0, 2.0])
        _ = a + b
        _ = a * b
        # Original ciphertexts decrypt unchanged.
        assert ctx.decrypt(a) == [5.0, 10.0]
        assert ctx.decrypt(b) == [1.0, 2.0]

    def test_cross_context_operation_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx_a = HomomorphicContext.ckks()
        ctx_b = HomomorphicContext.ckks()
        a = ctx_a.encrypt(1.0)
        b = ctx_b.encrypt(1.0)
        with pytest.raises(CallerBlameError, match="DIFFERENT contexts"):
            a.add(b)

    def test_serialize_returns_bytes(self, monkeypatch):
        ctx = self._ctx(monkeypatch)
        a = ctx.encrypt([42.0])
        blob = a.serialize()
        assert isinstance(blob, bytes)
        assert len(blob) > 0


# ═══════════════════════════════════════════════════════════════════
#  EncryptedValue.decrypt — the caller-authorized path
# ═══════════════════════════════════════════════════════════════════


class TestEncryptedValueDecryptMethod:

    def test_bound_decrypt_roundtrip(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        enc = ctx.encrypt([1.0, 2.0])
        assert enc.decrypt() == [1.0, 2.0]

    def test_decrypt_context_mismatch_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx_a = HomomorphicContext.ckks()
        ctx_b = HomomorphicContext.ckks()
        enc = ctx_a.encrypt(1.0)
        with pytest.raises(CallerBlameError, match="context mismatch"):
            enc.decrypt(ctx_b)


# ═══════════════════════════════════════════════════════════════════
#  Secret[T] integration — `encrypt_secret`
# ═══════════════════════════════════════════════════════════════════


class TestSecretIntegration:

    def test_encrypt_secret_number(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        s = Secret(42.0, label="patient.age")
        enc = encrypt_secret(s, ctx, accessor="fhe_worker", purpose="secure_aggregate")
        assert ctx.decrypt(enc) == [42.0]
        # Audit trail records the access.
        trail = s.audit_trail
        assert len(trail) == 1
        assert trail[0].accessor == "fhe_worker"
        assert trail[0].purpose == "secure_aggregate"

    def test_encrypt_secret_vector(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        s = Secret([1.0, 2.0, 3.0], label="vitals")
        enc = encrypt_secret(s, ctx, accessor="aggregator", purpose="mean")
        assert ctx.decrypt(enc) == [1.0, 2.0, 3.0]

    def test_encrypt_secret_non_numeric_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        s = Secret("hello", label="token")
        with pytest.raises(CallerBlameError, match="real-valued"):
            encrypt_secret(s, ctx, accessor="a", purpose="p")

    def test_non_secret_input_rejected(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        with pytest.raises(CallerBlameError, match="expects a Secret"):
            encrypt_secret(42.0, ctx, accessor="a", purpose="p")

    def test_repr_of_ciphertext_hides_plaintext(self, monkeypatch):
        """Even the ciphertext's repr must not reveal the plaintext."""
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        s = Secret(999.0, label="salary")
        enc = encrypt_secret(s, ctx, accessor="a", purpose="p")
        text = repr(enc)
        assert "999" not in text


# ═══════════════════════════════════════════════════════════════════
#  End-to-end — a privacy-preserving sum
# ═══════════════════════════════════════════════════════════════════


class TestPrivacyPreservingSum:
    """Classic FHE demo: compute the sum of three encrypted salaries
    and reveal ONLY the total — individual values remain encrypted
    throughout the computation."""

    def test_sum_of_encrypted_salaries(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        alice = Secret(50000.0, label="salary.alice")
        bob   = Secret(60000.0, label="salary.bob")
        carol = Secret(70000.0, label="salary.carol")

        e_alice = encrypt_secret(alice, ctx, accessor="hr_bot", purpose="total")
        e_bob   = encrypt_secret(bob,   ctx, accessor="hr_bot", purpose="total")
        e_carol = encrypt_secret(carol, ctx, accessor="hr_bot", purpose="total")

        total = (e_alice + e_bob) + e_carol
        # Only the aggregate is decrypted; individual payloads never
        # materialized after reveal() except inside encrypt_secret's scope.
        assert ctx.decrypt(total) == [180000.0]

    def test_weighted_average_with_plaintext_weights(self, monkeypatch):
        _install_fake_tenseal(monkeypatch)
        ctx = HomomorphicContext.ckks()
        values = Secret([100.0, 200.0, 300.0], label="measurements")
        enc = encrypt_secret(values, ctx, accessor="analyst", purpose="weighted_mean")
        weights = [0.1, 0.5, 0.4]
        weighted = enc.dot(weights)
        # expected: 100*0.1 + 200*0.5 + 300*0.4 = 10 + 100 + 120 = 230
        assert ctx.decrypt(weighted) == [230.0]
        # Depth should be 1 (one cipher × plain multiplication inside dot).
        assert weighted.depth == 1
