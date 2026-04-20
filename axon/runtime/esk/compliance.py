"""
AXON Runtime — Regulatory Compliance Registry
================================================
Canonical vocabulary for the ESK κ (regulatory class) annotation.

Every class in this registry must correspond to a real-world regulation
or framework; typos are compile-time errors thanks to §6.1 enforcement.

See docs/plan_io_cognitivo.md Fase 6.1 — "Compile-time Compliance".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ═══════════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RegulatoryClass:
    """Metadata for one regulatory framework."""
    name: str                        # canonical label (matches AST)
    title: str                       # human-readable name
    jurisdiction: str                # US | EU | Global | Sector
    sector: str                      # healthcare | financial | gov | ...
    description: str

    def covers(self, other: "RegulatoryClass") -> bool:
        """Reflexive coverage — a class covers itself.  Overlap between
        frameworks (e.g. HIPAA ⇒ some SOX obligations) is an explicit
        policy decision, not an implicit one."""
        return self.name == other.name


# Canonical set — must match type_checker._REGULATORY_CLASSES exactly.
REGISTRY: dict[str, RegulatoryClass] = {
    "HIPAA": RegulatoryClass(
        name="HIPAA",
        title="Health Insurance Portability and Accountability Act",
        jurisdiction="US",
        sector="healthcare",
        description="PHI confidentiality, integrity, and availability for US healthcare providers.",
    ),
    "PCI_DSS": RegulatoryClass(
        name="PCI_DSS",
        title="Payment Card Industry Data Security Standard",
        jurisdiction="Global",
        sector="financial",
        description="Cardholder data protection for merchants and payment processors.",
    ),
    "GDPR": RegulatoryClass(
        name="GDPR",
        title="General Data Protection Regulation",
        jurisdiction="EU",
        sector="cross-sector",
        description="Personal data protection for EU residents, with right-to-erasure.",
    ),
    "SOX": RegulatoryClass(
        name="SOX",
        title="Sarbanes-Oxley Act",
        jurisdiction="US",
        sector="financial",
        description="Financial reporting integrity for public companies.",
    ),
    "FINRA": RegulatoryClass(
        name="FINRA",
        title="Financial Industry Regulatory Authority",
        jurisdiction="US",
        sector="financial",
        description="Broker-dealer oversight — communications, record retention, surveillance.",
    ),
    "ISO27001": RegulatoryClass(
        name="ISO27001",
        title="ISO/IEC 27001",
        jurisdiction="Global",
        sector="cross-sector",
        description="Information security management system certification.",
    ),
    "SOC2": RegulatoryClass(
        name="SOC2",
        title="SOC 2 Type II",
        jurisdiction="Global",
        sector="cross-sector",
        description="Trust Services Criteria — security, availability, confidentiality.",
    ),
    "FISMA": RegulatoryClass(
        name="FISMA",
        title="Federal Information Security Management Act",
        jurisdiction="US",
        sector="government",
        description="US federal government information security baseline.",
    ),
    "GxP": RegulatoryClass(
        name="GxP",
        title="Good x Practice",
        jurisdiction="Global",
        sector="pharma",
        description="Quality guidelines for pharma / clinical / manufacturing (GLP/GMP/GCP).",
    ),
    "CCPA": RegulatoryClass(
        name="CCPA",
        title="California Consumer Privacy Act",
        jurisdiction="US-CA",
        sector="cross-sector",
        description="Consumer data rights for California residents.",
    ),
    "NIST_800_53": RegulatoryClass(
        name="NIST_800_53",
        title="NIST SP 800-53",
        jurisdiction="US",
        sector="government",
        description="Security and privacy controls catalog for US federal systems.",
    ),
}


# ═══════════════════════════════════════════════════════════════════
#  Coverage predicates — used by the compiler AND the runtime
# ═══════════════════════════════════════════════════════════════════

def is_known(label: str) -> bool:
    return label in REGISTRY


def get(label: str) -> RegulatoryClass:
    if label not in REGISTRY:
        raise KeyError(f"unknown regulatory class '{label}'")
    return REGISTRY[label]


def covers(shield_compliance: Iterable[str], required: Iterable[str]) -> set[str]:
    """Return the MISSING classes — i.e. required minus covered.

    A shield covers a required class exactly when the class appears in
    the shield's compliance list.  No transitive coverage: each class
    must be listed explicitly (audit trails demand this).
    """
    provided = set(shield_compliance or [])
    needed = set(required or [])
    return needed - provided


def classify_sector(labels: Iterable[str]) -> set[str]:
    """Return the set of regulated sectors the labels span — useful for
    dossiers and audit reporting."""
    sectors: set[str] = set()
    for label in labels:
        if label in REGISTRY:
            sectors.add(REGISTRY[label].sector)
    return sectors


__all__ = [
    "REGISTRY",
    "RegulatoryClass",
    "classify_sector",
    "covers",
    "get",
    "is_known",
]
