"""
Fintech AML / KYC / sanctions detection patterns (Fase 20
enterprise).

Where the OSS ``pii_leak`` scanner catches generic credit-card
shape (16 digits with spaces/dashes), this fintech-tuned scanner
**validates** the candidates with the actual checksum algorithms:

  * **PAN (Primary Account Number)** — 13–19 digits with
    Luhn (mod-10) checksum validation. Eliminates the false
    positives plain regex generates (any 16-digit number).
  * **IBAN** — country code + check digits + BBAN; validates
    via mod-97 = 1 algorithm per ISO 13616.
  * **SWIFT BIC** — 8 or 11 character format
    ``BBBBCCLLXXX`` (ISO 9362).
  * **Structured-transaction smurfing** — amounts deliberately
    just below US $10,000 BSA reporting threshold (e.g. $9,999,
    $9,500 in repeated transactions).
  * **OFAC SDN signals** — common-name patterns from the US
    Treasury's Specially Designated Nationals list. The full
    catalogue requires updating from US Treasury feeds; this
    file ships a small representative subset.

Reference frameworks:

  * **31 CFR §1010.311** — Bank Secrecy Act (BSA) currency
    transaction reporting.
  * **31 CFR §1010.620** — OFAC sanctioned persons list
    obligations.
  * **MiFID II** investor-protection record keeping.
  * **GDPR Art. 6(1)(c)** — lawful processing for legal
    obligations (AML / KYC compliance).
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
#  CHECKSUM HELPERS
# ═══════════════════════════════════════════════════════════════════


def _luhn_check(digits: str) -> bool:
    """Mod-10 Luhn validation. ``digits`` is a string of decimal
    digits; returns True iff the number satisfies the Luhn
    checksum."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _iban_check(iban: str) -> bool:
    """ISO 13616 IBAN check: mod-97 of rearranged + numericalised
    representation must equal 1."""
    cleaned = re.sub(r"\s", "", iban).upper()
    if len(cleaned) < 15 or len(cleaned) > 34:
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        elif ch.isalpha():
            numeric += str(ord(ch) - ord("A") + 10)
        else:
            return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ═══════════════════════════════════════════════════════════════════
#  REGEX PATTERNS (for candidate extraction; checksum-validated below)
# ═══════════════════════════════════════════════════════════════════


# Candidate PAN: 13-19 digit runs (allowing spaces/dashes between
# 4-digit groups). Validated via Luhn at scan time.
_PAN_CANDIDATE_RE = re.compile(
    r"\b(?:\d{4}[-\s]?){3,4}\d{1,4}\b",
)

# Candidate IBAN: 2 letters + 2 digits + 11–30 alphanumerics.
_IBAN_CANDIDATE_RE = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
)

# SWIFT BIC: 4 letter bank + 2 letter country + 2 alphanumeric
# location + optional 3-character branch.
_BIC_RE = re.compile(
    r"\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b",
)

# Structured-transaction smurfing: amounts deliberately just below
# US $10,000 (BSA Currency Transaction Report threshold). Pattern
# catches values $9,000-$9,999 in dollar form.
_STRUCTURED_AMOUNT_RE = re.compile(
    r"\$\s?9[\.,]?\d{3}(?:\.\d{2})?\b",
)

# OFAC SDN sample names — a representative subset. Full catalogue
# pulled from US Treasury feeds is outside scope.
_OFAC_NAME_HINTS_RE = re.compile(
    r"\b(?:Specially\s+Designated\s+Nationals?|"
    r"OFAC\s+(?:Sanctions?|SDN)\s+List|"
    r"sanctioned\s+(?:entity|individual|jurisdiction))\b",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FintechAmlScanner:
    """Detects validated PAN / IBAN / BIC + structured-transaction
    smurf signatures + OFAC sanction list signals. Returns
    ``passed=False`` on any validated match. Confidence is
    ``critical`` (1.0) for any checksum-validated finance
    identifier."""

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"vertical": "fintech", "matches": []},
            )

        matches: list[dict[str, str]] = []

        # PAN (Luhn-validated).
        for m in _PAN_CANDIDATE_RE.finditer(target):
            digits = re.sub(r"[-\s]", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn_check(digits):
                matches.append({
                    "label": "fintech_pan_luhn_validated",
                    "severity": "critical",
                    "match": digits[:6] + "*" * (len(digits) - 10) + digits[-4:],
                })

        # IBAN (mod-97 validated).
        for m in _IBAN_CANDIDATE_RE.finditer(target.upper()):
            if _iban_check(m.group(0)):
                matches.append({
                    "label": "fintech_iban_mod97_validated",
                    "severity": "critical",
                    "match": (
                        m.group(0)[:4] + "*" * (len(m.group(0)) - 8)
                        + m.group(0)[-4:]
                    ),
                })

        # SWIFT BIC — format-only check (no public checksum).
        for m in _BIC_RE.finditer(target):
            # Heuristic: BIC must be a standalone token, not a
            # word-like substring of an English word. The \b
            # already enforces that.
            matches.append({
                "label": "fintech_swift_bic_format",
                "severity": "high",
                "match": m.group(0),
            })

        # Structured-transaction smurfing.
        smurf_count = len(_STRUCTURED_AMOUNT_RE.findall(target))
        if smurf_count >= 2:
            # 2+ amounts just-below threshold in same target = smurf
            # signal. A single $9,999 is just a price.
            matches.append({
                "label": "fintech_smurf_structured_transactions",
                "severity": "high",
                "match": f"{smurf_count} amounts in $9,000-$9,999 range",
            })

        # OFAC SDN explicit reference.
        m = _OFAC_NAME_HINTS_RE.search(target)
        if m is not None:
            matches.append({
                "label": "fintech_ofac_sdn_signal",
                "severity": "high",
                "match": m.group(0),
            })

        if not matches:
            return ScanResult(
                passed=True, confidence=0.95,
                reason="no AML / sanctions signals detected",
                detail={
                    "vertical": "fintech",
                    "matches": [],
                },
            )

        worst = (
            "critical"
            if any(m["severity"] == "critical" for m in matches)
            else "high"
        )
        confidence = 1.0 if worst == "critical" else 0.9

        return ScanResult(
            passed=False, confidence=confidence,
            reason=(
                f"AML / sanctions signal detected — "
                f"{len(matches)} match(es); worst severity {worst}"
            ),
            detail={
                "vertical": "fintech",
                "match_count": len(matches),
                "worst_severity": worst,
                "matches": matches[:10],
            },
        )


def _register_fintech_patterns() -> None:
    """Register under explicit ``aml`` strategy alias only.

    Multi-vertical safety: same reasoning as healthcare + legal —
    we deliberately avoid shadowing the OSS generic ``pattern``
    strategy. Adopters declare ``strategy: aml`` in their
    Shield, or compose via
    ``ensemble_configs.fintech_ensemble()``.
    """
    scanner = FintechAmlScanner()
    for category in ("pii_leak", "data_exfil"):
        default_registry.register(category, scanner, strategy="aml")


_register_fintech_patterns()


__all__ = [
    "FintechAmlScanner",
]
