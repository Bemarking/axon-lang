"""
AXON Audit Evidence Engine — ControlImplementationStatement
================================================================
For every control in a framework, produce the auditor-ready
"Implementation Statement" that an organization typically writes
by hand during the audit-prep cycle.  AXON can pre-populate most of
these from the framework catalog + IR program inspection.

Output shape (JSON-serializable) matches the fields SOC 2 auditors
and ISO 27001 lead auditors typically request in Stage 1 intake
questionnaires:

  [
    {
      "control_id":            "CC6.1",
      "control_title":         "...",
      "status":                "implemented" | "partially_implemented" | "planned" | "not_applicable",
      "implementation_detail": "...",
      "evidence":              ["link/to/artifact", ...],
      "owner_role":            "SRE" | "Security" | ...,
      "test_frequency":        "continuous" | "weekly" | "quarterly" | "annual",
    },
    ...
  ]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import IRProgram

from .frameworks import Control, EvidenceKind, FrameworkId, controls_for
from .gap_analyzer import analyze_gaps


# ═══════════════════════════════════════════════════════════════════
#  Owner + frequency defaults per evidence kind
# ═══════════════════════════════════════════════════════════════════

_OWNER_FOR_KIND: dict[EvidenceKind, str] = {
    EvidenceKind.COMPILE_TIME:        "Engineering (Language Team)",
    EvidenceKind.RUNTIME_INVARIANT:   "Engineering (Runtime Team)",
    EvidenceKind.AUTOMATED_ARTIFACT:  "Engineering (CI/CD)",
    EvidenceKind.TEST_SUITE:          "Engineering (QA)",
    EvidenceKind.MANUAL_POLICY:       "Security / GRC",
    EvidenceKind.EXTERNAL_OPERATIONAL: "Operations / SRE",
}

_FREQ_FOR_KIND: dict[EvidenceKind, str] = {
    EvidenceKind.COMPILE_TIME:        "continuous",   # every commit via axon check
    EvidenceKind.RUNTIME_INVARIANT:   "continuous",   # every request
    EvidenceKind.AUTOMATED_ARTIFACT:  "per-release",
    EvidenceKind.TEST_SUITE:          "per-commit",
    EvidenceKind.MANUAL_POLICY:       "annual_review",
    EvidenceKind.EXTERNAL_OPERATIONAL: "per-release",
}


@dataclass
class ControlImplementationStatement:
    control_id: str
    control_title: str
    status: str
    implementation_detail: str
    evidence: list[str]
    owner_role: str
    test_frequency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id":            self.control_id,
            "control_title":         self.control_title,
            "status":                self.status,
            "implementation_detail": self.implementation_detail,
            "evidence":              list(self.evidence),
            "owner_role":            self.owner_role,
            "test_frequency":        self.test_frequency,
        }


def _status_from_analysis(assessment_status: str) -> str:
    if assessment_status == "ready":
        return "implemented"
    if assessment_status == "pending_code":
        return "partially_implemented"
    if assessment_status == "pending_external":
        return "planned"
    return "not_applicable"


def _implementation_detail(control: Control) -> str:
    return (
        f"{control.axon_primitive}. Evidence kind: "
        f"{control.evidence_kind.value}. Verification locus: "
        f"{control.evidence_locator}."
    )


def generate_control_statements(
    program: IRProgram,
    framework: FrameworkId,
) -> list[ControlImplementationStatement]:
    """Produce one statement per control in the framework."""
    analysis = analyze_gaps(program, framework)
    by_id = {a.control_id: a for a in analysis.assessments}

    statements: list[ControlImplementationStatement] = []
    for control in controls_for(framework):
        assessment = by_id.get(control.control_id)
        status_raw = assessment.status if assessment else "pending_code"
        statement = ControlImplementationStatement(
            control_id=control.control_id,
            control_title=control.title,
            status=_status_from_analysis(status_raw),
            implementation_detail=_implementation_detail(control),
            evidence=[control.evidence_locator],
            owner_role=_OWNER_FOR_KIND[control.evidence_kind],
            test_frequency=_FREQ_FOR_KIND[control.evidence_kind],
        )
        statements.append(statement)
    return statements


def statements_to_dict(
    statements: list[ControlImplementationStatement],
    framework: FrameworkId,
) -> dict[str, Any]:
    return {
        "schema":           "axon.esk.control_implementation_statements.v1",
        "framework":        framework.value,
        "total_controls":   len(statements),
        "statements":       [s.to_dict() for s in statements],
    }


__all__ = [
    "ControlImplementationStatement",
    "generate_control_statements",
    "statements_to_dict",
]
