"""
AXON Engine — MDN (Multi-Document Navigation)
================================================
Formal framework for navigating document collections with typed,
weighted cross-reference graphs.

Extends PIX's single-document tree navigation to graph-structured corpora
with provenance tracking, epistemic typing, and bounded traversal guarantees.

Mathematical foundation: §2.1 Definition 1 (Document Corpus Graph)
  C = (D, R, τ, ω, σ)

Memory-Augmented extension: §3 (Memory-Augmented MDN)
  C* = (D, R, τ, ω, σ, H, μ)

Public API:
    CorpusGraph, Document, Edge, RelationType, Budget
    ProvenancePath, NavigationResult
    CorpusNavigator, MemoryAugmentedNavigator
    EpistemicPageRank
    CorpusBuilder
    InteractionRecord, History
    EpisodicMemory, SemanticMemory, ProceduralMemory
    MemoryOperator, MemoryAugmentedCorpus
"""

from __future__ import annotations

from axon.engine.mdn.corpus_graph import (
    Budget,
    CorpusGraph,
    Document,
    Edge,
    NavigationResult,
    ProvenancePath,
    RelationType,
)
from axon.engine.mdn.navigator import CorpusNavigator, MemoryAugmentedNavigator
from axon.engine.mdn.epr import EpistemicPageRank
from axon.engine.mdn.builder import CorpusBuilder
from axon.engine.mdn.epistemic_types import (
    EpistemicLevel,
    classify_provenance,
    promote,
    demote,
    aggregate_levels,
)
from axon.engine.mdn.memory import (
    InteractionRecord,
    History,
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
    MemoryOperator,
    MemoryAugmentedCorpus,
)

__all__ = [
    # Core data structures (§2.1, §5.1)
    "CorpusGraph",
    "Document",
    "Edge",
    "RelationType",
    "Budget",
    "ProvenancePath",
    "NavigationResult",
    # Navigator (§5.4)
    "CorpusNavigator",
    # Memory-Augmented Navigator (§5.2, Memory Paper)
    "MemoryAugmentedNavigator",
    # EPR (§2.3, Theorem 3)
    "EpistemicPageRank",
    # Builder
    "CorpusBuilder",
    # Epistemic types (§7.1)
    "EpistemicLevel",
    "classify_provenance",
    "promote",
    "demote",
    "aggregate_levels",
    # Memory (Memory-Augmented MDN Paper)
    "InteractionRecord",
    "History",
    "EpisodicMemory",
    "SemanticMemory",
    "ProceduralMemory",
    "MemoryOperator",
    "MemoryAugmentedCorpus",
]

