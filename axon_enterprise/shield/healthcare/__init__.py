"""
Healthcare vertical shield scanners — HIPAA PHI detection +
Security Rule judge.

This subpackage's import-time hooks register PHI-aware scanners
against ``axon.runtime.shield_scanners.default_registry``,
shadowing the OSS generic ``pii_leak`` and ``data_exfil`` scanners
under the same ``(category, strategy)`` keys.

Modules:
  * :mod:`hipaa_patterns` — regex catalog for the 18 HIPAA Safe
    Harbor identifiers (Mass General Brigham + 45 CFR §164.514(b)
    based subset that's safe to ship — no real PHI corpus).
  * :mod:`hipaa_judge` — judge prompt for the ``dual_llm`` strategy,
    rubric calibrated against HIPAA Security Rule §164.308–.314 +
    GDPR Art. 25 minimisation.
"""

from axon_enterprise.shield.healthcare import (  # noqa: F401 — side effects
    hipaa_patterns,
    hipaa_judge,
)


__all__ = [
    "hipaa_patterns",
    "hipaa_judge",
]
