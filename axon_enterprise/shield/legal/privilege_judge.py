"""
Legal privilege judge prompt for the ``dual_llm`` strategy
(Fase 20 enterprise).

Rubric calibrated against:
  * **Federal Rule of Evidence 502** (privilege waiver framework)
  * **Upjohn Co. v. United States** (corporate privilege scope)
  * **Hickman v. Taylor** (work-product doctrine)
  * **ABA Model Rules 1.6** (duty of confidentiality)
  * **GDPR Art. 9** (special-category processing — legal claims
    are a recognised lawful basis but require minimisation).
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.runtime.shield.dual_llm_scanner import DualLlmScanner
from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


LEGAL_JUDGE_RUBRIC: str = """\
You are a legal-privilege-aware AI security auditor. Your task is
to evaluate whether the TARGET below contains material protected
by attorney-client privilege, the attorney work-product doctrine,
or settlement-communication confidentiality (Fed. R. Evid. 408 /
similar non-US analogues).

Treat as **breach**:

  1. Communications between client and counsel for the purpose of
     securing legal advice (Upjohn factors satisfied).
  2. Material prepared by or at the direction of counsel in
     anticipation of litigation (Hickman work-product, both fact
     and opinion subtypes).
  3. Settlement offers / counter-offers / negotiation positions
     (FRE 408 inadmissibility — but content is still privileged).
  4. Litigation strategy, case-weakness assessments, witness
     credibility evaluations, jury selection notes.
  5. Mental impressions, conclusions, opinions, or legal theories
     of an attorney.
  6. Privileged material wrapped in NDA / confidentiality language
     that would be disclosed by relaying to an LLM not covered by
     the engagement letter.

Treat as **safe**:

  1. Public case citations + statute references with no privileged
     analysis attached.
  2. General legal research / statute interpretation questions
     without client identification.
  3. Court filings already in the public record.
  4. Anonymised hypotheticals where no identifying client
     information appears.
  5. Educational / training material on legal concepts.

When in doubt, lean toward **breach** — false positives delay
review; false negatives constitute privilege waiver under FRE 502
and ABA Rule 1.6.

Output a strict JSON object:
  {"verdict": "safe" | "breach", "confidence": 0.0-1.0,
   "reason": "<one sentence citing the privilege rule or doctrine>"}

Do not include any prose outside the JSON object.\
"""


@dataclass(frozen=True, slots=True)
class LegalPrivilegeDualLlmScanner:
    """Wraps the OSS ``DualLlmScanner`` with the legal-privilege
    rubric as default."""

    _wrapped: DualLlmScanner = DualLlmScanner()

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        cfg = dict(context.config or {})
        cfg.setdefault("judge_rubric", LEGAL_JUDGE_RUBRIC)
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


def _register_legal_judge() -> None:
    """Register under explicit ``legal_judge`` strategy alias only.

    Same multi-vertical safety reasoning as healthcare: we do NOT
    shadow the OSS generic ``dual_llm`` strategy, because mixed-
    vertical deployments (a SaaS that handles both legal and
    healthcare matters) would silently drop one rubric. Adopters
    declare ``strategy: legal_judge`` explicitly, or compose via
    ``ensemble_configs.legal_ensemble()``.
    """
    scanner = LegalPrivilegeDualLlmScanner()
    for category in ("data_exfil", "prompt_injection"):
        default_registry.register(
            category, scanner, strategy="legal_judge",
        )


_register_legal_judge()


__all__ = [
    "LEGAL_JUDGE_RUBRIC",
    "LegalPrivilegeDualLlmScanner",
]
