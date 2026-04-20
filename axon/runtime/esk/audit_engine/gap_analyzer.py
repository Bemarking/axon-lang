"""
AXON Audit Evidence Engine — GapAnalyzer
==========================================
Runs the framework catalog against a compiled `IRProgram` and the
present-state of the codebase, producing a **gap analysis** that tells
the engineering team exactly what is left to do before hiring an
external auditor.

Three gap categories:
  • **Ready**         — evidence artifact exists in the deployment.
  • **Pending (code)** — a repo-side deliverable we can still produce
                        (e.g. add a KAT test, author a policy doc).
  • **Pending (external)** — only an accredited lab / CPA firm can
                             produce the evidence.

The analyzer is deterministic and JSON-serializable so CI pipelines
can emit it as an artifact on every release.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import IRProgram

from .frameworks import (
    Control,
    EvidenceKind,
    FrameworkId,
    controls_for,
)


@dataclass(frozen=True)
class ControlAssessment:
    """The per-control verdict."""
    control_id: str
    title: str
    axon_primitive: str
    evidence_kind: str
    evidence_locator: str
    status: str                 # "ready" | "pending_code" | "pending_external"
    rationale: str


@dataclass
class GapAnalysis:
    """Full gap analysis for one framework."""
    framework: str
    total_controls: int
    ready: int = 0
    pending_code: int = 0
    pending_external: int = 0
    assessments: list[ControlAssessment] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)

    @property
    def readiness_percent(self) -> float:
        if self.total_controls == 0:
            return 100.0
        return 100.0 * self.ready / self.total_controls

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema":             "axon.esk.audit_gap_analysis.v1",
            "framework":          self.framework,
            "total_controls":     self.total_controls,
            "ready":              self.ready,
            "pending_code":       self.pending_code,
            "pending_external":   self.pending_external,
            "readiness_percent":  round(self.readiness_percent, 2),
            "missing_features":   list(self.missing_features),
            "assessments": [
                {
                    "control_id":        a.control_id,
                    "title":             a.title,
                    "axon_primitive":    a.axon_primitive,
                    "evidence_kind":     a.evidence_kind,
                    "evidence_locator":  a.evidence_locator,
                    "status":            a.status,
                    "rationale":         a.rationale,
                }
                for a in self.assessments
            ],
        }


# ═══════════════════════════════════════════════════════════════════
#  Feature detection — what's present in the IRProgram
# ═══════════════════════════════════════════════════════════════════

def _program_features(program: IRProgram) -> set[str]:
    """Enumerate high-level features present in this compiled program.

    The set is keyed on feature names that gap-analysis rules can
    reference (e.g. "has_shield", "has_immune", "has_compliance").
    """
    features: set[str] = set()
    if program.shields:
        features.add("has_shield")
    if program.resources:
        features.add("has_resource")
    if program.manifests:
        features.add("has_manifest")
    if program.observations:
        features.add("has_observe")
    if program.immunes:
        features.add("has_immune")
    if program.reflexes:
        features.add("has_reflex")
    if program.heals:
        features.add("has_heal")
    if program.reconciles:
        features.add("has_reconcile")
    if program.leases:
        features.add("has_lease")
    if program.ensembles:
        features.add("has_ensemble")
    if program.topologies:
        features.add("has_topology")
    if program.endpoints:
        features.add("has_endpoint")
    # Compliance declarations anywhere in the program.
    for bucket in (program.types, program.shields, program.endpoints, program.manifests):
        for node in bucket:
            if getattr(node, "compliance", ()):
                features.add("has_compliance_annotation")
                break
        if "has_compliance_annotation" in features:
            break
    return features


# ═══════════════════════════════════════════════════════════════════
#  Rules — which features are pre-requisites for which controls
# ═══════════════════════════════════════════════════════════════════

_FEATURE_REQUIREMENTS: dict[str, set[str]] = {
    # If the control references AnomalyDetector / immune primitives, the
    # program must actually declare an `immune`.
    "CC3.2": {"has_immune"},
    "CC3.3": {"has_reflex"},
    "CC6.3": {"has_lease"},
    "CC6.6": {"has_shield", "has_endpoint"},
    "CC6.8": set(),  # chain is at runtime, no program dependency
    "CC7.1": {"has_immune"},
    "CC7.2": {"has_immune"},
    "CC7.3": {"has_immune"},
    "CC7.4": {"has_reflex", "has_heal"},
    "CC7.5": {"has_reconcile"},
    "C1.1":  {"has_compliance_annotation"},
    "PI1.4": {"has_ensemble"},
    "P1.1":  {"has_compliance_annotation"},
    "P6.1":  {"has_shield", "has_compliance_annotation"},
    # ISO 27001
    "A.5.2": {"has_heal"},
    "A.5.7": {"has_immune"},
    "A.5.23": set(),  # Handler protocol exists regardless
    "A.5.24": {"has_immune", "has_reflex", "has_heal"},
    "A.5.30": {"has_reconcile"},
    "A.5.34": {"has_compliance_annotation"},
    "A.8.2": {"has_lease"},
    "A.8.7": {"has_immune", "has_reflex"},
    "A.8.8": {"has_heal"},
    "A.8.13": {"has_resource"},
}


_PENDING_KEYWORDS = ("PENDING",)
_EXTERNAL_KINDS = {EvidenceKind.EXTERNAL_OPERATIONAL, EvidenceKind.MANUAL_POLICY}


def _assess_control(
    control: Control,
    features: set[str],
) -> ControlAssessment:
    locator = control.evidence_locator
    is_pending = any(k in locator for k in _PENDING_KEYWORDS)

    required_features = _FEATURE_REQUIREMENTS.get(control.control_id, set())
    missing_program_features = required_features - features

    if is_pending and control.evidence_kind in _EXTERNAL_KINDS:
        status = "pending_external"
        rationale = (
            f"requires external engagement (accredited lab / CPA) — "
            f"{locator}"
        )
    elif is_pending:
        status = "pending_code"
        rationale = f"evidence artifact not yet produced — {locator}"
    elif missing_program_features:
        status = "pending_code"
        rationale = (
            f"program does not declare required primitive(s): "
            f"{', '.join(sorted(missing_program_features))}"
        )
    elif control.evidence_kind == EvidenceKind.EXTERNAL_OPERATIONAL:
        status = "ready" if not is_pending else "pending_external"
        rationale = f"operational artifact: {locator}"
    else:
        status = "ready"
        rationale = f"enforced by {control.axon_primitive}"

    return ControlAssessment(
        control_id=control.control_id,
        title=control.title,
        axon_primitive=control.axon_primitive,
        evidence_kind=control.evidence_kind.value,
        evidence_locator=locator,
        status=status,
        rationale=rationale,
    )


# ═══════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════

def analyze_gaps(
    program: IRProgram,
    framework: FrameworkId,
) -> GapAnalysis:
    """Compute the gap analysis for `program` against `framework`."""
    features = _program_features(program)
    controls = controls_for(framework)
    analysis = GapAnalysis(
        framework=framework.value,
        total_controls=len(controls),
    )
    for c in controls:
        a = _assess_control(c, features)
        analysis.assessments.append(a)
        if a.status == "ready":
            analysis.ready += 1
        elif a.status == "pending_code":
            analysis.pending_code += 1
            if c.control_id in _FEATURE_REQUIREMENTS:
                missing = _FEATURE_REQUIREMENTS[c.control_id] - features
                for m in missing:
                    if m not in analysis.missing_features:
                        analysis.missing_features.append(m)
        elif a.status == "pending_external":
            analysis.pending_external += 1
    return analysis


def analyze_all(program: IRProgram) -> dict[str, GapAnalysis]:
    """Compute gap analyses for every registered framework."""
    return {f.value: analyze_gaps(program, f) for f in FrameworkId}


__all__ = [
    "ControlAssessment",
    "GapAnalysis",
    "analyze_all",
    "analyze_gaps",
]
