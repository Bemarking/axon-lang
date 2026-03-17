"""
AXON Engine — Epistemic Type Lattice (§7.1)
============================================

Implements the epistemic lattice (T, ≤) for document and claim classification:

    Uncertainty ≤ ContestedClaim ≤ FactualClaim ≤ CitedFact ≤ CorroboratedFact

The ordering represents *epistemic justification strength*:
    A ≤ B  ⇔  "A is less justified or less informationally supported than B"

Key operations:
    - join(A, B) = sup{A, B}: least upper bound (stronger evidence wins)
    - meet(A, B) = inf{A, B}: greatest lower bound (conservative merge)
    - promote(A, evidence) → B where B ≥ A: strengthen via new evidence
    - demote(A, evidence) → B where B ≤ A: weaken via contradicting evidence

Integration with MDN:
    - Document.epistemic_level : EpistemicLevel — document-level trust
    - ProvenancePath.epistemic_type : EpistemicLevel — claim-level trust
    - Navigator assigns epistemic type based on provenance chain structure.

Mathematical reference:
    - Lattice theory: complete lattice with top ⊤ = CorroboratedFact, bottom ⊥ = Uncertainty
    - Monotonicity: corroboration can only promote, contradiction can only demote
    - Anchor/shield integration: anchored facts resist demotion, shielded claims cap promotion
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class EpistemicLevel(IntEnum):
    """Epistemic type lattice (T, ≤) — ordered by justification strength.

    The integer values encode the lattice ordering:
        UNCERTAINTY < CONTESTED_CLAIM < FACTUAL_CLAIM < CITED_FACT < CORROBORATED_FACT

    This means standard comparison operators (<=, >=, <, >) directly
    implement the lattice ordering — no extra methods needed.
    """

    UNCERTAINTY = 0
    CONTESTED_CLAIM = 1
    FACTUAL_CLAIM = 2
    CITED_FACT = 3
    CORROBORATED_FACT = 4

    # ── Lattice Operations ──────────────────────────────────────────

    def join(self, other: EpistemicLevel) -> EpistemicLevel:
        """Lattice join: sup{self, other} — least upper bound.

        Returns the higher epistemic level. Semantically:
        "given both pieces of evidence, what's the strongest justified level?"
        """
        return max(self, other)

    def meet(self, other: EpistemicLevel) -> EpistemicLevel:
        """Lattice meet: inf{self, other} — greatest lower bound.

        Returns the lower epistemic level. Semantically:
        "what's the most conservative common level?"
        """
        return min(self, other)

    # Aliases

    @property
    def is_top(self) -> bool:
        """⊤ = CorroboratedFact"""
        return self == EpistemicLevel.CORROBORATED_FACT

    @property
    def is_bottom(self) -> bool:
        """⊥ = Uncertainty"""
        return self == EpistemicLevel.UNCERTAINTY

    @property
    def is_reliable(self) -> bool:
        """Whether this level is at least a factual claim (≥ FactualClaim)."""
        return self >= EpistemicLevel.FACTUAL_CLAIM

    @property
    def is_contested(self) -> bool:
        """Whether this level indicates epistemic conflict."""
        return self <= EpistemicLevel.CONTESTED_CLAIM

    # String conversion

    def to_label(self) -> str:
        """Convert to the human-readable label used in Document/ProvenancePath."""
        return _LEVEL_TO_LABEL[self]

    @classmethod
    def from_label(cls, label: str) -> EpistemicLevel:
        """Parse from the string label used in Document/ProvenancePath.

        Raises ValueError if the label is not a valid epistemic level.
        """
        try:
            return _LABEL_TO_LEVEL[label]
        except KeyError:
            valid = ", ".join(sorted(_LABEL_TO_LEVEL.keys()))
            raise ValueError(
                f"Unknown epistemic level '{label}'. Valid levels: {valid}"
            ) from None


# ── Label Mapping ───────────────────────────────────────────────────

_LEVEL_TO_LABEL: dict[EpistemicLevel, str] = {
    EpistemicLevel.UNCERTAINTY: "Uncertainty",
    EpistemicLevel.CONTESTED_CLAIM: "ContestedClaim",
    EpistemicLevel.FACTUAL_CLAIM: "FactualClaim",
    EpistemicLevel.CITED_FACT: "CitedFact",
    EpistemicLevel.CORROBORATED_FACT: "CorroboratedFact",
}

_LABEL_TO_LEVEL: dict[str, EpistemicLevel] = {
    v: k for k, v in _LEVEL_TO_LABEL.items()
}


# ── Promotion / Demotion Rules ──────────────────────────────────────

# Promotion evidence types and their effects
PROMOTION_EVIDENCE = {
    "citation": 1,          # cited by another doc → +1
    "corroboration": 2,     # corroborated by independent source → +2
    "peer_review": 2,       # peer-reviewed → +2
    "authority": 1,         # cited by authoritative source → +1
}

# Demotion evidence types and their effects
DEMOTION_EVIDENCE = {
    "contradiction": -1,    # contradicted by another doc → -1
    "retraction": -2,       # retracted → -2
    "dispute": -1,          # disputed by qualified source → -1
    "obsolescence": -1,     # superseded by newer evidence → -1
}


def promote(
    level: EpistemicLevel,
    evidence_type: str,
    *,
    ceiling: EpistemicLevel | None = None,
) -> EpistemicLevel:
    """Promote an epistemic level given supporting evidence.

    Args:
        level: Current epistemic level.
        evidence_type: Type of evidence (key in PROMOTION_EVIDENCE).
        ceiling: Maximum level allowed (shield integration — caps promotion).

    Returns:
        New epistemic level ≥ current level (monotonic promotion).

    Raises:
        ValueError: If evidence_type is not a recognized promotion type.
    """
    if evidence_type not in PROMOTION_EVIDENCE:
        raise ValueError(
            f"Unknown promotion evidence type '{evidence_type}'. "
            f"Valid types: {sorted(PROMOTION_EVIDENCE.keys())}"
        )

    delta = PROMOTION_EVIDENCE[evidence_type]
    new_value = min(level.value + delta, EpistemicLevel.CORROBORATED_FACT.value)
    result = EpistemicLevel(new_value)

    # Shield integration: cap at ceiling
    if ceiling is not None and result > ceiling:
        result = ceiling

    return result


def demote(
    level: EpistemicLevel,
    evidence_type: str,
    *,
    anchored: bool = False,
    floor: EpistemicLevel | None = None,
) -> EpistemicLevel:
    """Demote an epistemic level given contradicting evidence.

    Args:
        level: Current epistemic level.
        evidence_type: Type of evidence (key in DEMOTION_EVIDENCE).
        anchored: If True, level is anchor-protected — cannot be demoted
                  below current level. Represents FactualClaim anchoring (§7.1).
        floor: Minimum level allowed (cannot demote below this).

    Returns:
        New epistemic level ≤ current level (monotonic demotion).
        If anchored, returns the current level unchanged.

    Raises:
        ValueError: If evidence_type is not a recognized demotion type.
    """
    if evidence_type not in DEMOTION_EVIDENCE:
        raise ValueError(
            f"Unknown demotion evidence type '{evidence_type}'. "
            f"Valid types: {sorted(DEMOTION_EVIDENCE.keys())}"
        )

    # Anchor protection: anchored facts resist demotion
    if anchored:
        return level

    delta = DEMOTION_EVIDENCE[evidence_type]  # negative value
    new_value = max(level.value + delta, EpistemicLevel.UNCERTAINTY.value)
    result = EpistemicLevel(new_value)

    # Floor enforcement
    if floor is not None and result < floor:
        result = floor

    return result


def classify_provenance(
    path_length: int,
    has_corroboration: bool = False,
    has_contradiction: bool = False,
) -> EpistemicLevel:
    """Classify a provenance path's epistemic type based on its structure.

    This is the rule used by CorpusNavigator during traversal:
        - No edges (direct claim) → FactualClaim
        - Has citation chain → CitedFact
        - Has corroboration → CorroboratedFact
        - Has contradiction → ContestedClaim

    Contradiction dominates corroboration (conservative principle).
    """
    if has_contradiction:
        return EpistemicLevel.CONTESTED_CLAIM

    if has_corroboration:
        return EpistemicLevel.CORROBORATED_FACT

    if path_length > 0:
        return EpistemicLevel.CITED_FACT

    return EpistemicLevel.FACTUAL_CLAIM


def aggregate_levels(levels: list[EpistemicLevel]) -> EpistemicLevel:
    """Aggregate multiple epistemic levels into a single level.

    Uses conservative aggregation: returns the meet (greatest lower bound)
    of all levels. This ensures the aggregate is no stronger than the
    weakest contributing evidence.

    Returns UNCERTAINTY for empty input.
    """
    if not levels:
        return EpistemicLevel.UNCERTAINTY

    result = levels[0]
    for level in levels[1:]:
        result = result.meet(level)
    return result


def level_to_dict(level: EpistemicLevel) -> dict[str, Any]:
    """Serialize an epistemic level for JSON/dict output."""
    return {
        "level": level.to_label(),
        "value": level.value,
        "is_reliable": level.is_reliable,
        "is_contested": level.is_contested,
    }


# ── Public API ──────────────────────────────────────────────────────

__all__ = [
    "EpistemicLevel",
    "promote",
    "demote",
    "classify_provenance",
    "aggregate_levels",
    "level_to_dict",
    "PROMOTION_EVIDENCE",
    "DEMOTION_EVIDENCE",
]
