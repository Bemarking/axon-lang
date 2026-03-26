"""
AXON Engine — PIX (Structured Cognitive Retrieval)
=====================================================
PIX navigates structured data. Documents and images are both cases.
The invariant is progressive, bounded, scored navigation with auditable trails.

Public API — Document Navigation (original):
    DocumentTree, PixNode, PixLocation
    PixNavigator, NavigationStep, ReasoningPath, NavigationConfig
    PixIndexer, MarkdownExtractor

Public API — Visual Navigation (Epistemic Vision extension):
    VisualTree, VisualNode, VisualLocation, TopologicalSignature
    TopologicalIndexer, ImageExtractor
    TopologicalScorer, BettiScorer
    VisualNavigator, VisualNavigationConfig
"""

from __future__ import annotations

# ── Document Navigation (original) ───────────────────────────────
from axon.engine.pix.document_tree import (
    DocumentTree,
    PixNode,
    PixLocation,
)
from axon.engine.pix.navigator import (
    NavigationConfig,
    NavigationStep,
    PixNavigator,
    ReasoningPath,
    ScoringFunction,
)
from axon.engine.pix.indexer import (
    PixIndexer,
    MarkdownExtractor,
    StructureExtractor,
)

# ── Visual Navigation (Epistemic Vision) ─────────────────────────
from axon.engine.pix.visual_tree import (
    VisualTree,
    VisualNode,
    VisualLocation,
    TopologicalSignature,
)
from axon.engine.pix.topological_indexer import (
    TopologicalIndexer,
    ImageExtractor,
)
from axon.engine.pix.topological_scorer import (
    TopologicalScorer,
    BettiScorer,
)
from axon.engine.pix.visual_navigator import (
    VisualNavigator,
    VisualNavigationConfig,
)

__all__ = [
    # Document navigation
    "DocumentTree",
    "PixNode",
    "PixLocation",
    "NavigationConfig",
    "NavigationStep",
    "PixNavigator",
    "ReasoningPath",
    "ScoringFunction",
    "PixIndexer",
    "MarkdownExtractor",
    "StructureExtractor",
    # Visual navigation
    "VisualTree",
    "VisualNode",
    "VisualLocation",
    "TopologicalSignature",
    "TopologicalIndexer",
    "ImageExtractor",
    "TopologicalScorer",
    "BettiScorer",
    "VisualNavigator",
    "VisualNavigationConfig",
]
