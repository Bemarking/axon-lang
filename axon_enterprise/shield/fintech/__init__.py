"""
Fintech vertical shield scanners — AML / KYC / sanctions detection
+ MiFID II judge (Fase 20 enterprise).

Modules:
  * :mod:`aml_patterns` — regex catalog with **validated** PAN
    (Luhn-checked), IBAN (mod-97 validated), SWIFT BIC, sanction-
    list common-name signals, structured-transaction smurf
    signatures.
  * :mod:`aml_judge` — judge prompt calibrated against MiFID II
    investor protection, BSA/AML record-keeping, OFAC SDN
    obligations, GDPR Art. 6(1)(c) legal-basis processing for
    AML / KYC.
"""

from axon_enterprise.shield.fintech import (  # noqa: F401 — side effects
    aml_patterns,
    aml_judge,
)


__all__ = [
    "aml_patterns",
    "aml_judge",
]
