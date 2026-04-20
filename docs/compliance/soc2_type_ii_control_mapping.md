# SOC 2 Type II — Control Mapping for AXON
## How the AXON language primitives map to the AICPA Trust Services Criteria

> **Scope:** Describes which AXON primitives, runtime modules, or CI checks satisfy — or contribute evidence toward — each SOC 2 Type II Trust Services Criterion (TSC). This document is a **scaffold for external audit engagements**; it does not constitute a certified audit.

> **Canonical reference:** AICPA *Trust Services Criteria for SOC 2* (2017 / updated 2022). Sections CC (Common Criteria), A (Availability), C (Confidentiality), PI (Processing Integrity), P (Privacy).

---

## 1. Executive summary

An organization auditing a system built on AXON can bring this mapping to its SOC 2 Type II auditor as **exhibit A** of a "control environment designed for compliance by construction". Unlike typical SOC 2 evidence (logs + screenshots collected ad-hoc), the AXON controls are:

- **Deterministic** — the same `.axon` program always produces the same SBOM hash and compliance dossier JSON
- **Continuous** — every commit re-runs `axon check` which enforces compile-time compliance coverage
- **Cryptographically anchored** — runtime provenance lives in a Merkle chain signed with HMAC (baseline) or Ed25519 (opt-in)

This does NOT replace the human audit; it reduces the audit surface from "examine all code" to "verify the compiler enforces its documented rules".

---

## 2. Control mapping table

### 2.1 Common Criteria (CC) — required for every SOC 2 report

| TSC | Control intent | AXON primitive / module | Evidence artifact |
|---|---|---|---|
| **CC1.1** | Entity demonstrates commitment to integrity and ethical values | Code-of-conduct (external) + zero tolerance for production shortcuts (feedback memory `no_shortcuts.md`) | Git history showing no `por ahora` / `// TODO: fix later` patterns |
| **CC2.1** | Information system generates quality information | Compile-time compliance (`_check_regulatory_compliance`) | `axon check` exit code 0 on every commit |
| **CC3.1** | Management specifies objectives | `manifest` with `compliance: [...]` declares the system's regulatory objectives | `axon dossier` JSON artifact lists every manifest's claimed κ |
| **CC3.2** | Identifies and analyzes risks | `immune` sensor with baseline-learned KL divergence | HealthReport stream (Fase 5) + red-teaming harness (Fase 5 §5.5) |
| **CC3.3** | Considers potential for fraud | `reflex` with `action: quarantine/terminate` on `on_level: doubt` | Signed reflex trace (HMAC-SHA256 per activation) |
| **CC4.1** | Selects and develops control activities | ESK runtime primitives (provenance, privacy, secret, attestation, eid) | 42 runtime tests in `tests/test_phase6_runtime.py` |
| **CC4.2** | Selects and develops general controls over technology | `shield` declarations + compile-time coverage verification | Type-checker diagnostics stored in CI artifacts |
| **CC5.1** | Deploys control activities through policies | `axonendpoint.shield` binding enforced at compile time | Any endpoint with `body.compliance ≠ ∅` must have covering shield |
| **CC6.1** | Logical access controls restrict access | `Secret[T]` with audit trail on `reveal()` | Audit log of every `SecretAccess(accessor, timestamp, purpose)` |
| **CC6.2** | Prior to issuing system credentials, registration and authorization procedures | Handler-level credential attestation; handler raises CT-3 `InfrastructureBlameError` on auth failure | `AwsHandler.NoCredentialsError` path coverage |
| **CC6.3** | Authorizes, modifies, or removes access | `lease` with τ-decay (paper §3 Fase 3.2) | `LeaseExpiredError` on post-expiry use (Anchor Breach CT-2) |
| **CC6.6** | Logical access controls are implemented over boundaries | `axonendpoint.shield` is MANDATORY for regulated `body_type` | `axon check` rejects programs missing shield |
| **CC6.7** | Logical access controls restrict transmission of information | `Secret[T]` no-materialize invariant | 9 tests in `tests/test_phase6_runtime.py::TestSecret` |
| **CC6.8** | Prevents or detects unauthorized changes | `ProvenanceChain` Merkle-linked, tamper-evident | `chain.verify()` returns False on tamper; test `test_h_tampering_is_detected` |
| **CC7.1** | Detects and monitors events | `immune` + `EpistemicIntrusionDetector` | Anchored events in ProvenanceChain |
| **CC7.2** | Monitors controls for anomalies | KL-based anomaly detector with rolling window | `AnomalyDetector` emits HealthReports with ΛD envelope |
| **CC7.3** | Evaluates security events to identify incidents | EID severity mapping (know/believe/speculate/doubt → low/medium/high/critical) | `IntrusionEvent.severity` populated for every triggered event |
| **CC7.4** | Responds to security incidents | `reflex` deterministic O(1) actions + `heal` Linear Logic patches | `heal` mode `human_in_loop` with `review_sla: 24h` (paper §7.2) |
| **CC7.5** | Identifies recovery needs | `reconcile` with `on_drift: provision` | Active Inference loop closing belief-evidence gap |
| **CC8.1** | Authorizes, designs, develops, and implements changes | Deterministic SBOM with per-declaration content_hash | `axon sbom` output diff between commits |
| **CC9.1** | Identifies, selects, and develops risk mitigation activities | ε-budget for differential privacy | `PrivacyBudget` ledger + `BudgetExhaustedError` on overspend |
| **CC9.2** | Assesses and manages risks associated with vendors | `SupplyChainSBOM.dependencies` listing | `axon sbom` output |

### 2.2 Confidentiality (C) criteria

| TSC | Control intent | AXON primitive |
|---|---|---|
| **C1.1** | Identifies and maintains confidential information | `type X compliance [...]` annotation | Type-checker tracks κ flow through endpoints |
| **C1.2** | Disposes of confidential information | `lease` τ-decay + `Secret[T].audit_trail` | Post-expiry access = Anchor Breach CT-2 |

### 2.3 Processing Integrity (PI) criteria

| TSC | Control intent | AXON primitive |
|---|---|---|
| **PI1.1** | Processing meets specified objectives | `axon check` passes ⟺ program meets its declared objectives (manifest + compliance) | CI gate: `axon check` exit 0 |
| **PI1.4** | System produces complete, accurate output | Ensemble Byzantine quorum with certainty-mode fusion (min/weighted/harmonic) | `EnsembleAggregator` tests in Phase 3 |
| **PI1.5** | System retains information as required | `ProvenanceChain` append-only ledger | Merkle hash chain verification |

### 2.4 Privacy (P) criteria

| TSC | Control intent | AXON primitive |
|---|---|---|
| **P1.1** | Notice to data subjects | `manifest.compliance: [GDPR]` surfaces in `axon dossier` JSON | Dossier artifact consumed by privacy-notice generators |
| **P4.1** | Collection is limited to objectives | Differential Privacy Laplace/Gaussian mechanisms | `laplace_noise` / `gaussian_noise` with ε-budget |
| **P5.1** | Data subject access requests | Audit trail via `Secret[T].audit_trail` + ProvenanceChain | SecretAccess records |
| **P6.1** | Disclosure of personal information | `shield<GDPR>` mandatory coverage rule | Compile-time rejection of ungated GDPR endpoints |

---

## 3. Audit preparation checklist

When commissioning a SOC 2 Type II audit of a system built on AXON:

1. **Run `axon check` on every `.axon` source file in the audit scope.** Exit code 0 = RTT safety invariants satisfied. Capture the output as evidence.
2. **Emit `axon dossier` JSON for each `.axon` program.** Share with the auditor as the canonical "what regulatory classes does this system handle" artifact.
3. **Emit `axon sbom` JSON for the same programs.** Provides reproducible-build content hashes for supply-chain assessment.
4. **Export the `ProvenanceChain` tail hash at audit start and at audit end.** Any tampering in between is detectable by `chain.verify()`.
5. **Export the `PrivacyBudget` ledgers for every privacy-sensitive flow.** Demonstrates continuous ε-budget discipline.
6. **Provide access to the test suite.** `pytest` with `tests/test_phase6_*.py` exercises every ESK invariant claimed in this document.

---

## 4. Gaps and future work

| Gap | Plan |
|---|---|
| Formal Coq/Lean proofs of Theorems 10.1-10.5 (ESK paper) | Roadmap beyond Fase 7 |
| `in-toto` attestation bundle for CC8.1 | Fase 7.x |
| Real Ed25519 / Dilithium signing as default | User supplies signer in `EnterpriseApplication` constructor |
| External third-party audit | Business process — not a code artifact |

---

## 5. Disclaimer

This mapping is **engineering-side evidence prep** — not a SOC 2 Type II certification. Certification requires an independent CPA firm's examination per AICPA AT-C §205 / AT-C §320. AXON's guarantees are mechanical; the audit opinion remains the auditor's.

---

> **Mapping version:** v1.0
> **Authored by:** AXON Language Team
