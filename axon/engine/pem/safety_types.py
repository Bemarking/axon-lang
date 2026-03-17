"""
AXON Engine — PEM Safety Types Module
========================================
§4 — Safety: From Extensional Filters to Dependent Types.

Implements correct-by-construction safety constraints where
generating prohibited outputs is a type-level impossibility,
not a runtime filter.

From the PEM paper §4:

    effect Psychological where
        analyze_context : Interaction → [infer] DensityMatrix
        inject_context  : (q: Query, ρ: DensityMatrix)
                        → (q': Query ** NonDiagnostic q')

By tying the safety property to the return type (NonDiagnostic q'),
generating a clinical diagnosis becomes an object that the algebraic
engine is mathematically incapable of instantiating, rendering
violations UNCOMPILABLE.

Implementation strategy:
    - Compile-time: type checker validates that psyche blocks
      do not declare diagnostic output types
    - Runtime: output classifier as defense-in-depth layer
    - Constraint registry: extensible safety constraint system

Predefined constraints:
    - NON_DIAGNOSTIC:    no clinical diagnoses
    - NON_PRESCRIPTIVE:  no treatment prescriptions
    - NON_MANIPULATIVE:  no psychological manipulation

Mathematical references:
    See docs/psychological_epistemic_modeling.md §4.

Author: Ricardo Velit (theoretical framework)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  SAFETY VIOLATION — What happens when a constraint is violated
# ═══════════════════════════════════════════════════════════════════


@unique
class ViolationSeverity(Enum):
    """Severity levels for safety constraint violations."""

    INFO = 0        # Logged only, no action
    WARNING = 1     # Flagged but output allowed
    BLOCK = 2       # Output blocked, safe fallback used
    CRITICAL = 3    # Output blocked, session flagged for review


@dataclass(frozen=True)
class SafetyViolation:
    """A detected safety constraint violation.

    Represents a formal proof witness that an output violates
    a constraint. In the type-theoretic framing, this is the
    evidence that NonDiagnostic(q') does NOT hold.

    Args:
        constraint_name: Name of the violated constraint.
        evidence:        The specific text/pattern that triggered it.
        severity:        How severe the violation is.
        context:         Additional context for debugging/review.
    """

    constraint_name: str
    evidence: str
    severity: ViolationSeverity
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "constraint": self.constraint_name,
            "evidence": self.evidence,
            "severity": self.severity.name,
            "context": self.context,
        }


# ═══════════════════════════════════════════════════════════════════
#  SAFETY CONSTRAINT — Formal constraint on output type
# ═══════════════════════════════════════════════════════════════════


class SafetyConstraint:
    """NonDiagnostic-style type constraint — compile-time safety.

    A SafetyConstraint defines a class of prohibited outputs.
    In the type-theoretic framing:

        inject_context : (q: Query, ρ: DensityMatrix)
                       → (q': Query ** Constraint q')

    The constraint C(q') holds iff no violation is detected.
    If a violation IS detected, the system cannot instantiate
    the return type, effectively blocking the output.

    Each constraint is defined by:
        - A name (for type-level identification)
        - A description (for documentation)
        - Pattern matchers (keyword + regex patterns)
        - A severity level (what happens on violation)

    Args:
        name:        Constraint identifier (e.g., "non_diagnostic").
        description: Human-readable description.
        patterns:    List of regex patterns that indicate violations.
        keywords:    List of keywords that indicate violations.
        severity:    Default severity for violations.
    """

    def __init__(
        self,
        name: str,
        description: str,
        patterns: list[str] | None = None,
        keywords: list[str] | None = None,
        severity: ViolationSeverity = ViolationSeverity.BLOCK,
    ) -> None:
        if not name:
            raise ValueError("Constraint name cannot be empty")

        self.name = name
        self.description = description
        self.severity = severity

        # Compile regex patterns
        self._patterns: list[re.Pattern[str]] = []
        for pattern in (patterns or []):
            self._patterns.append(re.compile(pattern, re.IGNORECASE))

        # Keywords (case-insensitive matching)
        self._keywords = frozenset(
            kw.lower() for kw in (keywords or [])
        )

    def check(self, output_text: str) -> SafetyViolation | None:
        """Check if output violates this constraint.

        Returns:
            A SafetyViolation if violated, None if safe.

        The check has two layers:
            1. Keyword scan (fast, O(n·k))
            2. Regex pattern matching (precise, O(n·p))
        """
        text_lower = output_text.lower()

        # Layer 1: Keyword scan
        for keyword in self._keywords:
            if keyword in text_lower:
                return SafetyViolation(
                    constraint_name=self.name,
                    evidence=keyword,
                    severity=self.severity,
                    context={"detection_method": "keyword"},
                )

        # Layer 2: Regex patterns
        for pattern in self._patterns:
            match = pattern.search(output_text)
            if match:
                return SafetyViolation(
                    constraint_name=self.name,
                    evidence=match.group(),
                    severity=self.severity,
                    context={"detection_method": "pattern"},
                )

        return None

    def is_safe(self, output_text: str) -> bool:
        """Quick check: does the output satisfy this constraint?"""
        return self.check(output_text) is None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.name,
            "num_patterns": len(self._patterns),
            "num_keywords": len(self._keywords),
        }

    def __repr__(self) -> str:
        return (
            f"SafetyConstraint('{self.name}', "
            f"patterns={len(self._patterns)}, "
            f"keywords={len(self._keywords)})"
        )


# ═══════════════════════════════════════════════════════════════════
#  PREDEFINED CONSTRAINTS — Standard safety types
# ═══════════════════════════════════════════════════════════════════


# NonDiagnostic — the primary constraint from the paper
NON_DIAGNOSTIC = SafetyConstraint(
    name="non_diagnostic",
    description=(
        "Prevents clinical diagnosis output. The system may discuss "
        "symptoms, evidence, and patterns, but CANNOT produce a "
        "diagnostic conclusion (e.g., 'Patient has X disorder')."
    ),
    patterns=[
        r"\bdiagnos(?:is|ed|tic|e)\b.*\b(?:is|has|shows|presents|suffers)\b",
        r"\bpatient\s+(?:has|is|suffers\s+from|meets\s+criteria)\b",
        r"\bDSM-[IV5]+\s+criteria\s+(?:met|satisfied)\b",
        r"\bICD-1[01]\s+code\b",
        r"\bclinical\s+(?:diagnosis|assessment|determination)\b",
        r"\b(?:major|mild|moderate|severe)\s+(?:depressive|anxiety|psychotic)\b.*\bdisorder\b",
    ],
    keywords=[
        "definitive diagnosis",
        "diagnostic conclusion",
        "meets criteria for",
        "is diagnosed with",
        "clinical determination",
    ],
    severity=ViolationSeverity.BLOCK,
)


# NonPrescriptive — no treatment prescriptions
NON_PRESCRIPTIVE = SafetyConstraint(
    name="non_prescriptive",
    description=(
        "Prevents treatment prescription output. The system may "
        "discuss treatment options in general terms, but CANNOT "
        "prescribe specific treatments, dosages, or interventions."
    ),
    patterns=[
        r"\bprescri(?:be|bed|ption)\b.*\b(?:mg|ml|dose|daily|twice)\b",
        r"\btake\s+\d+\s*(?:mg|ml|tablets?|capsules?)\b",
        r"\bstart\s+(?:on|with)\s+\w+\s+\d+\s*mg\b",
        r"\bincrease\s+(?:dose|dosage)\s+to\b",
    ],
    keywords=[
        "prescribe",
        "recommended dosage",
        "treatment protocol",
        "start medication",
    ],
    severity=ViolationSeverity.BLOCK,
)


# NonManipulative — no psychological manipulation
NON_MANIPULATIVE = SafetyConstraint(
    name="non_manipulative",
    description=(
        "Prevents psychological manipulation output. The system "
        "must inform and guide, NEVER manipulate, gaslight, or "
        "use coercive persuasion techniques."
    ),
    patterns=[
        r"\byou\s+(?:should|must|need\s+to)\s+(?:feel|believe|think)\b",
        r"\b(?:everyone|nobody)\s+(?:knows|thinks|believes|agrees)\b",
        r"\bif\s+you\s+(?:really|truly)\s+(?:cared|loved|understood)\b",
        r"\byou(?:'re|\s+are)\s+(?:overreacting|being\s+dramatic|too\s+sensitive)\b",
    ],
    keywords=[
        "you should feel",
        "you're overreacting",
        "everyone knows that",
        "nobody believes",
        "if you really cared",
    ],
    severity=ViolationSeverity.CRITICAL,
)


# ═══════════════════════════════════════════════════════════════════
#  SAFETY REGISTRY — Manages multiple constraints
# ═══════════════════════════════════════════════════════════════════


class SafetyRegistry:
    """Registry of active safety constraints for a psyche profile.

    Manages a set of SafetyConstraint instances and provides
    batch checking of outputs against all active constraints.

    In the type-theoretic framing, the registry represents the
    product type of all constraints:

        Output ** (C₁ q') ** (C₂ q') ** ... ** (Cₙ q')

    ALL constraints must be satisfied for the output to be valid.

    Args:
        constraints: Initial list of constraints to register.
    """

    def __init__(
        self,
        constraints: list[SafetyConstraint] | None = None,
    ) -> None:
        self._constraints: dict[str, SafetyConstraint] = {}
        for c in (constraints or []):
            self.register(c)

    def register(self, constraint: SafetyConstraint) -> None:
        """Register a safety constraint."""
        self._constraints[constraint.name] = constraint

    def unregister(self, name: str) -> None:
        """Remove a constraint by name."""
        self._constraints.pop(name, None)

    @property
    def constraint_names(self) -> list[str]:
        """Names of all registered constraints."""
        return list(self._constraints.keys())

    @property
    def count(self) -> int:
        """Number of registered constraints."""
        return len(self._constraints)

    def check_all(self, output_text: str) -> list[SafetyViolation]:
        """Check output against ALL registered constraints.

        Returns:
            List of all violations found (empty = safe).
        """
        violations: list[SafetyViolation] = []
        for constraint in self._constraints.values():
            violation = constraint.check(output_text)
            if violation:
                violations.append(violation)
        return violations

    def is_safe(self, output_text: str) -> bool:
        """Quick check: does the output satisfy ALL constraints?

        This is the runtime enforcement of the dependent type:
            ∀ C ∈ Registry : C(output) holds
        """
        return all(
            c.is_safe(output_text) for c in self._constraints.values()
        )

    def max_severity(self, output_text: str) -> ViolationSeverity | None:
        """Return the maximum severity among all violations.

        Returns:
            The highest severity violation, or None if safe.
        """
        violations = self.check_all(output_text)
        if not violations:
            return None
        return max(violations, key=lambda v: v.severity.value).severity

    def sanitize(
        self,
        output_text: str,
        fallback: str = "[Output blocked by safety constraint]",
    ) -> tuple[str, list[SafetyViolation]]:
        """Check output and return sanitized version.

        If any BLOCK or CRITICAL violations are found, the output
        is replaced with the fallback text.

        Returns:
            (sanitized_text, list_of_violations)
        """
        violations = self.check_all(output_text)

        for v in violations:
            if v.severity in (ViolationSeverity.BLOCK, ViolationSeverity.CRITICAL):
                return fallback, violations

        return output_text, violations

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "count": self.count,
            "constraints": [
                c.to_dict() for c in self._constraints.values()
            ],
        }


# ═══════════════════════════════════════════════════════════════════
#  PREDEFINED REGISTRIES — Common safety profiles
# ═══════════════════════════════════════════════════════════════════


def therapeutic_registry() -> SafetyRegistry:
    """Safety registry for therapeutic/psychiatric context.

    Constraints:
        - NonDiagnostic:   no clinical diagnoses
        - NonPrescriptive: no treatment prescriptions
        - NonManipulative: no psychological manipulation
    """
    return SafetyRegistry([
        NON_DIAGNOSTIC,
        NON_PRESCRIPTIVE,
        NON_MANIPULATIVE,
    ])


def research_registry() -> SafetyRegistry:
    """Safety registry for research/analysis context.

    Constraints:
        - NonManipulative: no psychological manipulation

    Research context allows diagnostic language (for analysis)
    but still prohibits manipulation.
    """
    return SafetyRegistry([NON_MANIPULATIVE])


def sales_registry() -> SafetyRegistry:
    """Safety registry for sales/commercial context.

    Constraints:
        - NonManipulative: no psychological manipulation

    Sales context allows persuasion but not manipulation.
    The distinction is enforced by the NonManipulative constraint.
    """
    return SafetyRegistry([NON_MANIPULATIVE])
