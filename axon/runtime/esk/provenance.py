"""
AXON Runtime — Cryptographic Provenance (ESK Fase 6.2)
========================================================
Signed ΛD envelopes + Merkle-hash audit chain.

Design
------
Every `HandlerOutcome`, `HealthReport`, and `ReconcileTickReport` carries
a ΛD envelope ⟨c, τ, ρ, δ⟩.  ESK §6.2 extends this with an optional
`signature` ρ′ bound to `(c, τ, ρ, δ, data_hash)` using a symmetric HMAC
baseline.  Installations that need non-repudiation plug in an asymmetric
signer (Ed25519, Dilithium3 — see `sign_ed25519` hook).

Merkle Chain
------------
A `ProvenanceChain` accumulates signed entries as a hash-linked ledger:

    h_0 = H("genesis")
    h_i = H(h_{i-1} || entry_i_canonical)

Any tampering of a past entry invalidates every subsequent hash.  The
chain is verifiable in O(n) without any external trust anchor.

Runtime
-------
This module is dependency-free.  Ed25519 / Dilithium are optional via
`cryptography` / `oqs` libraries when available; absent that, HMAC is
authoritative.  Both flavours share the `Signer` protocol.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol


# ═══════════════════════════════════════════════════════════════════
#  Signer protocol — HMAC baseline + pluggable asymmetric
# ═══════════════════════════════════════════════════════════════════

class Signer(Protocol):
    algorithm: str

    def sign(self, message: bytes) -> bytes: ...
    def verify(self, message: bytes, signature: bytes) -> bool: ...


@dataclass
class HmacSigner:
    """Symmetric HMAC-SHA256 signer — the baseline always available."""
    key: bytes
    algorithm: str = "HMAC-SHA256"

    @classmethod
    def random(cls) -> "HmacSigner":
        return cls(key=secrets.token_bytes(32))

    def sign(self, message: bytes) -> bytes:
        return hmac.new(self.key, message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        expected = self.sign(message)
        return hmac.compare_digest(expected, signature)


@dataclass
class Ed25519Signer:
    """Asymmetric signer using ``cryptography``'s Ed25519 — opt-in.

    Falls back at import-time if the library is unavailable; operators
    must wire this explicitly (we do not silently enable non-repudiation
    without confirmation — §6.2 is a forensic contract).
    """
    private_key: Any  # cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey
    public_key: Any
    algorithm: str = "Ed25519"

    @classmethod
    def generate(cls) -> "Ed25519Signer":
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Ed25519Signer requires the 'cryptography' package. "
                "Install with `pip install cryptography`."
            ) from exc
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return cls(private_key=private_key, public_key=public_key)

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self.public_key.verify(signature, message)
            return True
        except Exception:  # noqa: BLE001
            return False


# ═══════════════════════════════════════════════════════════════════
#  Post-Quantum — ESK Fase 6.3 (NIST FIPS 204 / Dilithium3)
# ═══════════════════════════════════════════════════════════════════

class DilithiumSigner:
    """
    ML-DSA-65 (formerly Dilithium3) signer — NIST FIPS 204 post-quantum
    standard.  Opt-in: requires the `oqs` (Open Quantum Safe) library.

    Dilithium is **quantum-resistant** under the NIST PQC standardization
    (ratified 2024).  Banking and government adopters with PQ migration
    mandates (OMB M-23-02, BSI, ANSSI) can drop this signer into any
    `ProvenanceChain` or `sign_envelope()` call that currently uses HMAC
    or Ed25519 — zero code changes beyond the constructor.

    Fallback philosophy: absent `oqs`, this class raises at instantiation
    time.  There is NO silent fallback to a non-PQ algorithm — a
    deployment that asked for Dilithium gets Dilithium or an error.
    """

    algorithm: str = "ML-DSA-65"

    def __init__(self, *, public_key: bytes, secret_key: bytes | None) -> None:
        try:
            import oqs  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "DilithiumSigner requires the 'oqs' (Open Quantum Safe) package. "
                "Install via `pip install liboqs-python` after installing liboqs "
                "(https://github.com/open-quantum-safe/liboqs)."
            ) from exc
        self._oqs = oqs
        self.public_key = public_key
        self._secret_key = secret_key  # None for verify-only instances

    @classmethod
    def generate(cls) -> "DilithiumSigner":
        """Generate a fresh (pk, sk) pair."""
        try:
            import oqs  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "DilithiumSigner.generate requires 'oqs'. "
                "See class docstring for install instructions."
            ) from exc
        with oqs.Signature("ML-DSA-65") as signer:
            pk = signer.generate_keypair()
            sk = signer.export_secret_key()
        return cls(public_key=pk, secret_key=sk)

    def sign(self, message: bytes) -> bytes:
        if self._secret_key is None:
            raise RuntimeError("DilithiumSigner has no secret key — verify-only instance")
        with self._oqs.Signature("ML-DSA-65", self._secret_key) as signer:
            return signer.sign(message)

    def verify(self, message: bytes, signature: bytes) -> bool:
        with self._oqs.Signature("ML-DSA-65") as verifier:
            try:
                return bool(verifier.verify(message, signature, self.public_key))
            except Exception:  # noqa: BLE001
                return False


# ═══════════════════════════════════════════════════════════════════
#  Hybrid signer — classical + post-quantum, NIST transition-safe
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HybridSigner:
    """
    Dual-signature hybrid: every `sign()` produces a classical signature
    AND a post-quantum signature concatenated with a 2-byte length prefix
    for each component.  Verification requires BOTH signatures to validate.

    This is the NIST-recommended transition posture (SP 800-208): run
    classical AND PQ in parallel so that a break of either algorithm does
    not compromise the signature.  Once PQ algorithms mature, operators
    can drop to PQ-only by replacing `HybridSigner` with `DilithiumSigner`
    with no caller-side changes.

    Wire format:
        [2 bytes len(classical)][classical bytes][2 bytes len(pq)][pq bytes]

    Both component signers must implement the `Signer` protocol.
    """

    classical: Signer
    post_quantum: Signer
    algorithm: str = "Hybrid(classical+PQ)"

    def __post_init__(self) -> None:
        self.algorithm = f"Hybrid({self.classical.algorithm}+{self.post_quantum.algorithm})"

    def sign(self, message: bytes) -> bytes:
        sig_c = self.classical.sign(message)
        sig_q = self.post_quantum.sign(message)
        if len(sig_c) > 0xFFFF or len(sig_q) > 0xFFFF:
            raise ValueError(
                f"hybrid signer: component signature > 65535 bytes "
                f"(classical={len(sig_c)}, pq={len(sig_q)})"
            )
        return (
            len(sig_c).to_bytes(2, "big")
            + sig_c
            + len(sig_q).to_bytes(2, "big")
            + sig_q
        )

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            len_c = int.from_bytes(signature[:2], "big")
            sig_c = signature[2:2 + len_c]
            offset = 2 + len_c
            len_q = int.from_bytes(signature[offset:offset + 2], "big")
            sig_q = signature[offset + 2:offset + 2 + len_q]
        except Exception:  # noqa: BLE001
            return False
        return (
            self.classical.verify(message, sig_c)
            and self.post_quantum.verify(message, sig_q)
        )


# ═══════════════════════════════════════════════════════════════════
#  Canonical serialization — signatures cover deterministic JSON
# ═══════════════════════════════════════════════════════════════════

def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding: sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(payload: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonical serialization."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# ═══════════════════════════════════════════════════════════════════
#  Signed entry + provenance chain
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SignedEntry:
    """One tamper-evident entry in a provenance chain."""
    index: int
    previous_hash: str
    payload_hash: str
    signature_hex: str
    algorithm: str
    chain_hash: str        # SHA-256(previous_hash || payload_hash || signature)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "payload_hash": self.payload_hash,
            "signature": self.signature_hex,
            "algorithm": self.algorithm,
            "chain_hash": self.chain_hash,
        }


GENESIS_HASH = "0" * 64


class ProvenanceChain:
    """Append-only Merkle chain over canonical payloads.

    Thread-safety is the caller's responsibility; the primary use case is
    per-request, per-handler or per-run where a single writer owns the
    chain.
    """

    def __init__(self, signer: Signer) -> None:
        self.signer = signer
        self._entries: list[SignedEntry] = []

    @property
    def head(self) -> str:
        return self._entries[-1].chain_hash if self._entries else GENESIS_HASH

    def append(self, payload: dict[str, Any]) -> SignedEntry:
        payload_bytes = canonical_bytes(payload)
        payload_h = hashlib.sha256(payload_bytes).hexdigest()
        prev = self.head
        message = f"{prev}|{payload_h}".encode("ascii")
        signature = self.signer.sign(message)
        chain_h = hashlib.sha256(
            f"{prev}|{payload_h}|{signature.hex()}".encode("ascii")
        ).hexdigest()
        entry = SignedEntry(
            index=len(self._entries),
            previous_hash=prev,
            payload_hash=payload_h,
            signature_hex=signature.hex(),
            algorithm=self.signer.algorithm,
            chain_hash=chain_h,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> list[SignedEntry]:
        return list(self._entries)

    def verify(self, payloads: Iterable[dict[str, Any]]) -> bool:
        """Re-derive chain hashes from supplied payloads and verify each
        signature + linkage.  `payloads` must be presented in the same
        order they were appended.
        """
        prev = GENESIS_HASH
        for i, (entry, payload) in enumerate(zip(self._entries, payloads)):
            payload_bytes = canonical_bytes(payload)
            payload_h = hashlib.sha256(payload_bytes).hexdigest()
            if payload_h != entry.payload_hash:
                return False
            if entry.previous_hash != prev:
                return False
            message = f"{prev}|{payload_h}".encode("ascii")
            try:
                sig = bytes.fromhex(entry.signature_hex)
            except ValueError:
                return False
            if not self.signer.verify(message, sig):
                return False
            recomputed_chain = hashlib.sha256(
                f"{prev}|{payload_h}|{entry.signature_hex}".encode("ascii")
            ).hexdigest()
            if recomputed_chain != entry.chain_hash:
                return False
            prev = entry.chain_hash
        return True


# ═══════════════════════════════════════════════════════════════════
#  Signed envelope helper — wraps any ΛD-bearing outcome
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SignedEnvelope:
    """A cryptographically signed ΛD envelope, parallel to LambdaEnvelope
    but with a provenance signature bound to (c, τ, ρ, δ, data)."""
    c: float
    tau: str
    rho: str
    delta: str
    data_hash: str
    signature_hex: str
    algorithm: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "c": self.c, "tau": self.tau, "rho": self.rho, "delta": self.delta,
            "data_hash": self.data_hash,
            "signature": self.signature_hex,
            "algorithm": self.algorithm,
        }


def sign_envelope(
    *,
    c: float,
    tau: str,
    rho: str,
    delta: str,
    data: dict[str, Any],
    signer: Signer,
) -> SignedEnvelope:
    data_h = content_hash(data)
    message = canonical_bytes({
        "c": c, "tau": tau, "rho": rho, "delta": delta, "data_hash": data_h,
    })
    signature = signer.sign(message)
    return SignedEnvelope(
        c=c, tau=tau, rho=rho, delta=delta,
        data_hash=data_h,
        signature_hex=signature.hex(),
        algorithm=signer.algorithm,
    )


def verify_envelope(
    envelope: SignedEnvelope,
    data: dict[str, Any],
    signer: Signer,
) -> bool:
    data_h = content_hash(data)
    if data_h != envelope.data_hash:
        return False
    message = canonical_bytes({
        "c": envelope.c, "tau": envelope.tau, "rho": envelope.rho,
        "delta": envelope.delta, "data_hash": data_h,
    })
    try:
        signature = bytes.fromhex(envelope.signature_hex)
    except ValueError:
        return False
    return signer.verify(message, signature)


__all__ = [
    "DilithiumSigner",
    "Ed25519Signer",
    "GENESIS_HASH",
    "HmacSigner",
    "HybridSigner",
    "ProvenanceChain",
    "SignedEnvelope",
    "SignedEntry",
    "Signer",
    "canonical_bytes",
    "content_hash",
    "sign_envelope",
    "verify_envelope",
]
