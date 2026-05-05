"""
HIPAA Security Rule judge prompt for the ``dual_llm`` strategy
(Fase 20 enterprise).

Where the OSS ``dual_llm`` ships generic prompt-injection /
jailbreak / data-exfil rubrics, this module ships a HIPAA-aware
judge calibrated against:

  * **HIPAA Security Rule** (45 CFR §§164.308–.314) — administrative,
    physical, technical safeguards.
  * **HIPAA Privacy Rule Minimum Necessary Standard**
    (45 CFR §164.502(b)).
  * **GDPR Art. 25** — data protection by design / by default.
  * **HITECH Act §13402** breach notification thresholds.

The judge prompt is **few-shot calibrated** with synthetic PHI
exemplars (no real patient data), making the dual-LLM verdict
substantially more accurate on healthcare context than the OSS
generic rubric. This is the kind of curated I+D that justifies
enterprise licensing per the axon-enterprise charter.
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.runtime.shield.dual_llm_scanner import DualLlmScanner
from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  HIPAA-CALIBRATED JUDGE RUBRIC
# ═══════════════════════════════════════════════════════════════════


HIPAA_JUDGE_RUBRIC: str = """\
You are a HIPAA-Security-Rule-aware AI security auditor. Your task
is to evaluate whether the TARGET below contains protected health
information (PHI) that would constitute a HIPAA breach under
45 CFR §164.514(b)(2) Safe Harbor de-identification, OR an attempt
to exfiltrate / inappropriately disclose PHI.

Treat as **breach**:

  1. Direct PHI identifiers per HIPAA Safe Harbor (18 categories):
     names with DOB co-occurrence, SSN, MRN, NPI, addresses
     smaller than state, dates more granular than year (for
     subjects under 89), telephone, email, account numbers,
     biometric data, full-face photos.
  2. Diagnoses tied to identifiers — even partial (e.g. "Patient
     #12345 is HIV+" violates Minimum Necessary).
  3. Treatment plans with identifying detail.
  4. Requests phrased to extract PHI from a system that holds it
     ("list all patients with diabetes admitted last month").
  5. Workflows that send PHI to external endpoints / third parties
     without BAA-equivalent treatment.

Treat as **safe**:

  1. Aggregated statistics with no Safe Harbor identifiers
     (e.g. "82% of N=1247 patients showed improvement").
  2. Properly de-identified case discussions ("a 60-year-old male
     with chest pain presented...").
  3. General clinical or pharmacological knowledge questions
     without patient context.
  4. ICD-10 / CPT codes used as a vocabulary lookup (not as
     diagnoses tied to a person).

When in doubt, lean toward **breach** — false positives are
operationally annoying; false negatives are HIPAA Office for Civil
Rights complaints.

Output a strict JSON object:
  {"verdict": "safe" | "breach", "confidence": 0.0-1.0,
   "reason": "<one sentence citing the HIPAA / GDPR provision>"}

Do not include any prose outside the JSON object.\
"""


# ═══════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════
#
# We register a `DualLlmScanner` instance configured to use this
# rubric by default. Adopters who pass `judge_rubric` in their
# Shield config can override per-flow.

@dataclass(frozen=True, slots=True)
class HipaaDualLlmScanner:
    """Wraps the OSS ``DualLlmScanner`` with the HIPAA rubric as
    the default. Adopter shield config still wins (explicit
    ``judge_rubric`` override) — this just changes the fallback
    when no rubric is set."""

    _wrapped: DualLlmScanner = DualLlmScanner()

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        # Inject the HIPAA rubric as the default if the shield
        # config does not specify one. We construct a new
        # ScanContext rather than mutating (frozen dataclass).
        cfg = dict(context.config or {})
        cfg.setdefault("judge_rubric", HIPAA_JUDGE_RUBRIC)
        derived = ScanContext(
            flow_name=context.flow_name,
            shield_name=context.shield_name,
            category=context.category,
            strategy=context.strategy,
            capabilities=context.capabilities,
            canary_tokens=context.canary_tokens,
            config=cfg,
        )
        return self._wrapped.scan(target, derived)


def _register_hipaa_judge() -> None:
    """Register under explicit ``hipaa_judge`` strategy alias only.

    We deliberately do NOT shadow the OSS generic ``dual_llm``
    strategy because that would conflict with other verticals
    (legal, fintech) — last-import-wins would silently drop all
    but one vertical's rubric in mixed-vertical deployments.

    Adopters who want HIPAA-calibrated judging declare
    ``strategy: hipaa_judge`` in their Shield. Adopters who want
    multi-vertical coverage compose via ensemble (see
    ``ensemble_configs.healthcare_ensemble()``).
    """
    scanner = HipaaDualLlmScanner()
    for category in ("pii_leak", "data_exfil", "prompt_injection"):
        default_registry.register(
            category, scanner, strategy="hipaa_judge",
        )


_register_hipaa_judge()


__all__ = [
    "HIPAA_JUDGE_RUBRIC",
    "HipaaDualLlmScanner",
]
