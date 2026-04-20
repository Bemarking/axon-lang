"""
AXON Audit Evidence Engine
============================
Closes the gap between AXON's security primitives and real external
audits (SOC 2 Type II, ISO 27001:2022, FIPS 140-3, Common Criteria
EAL 4+) by automating every step that an engineering team can do
BEFORE hiring an accredited lab / CPA firm.

What this package DOES NOT do
-----------------------------
Perform the audits themselves.  External audits are legal / regulated
processes executed by accredited third parties over 6-21 months, with
costs of $50k-$500k per framework.  No software can replace that.

What this package DOES do
-------------------------
1. **GapAnalyzer** — compares an IRProgram + codebase state against
   each framework's control catalog, producing a deterministic gap
   analysis JSON.
2. **ControlImplementationStatement** — pre-populates the "how did
   you implement this control" fields auditors ask for.
3. **RiskRegister** — derives an ISO 27005-shaped risk register,
   pruned to the primitives the program actually declares.
4. **EvidencePackager** — bundles every artifact an auditor typically
   requests into a single deterministic ZIP with SHA-256 manifest.

These four together reduce the months of pre-audit engineering work
to a single `axon audit-package` command.
"""

from __future__ import annotations

from .control_statements import (
    ControlImplementationStatement,
    generate_control_statements,
    statements_to_dict,
)
from .evidence_packager import (
    EvidencePackage,
    build_evidence_package,
)
from .frameworks import (
    Control,
    EvidenceKind,
    FrameworkId,
    all_frameworks,
    control_count,
    controls_for,
)
from .gap_analyzer import (
    ControlAssessment,
    GapAnalysis,
    analyze_all,
    analyze_gaps,
)
from .risk_register import (
    Impact,
    Likelihood,
    Risk,
    Treatment,
    generate_risk_register,
    risk_register_to_dict,
)


__all__ = [
    # frameworks
    "Control",
    "EvidenceKind",
    "FrameworkId",
    "all_frameworks",
    "control_count",
    "controls_for",
    # gap analysis
    "ControlAssessment",
    "GapAnalysis",
    "analyze_all",
    "analyze_gaps",
    # risk register
    "Impact",
    "Likelihood",
    "Risk",
    "Treatment",
    "generate_risk_register",
    "risk_register_to_dict",
    # control statements
    "ControlImplementationStatement",
    "generate_control_statements",
    "statements_to_dict",
    # evidence packager
    "EvidencePackage",
    "build_evidence_package",
]
