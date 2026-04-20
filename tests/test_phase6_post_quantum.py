"""
AXON Runtime — Post-Quantum cryptography tests (ESK Fase 6.3)
================================================================
Verifies:
  • DilithiumSigner lazy-imports `oqs` and raises a clear error when
    the library is absent (no silent fallback).
  • DilithiumSigner roundtrip works under a fake `oqs` (mocked in
    sys.modules) — we do not require a real liboqs install in CI.
  • HybridSigner composes a classical + post-quantum signer per
    NIST SP 800-208 transition-safe posture: both signatures must
    validate for verify() to return True.
  • HybridSigner wire format is stable (2-byte length-prefixed
    components) so downstream tools can parse without running Axon.
"""

from __future__ import annotations

import hashlib
import sys
from unittest.mock import MagicMock

import pytest

from axon.runtime.esk import (
    DilithiumSigner,
    HmacSigner,
    HybridSigner,
    ProvenanceChain,
)


# ═══════════════════════════════════════════════════════════════════
#  DilithiumSigner — lazy-import contract
# ═══════════════════════════════════════════════════════════════════


class TestDilithiumSignerLazyImport:

    def test_constructor_without_oqs_raises_runtime_error(self, monkeypatch):
        """No silent fallback — explicit failure when `oqs` missing."""
        monkeypatch.setitem(sys.modules, "oqs", None)
        with pytest.raises(RuntimeError, match="requires the 'oqs'"):
            DilithiumSigner(public_key=b"stub", secret_key=b"stub")

    def test_generate_without_oqs_raises(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "oqs", None)
        with pytest.raises(RuntimeError, match="requires 'oqs'"):
            DilithiumSigner.generate()


# ═══════════════════════════════════════════════════════════════════
#  DilithiumSigner — behaviour under a mocked oqs
# ═══════════════════════════════════════════════════════════════════


def _install_fake_oqs(monkeypatch):
    """Install a minimal mock of the `oqs` API that mimics Dilithium behaviour."""
    fake_module = MagicMock()

    class FakeSignature:
        """Context-manager mock for `oqs.Signature(...)`."""

        def __init__(self, algo, secret_key=None):
            self.algo = algo
            self._sk = secret_key

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def generate_keypair(self):
            return b"pk-" + self.algo.encode()

        def export_secret_key(self):
            return b"sk-" + self.algo.encode()

        def sign(self, message):
            # deterministic stub: sk + message hash
            return b"sig-" + hashlib.sha256(message).digest()

        def verify(self, message, signature, public_key):
            return signature == b"sig-" + hashlib.sha256(message).digest()

    fake_module.Signature = FakeSignature
    monkeypatch.setitem(sys.modules, "oqs", fake_module)
    return fake_module


class TestDilithiumSignerBehaviour:

    def test_generate_produces_keypair(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        signer = DilithiumSigner.generate()
        assert signer.public_key.startswith(b"pk-")
        assert signer._secret_key.startswith(b"sk-")
        assert signer.algorithm == "ML-DSA-65"

    def test_sign_verify_roundtrip(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        signer = DilithiumSigner.generate()
        msg = b"transfer-USD-100000-to-account-X"
        sig = signer.sign(msg)
        assert signer.verify(msg, sig)

    def test_verify_rejects_tampered_message(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        signer = DilithiumSigner.generate()
        sig = signer.sign(b"original")
        assert not signer.verify(b"tampered", sig)

    def test_verify_rejects_tampered_signature(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        signer = DilithiumSigner.generate()
        sig = signer.sign(b"message")
        assert not signer.verify(b"message", sig + b"!")

    def test_verify_only_instance_cannot_sign(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        original = DilithiumSigner.generate()
        verify_only = DilithiumSigner(public_key=original.public_key, secret_key=None)
        with pytest.raises(RuntimeError, match="no secret key"):
            verify_only.sign(b"msg")
        # But verifying with the original's signature still works:
        sig = original.sign(b"msg")
        assert verify_only.verify(b"msg", sig)


# ═══════════════════════════════════════════════════════════════════
#  HybridSigner — composition contract
# ═══════════════════════════════════════════════════════════════════


class TestHybridSigner:

    def test_algorithm_name_composes_components(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        classical = HmacSigner.random()
        pq = DilithiumSigner.generate()
        hybrid = HybridSigner(classical=classical, post_quantum=pq)
        assert "HMAC-SHA256" in hybrid.algorithm
        assert "ML-DSA-65" in hybrid.algorithm

    def test_sign_verify_roundtrip(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        hybrid = HybridSigner(
            classical=HmacSigner.random(),
            post_quantum=DilithiumSigner.generate(),
        )
        msg = b"regulated-payment-event"
        sig = hybrid.sign(msg)
        assert hybrid.verify(msg, sig)

    def test_classical_failure_rejects_signature(self, monkeypatch):
        """If the classical half fails to verify, the hybrid FAILS — both must pass."""
        _install_fake_oqs(monkeypatch)
        hybrid_a = HybridSigner(
            classical=HmacSigner(key=b"k" * 32),
            post_quantum=DilithiumSigner.generate(),
        )
        hybrid_b = HybridSigner(
            classical=HmacSigner(key=b"DIFFERENT_KEY_____32_BYTES______"),
            post_quantum=DilithiumSigner.generate(),
        )
        msg = b"attack-on-classical-half"
        sig = hybrid_a.sign(msg)
        # hybrid_b has different HMAC key → classical half fails → hybrid fails
        assert not hybrid_b.verify(msg, sig)

    def test_wire_format_is_length_prefixed(self, monkeypatch):
        """Verify the 2-byte big-endian length prefix of each component."""
        _install_fake_oqs(monkeypatch)
        hybrid = HybridSigner(
            classical=HmacSigner.random(),
            post_quantum=DilithiumSigner.generate(),
        )
        sig = hybrid.sign(b"msg")
        len_c = int.from_bytes(sig[:2], "big")
        # The rest after classical must start with another 2-byte length.
        tail = sig[2 + len_c:]
        len_q = int.from_bytes(tail[:2], "big")
        assert len(tail) == 2 + len_q  # exact fit — no extra bytes

    def test_malformed_signature_rejected(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        hybrid = HybridSigner(
            classical=HmacSigner.random(),
            post_quantum=DilithiumSigner.generate(),
        )
        assert not hybrid.verify(b"msg", b"\x00\x00\x00")  # truncated garbage


# ═══════════════════════════════════════════════════════════════════
#  Integration: HybridSigner drops into ProvenanceChain
# ═══════════════════════════════════════════════════════════════════


class TestHybridWithProvenanceChain:

    def test_provenance_chain_with_hybrid_signer(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        hybrid = HybridSigner(
            classical=HmacSigner.random(),
            post_quantum=DilithiumSigner.generate(),
        )
        chain = ProvenanceChain(hybrid)
        chain.append({"event": "login", "user": "alice"})
        chain.append({"event": "transfer", "amount": 100})
        assert chain.verify([
            {"event": "login", "user": "alice"},
            {"event": "transfer", "amount": 100},
        ])
        # Tampering still detected — signatures bind to payload hashes.
        assert not chain.verify([
            {"event": "login", "user": "alice"},
            {"event": "transfer", "amount": 999},  # tampered
        ])

    def test_chain_algorithm_reports_hybrid(self, monkeypatch):
        _install_fake_oqs(monkeypatch)
        hybrid = HybridSigner(
            classical=HmacSigner.random(),
            post_quantum=DilithiumSigner.generate(),
        )
        chain = ProvenanceChain(hybrid)
        entry = chain.append({"k": 1})
        assert "HMAC-SHA256" in entry.algorithm
        assert "ML-DSA-65" in entry.algorithm
