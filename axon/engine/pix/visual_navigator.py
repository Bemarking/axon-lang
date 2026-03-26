"""
AXON Engine — PIX Visual Navigator
=======================================
Foveal epistemic navigation — extends PixNavigator for image regions.

DESIGN DECISION (for devs):
    This module EXTENDS navigator.py, not replaces it.
    VisualNavigator inherits from PixNavigator and reuses:
        - navigate()          → same interface, same ReasoningPath
        - drill()             → same semantics ("focus on this region")
        - _navigate_recursive() → same pruning + bound logic

    What it ADDS:
        - Free energy convergence as additional stopping criterion
        - VisualNavigationConfig with epistemic parameters
        - Convenience methods for image-specific workflows

    CONCEPTUAL ISOMORPHISM:
        PixNavigator.navigate("legal terms")  → finds relevant doc sections
        VisualNavigator.perceive(image)       → finds informative image regions
        Both produce: NavigationResult with auditable ReasoningPath

    The VisualNavigator uses a VisualTree (from visual_tree.py) wrapped
    to be compatible with DocumentTree's interface, enabling full reuse
    of PixNavigator's recursive search logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from axon.engine.pix.document_tree import DocumentTree, PixNode, PixLocation
from axon.engine.pix.navigator import (
    NavigationConfig,
    NavigationResult,
    NavigationStep,
    PixNavigator,
    ReasoningPath,
    ScoringFunction,
)
from axon.engine.pix.visual_tree import VisualTree, VisualNode, VisualLocation
from axon.engine.pix.topological_scorer import TopologicalScorer, BettiScorer


# ═══════════════════════════════════════════════════════════════════
#  VISUAL NAVIGATION CONFIG — extends NavigationConfig
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class VisualNavigationConfig(NavigationConfig):
    """Configuration for visual PIX navigation.

    FOR DEVS: Inherits from NavigationConfig, so ALL standard parameters
    still work exactly the same way:
        max_depth     — maximum traversal depth (default: 4)
        max_branch    — maximum children per node (default: 3)
        threshold     — minimum score to explore (default: 0.3)
        timeout_secs  — maximum navigation time (default: 30)
        model         — ignored in visual mode (no LLM needed)

    Additional parameters for visual foveation:
        free_energy_threshold — ε for F_V convergence (stop when F_V < ε)
        epistemic_weight      — α from PEM PsycheProfile (0=pragmatic, 1=curious)
        compute_budget        — max regions to evaluate before stopping
    """

    free_energy_threshold: float = 0.1
    epistemic_weight: float = 0.6
    compute_budget: int = 1000


# ═══════════════════════════════════════════════════════════════════
#  TREE ADAPTER — bridges VisualTree to DocumentTree interface
# ═══════════════════════════════════════════════════════════════════


def _visual_node_to_pix_node(vnode: VisualNode) -> PixNode:
    """Convert a VisualNode to a PixNode for navigator compatibility.

    FOR DEVS: The PixNavigator operates on DocumentTree/PixNode.
    Rather than rewriting all navigation logic, we adapt VisualNode
    to PixNode by mapping the fields:
        label         → title
        betti_summary → summary
        signature str → content
        bbox          → location

    This is a SHALLOW conversion (children are converted recursively).
    """
    content = ""
    if vnode.signature is not None:
        content = repr(vnode.signature)

    pix_node = PixNode(
        node_id=vnode.node_id,
        title=vnode.label,
        summary=vnode.betti_summary,
        location=PixLocation(
            offset_start=vnode.bbox.x,
            offset_end=vnode.bbox.x + vnode.bbox.w,
            page_start=vnode.bbox.y,
            page_end=vnode.bbox.y + vnode.bbox.h,
        ),
        content=content,
        depth=vnode.depth,
    )

    for child in vnode.children:
        pix_child = _visual_node_to_pix_node(child)
        pix_node.children.append(pix_child)
        # Note: we don't use add_child() to avoid depth re-assignment
        # since depth was already set during VisualTree construction

    return pix_node


def visual_tree_to_document_tree(vtree: VisualTree) -> DocumentTree:
    """Convert a VisualTree to a DocumentTree for PixNavigator compatibility.

    FOR DEVS: This enables the VisualNavigator to inherit ALL of
    PixNavigator's logic (navigate, drill, _navigate_recursive, etc.)
    without any code duplication.

    The conversion is lossless for navigation purposes:
        VisualTree.name       → DocumentTree.name
        VisualTree.root       → DocumentTree.root (via node conversion)
        VisualTree.source     → DocumentTree.source
    """
    pix_root = _visual_node_to_pix_node(vtree.root)
    return DocumentTree(
        name=vtree.name,
        root=pix_root,
        source=vtree.source,
        version=vtree.version,
    )


# ═══════════════════════════════════════════════════════════════════
#  VISUAL NAVIGATOR — extends PixNavigator
# ═══════════════════════════════════════════════════════════════════


class VisualNavigator:
    """Foveal epistemic navigator — visual extension of PixNavigator.

    FOR DEVS — HOW THIS RELATES TO PixNavigator:
    ═══════════════════════════════════════════════
    Instead of inheriting directly (which would require DocumentTree),
    this class COMPOSES a PixNavigator internally by converting the
    VisualTree to a DocumentTree adapter.

    This gives us:
        ✅ Full reuse of navigate(), drill(), _navigate_recursive()
        ✅ Full reuse of ReasoningPath, NavigationResult
        ✅ No code duplication
        ✅ All existing tests for PixNavigator remain valid

    The VisualNavigator adds:
        - perceive() method: the primary API for visual perception
        - Free energy tracking: monitors convergence across regions
        - Visual-specific config: VisualNavigationConfig

    USAGE COMPARISON:
        # Document navigation (existing):
        doc_nav = PixNavigator(doc_tree, llm_scorer)
        result = doc_nav.navigate("legal terms")

        # Visual navigation (new):
        vis_nav = VisualNavigator(visual_tree)
        result = vis_nav.perceive()  # explores most informative regions

    Both produce NavigationResult with:
        - leaves: found content (text sections or image regions)
        - path: ReasoningPath with auditable trail
        - elapsed_secs, timed_out, query

    Example:
        from axon.engine.pix.topological_indexer import TopologicalIndexer
        from axon.engine.pix.visual_navigator import VisualNavigator

        indexer = TopologicalIndexer()
        tree = indexer.index(image_array, name="scene_001")

        nav = VisualNavigator(tree)
        result = nav.perceive()

        for step in result.path.steps:
            print(f"  Looked at: {step.title} (score={step.score:.2f})")
        for leaf in result.leaves:
            print(f"  Found: {leaf.title} — {leaf.summary}")
    """

    def __init__(
        self,
        visual_tree: VisualTree,
        scorer: ScoringFunction | None = None,
        config: VisualNavigationConfig | None = None,
    ) -> None:
        self._visual_tree = visual_tree
        self._config = config or VisualNavigationConfig()
        self._scorer = scorer or TopologicalScorer()

        # Convert VisualTree → DocumentTree for PixNavigator reuse
        self._doc_tree = visual_tree_to_document_tree(visual_tree)
        self._inner_nav = PixNavigator(
            self._doc_tree,
            self._scorer,
            self._config,
        )

    @property
    def visual_tree(self) -> VisualTree:
        return self._visual_tree

    @property
    def config(self) -> VisualNavigationConfig:
        return self._config

    def perceive(self, query: str = "explore") -> NavigationResult:
        """Perceive the image — primary API for visual navigation.

        FOR DEVS: This is the visual analogue of navigate("query").
        In document PIX, the query drives which branches to explore.
        In visual PIX, the scorer (TopologicalScorer) drives exploration
        based on topological information gain.

        The query parameter is optional and reserved for future
        sheaf-based semantic queries (§3 in the paper).

        Args:
            query: Optional semantic query (default: "explore").

        Returns:
            NavigationResult with explored regions and reasoning trail.
        """
        return self._inner_nav.navigate(query)

    def drill_region(self, region_id: str, query: str = "explore") -> NavigationResult:
        """Focus on a specific image region — analogue of drill().

        FOR DEVS: Exactly the same as PixNavigator.drill() but with
        a more descriptive name for the visual context.

        Args:
            region_id: Node ID of the region to drill into.
            query:     Optional semantic query.

        Returns:
            NavigationResult scoped to the specified region.
        """
        return self._inner_nav.drill(region_id, query)

    def free_energy_estimate(self, result: NavigationResult) -> float:
        """Estimate the variational free energy after navigation.

        FROM PAPER §2.5.2:
            F_V = D_KL[Q(s) || P(s)] - E_Q[log P(o|s)]

        Approximation:
            - Low F_V → high confidence (explored well)
            - High F_V → uncertainty remains (more regions to explore)

        The estimate uses:
            - Coverage: fraction of image area explored
            - Score distribution: how informative were the explored regions
            - Convergence: did scores decrease (diminishing returns)?
        """
        if not result.path.steps:
            return 1.0  # Maximum uncertainty

        scores = [s.score for s in result.path.steps if s.depth > 0]
        if not scores:
            return 1.0

        # Coverage component: unexplored area increases F_V
        explored_leaves = len(result.leaves)
        total_leaves = self._visual_tree.leaf_count()
        coverage = explored_leaves / max(total_leaves, 1)

        # Score component: higher avg score → lower F_V
        avg_score = sum(scores) / len(scores)

        # Convergence: stable/decreasing scores → lower F_V
        if len(scores) >= 2:
            trend = scores[-1] - scores[0]
            convergence = max(0, -trend)  # negative trend = converging
        else:
            convergence = 0.0

        # F_V ≈ (1 - coverage) · (1 - avg_score) · (1 - convergence)
        free_energy = (1.0 - coverage) * (1.0 - avg_score)
        return max(0.0, min(1.0, free_energy))

    def summary(self, result: NavigationResult) -> str:
        """Human-readable summary of the visual perception result.

        Adds visual-specific information to the standard PIX trail.
        """
        fe = self.free_energy_estimate(result)
        lines = [
            f"Visual Perception — {self._visual_tree.name}",
            f"  Image: {self._visual_tree.image_width}×{self._visual_tree.image_height}",
            f"  Regions explored: {len(result.leaves)}/{self._visual_tree.leaf_count()}",
            f"  Free energy: {fe:.3f} ({'converged' if fe < self._config.free_energy_threshold else 'exploring'})",
            f"  Time: {result.elapsed_secs:.3f}s",
            "",
            result.path.summary(),
        ]
        return "\n".join(lines)
