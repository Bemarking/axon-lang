"""
Axon Enterprise — Vertical Shield Scanners (Fase 20 R&D).

Where ``axon-lang`` (OSS) ships the registry + protocol + generic
baselines (pattern / canary / capability_validate / classifier
shells / dual_llm with generic rubrics), this package ships the
**vertical R&D** the OSS deliberately does not:

  * **Healthcare (HIPAA)**
    - PHI regex catalog: MRN, NPI (Luhn-validated), ICD-10 codes,
      CPT codes, DEA-scheduled drug names, patient-name+DOB
      co-occurrence.
    - Pre-curated HIPAA Security Rule judge rubric for the
      ``dual_llm`` strategy.
    - ``healthcare_ensemble()`` factory: pattern + classifier +
      dual_llm with HIPAA-tuned threshold (2-of-3 majority).

  * **Legal (privilege + work-product)**
    - Attorney-client privilege markers + work-product doctrine
      patterns.
    - Pre-curated legal privilege judge rubric.
    - ``legal_ensemble()`` factory.

  * **Fintech (AML + KYC + sanctions)**
    - PAN with Luhn checksum, IBAN with mod-97 checksum, SWIFT
      BIC format, structured-transaction smurf signatures.
    - SDN/OFAC sanction list common-name patterns (subset; full
      catalog requires updating from US Treasury feeds).
    - Pre-curated MiFID II / AML judge rubric.
    - ``fintech_ensemble()`` factory.

Per the axon-enterprise charter
(``memory/project_axon_enterprise_charter.md`` in axon-lang OSS):
this is the privileged R&D layer that justifies enterprise
licensing. A fork of axon-lang OSS is free to improve the
language; what it cannot replicate trivially is the curated
vertical knowledge that lives in this package.

Importing this package auto-registers the vertical scanners
against ``axon.runtime.shield_scanners.default_registry``. Adopters
who install axon-enterprise + import it (typically at app startup)
get vertical PHI / privilege / AML coverage immediately, shadowing
the OSS generic scanners for the same ``(category, strategy)``
keys.
"""

# Side-effectful imports: each module's auto-registration runs at
# load time. Order matters only for diagnostic clarity (later
# registrations under the same `(category, strategy)` key shadow
# earlier — vertical scanners deliberately shadow OSS baselines).
from axon_enterprise.shield import (  # noqa: F401 — import for side effects
    healthcare,
    legal,
    fintech,
    ensemble_configs,
)


__all__ = [
    "healthcare",
    "legal",
    "fintech",
    "ensemble_configs",
]
