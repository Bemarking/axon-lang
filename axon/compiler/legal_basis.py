"""
AXON Compiler — Fase 11.c legal-basis catalogue (Python mirror).

Mirror of ``axon-rs/src/legal_basis.rs``. The ordering + string
values MUST be identical so the parity test suite can assert the
two sides stay in lockstep.
"""

from __future__ import annotations

from enum import Enum


class Regulation(str, Enum):
    GDPR = "GDPR"
    CCPA = "CCPA"
    SOX = "SOX"
    HIPAA = "HIPAA"
    GLBA = "GLBA"
    PCI_DSS = "PCI_DSS"


#: Legal basis catalogue — stable ordering mirrored from Rust.
LEGAL_BASIS_CATALOG: tuple[str, ...] = (
    "GDPR.Art6.Consent",
    "GDPR.Art6.Contract",
    "GDPR.Art6.LegalObligation",
    "GDPR.Art6.VitalInterests",
    "GDPR.Art6.PublicTask",
    "GDPR.Art6.LegitimateInterests",
    "GDPR.Art9.ExplicitConsent",
    "GDPR.Art9.Employment",
    "GDPR.Art9.VitalInterests",
    "GDPR.Art9.NotForProfit",
    "GDPR.Art9.PublicData",
    "GDPR.Art9.LegalClaims",
    "GDPR.Art9.SubstantialPublicInterest",
    "GDPR.Art9.HealthcareProvision",
    "GDPR.Art9.PublicHealth",
    "GDPR.Art9.ArchivingResearch",
    "CCPA.1798_100",
    "SOX.404",
    "HIPAA.164_502",
    "GLBA.501b",
    "PCI_DSS.v4_Req3",
)

SENSITIVE_EFFECT_SLUG: str = "sensitive"
LEGAL_EFFECT_SLUG: str = "legal"


def is_legal_basis(slug: str) -> bool:
    return slug in LEGAL_BASIS_CATALOG


def regulation_for(slug: str) -> Regulation | None:
    if slug.startswith("GDPR."):
        return Regulation.GDPR
    if slug.startswith("CCPA."):
        return Regulation.CCPA
    if slug.startswith("SOX."):
        return Regulation.SOX
    if slug.startswith("HIPAA."):
        return Regulation.HIPAA
    if slug.startswith("GLBA."):
        return Regulation.GLBA
    if slug.startswith("PCI_DSS."):
        return Regulation.PCI_DSS
    return None


__all__ = [
    "LEGAL_BASIS_CATALOG",
    "LEGAL_EFFECT_SLUG",
    "Regulation",
    "SENSITIVE_EFFECT_SLUG",
    "is_legal_basis",
    "regulation_for",
]
