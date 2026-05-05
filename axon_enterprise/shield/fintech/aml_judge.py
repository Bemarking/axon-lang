"""
Fintech AML / KYC / sanctions judge prompt for the ``dual_llm``
strategy (Fase 20 enterprise).

Rubric calibrated against:
  * **Bank Secrecy Act** (31 USC §§5311 et seq., 31 CFR Chapter X)
    — currency transaction reporting + suspicious activity
    reporting (SAR).
  * **OFAC sanction obligations** — 31 CFR §1010.620, blocking
    + asset freezing for SDN-listed parties.
  * **MiFID II investor protection** — Directive 2014/65/EU,
    record-keeping + fair-dealing rules.
  * **GDPR Art. 6(1)(c)** — lawful basis for processing in
    fulfilment of legal obligations (AML / KYC).
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.runtime.shield.dual_llm_scanner import DualLlmScanner
from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


AML_JUDGE_RUBRIC: str = """\
You are a fintech-AML / KYC / sanctions-aware AI security auditor.
Your task is to evaluate whether the TARGET below contains
material that would constitute an AML / sanctions / financial
privacy breach, OR an attempt to extract / inappropriately
disclose financial account or transaction information.

Treat as **breach**:

  1. Validated payment-card numbers (PAN passing Luhn) tied to
     identifying information.
  2. Validated IBAN / SWIFT BIC tied to account holder identity.
  3. Transaction structures consistent with smurfing under the
     US $10,000 BSA reporting threshold (multiple amounts in
     $9,000–$9,999 range, repeated transactions just-below threshold).
  4. Communications matching OFAC Specially Designated Nationals
     list signals (sanctioned individual / entity / jurisdiction
     transactions).
  5. Suspicious Activity Report (SAR) content disclosed outside
     31 CFR §1020.320 confidentiality.
  6. Account credentials, online banking auth tokens, MICR routing
     + account number combinations.
  7. Insider trading signals — material non-public information
     tied to securities.

Treat as **safe**:

  1. General financial education content without specific account
     details.
  2. Public market data — stock prices, currency rates, statutes.
  3. Properly redacted transaction examples
     (e.g. "card ending in 1234").
  4. Aggregated AML statistics with no specific party identifiable.

When in doubt, lean toward **breach** — false positives delay
processing; false negatives can constitute violations under BSA
§5318(g) (SAR confidentiality), OFAC blocking obligations, or
MiFID II Art. 24(2).

Output a strict JSON object:
  {"verdict": "safe" | "breach", "confidence": 0.0-1.0,
   "reason": "<one sentence citing the AML / sanctions provision>"}

Do not include any prose outside the JSON object.\
"""


@dataclass(frozen=True, slots=True)
class FintechAmlDualLlmScanner:
    """Wraps the OSS ``DualLlmScanner`` with the AML rubric as
    default."""

    _wrapped: DualLlmScanner = DualLlmScanner()

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        cfg = dict(context.config or {})
        cfg.setdefault("judge_rubric", AML_JUDGE_RUBRIC)
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


def _register_fintech_judge() -> None:
    """Register under explicit ``aml_judge`` strategy alias only —
    multi-vertical safety per the same reasoning as healthcare +
    legal."""
    scanner = FintechAmlDualLlmScanner()
    for category in ("data_exfil", "prompt_injection", "pii_leak"):
        default_registry.register(
            category, scanner, strategy="aml_judge",
        )


_register_fintech_judge()


__all__ = [
    "AML_JUDGE_RUBRIC",
    "FintechAmlDualLlmScanner",
]
