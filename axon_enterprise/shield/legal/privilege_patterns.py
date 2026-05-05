"""
Legal privilege + work-product detection patterns (Fase 20
enterprise).

Catches the canonical markers that signal a document or communication
is protected by attorney-client privilege or the attorney
work-product doctrine. A flow that processes legal documents in a
multi-tenant SaaS setting MUST have these markers gate the boundary
where privileged content might cross to a model that is not
covered by the engagement letter.

Reference frameworks:

  * **Federal Rule of Evidence 502** (privilege waiver)
  * **Upjohn Co. v. United States, 449 U.S. 383 (1981)** — corporate
    attorney-client privilege scope.
  * **Hickman v. Taylor, 329 U.S. 495 (1947)** — work-product
    doctrine (qualified protection for materials prepared in
    anticipation of litigation).
  * **ABA Model Rules of Professional Conduct 1.6** — duty of
    confidentiality.

Per the Bemarking AI charter: this is privileged R&D material —
adopters running enterprise legal flows get patterns refined
against years of legal-tech experience. Charter compliance: this
file MUST appear in axon-enterprise only, never in OSS.
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
#  PRIVILEGE + WORK-PRODUCT PATTERNS
# ═══════════════════════════════════════════════════════════════════
#
# Every match is `critical` severity — privileged content leaving
# the privileged channel is a per-se professional-conduct issue.

_LEGAL_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # Explicit confidentiality + privilege markers (most common
    # boilerplate at the top of privileged emails / memos).
    (r"(?i)\bprivileged\s+and\s+confidential\b",
     "critical", "privileged_and_confidential_marker"),
    (r"(?i)\battorney[-\s]client\s+(?:privilege|communication)\b",
     "critical", "attorney_client_privilege_marker"),
    (r"(?i)\b(?:subject\s+to|protected\s+by)\s+"
     r"attorney[-\s]client\s+privilege\b",
     "critical", "explicit_privilege_invocation"),
    (r"(?i)\bdo\s+not\s+disclose\s+(?:without|except)\s+"
     r"(?:counsel|attorney|lawyer)\b",
     "critical", "disclosure_restriction_legal"),

    # Work-product doctrine markers (Hickman v. Taylor).
    (r"(?i)\bprepared\s+in\s+anticipation\s+of\s+litigation\b",
     "critical", "work_product_anticipation_marker"),
    (r"(?i)\battorney\s+work[-\s]product\b",
     "critical", "work_product_marker"),
    (r"(?i)\bmental\s+impressions\s+(?:of\s+)?counsel\b",
     "critical", "work_product_mental_impressions"),

    # Common privilege claim language.
    (r"(?i)\bunder\s+(?:the\s+)?(?:protection\s+of|claim\s+of)\s+"
     r"(?:attorney[-\s]client|legal)\s+privilege\b",
     "critical", "privilege_claim_language"),

    # Communications structure markers — attorney-client comms
    # often have specific salutation patterns.
    (r"(?i)\b(?:from|to)\s*:\s*[A-Z][a-z]+\s+[A-Z][a-z]+,?\s+"
     r"(?:Esq\.|Esquire|Attorney(?:\s+at\s+Law)?|"
     r"General\s+Counsel|Associate\s+Counsel|Of\s+Counsel)\b",
     "high", "attorney_signatory"),

    # Retainer / engagement letter language.
    (r"(?i)\bengagement\s+letter\b",
     "high", "engagement_letter_marker"),
    (r"(?i)\bretainer\s+agreement\b",
     "high", "retainer_marker"),

    # Litigation strategy markers.
    (r"(?i)\b(?:litigation|trial|case|defence)\s+strategy\b",
     "high", "litigation_strategy_marker"),
    (r"(?i)\b(?:weak|strong)\s+points\s+(?:of\s+)?"
     r"(?:our|the)\s+case\b",
     "high", "case_assessment_marker"),

    # Deposition / trial transcript signatures.
    (r"(?i)\bdeposition\s+of\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b",
     "high", "deposition_signature"),
    (r"(?i)\bQ[\.\:]\s+.+?\s+A[\.\:]\s+",
     "medium", "deposition_qa_format"),

    # Settlement / FRE 408 communications.
    (r"(?i)\bsettlement\s+(?:offer|negotiation|discussion)\b",
     "high", "settlement_communication"),
    (r"(?i)\bFRE\s+408\b",
     "high", "fre_408_invocation"),
    (r"(?i)\bwithout\s+prejudice\b",
     "high", "without_prejudice_marker"),

    # Case citation patterns (judicial opinions in privileged
    # research).
    (r"\b\d+\s+(?:U\.S\.|F\.\s?\d+d|S\.\s?Ct\.|F\.\s?Supp\.\s?\d*d?)\s+\d+\b",
     "low", "us_case_citation"),
    (r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+v\.\s+"
     r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
     "low", "case_caption_format"),

    # NDA / confidentiality boilerplate that often wraps privileged
    # material.
    (r"(?i)\b(?:non[-\s]disclosure|confidentiality)\s+agreement\b",
     "medium", "nda_marker"),
)


_compiled: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), sev, label)
    for p, sev, label in _LEGAL_PATTERNS
]


# ═══════════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LegalPrivilegeScanner:
    """Detects attorney-client privilege markers + work-product
    doctrine signals + deposition transcripts + settlement
    communications. Any match → breach (privileged content
    leaving privileged channel)."""

    _SEVERITY_CONFIDENCE = {
        "critical": 1.0, "high": 0.9, "medium": 0.75, "low": 0.5,
    }

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"vertical": "legal", "matches": []},
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
                passed=True, confidence=0.9,
                reason="no privilege / work-product markers detected",
                detail={
                    "vertical": "legal",
                    "patterns_evaluated": len(_compiled),
                    "matches": [],
                },
            )

        # Critical-only filter: low-severity case citations alone
        # do NOT trigger breach (they're public information). Only
        # medium+ count.
        non_low = [m for m in matches if m["severity"] != "low"]
        if not non_low:
            return ScanResult(
                passed=True, confidence=0.6,
                reason=(
                    f"only public case citations matched ({len(matches)}); "
                    f"not privileged"
                ),
                detail={
                    "vertical": "legal",
                    "match_count": len(matches),
                    "low_severity_only": True,
                    "matches": matches[:10],
                },
            )

        return ScanResult(
            passed=False,
            confidence=self._SEVERITY_CONFIDENCE.get(worst, 0.5),
            reason=(
                f"legal privilege detected — {len(non_low)} "
                f"privileged marker(s); worst severity {worst}"
            ),
            detail={
                "vertical": "legal",
                "match_count": len(non_low),
                "worst_severity": worst,
                "matches": non_low[:10],
            },
        )


def _register_legal_patterns() -> None:
    scanner = LegalPrivilegeScanner()
    # Privileged content leaving the system is a data_exfil concern.
    # Privileged content asked-for in a prompt is a prompt_injection
    # / extraction attempt.
    default_registry.register("data_exfil", scanner, strategy="legal")
    default_registry.register(
        "prompt_injection", scanner, strategy="legal",
    )
    # Also under explicit "privilege" alias for clarity.
    default_registry.register(
        "data_exfil", scanner, strategy="privilege",
    )


_register_legal_patterns()


__all__ = [
    "LegalPrivilegeScanner",
]
