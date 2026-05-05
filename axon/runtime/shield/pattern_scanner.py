"""
Pattern strategy — regex matchers against curated threat catalogs
(Fase 20.b).

OSS baseline catalogs cover the GENERIC threat surface every adopter
shares: prompt injection, jailbreak attempts, basic data exfil
signals, generic PII (RFC-compliant email + ITU E.164 phone),
shell/SQL code injection markers, model-theft probes, training-
poisoning markers.

What is NOT in this file (per the axon-enterprise charter):

  * HIPAA-grade PHI patterns (medical record numbers, NPI, ICD-10
    codes, drug names, GCS scores, etc.) — those live in
    ``axon-enterprise``.
  * Legal-privilege markers (attorney-client phrases, work-product
    doctrine cues, deposition transcripts patterns).
  * Fintech AML / KYC patterns (PAN, IBAN regex with Luhn check,
    SDN list lookups, structured-transaction smurf signatures).

Adopters who need vertical patterns either install
``axon-enterprise`` (which registers them at import time, shadowing
the OSS baselines for the same category when configured) or call
``default_registry.register(category, MyScanner(), strategy="pattern")``
themselves.
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
#  CATALOGS
# ═══════════════════════════════════════════════════════════════════
#
# Each catalog is a list of (pattern, severity, label) tuples. The
# scanner compiles them lazily on first use and caches the compiled
# objects per category. Adopters who want to extend catalogs without
# subclassing can register a fresh PatternScanner with their own
# patterns under the same (category, "pattern") key.
#
# Patterns are case-insensitive and treat the target as a single
# multiline string. Match = breach.


_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+"
     r"(instructions?|prompts?|rules?|directives?)\b",
     "high", "ignore_previous_instructions"),
    (r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\b",
     "high", "disregard_previous"),
    (r"\byou\s+are\s+now\s+(?:a\s+)?(?:new|different|free|unrestricted)\b",
     "high", "role_override"),
    (r"\bforget\s+(everything\s+)?(?:i\s+)?(?:told\s+you|your\s+instructions)\b",
     "high", "forget_instructions"),
    (r"###\s*(end|stop|halt)\s+(of\s+)?(prompt|instructions)\s*###",
     "medium", "instruction_terminator"),
    (r"<\s*\|?\s*(system|admin|root|user|assistant)\s*\|?\s*>",
     "medium", "role_token_injection"),
    (r"\bprint\s+your\s+(system\s+)?(prompt|instructions|rules)\b",
     "high", "prompt_extraction"),
    (r"\brepeat\s+(your\s+)?(system|original|initial)\s+"
     r"(prompt|instructions|message)\b",
     "high", "prompt_extraction_repeat"),
)

_JAILBREAK_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bDAN\b.{0,20}\b(do\s+anything\s+now|jailbreak|unrestricted)\b",
     "critical", "DAN_jailbreak"),
    (r"\bdo\s+anything\s+now\b",
     "critical", "do_anything_now"),
    # Matches either order: "developer mode ... enable" or
    # "enable/activate/turn on ... developer mode".
    (r"\b(?:developer\s+mode\b.{0,40}\b(?:enable[ds]?|activate[ds]?|on|now)\b"
     r"|(?:enable|activate|turn\s+on|switch\s+on)\b.{0,40}\b"
     r"developer\s+mode\b)",
     "high", "developer_mode_enable"),
    (r"\bevil\s+(?:confidant|twin|persona|mode)\b",
     "high", "evil_persona"),
    (r"\b(?:no|without)\s+(?:rules|restrictions|limits|filters|safety)\b",
     "high", "no_safety_request"),
    (r"\bpretend\s+(?:to\s+be|you\s+are)\s+(?:an?\s+)?(?:ai|llm|model)\s+"
     r"(?:without|with\s+no)\s+(?:rules|restrictions|filters)\b",
     "high", "pretend_no_safety"),
    (r"\bSTAN\b.{0,30}\b(strive\s+to\s+avoid|jailbreak)\b",
     "high", "STAN_jailbreak"),
)

_DATA_EXFIL_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # Generic webhook beacons — known telemetry collectors.
    (r"https?://(?:[\w-]+\.)?(?:webhook\.site|requestbin\.[a-z]+|"
     r"pipedream\.com|ngrok\.io|requestcatcher\.com)/[\w-]+",
     "critical", "known_exfil_webhook"),
    # Base64-encoded blocks > 200 chars are suspicious as a tunnel.
    (r"(?:[A-Za-z0-9+/]{4}){50,}={0,2}",
     "medium", "long_base64_block"),
    # Suspicious data URIs that hide a payload.
    (r"data:[\w/+-]+;base64,[A-Za-z0-9+/=]{200,}",
     "high", "data_uri_payload"),
)

_PII_LEAK_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # RFC-compliant email — generic, not domain-restricted.
    # Adopters in healthcare get HIPAA-grade variants from
    # axon-enterprise that strip emails matching specific
    # patient-facing domains.
    (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
     "medium", "email_address"),
    # ITU E.164 phone numbers (international format).
    (r"\+?\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{2,4}[\s-]?\d{2,9}",
     "medium", "phone_number_e164"),
    # Generic SSN / national ID format (XXX-XX-XXXX). NOT
    # validated — that's a SPLIT enterprise responsibility.
    (r"\b\d{3}-\d{2}-\d{4}\b",
     "high", "us_ssn_format"),
    # Generic credit card number format (Luhn check is enterprise).
    (r"\b(?:\d[\s\-]?){13,19}\b",
     "high", "credit_card_format"),
)

_CODE_INJECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # Shell command injection markers.
    (r";\s*(?:rm|cat|wget|curl|nc|bash|sh)\s+",
     "critical", "shell_command_chain"),
    (r"\$\(\s*(?:rm|cat|wget|curl|nc|bash|sh|eval)\b",
     "critical", "shell_command_substitution"),
    (r"`\s*(?:rm|cat|wget|curl|nc|bash|sh)\s+[^`]+`",
     "critical", "shell_backtick_substitution"),
    # SQL injection markers.
    (r"(?i)\b(?:union\s+(?:all\s+)?select|or\s+1\s*=\s*1|"
     r"drop\s+table|insert\s+into|delete\s+from)\b",
     "critical", "sql_injection"),
    # Python eval/exec patterns.
    (r"\b(?:eval|exec|__import__)\s*\(\s*[\"']",
     "high", "python_dynamic_exec"),
    # Prototype pollution in JS-like inputs.
    (r"__proto__\s*[:\[]",
     "high", "prototype_pollution"),
)

_TOXICITY_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # OSS baseline does NOT ship slur lists — those live in enterprise
    # with proper localisation + cultural review. We only catch
    # explicit threat language patterns here.
    (r"\b(?:i\s+(?:will|shall)|going\s+to)\s+(?:kill|murder|harm|"
     r"hurt|stab|shoot)\s+(?:you|him|her|them)\b",
     "critical", "explicit_threat"),
    (r"\bcommit\s+(?:suicide|self.?harm)\b",
     "critical", "self_harm_advocacy"),
)

_BIAS_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # OSS baseline is empty — bias detection is heavily
    # context-dependent and requires curated corpora. Enterprise
    # ships domain-specific bias detectors.
)

_HALLUCINATION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # Pattern-based hallucination detection is unreliable; this
    # category is best served by `dual_llm` or `classifier`.
    # The OSS pattern catalog is intentionally minimal — only catches
    # the most common over-confident phrasing.
    (r"(?i)\b(?:i\s+am\s+)?(?:100%|completely|absolutely|definitely)\s+"
     r"(?:certain|sure)\s+that\b.{0,200}\b(?:always|never|every|none)\b",
     "low", "overconfident_universal"),
)

_SOCIAL_ENGINEERING_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"(?i)\bthis\s+is\s+(?:an\s+)?(?:emergency|urgent|critical)\b.{0,200}"
     r"\b(?:password|api[_\s]key|secret|token|credential)\b",
     "high", "urgency_credential_request"),
    (r"(?i)\bi'm\s+(?:the\s+)?(?:ceo|cto|admin|root|owner)\b.{0,200}"
     r"\b(?:override|bypass|disable)\b",
     "high", "authority_override_claim"),
    (r"(?i)\bjust\s+(?:between|trust|tell)\s+(?:us|me|you)\b.{0,150}"
     r"\b(?:password|secret|token|credential|confidential)\b",
     "high", "trust_appeal"),
)

_MODEL_THEFT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"(?i)\b(?:repeat|output|print)\s+(?:your\s+)?(?:weights|"
     r"parameters|logits|hidden\s+states)\b",
     "critical", "weights_extraction_request"),
    (r"(?i)\benumerate\s+(?:all\s+)?(?:training|fine[\s-]tun(?:ing|ed))\s+"
     r"(?:examples|samples|data)\b",
     "high", "training_data_extraction"),
)

_TRAINING_POISONING_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"(?i)\bremember\s+(?:this|forever)\s+for\s+(?:future|all)\s+"
     r"(?:users|conversations|sessions)\b",
     "high", "cross_session_memory_injection"),
    (r"(?i)\bsave\s+(?:this|my)\s+(?:instruction|directive|rule)\s+"
     r"(?:permanently|globally|for\s+everyone)\b",
     "high", "global_directive_injection"),
)


_CATALOGS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "prompt_injection": _PROMPT_INJECTION_PATTERNS,
    "jailbreak": _JAILBREAK_PATTERNS,
    "data_exfil": _DATA_EXFIL_PATTERNS,
    "pii_leak": _PII_LEAK_PATTERNS,
    "code_injection": _CODE_INJECTION_PATTERNS,
    "toxicity": _TOXICITY_PATTERNS,
    "bias": _BIAS_PATTERNS,
    "hallucination": _HALLUCINATION_PATTERNS,
    "social_engineering": _SOCIAL_ENGINEERING_PATTERNS,
    "model_theft": _MODEL_THEFT_PATTERNS,
    "training_poisoning": _TRAINING_POISONING_PATTERNS,
}


# ═══════════════════════════════════════════════════════════════════
#  COMPILED PATTERNS — lazy
# ═══════════════════════════════════════════════════════════════════

_compiled_cache: dict[str, list[tuple[re.Pattern[str], str, str]]] = {}


def _compiled(category: str) -> list[tuple[re.Pattern[str], str, str]]:
    """Return the compiled patterns for ``category``. Compiles on
    first use and caches; subsequent calls are zero-cost."""
    cached = _compiled_cache.get(category)
    if cached is not None:
        return cached
    raw = _CATALOGS.get(category, ())
    compiled = [
        (re.compile(pattern, re.IGNORECASE | re.MULTILINE), severity, label)
        for pattern, severity, label in raw
    ]
    _compiled_cache[category] = compiled
    return compiled


# ═══════════════════════════════════════════════════════════════════
#  SCANNER IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PatternScanner:
    """Stateless regex scanner. One instance per category — registered
    once into ``default_registry`` at import time.

    The scanner returns a single :class:`ScanResult` aggregating ALL
    pattern matches found in the target. ``passed=False`` iff any
    pattern matched. ``confidence`` is derived from the highest
    severity hit (critical → 1.0, high → 0.85, medium → 0.7,
    low → 0.5).
    """

    category: str

    _SEVERITY_CONFIDENCE: tuple[tuple[str, float], ...] = (
        ("critical", 1.0),
        ("high", 0.85),
        ("medium", 0.7),
        ("low", 0.5),
    )

    @staticmethod
    def _severity_to_confidence(severity: str) -> float:
        for sev, conf in PatternScanner._SEVERITY_CONFIDENCE:
            if sev == severity:
                return conf
        return 0.5

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            # Empty target — nothing to match against. Pass with
            # max confidence; the dispatcher's category aggregation
            # will still see this as a passed scan.
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"category": self.category, "matches": []},
            )

        matches: list[dict[str, str]] = []
        worst_severity = "low"
        severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        for compiled, severity, label in _compiled(self.category):
            m = compiled.search(target)
            if m is not None:
                matches.append({
                    "label": label,
                    "severity": severity,
                    "match": m.group(0)[:120],
                    "span": f"{m.start()}-{m.end()}",
                })
                if severity_rank[severity] > severity_rank[worst_severity]:
                    worst_severity = severity

        if not matches:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="no patterns matched",
                detail={
                    "category": self.category,
                    "patterns_evaluated": len(_compiled(self.category)),
                    "matches": [],
                },
            )

        return ScanResult(
            passed=False,
            confidence=self._severity_to_confidence(worst_severity),
            reason=(
                f"{len(matches)} pattern(s) matched — worst severity: "
                f"{worst_severity}; first hit: {matches[0]['label']}"
            ),
            detail={
                "category": self.category,
                "match_count": len(matches),
                "worst_severity": worst_severity,
                "matches": matches[:10],  # cap for trace size
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


def _register_oss_baselines() -> None:
    """Register a :class:`PatternScanner` for every category that has
    a non-empty catalog. Called at import time. Adopters who want to
    shadow a category register their own under the same key — last
    registration wins."""
    for category, catalog in _CATALOGS.items():
        if catalog:
            default_registry.register(
                category, PatternScanner(category=category),
                strategy="pattern",
            )


_register_oss_baselines()


__all__ = [
    "PatternScanner",
]
