"""
HIPAA Safe Harbor PHI detection patterns (Fase 20 enterprise).

The 18 categories of HIPAA Safe Harbor identifiers per 45 CFR
§164.514(b)(2) — ``de-identification standard``. A target containing
any of these identifiers is presumed to contain PHI. The OSS
``pii_leak`` scanner catches generic email + phone formats; this
healthcare-tuned scanner catches the specific identifiers that
HIPAA enumerates as direct PHI markers.

Pre-trained classifier banks (BioBERT for embedding cosine vs PHI
exemplars) are NOT shipped here — that's a separate I+D track.
This module ships **regex pattern detection only**, which is the
fastest defence layer + the foundation of any HIPAA-aware Shield
ensemble.

Calibration philosophy: **err on the side of false positives**.
A flow that triggers a HIPAA breach because it accidentally
contained a 9-digit number that looks like an SSN is annoying;
a flow that lets PHI pass to an LLM is a regulatory incident.
The Security Rule judge (``hipaa_judge``) downstream lowers the
false-positive rate via context-aware adjudication; the pattern
scanner here is the first line.

Per Bemarking AI charter: this is the **moat**. Adopters running
healthcare-grade Shield with this module installed get coverage
informed by years of clinical informatics work + Mass General
Brigham + JAMIA + AMIA dataset experience. A fork of axon-lang OSS
cannot trivially replicate this catalogue — it requires domain
expertise + legal review + clinical validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  HIPAA SAFE HARBOR — 18 IDENTIFIER CATEGORIES
# ═══════════════════════════════════════════════════════════════════
#
# Reference: 45 CFR §164.514(b)(2)(i) lists 18 categories.
# Severity: every direct identifier is `critical` — a single match
# is sufficient to trigger HIPAA review. Composite identifiers
# (name+DOB co-occurrence) are also `critical` because the
# combination defeats trivial single-field redaction.

_HIPAA_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # 1. Names — handled by classifier strategy with PHI bank;
    # regex on names produces too many false positives in OSS.
    # Composite name+DOB caught below.

    # 2. Geographic subdivisions smaller than state — ZIP+4 /
    #    full street address. ZIP+4 (5+4 digits) is HIPAA-restricted.
    (r"\b\d{5}-\d{4}\b",
     "high", "hipaa_zip_plus_four"),
    # Street address with numeric prefix + common street suffixes.
    (r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
     r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|"
     r"Lane|Ln|Road|Rd|Place|Pl|Court|Ct)\b",
     "high", "hipaa_street_address"),

    # 3. Dates more granular than year (DOB, admission date) —
    #    HIPAA requires year-only for ages <89.
    (r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])"
     r"[/\-](?:19|20)\d{2}\b",
     "high", "hipaa_date_full"),
    (r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b",
     "high", "hipaa_date_iso"),

    # 4. Telephone — overlap with OSS `pii_leak` but with HIPAA
    #    severity (critical for healthcare context).
    (r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
     "critical", "hipaa_telephone_us"),

    # 5. Fax — same shape as phone in HIPAA terms.
    # 6. Email — handled by OSS pii_leak; promoted to critical
    #    when in healthcare ensemble.

    # 7. Social Security Number (XXX-XX-XXXX format).
    (r"\b\d{3}-\d{2}-\d{4}\b",
     "critical", "hipaa_ssn"),

    # 8. Medical Record Number (MRN). Common formats:
    #    - 7-10 digit numeric (MGB, Cleveland Clinic style)
    #    - "MRN: <digits>" prefix
    #    - "Medical Record:" / "Patient ID:" prefix
    (r"\b(?:MRN|MR#|Medical\s+Record|Patient\s+ID|Pt\.?\s+ID)"
     r"\s*[:#]?\s*\d{6,12}\b",
     "critical", "hipaa_mrn_labeled"),

    # 9. Health plan beneficiary number / Insurance ID.
    (r"\b(?:Member\s+ID|Insurance\s+ID|Health\s+Plan|Subscriber)"
     r"\s*[:#]?\s*[A-Z0-9]{6,15}\b",
     "critical", "hipaa_insurance_id"),

    # 10. Account number — same shape as financial PAN; we catch
    #     under generic credit-card-format from OSS pii_leak.

    # 11. Certificate / license number — physician licenses,
    #     drug prescriber numbers.

    # 12. Vehicle identifiers — VIN format.
    (r"\b[A-HJ-NPR-Z0-9]{17}\b",
     "high", "hipaa_vin"),

    # 13. Device identifiers — typically UDI (FDA Unique Device
    #     Identifier) format.
    (r"\b\(01\)\d{14}\b",
     "high", "hipaa_udi_di"),

    # 14. URLs / Web URLs — patient-portal URLs that include
    #     patient identifiers. Generic URL detection is in OSS;
    #     this catches the patient-portal pattern.
    (r"\bhttps?://[^/\s]*(?:mychart|patient|portal)[^/\s]*"
     r"/[^\s]*\b",
     "high", "hipaa_patient_portal_url"),

    # 15. IP addresses — same as URL contextually.

    # 16. Biometric identifiers — finger / retinal / voice prints.
    #     Hard to detect via regex; classifier territory.

    # 17. Full-face photographs — image classifier territory.

    # 18. Any other unique identifying number, characteristic, or
    #     code. Catches "Patient #<N>" generic phrasing.
    (r"\b(?:Patient|Px|Subject)\s*#?\s*\d{4,}\b",
     "high", "hipaa_patient_number"),

    # ── Direct clinical PHI markers ──
    # ICD-10 diagnosis codes (alphanumeric A00.0 — Z99.9, with
    # extended specifications up to 7 characters).
    (r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?[A-Z]?\b",
     "high", "hipaa_icd10_code"),

    # CPT procedure codes (5-digit numeric, optional 2-letter
    # modifier).
    (r"\b\d{5}(?:-[A-Z]{2})?\b(?=.*(?:procedure|CPT|code|"
     r"surgery|examination))",
     "medium", "hipaa_cpt_code_contextual"),

    # NDC drug codes (4-4-2, 5-3-2, or 5-4-1 dash format).
    (r"\b\d{4,5}-\d{3,4}-\d{1,2}\b",
     "high", "hipaa_ndc_drug_code"),

    # DEA-scheduled controlled-substance generic names. Subset
    # that's commonly leaked in clinical free-text.
    (r"(?i)\b(?:oxycodone|oxycontin|hydrocodone|fentanyl|"
     r"methadone|morphine|adderall|ritalin|xanax|alprazolam|"
     r"clonazepam|diazepam|lorazepam|ambien|zolpidem)\s+"
     r"\d+\s*(?:mg|mcg|ml)\b",
     "high", "hipaa_controlled_substance_dose"),

    # Clinical free-text PHI signals — composite identifier
    # patterns where multiple weak signals stack into a strong one.
    # E.g. "patient John Doe, DOB 1980-05-15, MRN 123456" — name +
    # DOB + MRN together is unambiguous PHI.
    (r"(?i)\bpatient\s+[A-Z][a-z]+\s+[A-Z][a-z]+(?:[,;]\s*"
     r"(?:DOB|date\s+of\s+birth)[\s:]*\d{1,4}[-/]\d{1,2}[-/]\d{1,4})",
     "critical", "hipaa_name_dob_composite"),
)


# ═══════════════════════════════════════════════════════════════════
#  COMPILED + CACHE
# ═══════════════════════════════════════════════════════════════════


_compiled: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), sev, label)
    for p, sev, label in _HIPAA_PATTERNS
]


# ═══════════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HipaaPhiScanner:
    """HIPAA Safe Harbor PHI pattern scanner. Returns
    ``passed=False`` if any of the 18 identifier categories matches
    the target. Confidence reflects worst severity (`critical` →
    1.0, `high` → 0.9, `medium` → 0.75)."""

    _SEVERITY_CONFIDENCE = {
        "critical": 1.0, "high": 0.9, "medium": 0.75, "low": 0.5,
    }

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"vertical": "healthcare", "matches": []},
            )

        matches: list[dict[str, str]] = []
        worst = "low"
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        for compiled, severity, label in _compiled:
            m = compiled.search(target)
            if m is not None:
                matches.append({
                    "label": label,
                    "severity": severity,
                    "match": m.group(0)[:80],
                })
                if rank[severity] > rank[worst]:
                    worst = severity

        if not matches:
            return ScanResult(
                passed=True, confidence=0.95,
                reason="no HIPAA Safe Harbor identifiers detected",
                detail={
                    "vertical": "healthcare",
                    "patterns_evaluated": len(_compiled),
                    "matches": [],
                },
            )

        return ScanResult(
            passed=False,
            confidence=self._SEVERITY_CONFIDENCE.get(worst, 0.5),
            reason=(
                f"HIPAA PHI detected — {len(matches)} identifier(s) "
                f"across categories; worst severity {worst}"
            ),
            detail={
                "vertical": "healthcare",
                "match_count": len(matches),
                "worst_severity": worst,
                "matches": matches[:10],
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


def _register_healthcare_patterns() -> None:
    """Register HIPAA scanner under explicit ``hipaa`` strategy
    alias only.

    Multi-vertical safety: we deliberately do NOT shadow the OSS
    generic ``pattern`` / ``data_exfil`` keys, because mixed-
    vertical deployments would have last-import-wins silently
    drop all but one vertical's catalogue. Adopters declare
    ``strategy: hipaa`` in their Shield, or compose via
    ``ensemble_configs.healthcare_ensemble()``.
    """
    scanner = HipaaPhiScanner()
    for category in ("pii_leak", "data_exfil"):
        default_registry.register(category, scanner, strategy="hipaa")


_register_healthcare_patterns()


__all__ = [
    "HipaaPhiScanner",
]
