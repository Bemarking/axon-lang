# Runbook — SOC 2 Type II for an AXON-based System

> **Audience.** Engineering leads preparing their product for a first SOC 2 Type II audit.
> **Outcome.** A signed CPA-firm attestation that your Trust Services Criteria (TSC) controls operated effectively over an observation window (typically 6-12 months).
> **This runbook does NOT replace the audit.** Only an AICPA-licensed CPA firm can issue the report.

---

## 0. What AXON gives you for free

The `axon` CLI already emits everything an auditor needs as *exhibit evidence*:

| Artifact | Command |
|---|---|
| Gap analysis against all 31 TSC controls | `axon audit <prog.axon> --framework soc2 -o gap_soc2.json` |
| SBOM (deterministic SHA-256) | `axon sbom <prog.axon> -o sbom.json` |
| Compliance dossier (κ coverage) | `axon dossier <prog.axon> -o dossier.json` |
| SLSA Provenance v1 attestation | embedded inside `axon evidence-package` |
| Merkle-chained runtime provenance | exported via `ProvenanceChain.to_json()` |
| Full audit evidence ZIP | `axon evidence-package <prog.axon> -o evidence.zip` |

The evidence ZIP is **deterministic** — rerunning on the same program yields byte-identical output, which lets auditors verify tamper-evidence trivially.

---

## 1. 90-day pre-audit checklist

### 1.1 Scope definition (week 1)
- [ ] Name the system(s) and sub-services in scope for the report.
- [ ] Decide on the TSC categories: **always CC**, plus whichever of **A / C / PI / P** you claim.
- [ ] Identify sub-service organizations (cloud providers, LLM vendors) and use the **carve-out** or **inclusive** method.
- [ ] Document the **observation period** (minimum 3 months for Type II initial; 12 months steady-state).

### 1.2 Policy stack (weeks 2-4)
SOC 2 requires written policies. AXON's primitives enforce most of them in code, but auditors still ask for the documents:
- [ ] Information Security Policy
- [ ] Access Control Policy (map to AXON `lease` TTLs)
- [ ] Change Management Policy (map to `axon check` on every PR)
- [ ] Incident Response Policy (map to `reflex` + `heal`)
- [ ] Vendor Management Policy
- [ ] Code of Conduct
- [ ] Data Classification Policy (map to `compliance: [...]` annotations)

### 1.3 Evidence generator in CI (week 5)
Add to your CI pipeline — see the template at `.github/workflows/axon_audit_evidence.yml`:
```
axon check   src/**/*.axon
axon audit   src/main.axon --framework all -o artifacts/audit.json
axon evidence-package src/main.axon -o artifacts/evidence.zip
```
Pin the resulting ZIP to every release tag. Auditors want **one artifact per sampled date**.

### 1.4 Gap closure (weeks 6-10)
Run `axon audit <prog> --framework soc2` weekly. Each run outputs `readiness_percent`; drive it to 100% of `ready` for code-side controls. `pending_external` entries require a CPA engagement — the only way to close them is to hire the auditor.

### 1.5 Readiness review (weeks 11-13)
Most CPA firms offer a **readiness assessment** (1-2 weeks, $10k-$30k) *before* the real Type II engagement. Bring:
- The latest evidence ZIP
- The policy stack
- A list of any TSC you've opted NOT to claim and why

---

## 2. During the audit (3-6 months)

### 2.1 Fieldwork cycle
The auditor will sample dates across the observation period. For each sampled date they want:
- The git commit deployed on that date
- The evidence ZIP generated from that commit
- Runtime provenance entries covering that date

Store these in an immutable bucket (S3 with object-lock or equivalent). Label by commit SHA.

### 2.2 Walk-throughs
For each TSC control the auditor will request a walk-through. The `control_statements/soc2_type_ii.json` inside the evidence ZIP pre-populates the answers; treat it as a starting-point script.

### 2.3 Deviation tracking
If a control failed on any sampled date (example: `axon check` red), the auditor lists it as a **deviation**. You MUST:
- Produce the remediation commit
- Show the redeployment evidence ZIP
- Document the root cause

Deviations are not audit failures per se — a pattern of them is.

---

## 3. Post-audit

### 3.1 Report issuance
A SOC 2 Type II report is **not public**. Share under NDA to prospects / procurement.

### 3.2 Continuous monitoring
Keep running the CI evidence generator after the audit. The next observation period begins the day after this one ended — SOC 2 is a renewed annual process.

---

## 4. Typical cost and timeline

| Item | Cost | Duration |
|---|---|---|
| Readiness assessment | $10k-$30k | 1-2 weeks |
| Type II initial (3-month window) | $40k-$70k | 4-6 months total |
| Type II annual renewal | $30k-$60k | 3-4 months |

Costs scale with scope (number of services) and auditor firm tier.

---

## 5. Reference mapping

The exhaustive per-control mapping lives in [soc2_type_ii_control_mapping.md](soc2_type_ii_control_mapping.md). The runbook above is the operational sequence; the mapping doc is the reference.
