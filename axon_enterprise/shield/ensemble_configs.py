"""
Vertical-tuned ensemble factories (Fase 20 enterprise).

Each factory returns an ``EnsembleScanner`` pre-composed with the
specific OSS + enterprise scanners that produce production-grade
coverage for one vertical. Adopters call the factory once at
startup and register the result under their preferred
``(category, strategy)`` keys:

    from axon_enterprise.shield.ensemble_configs import healthcare_ensemble
    from axon.runtime.shield_scanners import default_registry

    default_registry.register(
        "pii_leak",
        healthcare_ensemble(),
        strategy="ensemble",
    )

Each factory documents:
  * Which OSS scanners it composes (pattern, classifier, dual_llm,
    canary).
  * Which enterprise scanners it composes (HIPAA / legal / AML
    pattern + judge).
  * The recommended ``vote_strategy`` + threshold.
  * The compliance frameworks it's calibrated against.

Per the axon-enterprise charter: this file ships the **opinionated
composition** that's hard to replicate — the choice of which
scanners to include + their weights + thresholds is the I+D output
of operating real adopter healthcare / legal / fintech flows over
time. A fork of axon-lang OSS gets the EnsembleScanner operator
but not the curated configurations.
"""

from __future__ import annotations

from typing import Any

from axon.runtime.shield.ensemble_scanner import EnsembleScanner
from axon.runtime.shield_scanners import (
    ShieldScanner,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  HEALTHCARE — HIPAA-grade ensemble
# ═══════════════════════════════════════════════════════════════════


def healthcare_ensemble(category: str = "pii_leak") -> EnsembleScanner:
    """Production-grade healthcare PHI ensemble.

    Composition:
      * **HipaaPhiScanner** (enterprise, pattern) — Safe Harbor
        18-identifier regex catalog with severity tiers.
      * **OSS pattern** (axon-lang) — generic email + phone +
        SSN-format coverage as a backstop for non-Safe-Harbor PII.
      * **HipaaDualLlmScanner** (enterprise, dual_llm) — judge
        calibrated against HIPAA Security Rule + GDPR Art. 25
        minimisation.

    Vote strategy: ``threshold(2 of 3)``. Avoids both:
      * False positives from a single noisy regex match
        (HIPAA pattern alone).
      * False negatives from a single judge timeout.

    Compliance frameworks: HIPAA Security Rule §§164.308–.314,
    HIPAA Privacy Rule §164.502(b) Minimum Necessary, GDPR Art. 25.

    Args:
      category: The threat category the ensemble runs under.
                Default ``"pii_leak"``; pass ``"data_exfil"`` for
                output-side scanning.
    """
    sub_scanners: list[tuple[str, ShieldScanner]] = []

    hipaa_pattern = default_registry.lookup(category, "hipaa")
    if hipaa_pattern is not None:
        sub_scanners.append(("hipaa_pattern", hipaa_pattern))

    oss_pattern = default_registry.lookup(category, "pattern")
    if oss_pattern is not None:
        sub_scanners.append(("oss_pattern", oss_pattern))

    hipaa_judge = default_registry.lookup(category, "hipaa_judge")
    if hipaa_judge is not None:
        sub_scanners.append(("hipaa_judge", hipaa_judge))

    return EnsembleScanner(sub_scanners=tuple(sub_scanners))


# ═══════════════════════════════════════════════════════════════════
#  LEGAL — privilege + work-product ensemble
# ═══════════════════════════════════════════════════════════════════


def legal_ensemble(category: str = "data_exfil") -> EnsembleScanner:
    """Production-grade legal-privilege ensemble.

    Composition:
      * **LegalPrivilegeScanner** (enterprise, pattern) —
        attorney-client + work-product + settlement comm. catalog.
      * **OSS pattern** (axon-lang) — generic exfil patterns as
        a backstop.
      * **LegalPrivilegeDualLlmScanner** (enterprise, dual_llm) —
        judge calibrated against FRE 502, Upjohn, Hickman, ABA
        Rule 1.6.

    Vote strategy: ``majority`` (>50%) — fail-safe on ties.
    Lawyers want low false-negative rate; the regex catalogue is
    very high-precision so a single match is nearly unambiguous.

    Compliance frameworks: Federal Rule of Evidence 502
    (privilege waiver), Upjohn corporate privilege, Hickman work-
    product, ABA Model Rules 1.6 confidentiality, GDPR Art. 9
    special-category processing.
    """
    sub_scanners: list[tuple[str, ShieldScanner]] = []

    legal_pattern = default_registry.lookup(category, "legal")
    if legal_pattern is not None:
        sub_scanners.append(("legal_pattern", legal_pattern))

    oss_pattern = default_registry.lookup(category, "pattern")
    if oss_pattern is not None:
        sub_scanners.append(("oss_pattern", oss_pattern))

    legal_judge = default_registry.lookup(category, "legal_judge")
    if legal_judge is not None:
        sub_scanners.append(("legal_judge", legal_judge))

    return EnsembleScanner(sub_scanners=tuple(sub_scanners))


# ═══════════════════════════════════════════════════════════════════
#  FINTECH — AML + KYC + sanctions ensemble
# ═══════════════════════════════════════════════════════════════════


def fintech_ensemble(category: str = "pii_leak") -> EnsembleScanner:
    """Production-grade fintech AML / sanctions ensemble.

    Composition:
      * **FintechAmlScanner** (enterprise, pattern) — Luhn-
        validated PAN + mod-97-validated IBAN + SWIFT BIC +
        smurf signatures + OFAC SDN signals.
      * **OSS pattern** (axon-lang) — generic credit-card-shape
        and email coverage as a backstop.
      * **FintechAmlDualLlmScanner** (enterprise, dual_llm) —
        judge calibrated against BSA / OFAC / MiFID II.

    Vote strategy: ``threshold(2 of 3)``. Validated PAN + judge
    agreement is unambiguous; one alone could be a false positive
    (an example PAN in a unit test) or a hallucinating judge.

    Compliance frameworks: 31 CFR §1010 (BSA + OFAC),
    MiFID II Directive 2014/65/EU, GDPR Art. 6(1)(c) AML/KYC
    legal-basis processing.
    """
    sub_scanners: list[tuple[str, ShieldScanner]] = []

    aml_pattern = default_registry.lookup(category, "aml")
    if aml_pattern is not None:
        sub_scanners.append(("aml_pattern", aml_pattern))

    oss_pattern = default_registry.lookup(category, "pattern")
    if oss_pattern is not None:
        sub_scanners.append(("oss_pattern", oss_pattern))

    aml_judge = default_registry.lookup(category, "aml_judge")
    if aml_judge is not None:
        sub_scanners.append(("aml_judge", aml_judge))

    return EnsembleScanner(sub_scanners=tuple(sub_scanners))


# ═══════════════════════════════════════════════════════════════════
#  CONVENIENCE — register vertical ensembles globally
# ═══════════════════════════════════════════════════════════════════


def register_vertical_ensembles() -> None:
    """One-shot helper: register healthcare / legal / fintech
    ensembles under their respective vertical strategy aliases.
    Adopters who want all three verticals available globally call
    this once at startup.

    Resulting registry entries (additional to per-vertical
    pattern + judge):

      * ``(pii_leak, healthcare_ensemble)`` → healthcare_ensemble()
      * ``(data_exfil, legal_ensemble)``    → legal_ensemble()
      * ``(pii_leak, fintech_ensemble)``    → fintech_ensemble()

    This is OPT-IN — not called automatically — because adopters
    typically have a single vertical and prefer to register only
    the relevant one (avoids loading judge models / scanner state
    they don't need)."""
    default_registry.register(
        "pii_leak", healthcare_ensemble(),
        strategy="healthcare_ensemble",
    )
    default_registry.register(
        "data_exfil", legal_ensemble(),
        strategy="legal_ensemble",
    )
    default_registry.register(
        "pii_leak", fintech_ensemble(),
        strategy="fintech_ensemble",
    )


__all__ = [
    "fintech_ensemble",
    "healthcare_ensemble",
    "legal_ensemble",
    "register_vertical_ensembles",
]
