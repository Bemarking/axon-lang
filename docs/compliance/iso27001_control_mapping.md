# ISO/IEC 27001:2022 — Control Mapping for AXON
## Annex A controls satisfied or supported by AXON primitives

> **Scope:** Maps AXON's compiler + runtime guarantees to ISO/IEC 27001:2022 Annex A controls. Intended as a **scaffold for ISMS certification engagements**; not a certification itself.

> **Canonical reference:** ISO/IEC 27001:2022 Annex A (93 controls in 4 themes).

---

## 1. Overview by theme

ISO 27001:2022 organizes controls in four themes:

- **A.5 Organizational controls** (37 controls)
- **A.6 People controls** (8 controls)
- **A.7 Physical controls** (14 controls)
- **A.8 Technological controls** (34 controls)

AXON contributes primarily to **A.5** (policies, roles, compliance) and **A.8** (technology). A.6 and A.7 are out of scope for a language runtime.

---

## 2. Mapping — A.5 Organizational controls

| Control | Title | AXON contribution |
|---|---|---|
| A.5.1 | Policies for information security | `manifest.compliance: [ISO27001, ...]` declares the program's policy scope; the compiler refuses to produce an IR that violates it |
| A.5.2 | Information security roles | `heal.mode: human_in_loop` with `review_sla` enforces the human-in-loop role |
| A.5.3 | Segregation of duties | `shield.allow_tools` / `shield.deny_tools` (capability-based security) |
| A.5.7 | Threat intelligence | `immune` baseline-learned distribution is a per-tenant threat model; drift above threshold surfaces as HealthReport |
| A.5.8 | Information security in project management | Every `.axon` program compiles with `axon check` — CI gate is the project control |
| A.5.23 | Information security for use of cloud services | Handler protocol (Fase 2) abstracts cloud provisioning; each handler classifies errors into CT-1/2/3 |
| A.5.24 | Information security incident management planning and preparation | `reflex` + `heal` primitives + EID integration |
| A.5.25 | Assessment and decision on information security events | `EpistemicIntrusionDetector.observe()` classifies every HealthReport with severity |
| A.5.26 | Response to information security incidents | `reflex.action: quarantine/terminate/alert` with signed_trace |
| A.5.27 | Learning from information security incidents | `ProvenanceChain` append-only ledger captures full incident history |
| A.5.28 | Collection of evidence | Merkle chain hash + HMAC signatures = forensic evidence by construction |
| A.5.30 | ICT readiness for business continuity | `reconcile` with `on_drift: provision` (Active Inference self-healing) |
| A.5.33 | Protection of records | Immutable `ProvenanceChain` entries + deterministic `SupplyChainSBOM` |
| A.5.34 | Privacy and protection of PII | `type X compliance [GDPR, CCPA]` + `PrivacyBudget` ε-tracker + `Secret[T]` |
| A.5.36 | Compliance with policies and standards | Compile-time compliance coverage check — `axon check` rejects violations |

---

## 3. Mapping — A.8 Technological controls

| Control | Title | AXON contribution |
|---|---|---|
| A.8.1 | User endpoint devices | `axonendpoint.shield` gate (boundary enforcement) |
| A.8.2 | Privileged access rights | `lease` with τ-decay (time-bound capability) |
| A.8.3 | Information access restriction | `shield.allow_tools` + `Secret[T]` no-materialize |
| A.8.5 | Secure authentication | Handler-level credential flow + CT-3 classification on auth failure |
| A.8.6 | Capacity management | `resource.capacity` field; manifest-level zone count (A.8.6 + availability) |
| A.8.7 | Protection against malware | `immune` + `reflex` (behavioral detection beyond signatures) |
| A.8.8 | Management of technical vulnerabilities | `heal` with `human_in_loop` review + signed audit trail |
| A.8.9 | Configuration management | `axon sbom` deterministic program hash — config drift detectable |
| A.8.10 | Information deletion | `lease.on_expire: anchor_breach` forces lifecycle closure |
| A.8.12 | Data leakage prevention | `Secret[T]` invariant — `__repr__/__str__/__format__` never reveal plaintext |
| A.8.13 | Information backup | `resource.lifetime: persistent` + `AxonStore` HoTT transactional persistence |
| A.8.15 | Logging | Every `reflex` emits signed_trace (HMAC-SHA256) |
| A.8.16 | Monitoring activities | `immune` sensor continuous monitoring |
| A.8.17 | Clock synchronization | All ΛD envelopes use ISO-8601 UTC via `datetime.now(timezone.utc)` |
| A.8.20 | Network security | Handler layer (Fase 2) classifies network errors as CT-3 partitions |
| A.8.23 | Web filtering | `shield.scan: [prompt_injection, pii_leak, jailbreak, …]` |
| A.8.24 | Use of cryptography | `provenance.HmacSigner` baseline + `Ed25519Signer` opt-in |
| A.8.25 | Secure development life cycle | `axon check` in CI = SDL gate |
| A.8.26 | Application security requirements | `compliance: [...]` declarations at type/shield/endpoint level |
| A.8.27 | Secure system architecture and engineering principles | π-calculus + Linear Logic + Separation Logic at compile time |
| A.8.28 | Secure coding | Compile-time type errors replace runtime bugs (Theorem 5.1 in λ-L-E paper) |
| A.8.29 | Security testing in development | 3591 tests covering Fases 1-7 |
| A.8.30 | Outsourced development | Dual-remote strategy with SBOM verification |
| A.8.31 | Separation of development, test, and production environments | `fabric.ephemeral: true/false` distinguishes environments |
| A.8.32 | Change management | Deterministic SBOM = change detectable at commit level |
| A.8.33 | Test information | DP-noise-added test data via `laplace_noise` / `gaussian_noise` |

---

## 4. Statement of Applicability (SoA) template

An ISMS implementing AXON can use the following SoA structure:

```
Control    | Applicable | Implementation                 | Evidence
-----------+------------+--------------------------------+--------------------------
A.5.36     | Yes        | axon check CI gate             | CI logs + exit code 0
A.8.2      | Yes        | lease primitive                | LeaseKernel audit log
A.8.12     | Yes        | Secret[T] no-materialize       | tests/test_phase6_runtime.py
...        | ...        | ...                            | ...
```

The full 93-row SoA should be completed per-deployment.

---

## 5. ISMS documentation checklist

For ISO 27001:2022 certification audit:

- [ ] **Scope statement** — enumerate every `.axon` program in scope, link to their `axon dossier` JSON outputs.
- [ ] **Risk assessment** — the `immune` baseline period constitutes an empirical risk profile; document baseline training data.
- [ ] **Risk treatment plan** — map each identified risk to a `reflex`/`heal` primitive with `on_level` + `review_sla`.
- [ ] **Internal audit evidence** — provide `axon check` CI log history + PR diffs showing compile-time rejections.
- [ ] **Management review minutes** — business process, AXON provides evidence but not meetings.
- [ ] **SoA** — complete the 93-row table per §4.

---

## 6. Annex B — Self-assessment scoring

For operators doing pre-audit gap analysis:

| Maturity level | Criterion |
|:-:|---|
| 0 | No AXON primitive used |
| 1 | AXON primitive declared but no compile-time enforcement (`compliance: []`) |
| 2 | AXON primitive declared with compliance class; compiler enforces coverage |
| 3 | Compile-time + runtime enforcement + audit artifact (SBOM/dossier) generated |
| 4 | Level 3 + signed ProvenanceChain + DP ε-budget tracked |
| 5 | Level 4 + formal proof (future Coq/Lean mechanization) |

A well-configured AXON deployment reaches **Level 4** out of the box for every Annex A control we mapped.

---

## 7. Disclaimer

This mapping is not an ISO 27001 certification. Certification requires an accredited certification body audit per ISO 27006 / IAF MD 4. AXON's mechanical guarantees reduce the audit scope; they do not replace the audit itself.

---

> **Mapping version:** v1.0
> **Authored by:** AXON Language Team
