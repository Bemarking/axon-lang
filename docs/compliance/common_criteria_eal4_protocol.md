# Common Criteria EAL 4+ — Evaluation Protocol Scaffold
## Pre-evaluation documentation for AXON as a Target of Evaluation (TOE)

> **Scope:** Scaffold for a Common Criteria (ISO/IEC 15408) evaluation at **EAL 4 augmented** (`EAL4+`), targeting government and regulated-sector procurement. This is NOT a completed evaluation; it is the Protection Profile and Security Target outline an accredited lab would refine.

> **Canonical references:**
> - ISO/IEC 15408-1:2022 (introduction and general model)
> - ISO/IEC 15408-2:2022 (security functional requirements, SFRs)
> - ISO/IEC 15408-3:2022 (security assurance requirements, SARs)
> - CEM v3.1 Rev 5 (common evaluation methodology)

---

## 1. Target of Evaluation (TOE) identification

### 1.1 TOE name

**AXON Epistemic Security Kernel (ESK)** — as the cryptographic and compliance-enforcement subsystem of the AXON cognitive language runtime.

### 1.2 TOE scope

| Component | Inside TOE | Outside TOE |
|---|:-:|:-:|
| Compiler (type checker compile-time compliance) | ✓ | |
| ESK runtime (`axon/runtime/esk/*`) | ✓ | |
| Handlers (Fase 2 — DryRun, Terraform, AWS, K8s, Docker) | | ✓ (handlers are call-outs to external systems) |
| Immune system (Fase 5) | ✓ | |
| LLM providers (Anthropic, OpenAI, Gemini, etc.) | | ✓ (treated as untrusted inputs) |
| Operating system / Python runtime | | ✓ (underlying platform) |

### 1.3 TOE type

**Security Policy Enforcement Module** — enforces a regulatory type system + cryptographic provenance + differential privacy budget on AI applications.

### 1.4 TOE physical boundary

Pure software: the set of Python modules listed in §1.2, running in a Python 3.12+ interpreter on a commodity operating system.

---

## 2. Target EAL level

**EAL 4+** = EAL 4 (methodically designed, tested, and reviewed) plus augmentations:

- **ALC_FLR.2** — Flaw reporting procedures (AXON's GitHub Issues workflow)
- **AVA_VAN.5** — Advanced methodical vulnerability analysis (pentest by accredited lab)

EAL 4 is the highest level realistically achievable without formal methods (which would be EAL 5+ with Coq/Lean mechanization — roadmap).

---

## 3. Security Problem Definition

### 3.1 Assets

| Asset | Description | Protection need |
|---|---|---|
| **A.1 Regulated data (PHI, PAN, PII)** | Subject data handled by AXON programs | Confidentiality + integrity |
| **A.2 Model outputs** | LLM responses in AXON flows | Integrity + authenticity |
| **A.3 Audit evidence** | ProvenanceChain + dossiers + SBOM | Integrity + non-repudiation |
| **A.4 Cryptographic keys** | HmacSigner.key, Ed25519Signer.private_key | Confidentiality |
| **A.5 Privacy budget state** | PrivacyBudget.epsilon_spent ledger | Integrity |

### 3.2 Threats

| Threat | Description | Asset(s) threatened |
|---|---|---|
| **T.REG_VIOLATION** | A program ships with regulated data crossing an uncovered boundary | A.1 |
| **T.PROMPT_INJECTION** | Adversarial prompt subverts intended flow behavior | A.2 |
| **T.DATA_POISONING** | Training data injected to shift model behavior | A.2 |
| **T.EXFIL_VIA_LOG** | Secrets leaked via logging, tracing, or stack traces | A.1, A.4 |
| **T.TAMPER_AUDIT** | Attacker modifies audit records post-hoc | A.3 |
| **T.ZERO_DAY** | Unknown attack pattern evades signature-based IDS | A.1, A.2 |
| **T.BUDGET_OVERRUN** | Cumulative ε exceeds declared DP budget | A.1, A.5 |
| **T.PATCH_MISAPPLY** | Remediation patch applied twice or after collapse | System integrity |

### 3.3 Organizational Security Policies (OSPs)

| OSP | Statement |
|---|---|
| **P.COMPLIANCE_BY_CONSTRUCTION** | All regulated data flows gated by a shield covering their κ |
| **P.AUDITABILITY** | Every material security event is cryptographically recorded |
| **P.LEAST_PRIVILEGE** | Resources accessed via time-bounded leases (τ-decay) |
| **P.NO_SECRET_LEAK** | Plaintext secrets never materialize in logs, traces, or string conversions |

### 3.4 Assumptions

| Assumption | Statement |
|---|---|
| **A.TRUSTED_ADMIN** | Crypto Officer role (who generates and rotates keys) is trustworthy |
| **A.SECURE_OS** | Host OS enforces process isolation |
| **A.TRUSTED_TIME** | Host clock is synchronized and trustworthy (for τ-decay) |

---

## 4. Security Objectives

### 4.1 Objectives for the TOE

| Objective | Satisfies |
|---|---|
| **O.COVERAGE_CHECK** — compile-time rejection of κ-uncovered boundaries | T.REG_VIOLATION, P.COMPLIANCE_BY_CONSTRUCTION |
| **O.IMMUNE_DETECT** — anomaly detection via KL + FEP | T.ZERO_DAY, T.PROMPT_INJECTION, T.DATA_POISONING |
| **O.REFLEX_RESPOND** — sub-millisecond deterministic reflex | T.PROMPT_INJECTION |
| **O.HEAL_LINEAR** — Linear-Logic one-shot remediation | T.PATCH_MISAPPLY |
| **O.SIGN_PROVENANCE** — tamper-evident Merkle chain | T.TAMPER_AUDIT, P.AUDITABILITY |
| **O.SECRET_OPAQUE** — no-materialize Secret[T] | T.EXFIL_VIA_LOG, P.NO_SECRET_LEAK |
| **O.DP_BUDGET** — enforced PrivacyBudget | T.BUDGET_OVERRUN |
| **O.LEASE_TEMPORAL** — τ-decay on capabilities | P.LEAST_PRIVILEGE |

### 4.2 Objectives for the Operational Environment

| Objective | Statement |
|---|---|
| **OE.ADMIN** | The operator protects crypto-officer credentials |
| **OE.OS** | Host OS provides memory isolation and filesystem ACLs |
| **OE.TIME** | Host maintains UTC time sync (NTP) |

---

## 5. Security Functional Requirements (SFRs)

Mapped from ISO/IEC 15408-2:

| SFR class | SFR | AXON realization |
|---|---|---|
| **FAU** Security Audit | FAU_GEN.1 Audit data generation | Every reflex, heal, intrusion → signed trace in ProvenanceChain |
| | FAU_GEN.2 User identity association | `Secret[T].audit_trail` records accessor |
| | FAU_SAR.1 Audit review | `axon dossier` / `axon sbom` CLI + `chain.entries()` |
| | FAU_STG.1 Protected audit trail storage | ProvenanceChain append-only + HMAC |
| **FCO** Communication | FCO_NRO.1 Selective proof of origin | Ed25519Signer for asymmetric non-repudiation |
| **FCS** Cryptographic support | FCS_COP.1 Cryptographic operation | HMAC-SHA256, SHA-256 KAT-verified |
| | FCS_CKM.1 Cryptographic key generation | `HmacSigner.random()` via `secrets.token_bytes(32)` |
| **FDP** User data protection | FDP_ACC.1 Subset access control | Compliance coverage rule (RTT) |
| | FDP_IFC.1 Subset information flow control | κ propagation through type annotations |
| | FDP_IFF.1 Simple security attributes | `compliance: [HIPAA, …]` on types |
| | FDP_ITC.2 Import with security attributes | `manifest.compliance` declared at import boundary |
| **FIA** Identification & Authentication | FIA_UAU.1 Timing of authentication | Handler-level credential flow |
| **FMT** Security Management | FMT_MSA.1 Management of security attributes | `shield.compliance` assignment restricted to declared shields |
| | FMT_SMR.1 Security roles | Crypto Officer, User, Reviewer (heal.mode=human_in_loop) |
| **FPR** Privacy | FPR_PSE.1 Pseudonymity | Differential Privacy Laplace mechanism |
| | FPR_UNL.1 Unlinkability | Gaussian mechanism with composition tracking |
| **FPT** Protection of the TSF | FPT_TST.1 TSF testing | pytest suite 3591 tests |
| | FPT_ITC.1 Inter-TSF confidentiality | Secret[T] no-materialize invariant |
| **FRU** Resource utilisation | FRU_RSA.1 Maximum quotas | `resource.capacity` limits + `max_patches` in heal |
| **FTP** Trusted path/channels | FTP_ITC.1 Inter-TSF trusted channel | Operator's TLS stack (outside TOE) |

---

## 6. Security Assurance Requirements (SARs)

EAL 4+ augmentations:

| SAR | Title | Status |
|---|---|---|
| ADV_ARC.1 | Security architecture description | `docs/paper_esk.md` provides this |
| ADV_FSP.4 | Complete functional specification | Documented API surface in `axon/runtime/esk/__init__.py` |
| ADV_IMP.1 | Implementation representation of the TSF | Open source on GitHub — full implementation available |
| ADV_TDS.3 | Basic modular design | Package decomposition: compliance, provenance, privacy, attestation, secret, eid |
| AGD_OPE.1 | Operational user guidance | `DEVELOPMENT.md` + `docs/paper_axon_enterprise.md` |
| AGD_PRE.1 | Preparative procedures | `pyproject.toml` extras (`aws`, `kubernetes`, `docker`) |
| ALC_CMC.4 | Production support, acceptance procedures, automation | GitHub CI pipeline |
| ALC_CMS.4 | Problem tracking CM coverage | GitHub Issues |
| ALC_DEL.1 | Delivery procedures | PyPI package distribution |
| ALC_DVS.1 | Identification of security measures | Dual-remote strategy (`DEVELOPMENT.md`) |
| ALC_LCD.1 | Developer defined life-cycle model | SemVer + CHANGELOG |
| ALC_TAT.1 | Well-defined development tools | pytest, mypy, ruff |
| **ALC_FLR.2** | Flaw reporting procedures (EAL 4+) | GitHub Issues SLA (business commitment) |
| ATE_COV.2 | Analysis of coverage | pytest-cov reports |
| ATE_DPT.1 | Testing: basic design | Tests organized by Fase (1-7) |
| ATE_FUN.1 | Functional testing | 3591 tests |
| ATE_IND.2 | Independent testing - sample | Evaluator's responsibility |
| **AVA_VAN.5** | Advanced methodical vulnerability analysis (EAL 4+) | External pentest required |

---

## 7. Evaluation activities (CEM)

### 7.1 Activities already satisfied by the codebase

- **ADV** (Development): code is open source and documented.
- **AGD** (Guidance): paper + DEVELOPMENT.md + this folder.
- **ATE** (Tests): 3591 tests with coverage instrumentation.

### 7.2 Activities requiring external work

- **ALC_FLR.2**: formalize the SLA for security flaw response (business).
- **AVA_VAN.5**: commission a pentest by an accredited CC lab.
- **ASE** (Security Target): an accredited lab produces a CC-formatted Security Target based on this scaffold.
- **ACM** (Certificate Maintenance): post-evaluation.

---

## 8. Deliverables checklist (for a CC EAL 4+ evaluation submission)

- [x] Target of Evaluation identification (§1)
- [x] Security Problem Definition (§3)
- [x] Security Objectives (§4)
- [x] SFR list (§5)
- [x] SAR list (§6)
- [ ] Formal Security Target document (requires CC-lab CAS-formatted)
- [ ] Security Architecture Description (partially covered by paper_esk.md)
- [ ] Vulnerability Analysis report (external pentest pending)
- [ ] Independent evaluator's test plan (external)

---

## 9. Typical timeline

| Phase | Effort |
|---|---|
| ST preparation with accredited lab | 2-4 months |
| Developer evidence compilation | 1-2 months (bulk already done via this scaffold) |
| Lab evaluation | 6-12 months |
| Certification body decision | 1-3 months |
| **Total** | **10-21 months** |

Budget estimate: **$150k - $500k USD** depending on scope.

---

## 10. Disclaimer

This is a **pre-evaluation scaffold** authored by the development team. A real CC evaluation is conducted by an accredited lab (e.g., atsec, SRC, TÜV) under the oversight of a Certification Body (e.g., BSI, CCRA member). Operators seeking a CC-certified AXON deployment should engage an accredited lab and provide this document as starting technical documentation.

---

> **Template version:** v1.0
> **Authored by:** AXON Language Team
