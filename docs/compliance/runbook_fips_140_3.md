# Runbook — FIPS 140-3 (Cryptographic Module) Validation for AXON

> **Audience.** Teams shipping an AXON-based cryptographic product into US federal, Canadian, or allied government markets that require validated crypto modules.
> **Outcome.** A CMVP (Cryptographic Module Validation Program) certificate listed at `csrc.nist.gov/projects/cryptographic-module-validation-program`.
> **This runbook does NOT replace the lab submission.** Only a NIST-accredited CST (Cryptographic and Security Testing) laboratory can perform the testing and draft the submission package.

---

## 0. What AXON gives you for free

```
axon audit <prog.axon> --framework fips -o gap_fips.json
axon evidence-package <prog.axon> -o evidence.zip
```

The engine tracks 14 FIPS 140-3 sections / assertions with status breakdown: some are **ready** (already enforced by AXON primitives like `DilithiumSigner`, `HybridSigner`, `HmacSigner`), many are **pending_external** (algorithm test vectors, entropy source validation, side-channel testing can only be performed by an accredited lab).

---

## 1. Pre-submission checklist (6-12 months)

### 1.1 Scope decisions
- [ ] Decide the module boundary: software, hybrid, or hardware.
- [ ] Select the target **security level** (1-4). For software AI infrastructure, Level 1 is typical; Level 2 requires tamper evidence; Levels 3-4 require tamper resistance and are unusual for pure software.
- [ ] Enumerate **Approved Algorithms** used: `DilithiumSigner` (ML-DSA-65, FIPS 204), `Ed25519Signer` (FIPS 186-5, Approved under specific conditions), `HmacSigner` (SHA-256 HMAC, FIPS 198-1). Non-approved algorithms MUST be disabled or clearly partitioned.

### 1.2 CAVP test-vector runs
- [ ] Engage a CST lab to run **CAVP** (Cryptographic Algorithm Validation Program) tests BEFORE submission — CAVP certificates are a prerequisite.
- [ ] For each approved algorithm, provide Known Answer Test (KAT) vectors and self-test code. AXON exposes self-test hooks via `DilithiumSigner._self_test()`; wire them into module initialization.

### 1.3 Security Policy document
Required by ISO/IEC 19790:2012 §11. Must be PUBLIC on NIST's site after certification.
- [ ] Describe the module cryptographic boundary (diagram).
- [ ] List roles and services (operator / user / crypto-officer).
- [ ] Specify approved modes of operation (exclude non-approved algorithms from the Approved mode).
- [ ] Document self-tests: power-on + conditional.
- [ ] Life-cycle procedures: key generation, zeroization, distribution.

### 1.4 Module source + build procedure
- [ ] The submitted module MUST be reproducible — AXON's deterministic SBOM is a strong asset here. Attach `program_sbom.json` + the `axon-lang` wheel SHA-256.
- [ ] Freeze the compiler version; any change triggers re-validation.

### 1.5 Vendor evidence
- [ ] Design documentation: high- and low-level design showing approved vs. non-approved paths.
- [ ] Developer testing results: unit tests with coverage reports.
- [ ] User guidance: how to install/initialize in FIPS-approved mode.
- [ ] Operator authentication and role-based access evidence.

### 1.6 Physical security (Levels 2+)
Typically N/A for pure software modules. If using HSM-like components, coordinate with the hardware vendor's existing FIPS certificate.

### 1.7 Side-channel analysis (Levels 3+)
Requires SCA-capable lab equipment. Budget significantly more time and cost.

---

## 2. Laboratory engagement (3-9 months)

### 2.1 Lab selection
- [ ] Pick a NIST-accredited CST lab (list at `nvlpubs.nist.gov`). Typical labs: atsec, Leidos, Gossamer Sec, etc.
- [ ] Execute NDA + engagement contract (expect $100k-$400k for Level 1 software module).

### 2.2 Evidence handoff
- [ ] Deliver: module source, Security Policy draft, build artifacts, test-vector outputs, design documents, evidence ZIP.
- [ ] Lab will issue an Evidence List; any missing item halts testing.

### 2.3 Testing phase
- [ ] Lab runs the 11 test areas (power-on self-tests, conditional self-tests, crypto-officer authentication, zeroization, etc.).
- [ ] Lab raises questions via an issue-log; respond promptly — delays blow the schedule.

### 2.4 Submission to CMVP
- [ ] Lab submits the Submission Package to NIST's MIP (Modules In Process) queue.
- [ ] MIP review takes 6-18 months depending on NIST backlog.

---

## 3. Post-validation

- [ ] Module appears on the **Validated Modules list** at NIST.
- [ ] Any change to the module requires a **maintenance letter** (minor) or **revalidation** (major).
- [ ] Certificates carry a **sunset date** — typically 5 years from issue date; after 2026 new certs expire faster as FIPS 140-2 is fully retired.

---

## 4. Typical cost and timeline

| Item | Cost | Duration |
|---|---|---|
| CAVP algorithm validation | $5k-$20k per algorithm | 2-6 weeks per algorithm |
| Level 1 software module validation | $100k-$400k | 6-18 months total |
| Level 2+ | $200k-$1M+ | 12-24 months |
| Maintenance letter | $5k-$15k | 1-3 months |

---

## 5. AXON-specific notes

- `DilithiumSigner` requires `liboqs` — FIPS 204 ML-DSA is itself under CAVP; ensure the liboqs build you ship has been algorithm-tested.
- `HybridSigner` (classical + PQ) is permitted under NIST SP 800-208; the classical half must also be Approved.
- `Ed25519Signer` is Approved under FIPS 186-5 with specific format constraints — the lab will verify.
- AXON's `ProvenanceChain` Merkle construction is not itself FIPS-relevant, but the HMAC/Ed25519 used inside it IS.

## 6. Reference submission template

The long-form submission template lives in [fips_140_3_submission_template.md](fips_140_3_submission_template.md). Use it as the skeleton for the Security Policy document.
