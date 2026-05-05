"""
Legal vertical shield scanners — attorney-client privilege,
work-product doctrine, deposition transcripts (Fase 20 enterprise).

Modules:
  * :mod:`privilege_patterns` — regex catalog for privilege markers
    + work-product doctrine cues + deposition transcript signatures
    + case citation patterns.
  * :mod:`privilege_judge` — judge prompt calibrated against
    Federal Rule of Evidence 502 (privilege waiver), Upjohn corp
    privilege, attorney work-product doctrine (Hickman v. Taylor).
"""

from axon_enterprise.shield.legal import (  # noqa: F401 — side effects
    privilege_patterns,
    privilege_judge,
)


__all__ = [
    "privilege_patterns",
    "privilege_judge",
]
