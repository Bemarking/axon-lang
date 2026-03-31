"""
AXON APX - Epistemic Lattice

Formal lattice for epistemic typing used by the APX dependency manager.
The implementation encodes:
- Partial order over epistemic levels
- Hard incompatibility boundary (objective vs subjective claims)
- Conservative uncertainty propagation
"""

from __future__ import annotations

from enum import IntEnum


class EpistemicLevel(IntEnum):
    """Total order used for lattice operations in APX.

    Higher value means stronger epistemic support.
    """

    UNCERTAINTY = 0
    SPECULATION = 1
    OPINION = 2
    FACTUAL_CLAIM = 3
    CITED_FACT = 4
    CORROBORATED_FACT = 5


OBJECTIVE_REGION = {
    EpistemicLevel.FACTUAL_CLAIM,
    EpistemicLevel.CITED_FACT,
    EpistemicLevel.CORROBORATED_FACT,
}

SUBJECTIVE_REGION = {
    EpistemicLevel.SPECULATION,
    EpistemicLevel.OPINION,
}


class EpistemicLattice:
    """Lattice operations for APX epistemic reasoning."""

    @staticmethod
    def leq(left: EpistemicLevel, right: EpistemicLevel) -> bool:
        """Partial-order check: left <= right."""
        return int(left) <= int(right)

    @staticmethod
    def meet(left: EpistemicLevel, right: EpistemicLevel) -> EpistemicLevel:
        """Greatest lower bound (conservative merge)."""
        return EpistemicLevel(min(int(left), int(right)))

    @staticmethod
    def join(left: EpistemicLevel, right: EpistemicLevel) -> EpistemicLevel:
        """Least upper bound with hard-boundary handling.

        Crossing objective<->subjective regions degrades to UNCERTAINTY by design.
        """
        if EpistemicLattice._crosses_hard_boundary(left, right):
            return EpistemicLevel.UNCERTAINTY
        return EpistemicLevel(max(int(left), int(right)))

    @staticmethod
    def can_substitute(actual: EpistemicLevel, expected: EpistemicLevel) -> bool:
        """Substitution rule with hard incompatibility boundary."""
        if EpistemicLattice._crosses_hard_boundary(actual, expected):
            return False
        return EpistemicLattice.leq(expected, actual)

    @staticmethod
    def taint_with_uncertainty(level: EpistemicLevel) -> EpistemicLevel:
        """Epistemic tainting: uncertainty is infectious."""
        _ = level
        return EpistemicLevel.UNCERTAINTY

    @staticmethod
    def _crosses_hard_boundary(left: EpistemicLevel, right: EpistemicLevel) -> bool:
        in_objective = left in OBJECTIVE_REGION or right in OBJECTIVE_REGION
        in_subjective = left in SUBJECTIVE_REGION or right in SUBJECTIVE_REGION
        return in_objective and in_subjective
