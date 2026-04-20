# Runbook — Common Criteria EAL 4+ for an AXON-based Target of Evaluation (TOE)

> **Audience.** Teams shipping security-sensitive AI products into defense, government, or critical-infrastructure markets that require a CC certificate.
> **Outcome.** A Common Criteria certificate issued under a CCRA signatory scheme (e.g. BSI in Germany, ANSSI in France, NIAP in the US).
> **This runbook does NOT replace the evaluation.** Only an accredited Commercial Testing Laboratory (CTL / ITSEF) under a national CC scheme can perform the evaluation.

---

## 0. What AXON gives you for free

```
axon audit <prog.axon> --framework cc -o gap_cc.json
axon evidence-package <prog.axon> -o evidence.zip
```

The engine tracks 22 CC entries — a combination of Security Functional Requirements (SFRs from Part 2) and Security Assurance Requirements (SARs from Part 3). AXON primitives enforce many SFRs by construction:
- **FDP_ACC.1** (access control) — enforced by `lease` + `endpoint.shield`
- **FDP_IFC.1** (information flow) — enforced by Linear Logic + Separation Logic
- **FAU_STG.1** (audit trail tamper resistance) — `ProvenanceChain` Merkle + signatures
- **FCS_COP.1** (cryptographic operations) — `DilithiumSigner`, `HybridSigner`
- **FPT_TST.1** (TSF self-test) — can be wired via `immune` + `reconcile`
- **FIA_UAU.2** (user authentication before action) — `endpoint` authn hooks

SARs (e.g. **ADV_IMP.1** implementation representation, **AGD_OPE.1** operational user guidance) require written documentation the engine cannot synthesize.

---

## 1. Pre-evaluation checklist (6-18 months)

### 1.1 TOE scope and Security Target (ST)
- [ ] Define the TOE boundary — which AXON programs / runtime components / deployed services.
- [ ] Draft the **Security Problem Definition**: threats, OSPs (Organizational Security Policies), assumptions.
- [ ] Draft the **Security Objectives**: for the TOE and for the operational environment.
- [ ] Map Security Objectives to **SFRs** (CC Part 2) — use AXON's catalog as the starting point.
- [ ] Select the **assurance level** — EAL 4+ typically means "EAL 4 augmented with ALC_FLR.2 (flaw remediation)".
- [ ] Choose a **Protection Profile (PP)** if one applies (e.g. NIAP PPs for network devices, application software, mobile devices).

### 1.2 Developer evidence (by SAR family)

| SAR | Evidence artifact | AXON source |
|---|---|---|
| ADV_ARC.1 | TSF security architecture | SBOM + dossier + prose design doc |
| ADV_FSP.4 | Functional specification | `axon compile --stdout` IR JSON |
| ADV_IMP.1 | Implementation representation | Source code + reproducible build evidence |
| ADV_TDS.3 | TOE design | Prose design doc referencing AXON primitives |
| AGD_OPE.1 | Operational user guidance | Written user manual |
| AGD_PRE.1 | Preparative procedures | Install + initialization script |
| ALC_CMC.4 | Configuration management | Git SHA + evidence ZIP per release |
| ALC_CMS.4 | CM scope | SBOM from evidence ZIP |
| ALC_DEL.1 | Delivery procedures | How to ship signed artifacts |
| ALC_DVS.1 | Development security | Access controls on the repo + build infra |
| ALC_LCD.1 | Life-cycle definition | Documented SDLC |
| ALC_TAT.1 | Well-defined development tools | `axon --version` pin + toolchain hashes |
| ALC_FLR.2 (+) | Flaw reporting procedures | Vulnerability-response policy |
| ATE_COV.2 | Analysis of coverage | pytest coverage report |
| ATE_DPT.1 | Depth testing | Subsystem tests from the evidence ZIP |
| ATE_FUN.1 | Functional tests | `tests/` directory |
| ATE_IND.2 | Independent testing | The lab runs this |
| AVA_VAN.3 | Vulnerability analysis | Lab-driven penetration testing |

### 1.3 Prepare the lab engagement
- [ ] Pick a CTL from the CCRA list. Budget $300k-$2M depending on SAR scope.
- [ ] Sign NDAs and the evaluation contract.
- [ ] Agree on the PP / ST before fieldwork.

---

## 2. Evaluation (6-18 months)

### 2.1 Phase 1 — ST review (ASE)
The lab reviews the Security Target for internal consistency and coverage (family ASE).

### 2.2 Phase 2 — development evidence (ADV / AGD / ALC)
Iterate with the lab — they issue Observation Reports (ORs); respond promptly. This phase is where most CC projects slip schedule.

### 2.3 Phase 3 — testing (ATE / AVA)
- [ ] Hand over the TOE build with stable reproducible hashes.
- [ ] Lab runs independent testing (ATE_IND.2).
- [ ] Lab performs vulnerability analysis (AVA_VAN.3 at EAL 4+). Budget 4-8 weeks — this is often where surprises appear.

### 2.4 Phase 4 — certification (national scheme)
- [ ] Lab submits the Evaluation Technical Report (ETR) to the national scheme (BSI / ANSSI / NIAP).
- [ ] Scheme validators review — 2-6 months.
- [ ] Certificate issued, published, and mutually recognized under CCRA (up to EAL 2 for network devices; EAL 4 for PPs listed in CCRA).

---

## 3. Post-certification

- [ ] The certificate is valid 2-5 years depending on scheme policy.
- [ ] **Assurance Continuity** process for minor changes (new patch release) — cheaper than full re-evaluation.
- [ ] **Full re-evaluation** triggered by major changes to TSF-relevant code.

---

## 4. Typical cost and timeline

| Item | Cost | Duration |
|---|---|---|
| PP/ST preparation | $30k-$100k | 2-4 months |
| EAL 4 evaluation (no PP) | $300k-$800k | 9-18 months |
| EAL 4+ (augmented) | $400k-$1.2M | 12-24 months |
| EAL 5-7 | $1M-$10M+ | 18-36+ months |
| Assurance Continuity | $20k-$80k | 2-4 months |

---

## 5. AXON-specific assets that accelerate CC

- **Deterministic SBOM** — directly satisfies ALC_CMS.4 without custom tooling.
- **SLSA Provenance v1** — supports ALC_CMC.4 configuration management evidence.
- **Compile-time κ checking** — enforces information-flow policies (FDP_IFC.1) without runtime monitoring.
- **Linear Logic + Separation Logic** — the compiler proves resource disjointness; this is stronger than typical CC evidence for FDP_ACC.1.
- **`ProvenanceChain`** — signed Merkle chain provides FAU_STG.1 tamper evidence.

## 6. Reference protocol

The long-form evaluation protocol document lives in [common_criteria_eal4_protocol.md](common_criteria_eal4_protocol.md). Use it as the template for the Security Target skeleton.
