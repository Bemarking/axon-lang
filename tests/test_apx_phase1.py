"""APX Phase 1 test suite.

Covers:
- Lattice semantics and hard incompatibility boundary
- Graph invariants (MEC, DAG, G5 anti-monotonicity)
- Deterministic Epistemic PageRank with blame penalty
"""

from __future__ import annotations

from axon.engine.apx import (
    EdgeKind,
    EpistemicContract,
    EpistemicEdge,
    EpistemicGraph,
    EpistemicLattice,
    EpistemicLevel,
    EpistemicNode,
    EpistemicPageRank,
)


def _valid_contract(seed: str) -> EpistemicContract:
    return EpistemicContract(ecid=f"ecid-{seed}", certificate_hash=f"hash-{seed}", witness_count=2)


def _make_graph() -> EpistemicGraph:
    g = EpistemicGraph("apx-core")
    g.add_node(EpistemicNode("base.core", EpistemicLevel.CITED_FACT, _valid_contract("base")))
    g.add_node(EpistemicNode("pkg.analytics", EpistemicLevel.FACTUAL_CLAIM, _valid_contract("analytics")))
    g.add_node(EpistemicNode("pkg.app", EpistemicLevel.FACTUAL_CLAIM, _valid_contract("app")))

    g.add_edge(EpistemicEdge("pkg.app", "pkg.analytics", EdgeKind.DEPENDS_ON, 0.9))
    g.add_edge(EpistemicEdge("pkg.analytics", "base.core", EdgeKind.DEPENDS_ON, 1.0))
    return g


# ------------------------------------------------------------------
# Lattice
# ------------------------------------------------------------------


def test_lattice_order_and_meet() -> None:
    assert EpistemicLattice.leq(EpistemicLevel.FACTUAL_CLAIM, EpistemicLevel.CITED_FACT)
    assert EpistemicLattice.meet(EpistemicLevel.CITED_FACT, EpistemicLevel.OPINION) == EpistemicLevel.OPINION


def test_lattice_hard_boundary_join_degrades_to_uncertainty() -> None:
    joined = EpistemicLattice.join(EpistemicLevel.CITED_FACT, EpistemicLevel.OPINION)
    assert joined == EpistemicLevel.UNCERTAINTY


def test_lattice_substitution_respects_hard_boundary() -> None:
    assert not EpistemicLattice.can_substitute(EpistemicLevel.OPINION, EpistemicLevel.FACTUAL_CLAIM)
    assert EpistemicLattice.can_substitute(EpistemicLevel.CORROBORATED_FACT, EpistemicLevel.FACTUAL_CLAIM)


def test_uncertainty_tainting_is_infectious() -> None:
    level = EpistemicLattice.taint_with_uncertainty(EpistemicLevel.CORROBORATED_FACT)
    assert level == EpistemicLevel.UNCERTAINTY


# ------------------------------------------------------------------
# Graph invariants
# ------------------------------------------------------------------


def test_graph_validates_clean_state() -> None:
    graph = _make_graph()
    assert graph.validate_all() == []


def test_graph_detects_cycle() -> None:
    graph = _make_graph()
    graph.add_edge(EpistemicEdge("base.core", "pkg.app", EdgeKind.DEPENDS_ON, 0.4))

    errors = graph.validate_acyclic()
    assert len(errors) == 1
    assert "cycle detected" in errors[0]


def test_graph_detects_g5_violation() -> None:
    graph = EpistemicGraph("g5")
    graph.add_node(EpistemicNode("base", EpistemicLevel.OPINION, _valid_contract("base")))
    graph.add_node(EpistemicNode("derived", EpistemicLevel.CITED_FACT, _valid_contract("derived")))
    graph.add_edge(EpistemicEdge("derived", "base", EdgeKind.DEPENDS_ON, 1.0))

    errors = graph.validate_g5()
    assert len(errors) == 1
    assert "G5 violation" in errors[0]


def test_graph_detects_mec_violation() -> None:
    graph = EpistemicGraph("mec")
    bad = EpistemicContract(ecid="", certificate_hash="", witness_count=0)
    graph.add_node(EpistemicNode("pkg.bad", EpistemicLevel.FACTUAL_CLAIM, bad))

    errors = graph.validate_mec()
    assert len(errors) == 1
    assert "MEC violation" in errors[0]


def test_graph_rejects_duplicate_node_and_self_loop() -> None:
    graph = EpistemicGraph("guards")
    node = EpistemicNode("pkg.a", EpistemicLevel.FACTUAL_CLAIM, _valid_contract("a"))
    graph.add_node(node)

    try:
        graph.add_node(node)
        assert False, "expected duplicate node error"
    except ValueError as exc:
        assert "duplicate node" in str(exc)

    try:
        graph.add_edge(EpistemicEdge("pkg.a", "pkg.a", EdgeKind.DEPENDS_ON, 1.0))
        assert False, "expected self-loop error"
    except ValueError as exc:
        assert "self-loops" in str(exc)


# ------------------------------------------------------------------
# EPR
# ------------------------------------------------------------------


def test_epr_returns_normalized_scores() -> None:
    graph = _make_graph()
    epr = EpistemicPageRank()
    scores = epr.compute(graph)

    assert set(scores.keys()) == {"base.core", "pkg.analytics", "pkg.app"}
    assert all(0.0 <= score <= 1.0 for score in scores.values())


def test_epr_penalizes_server_blame() -> None:
    graph = EpistemicGraph("blame")
    graph.add_node(EpistemicNode("trusted", EpistemicLevel.CITED_FACT, _valid_contract("trusted"), server_blame_count=0))
    graph.add_node(EpistemicNode("faulty", EpistemicLevel.CITED_FACT, _valid_contract("faulty"), server_blame_count=8))

    graph.add_edge(EpistemicEdge("trusted", "faulty", EdgeKind.DEPENDS_ON, 1.0))
    graph.add_edge(EpistemicEdge("faulty", "trusted", EdgeKind.DEPENDS_ON, 1.0))

    epr = EpistemicPageRank(blame_alpha=0.25)
    scores = epr.compute(graph)

    assert scores["trusted"] > scores["faulty"]


def test_epr_quarantine_candidates() -> None:
    scores = {"a": 0.9, "b": 0.4, "c": 0.1}
    q = EpistemicPageRank.quarantine_candidates(scores, threshold=0.2)
    assert q == ["c"]


def test_epr_empty_graph() -> None:
    graph = EpistemicGraph("empty")
    epr = EpistemicPageRank()
    assert epr.compute(graph) == {}
