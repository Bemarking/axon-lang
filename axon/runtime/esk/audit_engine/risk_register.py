"""
AXON Audit Evidence Engine — RiskRegister
===========================================
Derives an ISO 27001 / NIST 800-53-shaped risk register from a compiled
IRProgram.  Each risk row describes:

  • The threat                     (what goes wrong)
  • The asset(s) impacted          (which IRProgram element)
  • The applicable control(s)      (framework controls that mitigate it)
  • The likelihood + impact         (qualitative L/M/H defaults)
  • The treatment                  (accept / mitigate / transfer / avoid)
  • The AXON primitive implementing the treatment

The output is JSON-serializable so it can be consumed by a GRC platform
(ServiceNow, ZenGRC, Hyperproof) or attached directly to an ISO 27001
Stage 1 submission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from axon.compiler.ir_nodes import IRProgram


class Likelihood(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Treatment(str, Enum):
    ACCEPT = "accept"
    MITIGATE = "mitigate"
    TRANSFER = "transfer"
    AVOID = "avoid"


@dataclass(frozen=True)
class Risk:
    """A single row in the risk register."""
    risk_id: str
    threat: str
    asset: str
    likelihood: str
    impact: str
    applicable_controls: tuple[str, ...]
    treatment: str
    axon_primitive: str
    residual_score: int   # 1-9: likelihood_ordinal * impact_ordinal

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id":             self.risk_id,
            "threat":              self.threat,
            "asset":               self.asset,
            "likelihood":          self.likelihood,
            "impact":              self.impact,
            "applicable_controls": list(self.applicable_controls),
            "treatment":           self.treatment,
            "axon_primitive":      self.axon_primitive,
            "residual_score":      self.residual_score,
        }


# ═══════════════════════════════════════════════════════════════════
#  Canonical threat catalog — ISO 27005-informed
# ═══════════════════════════════════════════════════════════════════

_TEMPLATE_THREATS: list[dict[str, Any]] = [
    {
        "threat": "Regulated data crosses an uncovered boundary (HIPAA/PCI violation)",
        "likelihood": Likelihood.HIGH,
        "impact": Impact.CRITICAL,
        "controls": ("CC6.6", "FDP_ACC.1", "A.5.36"),
        "treatment": Treatment.MITIGATE,
        "primitive": "Compile-time Compliance (RTT)",
        "feature_gate": "has_compliance_annotation",
    },
    {
        "threat": "Prompt injection subverts intended flow behavior",
        "likelihood": Likelihood.HIGH,
        "impact": Impact.HIGH,
        "controls": ("CC7.1", "CC7.3", "A.8.7"),
        "treatment": Treatment.MITIGATE,
        "primitive": "immune + reflex + EID",
        "feature_gate": "has_immune",
    },
    {
        "threat": "Cryptographic keys or PII leak through logs / traces",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.CRITICAL,
        "controls": ("CC6.7", "A.8.12", "FPT_ITC.1"),
        "treatment": Treatment.MITIGATE,
        "primitive": "Secret[T] no-materialize",
        "feature_gate": None,    # always applicable
    },
    {
        "threat": "Audit records tampered after-the-fact",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.HIGH,
        "controls": ("CC6.8", "A.5.28", "FAU_STG.1"),
        "treatment": Treatment.MITIGATE,
        "primitive": "ProvenanceChain Merkle + HMAC/Ed25519",
        "feature_gate": None,
    },
    {
        "threat": "Resource aliased across manifests (double-provision / split-brain)",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.HIGH,
        "controls": ("CC6.1", "FDP_IFC.1", "A.8.2"),
        "treatment": Treatment.MITIGATE,
        "primitive": "Linear Logic + Separation Logic compile-time check",
        "feature_gate": "has_manifest",
    },
    {
        "threat": "Post-quantum break of classical signatures (Shor-capable adversary)",
        "likelihood": Likelihood.LOW,
        "impact": Impact.CRITICAL,
        "controls": ("CC6.8", "A.8.24", "FCS_COP.1"),
        "treatment": Treatment.MITIGATE,
        "primitive": "DilithiumSigner + HybridSigner (FIPS 204)",
        "feature_gate": None,
    },
    {
        "threat": "Unbounded AI agency (heal applied twice, reconcile never halts)",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.HIGH,
        "controls": ("CC5.1", "FRU_RSA.1"),
        "treatment": Treatment.MITIGATE,
        "primitive": "heal.max_patches + reconcile.max_retries bounds",
        "feature_gate": "has_heal",
    },
    {
        "threat": "Statistical extraction attack (model theft) over many queries",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.HIGH,
        "controls": ("P4.1", "FPR_PSE.1", "A.8.12"),
        "treatment": Treatment.MITIGATE,
        "primitive": "PrivacyBudget ε-limit (Differential Privacy)",
        "feature_gate": None,
    },
    {
        "threat": "Network partition observed as false-positive 'healthy'",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.MEDIUM,
        "controls": ("CC7.2", "A.5.30"),
        "treatment": Treatment.MITIGATE,
        "primitive": "NetworkPartitionError (CT-3, Decision D4)",
        "feature_gate": None,
    },
    {
        "threat": "Session deadlock between endpoint↔daemon↔resource",
        "likelihood": Likelihood.LOW,
        "impact": Impact.HIGH,
        "controls": ("CC4.2", "A.8.27"),
        "treatment": Treatment.MITIGATE,
        "primitive": "π-calculus Honda-liveness compile-time check",
        "feature_gate": "has_topology",
    },
    {
        "threat": "Lease token used post-expiration (stale capability)",
        "likelihood": Likelihood.MEDIUM,
        "impact": Impact.HIGH,
        "controls": ("CC6.3", "A.8.2", "A.8.10"),
        "treatment": Treatment.MITIGATE,
        "primitive": "LeaseKernel τ-decay + Anchor Breach (CT-2)",
        "feature_gate": "has_lease",
    },
    {
        "threat": "Supply-chain compromise (malicious dependency)",
        "likelihood": Likelihood.LOW,
        "impact": Impact.CRITICAL,
        "controls": ("CC8.1", "A.8.32", "A.5.33"),
        "treatment": Treatment.MITIGATE,
        "primitive": "Deterministic SBOM + in-toto SLSA v1 attestation",
        "feature_gate": None,
    },
]


_SCORE: dict[str, int] = {
    "low": 1, "medium": 2, "high": 3, "critical": 3,   # impact criticality saturates at 3
}


def _residual(likelihood: str, impact: str) -> int:
    return _SCORE[likelihood] * _SCORE[impact]


def _program_features(program: IRProgram) -> set[str]:
    # Delegate to GapAnalyzer's detector to stay consistent.
    from .gap_analyzer import _program_features as detect
    return detect(program)


def generate_risk_register(program: IRProgram) -> list[Risk]:
    """Build the risk register for a compiled program.

    Only risks whose `feature_gate` is None or present in the program's
    features are included — irrelevant risks are pruned.
    """
    features = _program_features(program)
    rows: list[Risk] = []
    counter = 0
    for tpl in _TEMPLATE_THREATS:
        gate = tpl["feature_gate"]
        if gate is not None and gate not in features:
            continue
        counter += 1
        rows.append(Risk(
            risk_id=f"AXON-RISK-{counter:03d}",
            threat=tpl["threat"],
            asset=tpl.get("asset", "program_state"),
            likelihood=tpl["likelihood"].value,
            impact=tpl["impact"].value,
            applicable_controls=tuple(tpl["controls"]),
            treatment=tpl["treatment"].value,
            axon_primitive=tpl["primitive"],
            residual_score=_residual(tpl["likelihood"].value, tpl["impact"].value),
        ))
    return rows


def risk_register_to_dict(risks: list[Risk]) -> dict[str, Any]:
    return {
        "schema":        "axon.esk.risk_register.v1",
        "iso_reference": "ISO/IEC 27005:2022",
        "total_risks":   len(risks),
        "risks":         [r.to_dict() for r in risks],
    }


__all__ = [
    "Impact",
    "Likelihood",
    "Risk",
    "Treatment",
    "generate_risk_register",
    "risk_register_to_dict",
]
