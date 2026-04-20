# Runbook — ISO/IEC 27001:2022 for an AXON-based System

> **Audience.** Organizations seeking an ISO/IEC 27001 certificate issued by an accredited certification body (CB).
> **Outcome.** A 3-year certificate, with surveillance audits in years 1 and 2 and recertification in year 3.
> **This runbook does NOT replace the audit.** Only an IAF-accredited CB (ANAB, UKAS, DAkkS, etc.) can issue the certificate.

---

## 0. What AXON gives you for free

```
axon audit   <prog.axon> --framework iso27001 -o gap_iso.json
axon evidence-package <prog.axon> -o evidence.zip
```

The evidence ZIP contains:
- Gap analysis against 41 Annex A controls
- Pre-filled control implementation statements
- ISO 27005-shaped risk register
- SBOM + SLSA Provenance v1 attestation
- Source snapshot

Auditors will also ask for a **Statement of Applicability (SoA)** — `axon` does not generate this (it is a management decision document). See §1.3.

---

## 1. 12-month pre-certification checklist

### 1.1 ISMS scope and context (month 1)
- [ ] Define the ISMS scope — which products, locations, and personnel are in scope (Clause 4.3).
- [ ] Identify interested parties and their requirements (Clause 4.2).
- [ ] Produce the ISMS context document.

### 1.2 Leadership and objectives (month 1)
- [ ] Assign an Information Security Management Representative.
- [ ] Issue a written information security policy signed by top management (Clause 5.2).
- [ ] Define measurable ISMS objectives (Clause 6.2) — map to your AXON `immune` sensitivity target and `reconcile` SLA.

### 1.3 Statement of Applicability (months 2-3)
The SoA lists every Annex A control, marks it applicable or not, and justifies the decision. Use the 41 controls tracked by AXON's gap analyzer plus the 52 remaining controls you must cover manually (see ISO 27001:2022 Annex A — 93 controls total).

- [ ] For each AXON-tracked control, copy the `control_statements/iso_27001.json` entry into the SoA as the implementation statement.
- [ ] For each remaining control, write an inclusion or exclusion statement with justification.

### 1.4 Risk management (months 3-4)
- [ ] Adopt ISO 27005 as your risk methodology (Clause 6.1.2 + 6.1.3).
- [ ] Use `risk_register.json` from the evidence ZIP as the baseline register.
- [ ] Conduct a risk assessment workshop — validate residual_score values, add organization-specific risks.
- [ ] Produce a Risk Treatment Plan (Clause 6.1.3).

### 1.5 Operational controls (months 4-8)
AXON enforces many Annex A controls by construction. For the remainder:
- [ ] Awareness training programme (A.6.3)
- [ ] Physical security procedures (A.7.*) if you operate on-prem
- [ ] Supplier management (A.5.19-A.5.23) — AXON covers Handler-protocol suppliers; HR/Legal suppliers are separate
- [ ] Business continuity / disaster recovery (A.5.29-A.5.30)

### 1.6 Internal audit (months 9-10)
Clause 9.2 requires at least one internal audit BEFORE the Stage 1 audit.
- [ ] Appoint an internal auditor (may be third-party for neutrality).
- [ ] Run a full internal audit against all 93 Annex A controls.
- [ ] Document findings, corrective actions, and closure evidence.

### 1.7 Management review (months 10-11)
- [ ] Hold a documented management review (Clause 9.3) — inputs include risk register, audit findings, ISMS objective progress.
- [ ] Keep minutes; the CB will ask for them.

---

## 2. The certification audit (Stages 1 + 2)

### 2.1 Stage 1 — documentation review (1-3 days on-site or remote)
- [ ] Submit ISMS manual, SoA, Risk Treatment Plan, management review minutes.
- [ ] Submit the latest evidence ZIP as supporting technical evidence.
- [ ] Resolve any Stage 1 findings before Stage 2.

### 2.2 Stage 2 — certification audit (3-5 days typical)
- [ ] The auditor samples controls; walk them through:
  1. `axon check` compile-time output
  2. `axon dossier` to show κ coverage
  3. `provenance_chain.json` for runtime audit trail
  4. `risk_register.json` linked to SoA
- [ ] Answer any minor/major nonconformities within the CB's deadline (typically 90 days).

### 2.3 Certificate issuance
The certificate is valid 3 years, contingent on annual surveillance audits.

---

## 3. Continuous operation

- [ ] Re-run `axon evidence-package` before every release — attach the ZIP to the release artifact.
- [ ] Schedule the annual internal audit (Clause 9.2).
- [ ] Hold the annual management review.
- [ ] Prepare for the **surveillance audit** in years 1 and 2, and **recertification** in year 3.

---

## 4. Typical cost and timeline

| Item | Cost | Duration |
|---|---|---|
| Gap analysis / pre-audit | $15k-$40k | 4-8 weeks |
| Stage 1 + Stage 2 audit | $25k-$60k | 6-12 months total including pre-audit |
| Annual surveillance | $8k-$20k | 2-3 days |
| 3-year recertification | $20k-$50k | 4-6 weeks |

Costs scale with number of sites, headcount, and SoA scope.

---

## 5. Reference mapping

The per-control mapping lives in [iso27001_control_mapping.md](iso27001_control_mapping.md). The AXON framework catalog covers 41 of 93 Annex A controls — the remaining 52 are HR / legal / physical controls outside the language scope.
