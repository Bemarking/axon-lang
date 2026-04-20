# FIPS 140-3 — Cryptographic Module Submission Template
## Scaffold for a potential CMVP validation of AXON's ESK cryptographic boundary

> **Scope:** Describes the AXON cryptographic boundary that would be submitted to NIST's Cryptographic Module Validation Program (CMVP) under FIPS 140-3. This is a **pre-validation scaffold** — not a validated module.

> **Canonical reference:** NIST FIPS 140-3 (2019), NIST SP 800-140 (DTR 2022), ISO/IEC 19790:2012.

---

## 1. Cryptographic module definition

### 1.1 Module name

**AXON Epistemic Security Kernel — Cryptographic Boundary (ESK-CB)**

### 1.2 Scope of the boundary

The ESK-CB is the smallest self-contained subset of AXON that performs cryptographic operations:

```
axon/runtime/esk/provenance.py       — HmacSigner, Ed25519Signer, ProvenanceChain
axon/runtime/esk/secret.py           — SHA-256 fingerprints for Secret[T]
axon/runtime/esk/attestation.py      — SHA-256 for SBOM content hashes
```

Excluded: compiler, handlers (Fase 2), immune/reflex/heal (Fase 5), network transport (left to the operator's FIPS-validated TLS stack).

### 1.3 Module type

**Software module** — implemented in pure Python 3.12+ with optional `cryptography` library dependency for Ed25519.

### 1.4 Security level claim

Target: **Security Level 1** (entry level) — software module with no physical security requirements. Future targets (Level 2+ with tamper evidence) would require hardware security module integration beyond the pure Python boundary.

---

## 2. Approved algorithms

FIPS 140-3 requires all cryptographic functions use NIST-approved algorithms. AXON's current and planned algorithms:

| Function | Algorithm | Status | NIST reference |
|---|---|:-:|---|
| Keyed hash (HMAC) | HMAC-SHA256 | ✓ Approved | FIPS 198-1 |
| Hash (for SBOM, fingerprints, chain) | SHA-256 | ✓ Approved | FIPS 180-4 |
| Canonical JSON encoding | RFC 8785 style (sorted keys, no whitespace) | N/A (non-cryptographic) | — |
| Asymmetric signature (opt-in) | Ed25519 | ✓ Approved (FIPS 186-5) | FIPS 186-5 |
| Post-quantum signature (planned) | ML-DSA-65 (Dilithium3) | Approved FIPS 204 | FIPS 204 (2024) |
| Post-quantum KEM (planned) | ML-KEM-1024 (Kyber-1024) | Approved FIPS 203 | FIPS 203 (2024) |
| RNG | Python `secrets` (stdlib, CSPRNG-backed) | ✓ Approved | SP 800-90A (via OS) |

No non-approved algorithms are used within the ESK-CB. The `Ed25519Signer` raises at instantiation if the `cryptography` package is unavailable — there is no silent fallback to an unvalidated algorithm.

---

## 3. Cryptographic interfaces

The module exposes:

### 3.1 `Signer` protocol

```python
class Signer(Protocol):
    algorithm: str
    def sign(self, message: bytes) -> bytes: ...
    def verify(self, message: bytes, signature: bytes) -> bool: ...
```

### 3.2 `HmacSigner`

- Key size: 256 bits (32 bytes) generated via `secrets.token_bytes(32)`
- Message input: arbitrary bytes
- Output: 32-byte HMAC tag

### 3.3 `Ed25519Signer`

- Private key: 32 bytes, generated via `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate()`
- Public key: 32 bytes, derived from private
- Signature output: 64 bytes

### 3.4 `ProvenanceChain`

- Internal operations: SHA-256 hashing + Signer delegation
- Append-only, no key material stored in the chain itself

---

## 4. Ports and interfaces

| Port | Direction | Data |
|---|:-:|---|
| `sign(message)` | In | plaintext bytes → signature bytes |
| `verify(message, sig)` | In | plaintext + sig → bool |
| `append(payload)` | In | Python dict → SignedEntry |
| `verify(payloads)` | In | list of dicts → bool |
| Key material | Internal | Never exits the boundary via any port |

### 4.1 Ports classification (FIPS 140-3)

- **Data input port** — `sign` / `verify` message arguments
- **Data output port** — `sign` signature return value; `verify` boolean
- **Control input port** — method dispatch (Python attribute access)
- **Status output port** — `verify` boolean; exception raises on error
- **Power port** — Python process lifecycle (not cryptographically relevant at Level 1)

No explicit "maintenance" port.

---

## 5. Roles, services, and authentication

FIPS 140-3 Level 1 permits role-based authentication via the host OS. Within ESK-CB:

| Role | Services | Authentication |
|---|---|---|
| User | `sign`, `verify`, `append` | Process owns the `HmacSigner.key` or `Ed25519Signer.private_key` by reference |
| Crypto Officer | Key generation (`HmacSigner.random()`, `Ed25519Signer.generate()`) | Same as User at Level 1 |

No operator authentication is enforced within the module at Level 1 (delegated to host OS).

---

## 6. Finite State Model

States of the module:

```
    ┌─────────────┐
    │  POWER-OFF  │
    └──────┬──────┘
           │ Python import of axon.runtime.esk.provenance
           ▼
    ┌─────────────┐
    │  INITIALIZED│
    └──────┬──────┘
           │ Signer.__init__
           ▼
    ┌─────────────┐
    │  OPERATIONAL│◄─── sign() / verify() / append() / verify()
    └─────────────┘
           │ Process exit / __del__
           ▼
    ┌─────────────┐
    │  POWER-OFF  │
    └─────────────┘
```

No explicit "error" state at Level 1 — exceptions propagate to the Python caller.

---

## 7. Self-tests

Required by FIPS 140-3:

### 7.1 Pre-operational self-tests

- **HMAC-SHA256 KAT (Known Answer Test):** verify a fixed key / message produces a known tag (pytest fixture `test_hmac_known_answer`).
- **SHA-256 KAT:** verify `SHA256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`.
- **Ed25519 KAT:** verify the NIST CAVP test vector (when `cryptography` is available).

*These tests need to be added.* Current `test_phase6_runtime.py::TestProvenanceSigning` tests roundtrip properties — KATs are a planned addition.

### 7.2 Conditional self-tests

- **Pairwise consistency test** on `Ed25519Signer.generate()`: sign a fixed challenge and verify immediately.
- **RNG continuous test**: inherited from Python `secrets` / OS CSPRNG.

---

## 8. Life-cycle assurance

### 8.1 Configuration management

- Deterministic SBOM (`axon sbom`) produces content hashes for every release.
- Git tags for every module version.
- No conditional compilation inside the cryptographic boundary.

### 8.2 Delivery and operation

- Python package distributed via PyPI with checksum verification.
- Documentation: this file + `docs/paper_esk.md`.

### 8.3 Development

- Test coverage: 100% of `provenance.py`, `secret.py`, `attestation.py` statements via pytest with coverage instrumentation.
- Code review via PRs on `github.com/Bemarking/axon-lang`.

### 8.4 End-of-life

- Module version deprecation via SemVer major bump.
- Pre-deprecation notice in CHANGELOG.

---

## 9. Mitigation of other attacks

FIPS 140-3 encourages but does not require:

- **Timing attacks:** HMAC verification uses `hmac.compare_digest` (constant-time comparison).
- **Side channels:** Ed25519 via the `cryptography` library which is backed by OpenSSL (vetted).
- **Fault injection:** out of scope for Level 1 software modules.

---

## 10. Gaps to Level 2 or higher

To reach Level 2:

1. Role-based authentication INSIDE the module (not delegated to OS).
2. Tamper-evident packaging — requires a compiled artifact, not pure Python.
3. Formal proofs of non-interference.

These are out of scope for the current AXON Level 1 scaffold.

---

## 11. Submission-readiness checklist

- [ ] All algorithms are FIPS-approved (✓)
- [x] Cryptographic boundary is precisely defined (§1.2)
- [x] Finite State Model diagrammed (§6)
- [ ] Pre-operational KATs implemented (pending)
- [ ] Conditional self-tests implemented (pending)
- [x] Documentation of ports, roles, services (§§4-5)
- [ ] Security policy document (this file is the scaffold)
- [ ] Third-party testing by a NIST-accredited laboratory (business action)
- [ ] CMVP submission package (business action)

---

## 12. Disclaimer

This is a **scaffold** — not a FIPS 140-3 validated module. FIPS validation requires:

1. CAVP algorithm testing by an accredited lab (approximately 2-3 months).
2. CMVP module validation (approximately 6-12 months).
3. ~$50k-200k USD in lab + NIST fees.

Operators seeking a FIPS 140-3 validated deployment should engage an accredited laboratory and submit this scaffold as the starting documentation.

---

> **Template version:** v1.0
> **Authored by:** AXON Language Team
