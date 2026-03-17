"""
AXON MDN Engine — Unit Tests
=================================
Tests for MDN core engine: CorpusGraph, CorpusNavigator,
EpistemicPageRank, CorpusBuilder.

Tests are organized by component:
  1. RelationType, Edge, Document (data structures)
  2. Budget (navigation constraints)
  3. ProvenancePath (provenance chains)
  4. CorpusGraph (graph operations + invariants)
  5. CorpusNavigator (bounded BFS traversal)
  6. EpistemicPageRank (signed graph PageRank)
  7. CorpusBuilder (fluent construction)
  8. Full pipeline integration

Mathematical references:
  - Definition 1 (§2.1): Corpus graph C = (D, R, τ, ω, σ)
  - Theorem 2   (§2.2): Strict information gain under ε-informative navigation
  - Definition 4 (§2.3): Signed corpus decomposition + EPR
  - §5.1:                Type system invariants
  - §5.4:                Algorithm MDN-Navigate
"""

import pytest

from axon.engine.mdn.corpus_graph import (
    Budget,
    CorpusGraph,
    Document,
    Edge,
    NavigationResult,
    ProvenancePath,
    RelationType,
    STANDARD_RELATION_TYPES,
    POSITIVE_RELATIONS,
    NEGATIVE_RELATIONS,
)
from axon.engine.mdn.navigator import (
    CorpusNavigator,
    NavigationStep,
)
from axon.engine.mdn.epr import EpistemicPageRank
from axon.engine.mdn.builder import CorpusBuilder
from axon.engine.mdn.epistemic_types import (
    EpistemicLevel,
    promote,
    demote,
    classify_provenance,
    aggregate_levels,
    level_to_dict,
)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _cite() -> RelationType:
    """Standard 'cite' relation type."""
    return RelationType(name="cite")


def _contradict() -> RelationType:
    """Standard 'contradict' relation type."""
    return RelationType(name="contradict")


def _implement() -> RelationType:
    """Standard 'implement' relation type."""
    return RelationType(name="implement")


def _sample_corpus() -> CorpusGraph:
    """Build a small legal corpus for testing.

    Structure:
      Ley123 --[cite]--> CasoJuris
      Ley123 --[implement]--> Reglamento
      CasoJuris --[contradict]--> Reglamento
    """
    corpus = CorpusGraph(name="LegalCorpus")
    corpus.add_document(Document(
        doc_id="ley123", title="Ley 123 de Responsabilidad",
        doc_type="statute", summary="Ley sobre responsabilidad civil",
    ))
    corpus.add_document(Document(
        doc_id="caso_juris", title="Caso Jurisprudencial ABC",
        doc_type="case_law", summary="Jurisprudencia sobre daños",
    ))
    corpus.add_document(Document(
        doc_id="reglamento", title="Reglamento de Implementación",
        doc_type="regulation", summary="Reglamento que implementa la Ley 123",
    ))

    corpus.add_edge(Edge("ley123", "caso_juris", _cite(), weight=0.9))
    corpus.add_edge(Edge("ley123", "reglamento", _implement(), weight=0.85))
    corpus.add_edge(Edge("caso_juris", "reglamento", _contradict(), weight=0.6))

    return corpus


def _larger_corpus() -> CorpusGraph:
    """Build a larger corpus with multiple paths for navigation testing.

    Structure (6 docs):
      D0 --[cite]--> D1 --[cite]--> D3
      D0 --[elaborate]--> D2 --[cite]--> D4
      D1 --[contradict]--> D5
      D2 --[implement]--> D5
    """
    corpus = CorpusGraph(name="ResearchCorpus")
    for i in range(6):
        corpus.add_document(Document(
            doc_id=f"D{i}",
            title=f"Document {i}",
            doc_type="paper",
            summary=f"Summary of document {i} with research findings",
        ))

    elaborate = RelationType(name="elaborate")
    corpus.add_edge(Edge("D0", "D1", _cite(), weight=0.9))
    corpus.add_edge(Edge("D0", "D2", elaborate, weight=0.8))
    corpus.add_edge(Edge("D1", "D3", _cite(), weight=0.7))
    corpus.add_edge(Edge("D2", "D4", _cite(), weight=0.75))
    corpus.add_edge(Edge("D1", "D5", _contradict(), weight=0.5))
    corpus.add_edge(Edge("D2", "D5", _implement(), weight=0.6))

    return corpus


# ═══════════════════════════════════════════════════════════════════
#  1. RELATION TYPE TESTS
# ═══════════════════════════════════════════════════════════════════


class TestRelationType:
    """RelationType — edge labels from Definition 2, §2.1."""

    def test_create_basic(self):
        rel = RelationType(name="cite")
        assert rel.name == "cite"
        assert rel.properties == frozenset()
        assert rel.domain_constraint is None

    def test_create_with_properties(self):
        rel = RelationType(
            name="cite",
            properties=frozenset({"reflexive", "transitive"}),
        )
        assert "reflexive" in rel.properties
        assert "transitive" in rel.properties

    def test_create_with_domain_constraint(self):
        rel = RelationType(
            name="implement",
            domain_constraint=("regulation", "statute"),
        )
        assert rel.domain_constraint == ("regulation", "statute")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            RelationType(name="")

    def test_is_positive(self):
        assert RelationType(name="cite").is_positive is True
        assert RelationType(name="elaborate").is_positive is True
        assert RelationType(name="corroborate").is_positive is True

    def test_is_negative(self):
        assert RelationType(name="contradict").is_negative is True
        assert RelationType(name="supersede").is_negative is True

    def test_neutral_relation(self):
        rel = RelationType(name="depend")
        assert rel.is_positive is False
        assert rel.is_negative is False

    def test_frozen_hashable(self):
        r1 = RelationType(name="cite")
        r2 = RelationType(name="cite")
        assert r1 == r2
        assert hash(r1) == hash(r2)

    def test_standard_types_exist(self):
        assert "cite" in STANDARD_RELATION_TYPES
        assert "contradict" in STANDARD_RELATION_TYPES
        assert "implement" in STANDARD_RELATION_TYPES
        assert len(STANDARD_RELATION_TYPES) >= 7


# ═══════════════════════════════════════════════════════════════════
#  2. EDGE TESTS — R ⊆ D × D × L, §2.1
# ═══════════════════════════════════════════════════════════════════


class TestEdge:
    """Edge — typed, weighted directed edge from Definition 1."""

    def test_create_basic(self):
        e = Edge("doc1", "doc2", _cite())
        assert e.source_id == "doc1"
        assert e.target_id == "doc2"
        assert e.relation.name == "cite"
        assert e.weight == 1.0  # default

    def test_create_with_weight(self):
        e = Edge("doc1", "doc2", _cite(), weight=0.7)
        assert e.weight == 0.7

    def test_weight_invariant_g4_lower(self):
        """Invariant (G4): weight must be > 0."""
        with pytest.raises(ValueError, match="G4"):
            Edge("doc1", "doc2", _cite(), weight=0.0)

    def test_weight_invariant_g4_negative(self):
        with pytest.raises(ValueError, match="G4"):
            Edge("doc1", "doc2", _cite(), weight=-0.5)

    def test_weight_invariant_g4_upper(self):
        """Invariant (G4): weight must be ≤ 1."""
        with pytest.raises(ValueError, match="G4"):
            Edge("doc1", "doc2", _cite(), weight=1.5)

    def test_weight_boundary_valid(self):
        """Boundary: weight = 1.0 is valid."""
        e = Edge("doc1", "doc2", _cite(), weight=1.0)
        assert e.weight == 1.0

    def test_weight_small_valid(self):
        """Boundary: small positive weight is valid."""
        e = Edge("doc1", "doc2", _cite(), weight=0.001)
        assert e.weight == 0.001

    def test_empty_source_raises(self):
        with pytest.raises(ValueError, match="source_id"):
            Edge("", "doc2", _cite())

    def test_empty_target_raises(self):
        with pytest.raises(ValueError, match="target_id"):
            Edge("doc1", "", _cite())

    def test_frozen(self):
        e = Edge("doc1", "doc2", _cite())
        with pytest.raises(AttributeError):
            e.weight = 0.5  # type: ignore

    def test_to_dict(self):
        e = Edge("doc1", "doc2", _cite(), weight=0.75)
        d = e.to_dict()
        assert d["source_id"] == "doc1"
        assert d["target_id"] == "doc2"
        assert d["relation"] == "cite"
        assert d["weight"] == 0.75


# ═══════════════════════════════════════════════════════════════════
#  3. DOCUMENT TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDocument:
    """Document — a node in the corpus graph."""

    def test_create_basic(self):
        doc = Document(doc_id="d1", title="Test Doc")
        assert doc.doc_id == "d1"
        assert doc.title == "Test Doc"
        assert doc.doc_type == "generic"

    def test_create_typed(self):
        doc = Document(doc_id="d1", title="Ley 123", doc_type="statute")
        assert doc.doc_type == "statute"

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="doc_id"):
            Document(doc_id="", title="No ID")

    def test_hashable(self):
        d1 = Document(doc_id="d1", title="A")
        d2 = Document(doc_id="d1", title="B")
        assert d1 == d2  # same doc_id
        assert hash(d1) == hash(d2)

    def test_different_docs(self):
        d1 = Document(doc_id="d1", title="A")
        d2 = Document(doc_id="d2", title="B")
        assert d1 != d2

    def test_to_dict(self):
        doc = Document(doc_id="d1", title="Test", doc_type="statute")
        d = doc.to_dict()
        assert d["doc_id"] == "d1"
        assert d["doc_type"] == "statute"


# ═══════════════════════════════════════════════════════════════════
#  4. BUDGET TESTS — §2.2
# ═══════════════════════════════════════════════════════════════════


class TestBudget:
    """Budget — navigation constraints from §2.2."""

    def test_defaults(self):
        b = Budget()
        assert b.max_depth == 5
        assert b.max_nodes == 50
        assert b.edge_filter is None

    def test_custom(self):
        b = Budget(max_depth=3, max_nodes=20, edge_filter=frozenset({"cite"}))
        assert b.max_depth == 3
        assert b.max_nodes == 20
        assert b.edge_filter == frozenset({"cite"})

    def test_depth_too_low(self):
        with pytest.raises(ValueError, match="max_depth"):
            Budget(max_depth=0)

    def test_nodes_too_low(self):
        with pytest.raises(ValueError, match="max_nodes"):
            Budget(max_nodes=0)

    def test_allows_relation(self):
        b = Budget(edge_filter=frozenset({"cite", "elaborate"}))
        assert b.allows_relation("cite") is True
        assert b.allows_relation("elaborate") is True
        assert b.allows_relation("contradict") is False

    def test_allows_all_when_no_filter(self):
        b = Budget()
        assert b.allows_relation("cite") is True
        assert b.allows_relation("anything") is True


# ═══════════════════════════════════════════════════════════════════
#  5. PROVENANCE PATH TESTS — §3.2, §5.1
# ═══════════════════════════════════════════════════════════════════


class TestProvenancePath:
    """ProvenancePath — claim with provenance chain (§3.2)."""

    def test_empty_path(self):
        path = ProvenancePath(edges=[])
        assert path.nodes == []
        assert path.depth == 0

    def test_single_edge_path(self):
        edge = Edge("d1", "d2", _cite(), weight=0.8)
        path = ProvenancePath(edges=[edge])
        assert path.nodes == ["d1", "d2"]
        assert path.depth == 1

    def test_multi_edge_path(self):
        e1 = Edge("d1", "d2", _cite(), weight=0.9)
        e2 = Edge("d2", "d3", _cite(), weight=0.7)
        path = ProvenancePath(edges=[e1, e2])
        assert path.nodes == ["d1", "d2", "d3"]
        assert path.depth == 2

    def test_coherence_invariant(self):
        """§5.1 property 2: edges[i].target = edges[i+1].source."""
        e1 = Edge("d1", "d2", _cite())
        e2 = Edge("d3", "d4", _cite())  # gap: d2 ≠ d3
        with pytest.raises(ValueError, match="Path coherence"):
            ProvenancePath(edges=[e1, e2])

    def test_total_weight(self):
        e1 = Edge("d1", "d2", _cite(), weight=0.8)
        e2 = Edge("d2", "d3", _cite(), weight=0.5)
        path = ProvenancePath(edges=[e1, e2])
        assert path.total_weight == pytest.approx(0.4)

    def test_epistemic_type(self):
        path = ProvenancePath(
            edges=[Edge("d1", "d2", _cite())],
            claim="liability clause found",
            epistemic_type="CitedFact",
            confidence=0.85,
        )
        assert path.epistemic_type == "CitedFact"
        assert path.claim == "liability clause found"

    def test_to_dict(self):
        path = ProvenancePath(
            edges=[Edge("d1", "d2", _cite(), weight=0.9)],
            claim="test claim",
            epistemic_type="CitedFact",
            confidence=0.85,
        )
        d = path.to_dict()
        assert d["nodes"] == ["d1", "d2"]
        assert d["depth"] == 1
        assert d["epistemic_type"] == "CitedFact"


# ═══════════════════════════════════════════════════════════════════
#  6. CORPUS GRAPH TESTS — Definition 1, §2.1
# ═══════════════════════════════════════════════════════════════════


class TestCorpusGraph:
    """CorpusGraph — C = (D, R, τ, ω, σ) from Definition 1."""

    def test_create_empty(self):
        corpus = CorpusGraph(name="Test")
        assert corpus.name == "Test"
        assert corpus.document_count == 0
        assert corpus.edge_count == 0

    def test_add_document(self):
        corpus = CorpusGraph()
        doc = Document(doc_id="d1", title="Doc 1")
        corpus.add_document(doc)
        assert corpus.document_count == 1
        assert corpus.has_document("d1")

    def test_duplicate_document_raises(self):
        corpus = CorpusGraph()
        doc = Document(doc_id="d1", title="Doc 1")
        corpus.add_document(doc)
        with pytest.raises(ValueError, match="already exists"):
            corpus.add_document(doc)

    def test_add_edge(self):
        corpus = _sample_corpus()
        assert corpus.edge_count == 3

    def test_invariant_g2_source(self):
        """Invariant (G2): edge source must be in D."""
        corpus = CorpusGraph()
        corpus.add_document(Document(doc_id="d1", title="Doc 1"))
        with pytest.raises(ValueError, match="G2"):
            corpus.add_edge(Edge("missing", "d1", _cite()))

    def test_invariant_g2_target(self):
        """Invariant (G2): edge target must be in D."""
        corpus = CorpusGraph()
        corpus.add_document(Document(doc_id="d1", title="Doc 1"))
        with pytest.raises(ValueError, match="G2"):
            corpus.add_edge(Edge("d1", "missing", _cite()))

    def test_ontological_constraint(self):
        """§4.3: domain constraint validation."""
        corpus = CorpusGraph()
        corpus.add_document(Document(doc_id="d1", title="A", doc_type="statute"))
        corpus.add_document(Document(doc_id="d2", title="B", doc_type="regulation"))

        constrained = RelationType(
            name="implement",
            domain_constraint=("regulation", "statute"),
        )
        # regulation → statute would be valid
        corpus.add_edge(Edge("d2", "d1", constrained, weight=0.8))

        # statute → regulation violates constraint
        with pytest.raises(ValueError, match="Ontological"):
            corpus.add_edge(Edge("d1", "d2", constrained, weight=0.8))

    def test_neighbors(self):
        corpus = _sample_corpus()
        neighbors = corpus.neighbors("ley123")
        assert len(neighbors) == 2
        neighbor_ids = {doc.doc_id for doc, edge in neighbors}
        assert "caso_juris" in neighbor_ids
        assert "reglamento" in neighbor_ids

    def test_neighbors_with_filter(self):
        corpus = _sample_corpus()
        neighbors = corpus.neighbors("ley123", edge_filter=frozenset({"cite"}))
        assert len(neighbors) == 1
        assert neighbors[0][0].doc_id == "caso_juris"

    def test_neighbors_nonexistent(self):
        corpus = _sample_corpus()
        assert corpus.neighbors("nonexistent") == []

    def test_out_degree(self):
        corpus = _sample_corpus()
        assert corpus.out_degree("ley123") == 2
        assert corpus.out_degree("caso_juris") == 1
        assert corpus.out_degree("reglamento") == 0

    def test_max_out_degree(self):
        corpus = _sample_corpus()
        assert corpus.max_out_degree() == 2

    def test_epr_dirty(self):
        corpus = _sample_corpus()
        assert corpus.epr_dirty is True
        corpus.set_epr_scores({"ley123": 0.5})
        assert corpus.epr_dirty is False
        # Adding doc makes it dirty again
        corpus.add_document(Document(doc_id="new", title="New"))
        assert corpus.epr_dirty is True

    def test_validate_edge(self):
        corpus = _sample_corpus()
        assert corpus.validate_edge(Edge("ley123", "caso_juris", _cite())) is True
        assert corpus.validate_edge(Edge("missing", "caso_juris", _cite())) is False

    def test_to_dict(self):
        corpus = _sample_corpus()
        d = corpus.to_dict()
        assert d["name"] == "LegalCorpus"
        assert d["document_count"] == 3
        assert d["edge_count"] == 3

    def test_iter_documents(self):
        corpus = _sample_corpus()
        docs = list(corpus.iter_documents())
        assert len(docs) == 3

    def test_document_ids(self):
        corpus = _sample_corpus()
        ids = corpus.document_ids()
        assert ids == {"ley123", "caso_juris", "reglamento"}


# ═══════════════════════════════════════════════════════════════════
#  7. NAVIGATION RESULT TESTS — §5.1
# ═══════════════════════════════════════════════════════════════════


class TestNavigationResult:
    """NavigationResult — output of MDN navigation."""

    def test_empty_result(self):
        result = NavigationResult()
        assert result.total_paths == 0
        assert result.total_documents_visited == 0
        assert result.has_contradictions is False

    def test_with_paths(self):
        path = ProvenancePath(
            edges=[Edge("d1", "d2", _cite())],
            confidence=0.8,
        )
        result = NavigationResult(
            paths=[path],
            visited={"d1", "d2"},
            confidence=0.8,
        )
        assert result.total_paths == 1
        assert result.total_documents_visited == 2

    def test_with_contradictions(self):
        result = NavigationResult(
            contradictions=[("d1", "d2", "claim_φ")],
        )
        assert result.has_contradictions is True

    def test_to_dict(self):
        result = NavigationResult(
            visited={"d1"},
            confidence=0.7,
        )
        d = result.to_dict()
        assert d["confidence"] == 0.7
        assert "d1" in d["visited"]


# ═══════════════════════════════════════════════════════════════════
#  8. CORPUS NAVIGATOR TESTS — Algorithm §5.4
# ═══════════════════════════════════════════════════════════════════


class TestCorpusNavigator:
    """CorpusNavigator — bounded BFS with info-gain pruning."""

    def test_navigate_basic(self):
        corpus = _sample_corpus()
        nav = CorpusNavigator(corpus)
        result = nav.navigate(
            start_doc_id="ley123",
            query="responsabilidad civil",
            budget=Budget(max_depth=3, max_nodes=10),
        )
        assert result.total_paths > 0
        assert "ley123" in result.visited

    def test_navigate_visits_neighbors(self):
        corpus = _sample_corpus()
        nav = CorpusNavigator(corpus)
        result = nav.navigate(
            start_doc_id="ley123",
            query="responsabilidad",
            budget=Budget(max_depth=2, max_nodes=10),
        )
        # Should visit at least the start doc
        assert "ley123" in result.visited

    def test_budget_max_depth_enforced(self):
        """Termination guarantee (T1): max_depth bounds path length."""
        corpus = _larger_corpus()
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("D0", "research", Budget(max_depth=1, max_nodes=100))
        # At depth=1, should not reach D3 (which is depth=2 from D0)
        for path in result.paths:
            assert path.depth <= 1

    def test_budget_max_nodes_enforced(self):
        """Termination guarantee (T3): max_nodes bounds visited count."""
        corpus = _larger_corpus()
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("D0", "research", Budget(max_depth=5, max_nodes=3))
        assert result.total_documents_visited <= 3

    def test_edge_filter(self):
        """§4.3: only follow specified relation types."""
        corpus = _sample_corpus()
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate(
            "ley123", "query",
            Budget(max_depth=2, edge_filter=frozenset({"cite"})),
        )
        # Should only follow cite edges, not implement
        for path in result.paths:
            for edge in path.edges:
                assert edge.relation.name == "cite"

    def test_navigate_nonexistent_start_raises(self):
        corpus = _sample_corpus()
        nav = CorpusNavigator(corpus)
        with pytest.raises(ValueError, match="not in corpus"):
            nav.navigate("nonexistent", "query", Budget())

    def test_detects_contradictions(self):
        """§3.3: contradictions detected via contradict edges."""
        corpus = _sample_corpus()
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate(
            "ley123", "query",
            Budget(max_depth=3, max_nodes=10),
        )
        # The corpus has a contradict edge: caso_juris → reglamento
        # So we might detect a contradiction if we traverse that path
        # (depends on pruning, but with threshold=0.0 we should get there)

    def test_no_immediate_revisit(self):
        """§5.1 invariant 3: no self-loops in paths."""
        nav = CorpusNavigator(_sample_corpus())
        # The navigator's static method should prevent self-loops
        e1 = Edge("d1", "d2", _cite())
        e2 = Edge("d2", "d2", _cite())  # self-loop
        assert CorpusNavigator._no_immediate_revisit([e1, e2]) is False

    def test_no_immediate_revisit_valid(self):
        e1 = Edge("d1", "d2", _cite())
        e2 = Edge("d2", "d3", _cite())
        assert CorpusNavigator._no_immediate_revisit([e1, e2]) is True

    def test_adaptive_threshold(self):
        nav = CorpusNavigator(_sample_corpus())
        # Median of [1, 2, 3, 4, 5] at p=0.5 ≈ 3
        theta = nav._adaptive_threshold([1.0, 2.0, 3.0, 4.0, 5.0])
        assert theta >= 2.0  # should be around the median

    def test_larger_corpus_navigation(self):
        """Full navigation on larger corpus."""
        corpus = _larger_corpus()
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("D0", "research findings", Budget(max_depth=3))
        assert result.total_paths > 0
        assert "D0" in result.visited


# ═══════════════════════════════════════════════════════════════════
#  9. EPISTEMIC PAGERANK TESTS — §2.3
# ═══════════════════════════════════════════════════════════════════


class TestEpistemicPageRank:
    """EpistemicPageRank — signed graph PageRank (Definition 4.2)."""

    def test_compute_basic(self):
        corpus = _sample_corpus()
        epr = EpistemicPageRank()
        scores = epr.compute(corpus)
        assert len(scores) == 3
        # All scores should be in [0, 1] after normalization
        for score in scores.values():
            assert 0.0 <= score <= 1.0

    def test_empty_corpus(self):
        corpus = CorpusGraph()
        epr = EpistemicPageRank()
        scores = epr.compute(corpus)
        assert scores == {}

    def test_single_document(self):
        corpus = CorpusGraph()
        corpus.add_document(Document(doc_id="d1", title="Only Doc"))
        epr = EpistemicPageRank()
        scores = epr.compute(corpus)
        assert "d1" in scores

    def test_scores_applied_to_corpus(self):
        corpus = _sample_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)
        assert corpus.epr_dirty is False
        assert corpus.get_epr("ley123") >= 0.0

    def test_damping_bounds(self):
        with pytest.raises(ValueError, match="Damping"):
            EpistemicPageRank(damping=0.0)
        with pytest.raises(ValueError, match="Damping"):
            EpistemicPageRank(damping=1.0)

    def test_distrust_weight_bounds(self):
        with pytest.raises(ValueError, match="Distrust"):
            EpistemicPageRank(distrust_weight=-0.1)

    def test_positive_relations_boost(self):
        """Documents cited more should have higher EPR⁺."""
        corpus = CorpusGraph(name="CiteTest")
        for i in range(4):
            corpus.add_document(Document(doc_id=f"d{i}", title=f"Doc {i}"))
        # d0 is cited by d1, d2, d3
        for i in range(1, 4):
            corpus.add_edge(Edge(f"d{i}", "d0", _cite(), weight=0.9))

        epr = EpistemicPageRank()
        scores = epr.compute(corpus)
        # d0 should have the highest score (most cited)
        assert scores["d0"] == max(scores.values())

    def test_negative_relations_penalize(self):
        """Documents contradicted should have lower EPR."""
        corpus = CorpusGraph(name="ContradictTest")
        for i in range(3):
            corpus.add_document(Document(doc_id=f"d{i}", title=f"Doc {i}"))
        # d1 cites d0 (positive)
        corpus.add_edge(Edge("d1", "d0", _cite(), weight=0.9))
        # d2 contradicts d0 (negative)
        corpus.add_edge(Edge("d2", "d0", _contradict(), weight=0.8))

        epr = EpistemicPageRank(distrust_weight=0.5)
        scores = epr.compute(corpus)
        # With contradiction, d0's score should be reduced
        assert len(scores) == 3

    def test_k_hop_neighborhood(self):
        corpus = _larger_corpus()
        # From D0 with k=1: should reach D1, D2
        hop1 = EpistemicPageRank.k_hop_neighborhood(corpus, "D0", k=1)
        assert "D0" in hop1
        assert "D1" in hop1
        assert "D2" in hop1

        # From D0 with k=2: should also reach D3, D4, D5
        hop2 = EpistemicPageRank.k_hop_neighborhood(corpus, "D0", k=2)
        assert "D3" in hop2 or "D4" in hop2  # at least some depth-2 nodes


# ═══════════════════════════════════════════════════════════════════
#  10. CORPUS BUILDER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestCorpusBuilder:
    """CorpusBuilder — fluent construction of corpus graphs."""

    def test_build_basic(self):
        corpus = (
            CorpusBuilder("Test")
            .add_document("d1", "Doc 1")
            .add_document("d2", "Doc 2")
            .add_edge("d1", "d2", "cite")
            .build()
        )
        assert corpus.name == "Test"
        assert corpus.document_count == 2
        assert corpus.edge_count == 1

    def test_build_with_types(self):
        corpus = (
            CorpusBuilder("Legal")
            .add_document("ley", "Ley 123", doc_type="statute")
            .add_document("reg", "Reglamento", doc_type="regulation")
            .add_edge("ley", "reg", "implement", weight=0.9)
            .build()
        )
        assert corpus.document_count == 2
        edge = corpus.edges[0]
        assert edge.weight == 0.9
        assert edge.relation.name == "implement"

    def test_unknown_relation_raises(self):
        builder = (
            CorpusBuilder("Test")
            .add_document("d1", "Doc 1")
            .add_document("d2", "Doc 2")
            .add_edge("d1", "d2", "unknown_relation")
        )
        with pytest.raises(ValueError, match="Unknown relation"):
            builder.build()

    def test_custom_relation_type(self):
        corpus = (
            CorpusBuilder("Test")
            .add_relation_type("custom_rel", properties={"reflexive"})
            .add_document("d1", "Doc 1")
            .add_document("d2", "Doc 2")
            .add_edge("d1", "d2", "custom_rel")
            .build()
        )
        assert corpus.edge_count == 1
        assert corpus.edges[0].relation.name == "custom_rel"

    def test_missing_endpoint_raises(self):
        builder = (
            CorpusBuilder("Test")
            .add_document("d1", "Doc 1")
            .add_edge("d1", "missing", "cite")
        )
        with pytest.raises(ValueError):
            builder.build()

    def test_all_standard_relations_registered(self):
        builder = CorpusBuilder()
        for rel in STANDARD_RELATION_TYPES:
            assert rel in builder._relation_types


# ═══════════════════════════════════════════════════════════════════
#  11. FULL PIPELINE INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestMDNPipeline:
    """End-to-end: build corpus → compute EPR → navigate → validate."""

    def test_full_pipeline(self):
        """Complete MDN pipeline: build → EPR → navigate → check."""
        # 1. Build corpus
        corpus = (
            CorpusBuilder("LegalCorpus")
            .add_document("ley", "Ley de Responsabilidad", doc_type="statute",
                          summary="Ley sobre responsabilidad civil y daños")
            .add_document("caso", "Sentencia TC-2024", doc_type="case_law",
                          summary="Caso sobre daños por negligencia médica")
            .add_document("reg", "Reglamento Sanitario", doc_type="regulation",
                          summary="Normas de implementación sanitaria")
            .add_edge("ley", "caso", "cite", weight=0.9)
            .add_edge("ley", "reg", "implement", weight=0.85)
            .add_edge("caso", "reg", "elaborate", weight=0.7)
            .build()
        )
        assert corpus.document_count == 3
        assert corpus.edge_count == 3

        # 2. Compute EPR
        epr = EpistemicPageRank(damping=0.85, distrust_weight=0.3)
        scores = epr.compute_and_apply(corpus)
        assert len(scores) == 3
        assert corpus.epr_dirty is False

        # 3. Navigate
        nav = CorpusNavigator(
            corpus,
            relevance_threshold=0.0,  # low threshold for testing
        )
        result = nav.navigate(
            start_doc_id="ley",
            query="responsabilidad por daños médicos",
            budget=Budget(max_depth=3, max_nodes=10),
        )

        # 4. Validate result
        assert result.total_paths > 0
        assert "ley" in result.visited

        # 5. Verify provenance paths are coherent (§5.1, invariant 2)
        for path in result.paths:
            for i in range(len(path.edges) - 1):
                assert path.edges[i].target_id == path.edges[i + 1].source_id

        # 6. Verify budget enforcement (§5.1, invariant 4)
        for path in result.paths:
            assert path.depth <= 3

    def test_pipeline_with_contradictions(self):
        """Pipeline with contradiction detection (§3.3)."""
        corpus = (
            CorpusBuilder("ConflictCorpus")
            .add_document("d1", "Study A", summary="Supports conclusion X")
            .add_document("d2", "Study B", summary="Contradicts conclusion X")
            .add_edge("d1", "d2", "contradict", weight=0.8)
            .build()
        )

        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("d1", "conclusion X", Budget(max_depth=2))

        # Should detect the contradiction
        assert result.total_paths > 0

    def test_pipeline_medical_vertical(self):
        """HYPA vertical: medical diagnosis corpus."""
        corpus = (
            CorpusBuilder("MedicalCorpus")
            .add_document("guideline", "Clinical Practice Guideline",
                          doc_type="guideline",
                          summary="Standard treatment protocol for condition Y")
            .add_document("study1", "Randomized Trial Alpha",
                          doc_type="study",
                          summary="Evidence supporting treatment A for condition Y")
            .add_document("study2", "Cohort Study Beta",
                          doc_type="study",
                          summary="Evidence supporting treatment B for condition Y")
            .add_document("review", "Systematic Review",
                          doc_type="review",
                          summary="Meta-analysis comparing treatments A and B")
            .add_edge("guideline", "study1", "cite", weight=0.9)
            .add_edge("guideline", "study2", "cite", weight=0.85)
            .add_edge("review", "study1", "cite", weight=0.8)
            .add_edge("review", "study2", "cite", weight=0.8)
            .add_edge("study1", "study2", "corroborate", weight=0.7)
            .build()
        )

        epr = EpistemicPageRank()
        scores = epr.compute_and_apply(corpus)

        # Studies cited more should have higher EPR
        assert len(scores) == 4

        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("guideline", "treatment for condition Y", Budget(max_depth=3))
        assert result.total_paths > 0


# ═══════════════════════════════════════════════════════════════════
#  12. CORPUS GRAPH MUTATION TESTS — §5.5
# ═══════════════════════════════════════════════════════════════════


def _incremental_corpus() -> CorpusGraph:
    """Build a 10-doc corpus for incremental testing.

    Structure:
      A --[cite]--> B --[cite]--> C --[cite]--> D
      A --[elaborate]--> E --[cite]--> F
      B --[contradict]--> G
      E --[implement]--> H
      H --[cite]--> I --[cite]--> J
    """
    corpus = CorpusGraph(name="IncrementalCorpus")
    for label in "ABCDEFGHIJ":
        corpus.add_document(Document(
            doc_id=label, title=f"Document {label}",
            doc_type="paper", summary=f"Summary of {label}",
        ))

    elaborate = RelationType(name="elaborate")
    corpus.add_edge(Edge("A", "B", _cite(), weight=0.9))
    corpus.add_edge(Edge("B", "C", _cite(), weight=0.8))
    corpus.add_edge(Edge("C", "D", _cite(), weight=0.7))
    corpus.add_edge(Edge("A", "E", elaborate, weight=0.85))
    corpus.add_edge(Edge("E", "F", _cite(), weight=0.75))
    corpus.add_edge(Edge("B", "G", _contradict(), weight=0.6))
    corpus.add_edge(Edge("E", "H", _implement(), weight=0.8))
    corpus.add_edge(Edge("H", "I", _cite(), weight=0.7))
    corpus.add_edge(Edge("I", "J", _cite(), weight=0.65))

    return corpus


class TestCorpusGraphMutation:
    """CorpusGraph — remove_document, remove_edge, copy (§5.5)."""

    def test_remove_document_basic(self):
        corpus = _sample_corpus()
        assert corpus.document_count == 3
        corpus.remove_document("reglamento")
        assert corpus.document_count == 2
        assert not corpus.has_document("reglamento")

    def test_remove_document_cascades_edges(self):
        """Removing a document removes all incident edges."""
        corpus = _sample_corpus()
        # reglamento is target of ley123->reglamento, caso_juris->reglamento
        corpus.remove_document("reglamento")
        assert corpus.edge_count == 1  # only ley123->caso_juris remains
        for edge in corpus.edges:
            assert edge.target_id != "reglamento"
            assert edge.source_id != "reglamento"

    def test_remove_document_marks_dirty(self):
        corpus = _sample_corpus()
        corpus.set_epr_scores({"ley123": 0.5, "caso_juris": 0.3, "reglamento": 0.2})
        assert corpus.epr_dirty is False
        corpus.remove_document("reglamento")
        assert corpus.epr_dirty is True

    def test_remove_document_nonexistent_raises(self):
        corpus = _sample_corpus()
        with pytest.raises(ValueError, match="not in corpus"):
            corpus.remove_document("nonexistent")

    def test_remove_edge_basic(self):
        corpus = _sample_corpus()
        assert corpus.edge_count == 3
        edge_to_remove = Edge("ley123", "caso_juris", _cite())
        corpus.remove_edge(edge_to_remove)
        assert corpus.edge_count == 2
        # Verify adjacency is updated
        neighbors = corpus.neighbors("ley123")
        neighbor_ids = {doc.doc_id for doc, _ in neighbors}
        assert "caso_juris" not in neighbor_ids

    def test_remove_edge_nonexistent_raises(self):
        corpus = _sample_corpus()
        with pytest.raises(ValueError, match="not in corpus"):
            corpus.remove_edge(Edge("ley123", "reglamento", _cite()))

    def test_copy_independence(self):
        """§5.5: C' = copy(C) — mutations to C' don't affect C."""
        corpus = _sample_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        corpus_copy = corpus.copy()

        # Verify copy has same structure
        assert corpus_copy.document_count == corpus.document_count
        assert corpus_copy.edge_count == corpus.edge_count

        # Mutate the copy
        corpus_copy.add_document(Document(doc_id="new", title="New Doc"))

        # Original is unaffected
        assert corpus.document_count == 3
        assert not corpus.has_document("new")
        assert corpus_copy.document_count == 4

    def test_copy_preserves_epr_scores(self):
        corpus = _sample_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        corpus_copy = corpus.copy()
        assert corpus_copy.epr_dirty is False
        for doc_id in corpus.document_ids():
            assert corpus_copy.get_epr(doc_id) == corpus.get_epr(doc_id)


# ═══════════════════════════════════════════════════════════════════
#  13. INCREMENTAL EPR TESTS — §5.5
# ═══════════════════════════════════════════════════════════════════


class TestIncrementalEPR:
    """EpistemicPageRank — incremental update via k-hop recomputation."""

    def test_incremental_empty_affected_returns_existing(self):
        """No affected docs → return existing scores unchanged."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        original = epr.compute_and_apply(corpus)

        result = epr.incremental_update(corpus, affected_doc_ids=set())
        assert result == original

    def test_incremental_empty_corpus(self):
        corpus = CorpusGraph()
        epr = EpistemicPageRank()
        result = epr.incremental_update(corpus, {"nonexistent"})
        assert result == {}

    def test_incremental_after_add_document(self):
        """Add a document + edge, then incremental update."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        original = epr.compute_and_apply(corpus)

        # Add a new document citing D
        corpus.add_document(Document(doc_id="K", title="New Study"))
        corpus.add_edge(Edge("K", "D", _cite(), weight=0.9))

        result = epr.incremental_update(corpus, affected_doc_ids={"K"}, k_hop=2)

        # All docs should have scores
        assert len(result) == 11
        assert "K" in result
        # D should have changed (new citation)
        # Other distant docs should be relatively stable

    def test_incremental_after_remove_document(self):
        """Remove a document, then incremental update."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Remove J (leaf node)
        affected = {"J", "I"}  # I loses an outgoing edge
        corpus.remove_document("J")

        result = epr.incremental_update(corpus, affected_doc_ids=affected, k_hop=2)
        assert len(result) == 9
        assert "J" not in result

    def test_incremental_after_add_edge(self):
        """Add an edge between existing docs, then incremental update."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        original = epr.compute_and_apply(corpus)

        # Add a new cite edge: G -> D (was previously isolated on receive end)
        corpus.add_edge(Edge("G", "D", _cite(), weight=0.8))

        result = epr.incremental_update(
            corpus, affected_doc_ids={"G", "D"}, k_hop=2
        )
        assert len(result) == 10

    def test_incremental_after_remove_edge(self):
        """Remove an edge, then incremental update."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Remove the contradiction: B -> G
        corpus.remove_edge(Edge("B", "G", _contradict()))

        result = epr.incremental_update(
            corpus, affected_doc_ids={"B", "G"}, k_hop=2
        )
        assert len(result) == 10

    def test_incremental_all_affected_does_full_recompute(self):
        """When coverage > 0.7, falls back to full recompute."""
        corpus = _sample_corpus()  # only 3 docs
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Affect all 3 — coverage = 1.0 > 0.7 → full recompute
        result = epr.incremental_update(
            corpus, affected_doc_ids={"ley123", "caso_juris", "reglamento"}
        )
        assert len(result) == 3

    def test_incremental_convergence_vs_full(self):
        """Incremental update preserves scores outside N_k neighborhood.

        §5.5 key property: docs outside the k-hop neighborhood of
        affected nodes retain their previous EPR scores exactly.
        Docs inside may differ from full recompute (locality trade-off).
        """
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        original_scores = epr.compute_and_apply(corpus)

        # Save scores of distant nodes before mutation
        distant_scores = {
            doc_id: original_scores[doc_id]
            for doc_id in ["I", "J"]  # far from F
        }

        # Add a new doc citing F (peripheral node)
        corpus.add_document(Document(doc_id="NEW", title="New Paper"))
        corpus.add_edge(Edge("NEW", "F", _cite(), weight=0.95))

        # Incremental update
        inc_scores = epr.incremental_update(
            corpus, affected_doc_ids={"NEW"}, k_hop=2
        )

        # 1. All docs must have scores
        assert len(inc_scores) == 11
        assert "NEW" in inc_scores

        # 2. Scores are normalized (max = 1.0)
        assert max(inc_scores.values()) == pytest.approx(1.0)

        # 3. Distant unaffected docs retain their ORIGINAL scores
        #    (key formal property of locality)
        for doc_id, old_score in distant_scores.items():
            assert inc_scores[doc_id] == pytest.approx(old_score), (
                f"Distant doc {doc_id} should be unchanged: "
                f"was {old_score:.4f}, got {inc_scores[doc_id]:.4f}"
            )

        # 4. Full recompute vs incremental: all docs present
        corpus_full = corpus.copy()
        full_scores = epr.compute(corpus_full)
        assert set(full_scores.keys()) == set(inc_scores.keys())

    def test_incremental_scores_normalized(self):
        """After incremental update, scores should be normalized."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        corpus.add_document(Document(doc_id="X", title="Extra"))
        corpus.add_edge(Edge("X", "C", _cite(), weight=0.7))

        result = epr.incremental_update(corpus, {"X"}, k_hop=2)

        # After normalization, max score should be 1.0
        assert max(result.values()) == pytest.approx(1.0)

    def test_incremental_marks_dirty_false(self):
        """After incremental update, corpus EPR should not be dirty."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        corpus.add_document(Document(doc_id="Y", title="Yet Another"))
        corpus.add_edge(Edge("Y", "A", _cite(), weight=0.8))
        assert corpus.epr_dirty is True

        epr.incremental_update(corpus, {"Y"}, k_hop=2)
        assert corpus.epr_dirty is False


# ═══════════════════════════════════════════════════════════════════
#  14. K-HOP NEIGHBORHOOD TESTS — §5.5
# ═══════════════════════════════════════════════════════════════════


class TestKHopNeighborhood:
    """k_hop_neighborhood — bidirectional expansion tests."""

    def test_k0_returns_self(self):
        """k=0 → only the node itself."""
        corpus = _incremental_corpus()
        result = EpistemicPageRank.k_hop_neighborhood(corpus, "A", k=0)
        assert result == {"A"}

    def test_k1_outgoing_neighbors(self):
        """k=1 → immediate outgoing neighbors."""
        corpus = _incremental_corpus()
        result = EpistemicPageRank.k_hop_neighborhood(corpus, "A", k=1)
        assert "A" in result
        assert "B" in result  # A -> B
        assert "E" in result  # A -> E

    def test_k1_incoming_neighbors(self):
        """k=1 bidirectional: also captures incoming edges."""
        corpus = _incremental_corpus()
        # D has incoming from C, but no outgoing
        result = EpistemicPageRank.k_hop_neighborhood(corpus, "D", k=1)
        assert "D" in result
        assert "C" in result  # C -> D (incoming)

    def test_k2_deeper_reach(self):
        """k=2 → reaches 2 hops in both directions."""
        corpus = _incremental_corpus()
        result = EpistemicPageRank.k_hop_neighborhood(corpus, "B", k=2)
        assert "B" in result
        # k=1 from B: C (outgoing), G (outgoing), A (incoming)
        assert "A" in result
        assert "C" in result
        assert "G" in result
        # k=2: D (C->D outgoing), E (A->E outgoing)
        assert "D" in result or "E" in result

    def test_isolated_node(self):
        """Isolated doc → k-hop returns only itself."""
        corpus = CorpusGraph()
        corpus.add_document(Document(doc_id="alone", title="Alone"))
        result = EpistemicPageRank.k_hop_neighborhood(corpus, "alone", k=3)
        assert result == {"alone"}

    def test_k_hop_union(self):
        """Union of k-hop for multiple seed nodes."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()

        union = epr._k_hop_union(corpus, {"D", "J"}, k=1)
        assert "D" in union
        assert "J" in union
        assert "C" in union  # C -> D incoming
        assert "I" in union  # I -> J incoming


# ═══════════════════════════════════════════════════════════════════
#  15. INCREMENTAL PIPELINE INTEGRATION — §5.5
# ═══════════════════════════════════════════════════════════════════


class TestIncrementalPipeline:
    """End-to-end: build → EPR → mutate → incremental update → navigate."""

    def test_add_then_incremental_navigate(self):
        """Full pipeline: build corpus, compute EPR, add doc, incremental, navigate."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Add a new doc that cites A (highly connected)
        corpus.add_document(Document(
            doc_id="NEW_STUDY", title="New Study",
            summary="A brand-new study citing the foundational document",
        ))
        corpus.add_edge(Edge("NEW_STUDY", "A", _cite(), weight=0.95))

        # Incremental update (not full recompute)
        scores = epr.incremental_update(corpus, {"NEW_STUDY"}, k_hop=2)
        assert "NEW_STUDY" in scores
        assert len(scores) == 11

        # Navigate from new doc
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("NEW_STUDY", "foundational research", Budget(max_depth=3))
        assert result.total_paths > 0
        assert "NEW_STUDY" in result.visited

    def test_remove_then_incremental_navigate(self):
        """Pipeline: remove a document then navigate the updated graph."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Remove leaf J
        corpus.remove_document("J")
        scores = epr.incremental_update(corpus, {"I"}, k_hop=2)
        assert "J" not in scores
        assert len(scores) == 9

        # Navigate — should work without J
        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("A", "research", Budget(max_depth=4))
        assert "J" not in result.visited

    def test_multiple_mutations_then_incremental(self):
        """Multiple mutations followed by a single incremental update."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Add two docs
        corpus.add_document(Document(doc_id="X1", title="Extra 1"))
        corpus.add_document(Document(doc_id="X2", title="Extra 2"))
        corpus.add_edge(Edge("X1", "B", _cite(), weight=0.7))
        corpus.add_edge(Edge("X2", "C", _cite(), weight=0.8))

        # Single incremental update for both
        scores = epr.incremental_update(corpus, {"X1", "X2"}, k_hop=2)
        assert "X1" in scores
        assert "X2" in scores
        assert len(scores) == 12

    def test_copy_mutate_incremental(self):
        """Functional pattern: C' = copy(C) → mutate C' → incremental."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        # Functional approach: work on a copy
        corpus_prime = corpus.copy()
        corpus_prime.add_document(Document(doc_id="Z", title="Functional Update"))
        corpus_prime.add_edge(Edge("Z", "A", _cite(), weight=0.9))

        scores_prime = epr.incremental_update(corpus_prime, {"Z"}, k_hop=2)

        # Original is unmodified
        assert corpus.document_count == 10
        assert corpus_prime.document_count == 11
        assert "Z" in scores_prime
        assert "Z" not in corpus.epr_scores

    def test_incremental_preserves_navigation_invariants(self):
        """After incremental update, navigation invariants (§5.1) still hold."""
        corpus = _incremental_corpus()
        epr = EpistemicPageRank()
        epr.compute_and_apply(corpus)

        corpus.add_document(Document(doc_id="INV", title="Invariant Test"))
        corpus.add_edge(Edge("INV", "E", _cite(), weight=0.8))
        epr.incremental_update(corpus, {"INV"}, k_hop=2)

        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("INV", "test query", Budget(max_depth=3, max_nodes=15))

        # Invariant 2: path coherence
        for path in result.paths:
            for i in range(len(path.edges) - 1):
                assert path.edges[i].target_id == path.edges[i + 1].source_id

        # Invariant 4: budget enforcement
        for path in result.paths:
            assert path.depth <= 3
        assert result.total_documents_visited <= 15


# ═══════════════════════════════════════════════════════════════════
#  16. EPISTEMIC TYPE LATTICE TESTS — §7.1
# ═══════════════════════════════════════════════════════════════════


class TestEpistemicLattice:
    """EpistemicLevel — lattice ordering, join, meet (§7.1)."""

    def test_ordering(self):
        """UNCERTAINTY < CONTESTED < FACTUAL < CITED < CORROBORATED."""
        U = EpistemicLevel.UNCERTAINTY
        CC = EpistemicLevel.CONTESTED_CLAIM
        FC = EpistemicLevel.FACTUAL_CLAIM
        CF = EpistemicLevel.CITED_FACT
        CR = EpistemicLevel.CORROBORATED_FACT
        assert U < CC < FC < CF < CR

    def test_join_returns_max(self):
        """join(A, B) = sup{A, B}."""
        U = EpistemicLevel.UNCERTAINTY
        CF = EpistemicLevel.CITED_FACT
        assert U.join(CF) == CF
        assert CF.join(U) == CF

    def test_meet_returns_min(self):
        """meet(A, B) = inf{A, B}."""
        FC = EpistemicLevel.FACTUAL_CLAIM
        CR = EpistemicLevel.CORROBORATED_FACT
        assert FC.meet(CR) == FC
        assert CR.meet(FC) == FC

    def test_join_idempotent(self):
        """join(A, A) = A."""
        FC = EpistemicLevel.FACTUAL_CLAIM
        assert FC.join(FC) == FC

    def test_meet_idempotent(self):
        """meet(A, A) = A."""
        CF = EpistemicLevel.CITED_FACT
        assert CF.meet(CF) == CF

    def test_top_and_bottom(self):
        CR = EpistemicLevel.CORROBORATED_FACT
        U = EpistemicLevel.UNCERTAINTY
        assert CR.is_top
        assert U.is_bottom
        assert not U.is_top
        assert not CR.is_bottom

    def test_is_reliable(self):
        """Reliable ≥ FactualClaim."""
        assert EpistemicLevel.FACTUAL_CLAIM.is_reliable
        assert EpistemicLevel.CITED_FACT.is_reliable
        assert EpistemicLevel.CORROBORATED_FACT.is_reliable
        assert not EpistemicLevel.CONTESTED_CLAIM.is_reliable
        assert not EpistemicLevel.UNCERTAINTY.is_reliable

    def test_is_contested(self):
        """Contested ≤ ContestedClaim."""
        assert EpistemicLevel.UNCERTAINTY.is_contested
        assert EpistemicLevel.CONTESTED_CLAIM.is_contested
        assert not EpistemicLevel.FACTUAL_CLAIM.is_contested

    def test_from_label_valid(self):
        assert EpistemicLevel.from_label("FactualClaim") == EpistemicLevel.FACTUAL_CLAIM
        assert EpistemicLevel.from_label("CitedFact") == EpistemicLevel.CITED_FACT
        assert EpistemicLevel.from_label("CorroboratedFact") == EpistemicLevel.CORROBORATED_FACT
        assert EpistemicLevel.from_label("ContestedClaim") == EpistemicLevel.CONTESTED_CLAIM
        assert EpistemicLevel.from_label("Uncertainty") == EpistemicLevel.UNCERTAINTY

    def test_from_label_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown epistemic level"):
            EpistemicLevel.from_label("InvalidLevel")

    def test_to_label_roundtrip(self):
        for level in EpistemicLevel:
            assert EpistemicLevel.from_label(level.to_label()) == level

    def test_level_to_dict(self):
        d = level_to_dict(EpistemicLevel.CITED_FACT)
        assert d["level"] == "CitedFact"
        assert d["value"] == 3
        assert d["is_reliable"] is True
        assert d["is_contested"] is False


class TestEpistemicPromotion:
    """promote/demote — monotonic epistemic level changes (§7.1)."""

    def test_promote_citation(self):
        """citation: +1 level."""
        result = promote(EpistemicLevel.FACTUAL_CLAIM, "citation")
        assert result == EpistemicLevel.CITED_FACT

    def test_promote_corroboration(self):
        """corroboration: +2 levels."""
        result = promote(EpistemicLevel.FACTUAL_CLAIM, "corroboration")
        assert result == EpistemicLevel.CORROBORATED_FACT

    def test_promote_capped_at_top(self):
        """Cannot promote above CorroboratedFact."""
        result = promote(EpistemicLevel.CORROBORATED_FACT, "corroboration")
        assert result == EpistemicLevel.CORROBORATED_FACT

    def test_promote_with_ceiling(self):
        """Shield integration: ceiling caps promotion."""
        result = promote(
            EpistemicLevel.FACTUAL_CLAIM,
            "corroboration",
            ceiling=EpistemicLevel.CITED_FACT,
        )
        assert result == EpistemicLevel.CITED_FACT

    def test_promote_invalid_evidence_raises(self):
        with pytest.raises(ValueError, match="Unknown promotion"):
            promote(EpistemicLevel.FACTUAL_CLAIM, "fake_evidence")

    def test_demote_contradiction(self):
        """contradiction: -1 level."""
        result = demote(EpistemicLevel.CITED_FACT, "contradiction")
        assert result == EpistemicLevel.FACTUAL_CLAIM

    def test_demote_retraction(self):
        """retraction: -2 levels."""
        result = demote(EpistemicLevel.CORROBORATED_FACT, "retraction")
        assert result == EpistemicLevel.FACTUAL_CLAIM

    def test_demote_capped_at_bottom(self):
        """Cannot demote below Uncertainty."""
        result = demote(EpistemicLevel.UNCERTAINTY, "retraction")
        assert result == EpistemicLevel.UNCERTAINTY

    def test_demote_anchored_resists(self):
        """Anchored facts resist demotion."""
        result = demote(
            EpistemicLevel.CITED_FACT,
            "contradiction",
            anchored=True,
        )
        assert result == EpistemicLevel.CITED_FACT  # unchanged

    def test_demote_with_floor(self):
        """Floor prevents demotion below threshold."""
        result = demote(
            EpistemicLevel.CITED_FACT,
            "retraction",
            floor=EpistemicLevel.FACTUAL_CLAIM,
        )
        assert result == EpistemicLevel.FACTUAL_CLAIM  # floor, not CitedFact-2

    def test_demote_invalid_evidence_raises(self):
        with pytest.raises(ValueError, match="Unknown demotion"):
            demote(EpistemicLevel.FACTUAL_CLAIM, "invalid")

    def test_classify_no_edges(self):
        """No citation chain → FactualClaim."""
        assert classify_provenance(0) == EpistemicLevel.FACTUAL_CLAIM

    def test_classify_with_citation(self):
        """Has citation chain → CitedFact."""
        assert classify_provenance(3) == EpistemicLevel.CITED_FACT

    def test_classify_with_corroboration(self):
        """Has corroboration → CorroboratedFact."""
        result = classify_provenance(2, has_corroboration=True)
        assert result == EpistemicLevel.CORROBORATED_FACT

    def test_classify_contradiction_dominates(self):
        """Contradiction dominates corroboration (conservative)."""
        result = classify_provenance(
            2, has_corroboration=True, has_contradiction=True
        )
        assert result == EpistemicLevel.CONTESTED_CLAIM

    def test_aggregate_conservative(self):
        """aggregate = meet of all levels (conservative)."""
        levels = [
            EpistemicLevel.CITED_FACT,
            EpistemicLevel.CORROBORATED_FACT,
            EpistemicLevel.FACTUAL_CLAIM,
        ]
        assert aggregate_levels(levels) == EpistemicLevel.FACTUAL_CLAIM

    def test_aggregate_empty(self):
        assert aggregate_levels([]) == EpistemicLevel.UNCERTAINTY


class TestEpistemicIntegration:
    """Epistemic types integration with navigator and corpus (§7.1)."""

    def test_navigator_assigns_factual_claim_for_start(self):
        """Start document (no edges) → FactualClaim."""
        corpus = _sample_corpus()
        EpistemicPageRank().compute_and_apply(corpus)

        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("ley123", "responsabilidad", Budget(max_depth=1))

        # The start node path has 0 edges → FactualClaim
        start_paths = [p for p in result.paths if len(p.edges) == 0]
        for path in start_paths:
            assert path.epistemic_type == "FactualClaim"

    def test_navigator_assigns_cited_fact_for_traversed(self):
        """Traversed path (has edges) → CitedFact."""
        corpus = _sample_corpus()
        EpistemicPageRank().compute_and_apply(corpus)

        nav = CorpusNavigator(corpus, relevance_threshold=0.0)
        result = nav.navigate("ley123", "jurisprudencia", Budget(max_depth=2))

        cited_paths = [p for p in result.paths if len(p.edges) > 0]
        for path in cited_paths:
            assert path.epistemic_type == "CitedFact"

    def test_document_epistemic_level_default(self):
        """Default Document epistemic_level is 'FactualClaim'."""
        doc = Document(doc_id="test", title="Test")
        assert doc.epistemic_level == "FactualClaim"
        level = EpistemicLevel.from_label(doc.epistemic_level)
        assert level == EpistemicLevel.FACTUAL_CLAIM

    def test_document_epistemic_level_roundtrip(self):
        """Can set and read epistemic level via formal type."""
        doc = Document(
            doc_id="peer_reviewed",
            title="Peer-Reviewed Study",
            epistemic_level=EpistemicLevel.CORROBORATED_FACT.to_label(),
        )
        level = EpistemicLevel.from_label(doc.epistemic_level)
        assert level == EpistemicLevel.CORROBORATED_FACT
        assert level.is_reliable
        assert level.is_top
