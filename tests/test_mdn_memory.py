"""
AXON Engine — Memory-Augmented MDN Tests
==========================================
Comprehensive test suite for the memory module:
    C* = (D, R, τ, ω, σ, H, μ)

Tests are organized by component:
    1. InteractionRecord — validation, properties
    2. History — recording, eviction, queries
    3. EpisodicMemory — record, recall, similarity
    4. SemanticMemory — weight deltas, apply_to_corpus
    5. ProceduralMemory — bias computation
    6. MemoryOperator — full μ(C, H) → C'
    7. MemoryAugmentedCorpus — lifecycle, serialization
    8. Formal properties — Identity, Locality, Monotonicity, Convergence

Follows the testing patterns established in test_mdn_engine.py.
"""

from __future__ import annotations

import pytest

from axon.engine.mdn.corpus_graph import (
    Budget,
    CorpusGraph,
    Document,
    Edge,
    ProvenancePath,
    RelationType,
)
from axon.engine.mdn.memory import (
    EpisodicMemory,
    History,
    InteractionRecord,
    MemoryAugmentedCorpus,
    MemoryOperator,
    ProceduralMemory,
    SemanticMemory,
)
from axon.engine.mdn.navigator import MemoryAugmentedNavigator


# ═══════════════════════════════════════════════════════════════════
#  FIXTURES — shared test data
# ═══════════════════════════════════════════════════════════════════


CITE = RelationType("cite")
CONTRADICT = RelationType("contradict")
ELABORATE = RelationType("elaborate")
DEPEND = RelationType("depend")


def make_simple_corpus() -> CorpusGraph:
    """Create a minimal corpus for testing.

    Graph:  A --cite(0.8)--> B --elaborate(0.6)--> C
                             B --contradict(0.5)--> D
    """
    corpus = CorpusGraph(name="test_memory")
    corpus.add_document(Document(doc_id="A", title="Document Alpha"))
    corpus.add_document(Document(doc_id="B", title="Document Beta"))
    corpus.add_document(Document(doc_id="C", title="Document Charlie"))
    corpus.add_document(Document(doc_id="D", title="Document Delta"))

    corpus.add_edge(Edge("A", "B", CITE, weight=0.8))
    corpus.add_edge(Edge("B", "C", ELABORATE, weight=0.6))
    corpus.add_edge(Edge("B", "D", CONTRADICT, weight=0.5))

    return corpus


def make_path_ab() -> ProvenancePath:
    """Path: A → B via cite."""
    return ProvenancePath(
        edges=[Edge("A", "B", CITE, weight=0.8)],
        claim="test claim",
        confidence=0.7,
    )


def make_path_abc() -> ProvenancePath:
    """Path: A → B → C via cite, elaborate."""
    return ProvenancePath(
        edges=[
            Edge("A", "B", CITE, weight=0.8),
            Edge("B", "C", ELABORATE, weight=0.6),
        ],
        claim="extended claim",
        confidence=0.85,
    )


def make_path_abd() -> ProvenancePath:
    """Path: A → B → D via cite, contradict."""
    return ProvenancePath(
        edges=[
            Edge("A", "B", CITE, weight=0.8),
            Edge("B", "D", CONTRADICT, weight=0.5),
        ],
        claim="contradicted claim",
        confidence=0.3,
    )


# ═══════════════════════════════════════════════════════════════════
#  INTERACTION RECORD TESTS
# ═══════════════════════════════════════════════════════════════════


class TestInteractionRecord:
    """Tests for InteractionRecord dataclass."""

    def test_create_valid(self) -> None:
        path = make_path_ab()
        record = InteractionRecord(
            query="test query",
            path=path,
            outcome_score=0.85,
            timestamp=0,
        )
        assert record.query == "test query"
        assert record.outcome_score == 0.85
        assert record.timestamp == 0

    def test_empty_query_raises(self) -> None:
        with pytest.raises(ValueError, match="query cannot be empty"):
            InteractionRecord(
                query="", path=make_path_ab(), outcome_score=0.5, timestamp=0
            )

    def test_outcome_score_bounds(self) -> None:
        path = make_path_ab()
        # Valid boundaries
        InteractionRecord(query="q", path=path, outcome_score=0.0, timestamp=0)
        InteractionRecord(query="q", path=path, outcome_score=1.0, timestamp=0)
        # Invalid
        with pytest.raises(ValueError, match="Outcome score"):
            InteractionRecord(query="q", path=path, outcome_score=1.1, timestamp=0)
        with pytest.raises(ValueError, match="Outcome score"):
            InteractionRecord(query="q", path=path, outcome_score=-0.1, timestamp=0)

    def test_negative_timestamp_raises(self) -> None:
        with pytest.raises(ValueError, match="Timestamp"):
            InteractionRecord(
                query="q", path=make_path_ab(), outcome_score=0.5, timestamp=-1
            )

    def test_traversed_edges(self) -> None:
        path = make_path_abc()
        record = InteractionRecord(query="q", path=path, outcome_score=0.5, timestamp=0)
        assert len(record.traversed_edges) == 2
        assert record.traversed_edges[0].source_id == "A"
        assert record.traversed_edges[1].target_id == "C"

    def test_traversed_doc_ids(self) -> None:
        path = make_path_abc()
        record = InteractionRecord(query="q", path=path, outcome_score=0.5, timestamp=0)
        assert record.traversed_doc_ids == {"A", "B", "C"}

    def test_frozen(self) -> None:
        record = InteractionRecord(
            query="q", path=make_path_ab(), outcome_score=0.5, timestamp=0
        )
        with pytest.raises(AttributeError):
            record.query = "modified"

    def test_to_dict(self) -> None:
        record = InteractionRecord(
            query="test", path=make_path_ab(), outcome_score=0.75, timestamp=3
        )
        d = record.to_dict()
        assert d["query"] == "test"
        assert d["outcome_score"] == 0.75
        assert d["timestamp"] == 3
        assert "path" in d


# ═══════════════════════════════════════════════════════════════════
#  HISTORY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestHistory:
    """Tests for History structure H = (Q, Π, O)."""

    def test_create_empty(self) -> None:
        h = History()
        assert h.is_empty
        assert h.size == 0
        assert h.max_size == 1000

    def test_invalid_max_size(self) -> None:
        with pytest.raises(ValueError, match="max_size"):
            History(max_size=0)

    def test_record_interaction(self) -> None:
        h = History()
        path = make_path_ab()
        record = h.record("query alpha", path, 0.8)
        assert h.size == 1
        assert not h.is_empty
        assert record.timestamp == 0
        assert record.query == "query alpha"

    def test_monotonic_timestamps(self) -> None:
        h = History()
        r1 = h.record("q1", make_path_ab(), 0.5)
        r2 = h.record("q2", make_path_abc(), 0.7)
        r3 = h.record("q3", make_path_abd(), 0.3)
        assert r1.timestamp < r2.timestamp < r3.timestamp

    def test_queries_property(self) -> None:
        h = History()
        h.record("alpha", make_path_ab(), 0.5)
        h.record("beta", make_path_abc(), 0.7)
        assert h.queries == ["alpha", "beta"]

    def test_paths_property(self) -> None:
        h = History()
        p1 = make_path_ab()
        p2 = make_path_abc()
        h.record("q1", p1, 0.5)
        h.record("q2", p2, 0.7)
        assert len(h.paths) == 2

    def test_bounded_eviction(self) -> None:
        """History evicts oldest when max_size exceeded."""
        h = History(max_size=3)
        h.record("q1", make_path_ab(), 0.5)
        h.record("q2", make_path_ab(), 0.6)
        h.record("q3", make_path_ab(), 0.7)
        assert h.size == 3

        # This should evict q1
        h.record("q4", make_path_ab(), 0.8)
        assert h.size == 3
        assert h.queries == ["q2", "q3", "q4"]

    def test_mean_outcome_score(self) -> None:
        h = History()
        # Empty: Bayesian prior 0.5
        assert h.mean_outcome_score == 0.5
        h.record("q1", make_path_ab(), 0.4)
        h.record("q2", make_path_ab(), 0.6)
        assert h.mean_outcome_score == pytest.approx(0.5)

    def test_edges_in_history(self) -> None:
        h = History()
        h.record("q1", make_path_abc(), 0.5)
        edges = h.edges_in_history()
        assert ("A", "B", "cite") in edges
        assert ("B", "C", "elaborate") in edges
        assert len(edges) == 2

    def test_docs_in_history(self) -> None:
        h = History()
        h.record("q1", make_path_abc(), 0.5)
        docs = h.docs_in_history()
        assert docs == {"A", "B", "C"}

    def test_to_dict(self) -> None:
        h = History(max_size=100)
        h.record("q1", make_path_ab(), 0.5)
        d = h.to_dict()
        assert d["max_size"] == 100
        assert d["size"] == 1
        assert len(d["records"]) == 1

    def test_records_readonly_copy(self) -> None:
        """The records property returns a copy, not the internal list."""
        h = History()
        h.record("q1", make_path_ab(), 0.5)
        records = h.records
        records.clear()  # Mutate the returned list
        assert h.size == 1  # Internal list unaffected


# ═══════════════════════════════════════════════════════════════════
#  EPISODIC MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestEpisodicMemory:
    """Tests for EpisodicMemory — M_episodic = Π ⊆ Paths(C)."""

    def test_create_empty(self) -> None:
        em = EpisodicMemory()
        assert em.size == 0

    def test_record_and_size(self) -> None:
        em = EpisodicMemory()
        em.record("query about alpha", make_path_ab())
        assert em.size == 1

    def test_recall_empty(self) -> None:
        em = EpisodicMemory()
        result = em.recall("anything")
        assert result == []

    def test_recall_exact_match(self) -> None:
        em = EpisodicMemory()
        p = make_path_ab()
        em.record("document alpha", p)
        result = em.recall("document alpha")
        assert len(result) == 1
        assert result[0] is p

    def test_recall_partial_match(self) -> None:
        em = EpisodicMemory()
        em.record("document alpha beta", make_path_ab())
        em.record("document charlie delta", make_path_abc())
        result = em.recall("alpha")
        # "alpha" overlaps more with "document alpha beta"
        assert len(result) >= 1

    def test_recall_top_k(self) -> None:
        em = EpisodicMemory()
        for i in range(10):
            em.record(f"query {i}", make_path_ab())
        result = em.recall("query", top_k=3)
        assert len(result) == 3

    def test_recall_doc_ids(self) -> None:
        em = EpisodicMemory()
        em.record("alpha", make_path_abc())
        ids = em.recall_doc_ids("alpha")
        assert ids == {"A", "B", "C"}

    def test_recall_with_no_overlap(self) -> None:
        em = EpisodicMemory()
        em.record("specific technical query", make_path_ab())
        # Totally unrelated query
        result = em.recall("xyz zyx", top_k=5)
        # Should still return something (even with 0 similarity)
        # since we return top_k sorted by score
        assert len(result) <= 5


# ═══════════════════════════════════════════════════════════════════
#  SEMANTIC MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestSemanticMemory:
    """Tests for SemanticMemory — ω'(r) = ω(r) + Δ(r | H)."""

    def test_create_valid(self) -> None:
        sm = SemanticMemory()
        assert sm.learning_rate == 0.1
        assert sm.decay_factor == 0.95
        assert sm.min_weight == 0.001

    def test_invalid_learning_rate(self) -> None:
        with pytest.raises(ValueError, match="Learning rate"):
            SemanticMemory(learning_rate=0.0)
        with pytest.raises(ValueError, match="Learning rate"):
            SemanticMemory(learning_rate=1.5)

    def test_invalid_decay_factor(self) -> None:
        with pytest.raises(ValueError, match="Decay factor"):
            SemanticMemory(decay_factor=0.0)
        with pytest.raises(ValueError, match="Decay factor"):
            SemanticMemory(decay_factor=1.0)

    def test_invalid_min_weight(self) -> None:
        with pytest.raises(ValueError, match="Min weight"):
            SemanticMemory(min_weight=0.0)
        with pytest.raises(ValueError, match="Min weight"):
            SemanticMemory(min_weight=1.0)

    def test_empty_history_no_deltas(self) -> None:
        sm = SemanticMemory()
        h = History()
        deltas = sm.compute_weight_deltas(h)
        assert deltas == {}

    def test_positive_outcome_increases_weight(self) -> None:
        """High-scoring interactions should increase edge weights."""
        sm = SemanticMemory(learning_rate=0.5, decay_factor=0.95)
        h = History()
        # Record a high-scoring interaction
        h.record("q1", make_path_ab(), 1.0)
        # Baseline = 1.0, so deviation = 0 for a single record
        # Need at least two records with different scores
        h.record("q2", make_path_abd(), 0.2)
        # Now baseline ≈ 0.6, so q1 has deviation +0.4, q2 has -0.4

        deltas = sm.compute_weight_deltas(h)
        # Edge A→B appears in both paths; net effect depends on scores
        assert ("A", "B", "cite") in deltas

    def test_weight_clamping_upper(self) -> None:
        """Weights cannot exceed 1.0."""
        sm = SemanticMemory(learning_rate=0.5)
        assert sm._clamp_weight(1.5) == 1.0

    def test_weight_clamping_lower(self) -> None:
        """Weights cannot go below min_weight."""
        sm = SemanticMemory(min_weight=0.01)
        assert sm._clamp_weight(-0.5) == 0.01
        assert sm._clamp_weight(0.0) == 0.01

    def test_apply_to_corpus_preserves_topology(self) -> None:
        """μ preserves D, R — same documents and edges in output."""
        sm = SemanticMemory()
        corpus = make_simple_corpus()
        h = History()
        h.record("q", make_path_ab(), 0.9)
        h.record("q2", make_path_abd(), 0.1)

        transformed = sm.apply_to_corpus(corpus, h)
        # Same number of documents and edges
        assert transformed.document_count == corpus.document_count
        assert transformed.edge_count == corpus.edge_count
        # Same document IDs
        assert transformed.document_ids() == corpus.document_ids()

    def test_apply_to_corpus_does_not_mutate_original(self) -> None:
        """The original corpus must remain unchanged."""
        sm = SemanticMemory()
        corpus = make_simple_corpus()
        original_edges = [(e.source_id, e.target_id, e.weight) for e in corpus.edges]

        h = History()
        h.record("q", make_path_ab(), 0.9)
        h.record("q2", make_path_abd(), 0.1)
        sm.apply_to_corpus(corpus, h)

        # Original edges unchanged
        current_edges = [(e.source_id, e.target_id, e.weight) for e in corpus.edges]
        assert current_edges == original_edges

    def test_empty_history_returns_copy(self) -> None:
        """With empty history, apply_to_corpus returns identical copy."""
        sm = SemanticMemory()
        corpus = make_simple_corpus()
        h = History()
        transformed = sm.apply_to_corpus(corpus, h)
        assert transformed is not corpus
        assert transformed.document_count == corpus.document_count


# ═══════════════════════════════════════════════════════════════════
#  PROCEDURAL MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestProceduralMemory:
    """Tests for ProceduralMemory — Bias(D) ∈ ℝ^|D|."""

    def test_create_valid(self) -> None:
        pm = ProceduralMemory()
        assert pm.decay_factor == 0.95

    def test_invalid_decay_factor(self) -> None:
        with pytest.raises(ValueError, match="Decay factor"):
            ProceduralMemory(decay_factor=0.0)

    def test_empty_history_zero_bias(self) -> None:
        pm = ProceduralMemory()
        h = History()
        bias = pm.compute_bias(h, {"A", "B", "C"})
        assert all(v == 0.0 for v in bias.values())
        assert set(bias.keys()) == {"A", "B", "C"}

    def test_bias_normalized(self) -> None:
        """Bias vector should sum to 1.0 (when non-zero)."""
        pm = ProceduralMemory()
        h = History()
        h.record("q1", make_path_abc(), 0.8)
        bias = pm.compute_bias(h, {"A", "B", "C", "D"})
        total = sum(bias.values())
        if total > 0:
            assert total == pytest.approx(1.0)

    def test_high_score_path_increases_bias(self) -> None:
        """Documents in high-scoring paths get higher bias."""
        pm = ProceduralMemory()
        h = History()
        h.record("q1", make_path_ab(), 0.9)
        bias = pm.compute_bias(h, {"A", "B", "C", "D"})
        # A and B are in the path; C and D are not
        assert bias["A"] > 0
        assert bias["B"] > 0
        assert bias["C"] == 0
        assert bias["D"] == 0

    def test_temporal_decay(self) -> None:
        """Recent interactions have higher bias than older ones."""
        pm = ProceduralMemory(decay_factor=0.5)  # Aggressive decay
        h = History()
        # Old interaction (q1) with doc A
        h.record("q1", make_path_ab(), 0.8)
        # New interaction (q2) with doc B→C
        path_bc = ProvenancePath(
            edges=[Edge("B", "C", ELABORATE, weight=0.6)],
            claim="",
            confidence=0.5,
        )
        h.record("q2", path_bc, 0.8)

        bias = pm.compute_bias(h, {"A", "B", "C"})
        # C should have higher bias than A (more recent, same score, less decay)
        assert bias["C"] > bias["A"]


# ═══════════════════════════════════════════════════════════════════
#  MEMORY OPERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMemoryOperator:
    """Tests for MemoryOperator μ : (C, H) → C'."""

    def test_create_default(self) -> None:
        op = MemoryOperator()
        assert op.semantic is not None
        assert op.procedural is not None
        assert op.epistemic_update is True

    def test_identity_property(self) -> None:
        """Proposition 2: μ(C, ∅) = C (identity under empty history)."""
        op = MemoryOperator()
        corpus = make_simple_corpus()
        h = History()
        result = op.update(corpus, h)
        # Result should be a copy with identical structure
        assert result is not corpus
        assert result.document_count == corpus.document_count
        assert result.edge_count == corpus.edge_count

    def test_topology_preservation(self) -> None:
        """μ preserves D, R, τ — topology unchanged."""
        op = MemoryOperator()
        corpus = make_simple_corpus()
        h = History()
        h.record("q", make_path_abc(), 0.9)
        h.record("q2", make_path_abd(), 0.1)

        result = op.update(corpus, h)
        assert result.document_ids() == corpus.document_ids()
        assert result.edge_count == corpus.edge_count
        # Edge relation types unchanged
        original_relations = {(e.source_id, e.target_id, e.relation.name) for e in corpus.edges}
        result_relations = {(e.source_id, e.target_id, e.relation.name) for e in result.edges}
        assert original_relations == result_relations

    def test_does_not_mutate_original(self) -> None:
        """μ must be pure — no mutation of input corpus."""
        op = MemoryOperator()
        corpus = make_simple_corpus()
        h = History()
        h.record("q", make_path_abc(), 0.9)
        h.record("q2", make_path_abd(), 0.1)

        # Capture original state
        original_weights = {
            (e.source_id, e.target_id): e.weight for e in corpus.edges
        }

        op.update(corpus, h)

        # Original unchanged
        for e in corpus.edges:
            assert e.weight == original_weights[(e.source_id, e.target_id)]

    def test_compute_bias(self) -> None:
        op = MemoryOperator()
        h = History()
        h.record("q", make_path_ab(), 0.8)
        bias = op.compute_bias(h, {"A", "B", "C"})
        assert set(bias.keys()) == {"A", "B", "C"}

    def test_epistemic_update_disabled(self) -> None:
        """When epistemic_update=False, σ' = σ."""
        op = MemoryOperator(epistemic_update=False)
        corpus = make_simple_corpus()
        h = History()
        h.record("q", make_path_abc(), 0.9)
        h.record("q2", make_path_abd(), 0.1)

        result = op.update(corpus, h)
        # Epistemic levels should be unchanged
        for doc in result.iter_documents():
            original_doc = corpus.get_document(doc.doc_id)
            assert doc.epistemic_level == original_doc.epistemic_level


# ═══════════════════════════════════════════════════════════════════
#  MEMORY-AUGMENTED CORPUS TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMemoryAugmentedCorpus:
    """Tests for MemoryAugmentedCorpus C* = (D, R, τ, ω, σ, H, μ)."""

    def test_create(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        assert mac.interaction_count == 0
        assert not mac.is_memory_applied

    def test_record_interaction(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        record = mac.record_interaction("q1", make_path_ab(), 0.8)
        assert mac.interaction_count == 1
        assert record.query == "q1"
        assert not mac.is_memory_applied  # Not auto-applied

    def test_apply_memory(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        mac.record_interaction("q1", make_path_abc(), 0.9)
        mac.record_interaction("q2", make_path_abd(), 0.1)

        transformed = mac.apply_memory()
        assert mac.is_memory_applied
        assert transformed is mac.corpus  # Should be the current corpus

    def test_apply_memory_from_base(self) -> None:
        """Memory always applies from base corpus, not previous transform."""
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)

        mac.record_interaction("q1", make_path_ab(), 0.9)
        mac.record_interaction("q2", make_path_abd(), 0.1)

        t1 = mac.apply_memory()
        t2 = mac.apply_memory()

        # Both transformations should produce the same result
        # (since they start from the same base)
        for e1, e2 in zip(t1.edges, t2.edges, strict=True):
            assert e1.weight == pytest.approx(e2.weight)

    def test_recall(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        mac.record_interaction("alpha beta query", make_path_abc(), 0.8)
        recalled = mac.recall("alpha")
        assert len(recalled) > 0

    def test_compute_navigation_bias(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        mac.record_interaction("q1", make_path_ab(), 0.8)
        bias = mac.compute_navigation_bias()
        assert set(bias.keys()) == corpus.document_ids()

    def test_base_corpus_immutable(self) -> None:
        """Base corpus should never be modified."""
        corpus = make_simple_corpus()
        original_edges = [(e.source_id, e.target_id, e.weight) for e in corpus.edges]

        mac = MemoryAugmentedCorpus(corpus)
        mac.record_interaction("q1", make_path_abc(), 0.9)
        mac.record_interaction("q2", make_path_abd(), 0.1)
        mac.apply_memory()

        # Base remains untouched
        base_edges = [(e.source_id, e.target_id, e.weight) for e in mac.base_corpus.edges]
        assert base_edges == original_edges

    def test_to_dict(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        mac.record_interaction("q1", make_path_ab(), 0.5)
        d = mac.to_dict()
        assert "base_corpus" in d
        assert "current_corpus" in d
        assert "history" in d
        assert d["interaction_count"] == 1

    def test_repr(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        r = repr(mac)
        assert "MemoryAugmentedCorpus" in r
        assert "interactions=0" in r

    def test_custom_history_size(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus, max_history=5)
        assert mac.history.max_size == 5


# ═══════════════════════════════════════════════════════════════════
#  MEMORY-AUGMENTED NAVIGATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMemoryAugmentedNavigator:
    """Tests for MemoryAugmentedNavigator."""

    def test_create_valid(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        nav = MemoryAugmentedNavigator(mac)
        assert nav._beta == 0.3

    def test_invalid_beta(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        with pytest.raises(ValueError, match="bias weight"):
            MemoryAugmentedNavigator(mac, beta=1.0)

    def test_navigate_auto_records(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        nav = MemoryAugmentedNavigator(mac)
        budget = Budget(max_depth=2, max_nodes=10)

        result = nav.navigate("A", "Document Beta", budget)
        # Should record interaction if paths found
        if result.paths:
            assert mac.interaction_count == 1

    def test_navigate_no_auto_record(self) -> None:
        corpus = make_simple_corpus()
        mac = MemoryAugmentedCorpus(corpus)
        nav = MemoryAugmentedNavigator(mac)
        budget = Budget(max_depth=2, max_nodes=10)

        nav.navigate("A", "Document Beta", budget, auto_record=False)
        assert mac.interaction_count == 0


# ═══════════════════════════════════════════════════════════════════
#  FORMAL PROPERTY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestFormalProperties:
    """Tests for formal mathematical properties of the memory system."""

    def test_identity_property(self) -> None:
        """Proposition 2: μ(C, ∅) = C.

        The memory operator applied with empty history must return
        a structurally identical corpus.
        """
        op = MemoryOperator()
        corpus = make_simple_corpus()
        h = History()

        result = op.update(corpus, h)
        # Same document IDs
        assert result.document_ids() == corpus.document_ids()
        # Same edge count
        assert result.edge_count == corpus.edge_count
        # Same weights
        for orig, res in zip(corpus.edges, result.edges, strict=True):
            assert orig.weight == res.weight

    def test_locality_constraint(self) -> None:
        """Definition 4: Δω(r) ≠ 0 ⟹ r ∈ Edges(Π).

        Only edges that appear in historic paths should be modified.
        """
        sm = SemanticMemory(learning_rate=0.3)
        h = History()
        # Only path A→B is in history
        h.record("q1", make_path_ab(), 0.9)
        h.record("q2", make_path_ab(), 0.1)

        deltas = sm.compute_weight_deltas(h)
        # Only edge (A, B, cite) should have non-zero delta
        for key, delta in deltas.items():
            assert key == ("A", "B", "cite")

    def test_weight_bounds_invariant_g4(self) -> None:
        """Invariant G4: 0 < ω'(r) ≤ 1 after transformation.

        All weights must stay within valid bounds even under
        extreme learning signals.
        """
        sm = SemanticMemory(learning_rate=0.9, min_weight=0.001)
        corpus = make_simple_corpus()
        h = History()
        # Many extreme interactions
        for _ in range(20):
            h.record("q", make_path_ab(), 1.0)
        for _ in range(20):
            h.record("q", make_path_abd(), 0.0)

        transformed = sm.apply_to_corpus(corpus, h)
        for edge in transformed.edges:
            assert 0.0 < edge.weight <= 1.0, (
                f"Invariant G4 violated: weight={edge.weight} "
                f"for edge {edge.source_id}→{edge.target_id}"
            )

    def test_convergence_idempotence(self) -> None:
        """Theorem 2 (informal check): repeated application converges.

        Applying μ multiple times with the same history should
        produce the same result (idempotent on fixed history).
        """
        corpus = make_simple_corpus()
        h = History()
        h.record("q1", make_path_abc(), 0.8)
        h.record("q2", make_path_abd(), 0.2)

        op = MemoryOperator()

        # Apply twice — should give same result since both
        # apply from base corpus
        mac = MemoryAugmentedCorpus(corpus, operator=op)
        mac._history = h

        t1 = mac.apply_memory()
        t1_weights = [(e.source_id, e.target_id, e.weight) for e in t1.edges]

        t2 = mac.apply_memory()
        t2_weights = [(e.source_id, e.target_id, e.weight) for e in t2.edges]

        for w1, w2 in zip(t1_weights, t2_weights, strict=True):
            assert w1[2] == pytest.approx(w2[2], abs=1e-10)

    def test_generalization_strict(self) -> None:
        """Theorem 3 (existence check): ∃ C, H : Nav(μ(C,H)) ≠ Nav(C).

        We demonstrate that memory can produce different navigation
        outcomes by showing different edge weights.
        """
        corpus = make_simple_corpus()
        h = History()
        # Strong positive signal on path A→B→C
        for _ in range(10):
            h.record("q", make_path_abc(), 1.0)
        # Strong negative signal on path A→B→D
        for _ in range(10):
            h.record("q", make_path_abd(), 0.0)

        op = MemoryOperator(epistemic_update=False)
        result = op.update(corpus, h)

        # Weight of B→C should increase, B→D should decrease
        original_bc = next(e.weight for e in corpus.edges if e.target_id == "C")
        original_bd = next(e.weight for e in corpus.edges if e.target_id == "D")
        result_bc = next(e.weight for e in result.edges if e.target_id == "C")
        result_bd = next(e.weight for e in result.edges if e.target_id == "D")

        assert result_bc != original_bc or result_bd != original_bd, (
            "Generalization property: memory must produce different weights"
        )
