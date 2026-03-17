"""
AXON Engine — MDN (Multi-Document Navigation)
================================================
Formal framework for navigating document collections with typed,
weighted cross-reference graphs.

Extends PIX's single-document tree navigation to graph-structured corpora
with provenance tracking, epistemic typing, and bounded traversal guarantees.

Mathematical foundation: §2.1 Definition 1 (Document Corpus Graph)
  C = (D, R, τ, ω, σ)

Public API:
    CorpusGraph, Document, Edge, RelationType, Budget
    ProvenancePath, NavigationResult
    CorpusNavigator
    EpistemicPageRank
    CorpusBuilder
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
from axon.engine.mdn.navigator import CorpusNavigator
from axon.engine.mdn.epr import EpistemicPageRank
from axon.engine.mdn.builder import CorpusBuilder
from axon.engine.mdn.epistemic_types import (
    EpistemicLevel,
    classify_provenance,
    promote,
    demote,
    aggregate_levels,
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
]
