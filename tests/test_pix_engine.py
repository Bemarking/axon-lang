"""
AXON PIX Engine — Unit Tests
================================
Tests for PIX core engine: DocumentTree, PixNavigator, PixIndexer.

Tests are organized by component:
  1. PixLocation & PixNode (data structures)
  2. DocumentTree (tree operations + traversals)
  3. NavigationStep & ReasoningPath (trail data)
  4. PixNavigator (LLM-guided traversal)
  5. MarkdownExtractor & PixIndexer (document-to-tree)
"""

import json
import pytest

from axon.engine.pix.document_tree import (
    DocumentTree,
    PixLocation,
    PixNode,
)
from axon.engine.pix.navigator import (
    NavigationConfig,
    NavigationResult,
    NavigationStep,
    PixNavigator,
    ReasoningPath,
    ThresholdScorer,
)
from axon.engine.pix.indexer import (
    MarkdownExtractor,
    PixIndexer,
    Section,
    TruncationSummarizer,
)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _sample_tree() -> DocumentTree:
    """Build a small 3-level document tree for testing.

    Structure:
      root ── s1 (Definitions)
           │   ├── s1a (Legal Terms)
           │   └── s1b (Financial Terms)
           └── s2 (Liabilities)
               └── s2a (Direct Damages)
    """
    root = PixNode(node_id="root", title="Master Agreement", summary="Full contract")
    s1 = PixNode(node_id="s1", title="Definitions", summary="Legal and financial definitions")
    s1a = PixNode(node_id="s1a", title="Legal Terms", content="Content about legal terms...", summary="Legal glossary")
    s1b = PixNode(node_id="s1b", title="Financial Terms", content="Content about financial terms...", summary="Financial glossary")
    s2 = PixNode(node_id="s2", title="Liabilities", summary="Liability clauses")
    s2a = PixNode(node_id="s2a", title="Direct Damages", content="Content about direct damages...", summary="Direct damage limits")

    s1.add_child(s1a)
    s1.add_child(s1b)
    s2.add_child(s2a)
    root.add_child(s1)
    root.add_child(s2)

    return DocumentTree("contract_v2", root=root, source="contract.md")


def _sample_markdown() -> str:
    """Sample Markdown document for indexer tests."""
    return """# Master Agreement

Overview of the master agreement between parties.

## Definitions

Key definitions used throughout this contract.

### Legal Terms

Force majeure, indemnification, liability caps.

### Financial Terms

Payment schedules, interest rates, penalties.

## Liabilities

Liability framework for all parties.

### Direct Damages

Capped at 2x annual contract value.

### Indirect Damages

Excluded except for gross negligence.
"""


# ═══════════════════════════════════════════════════════════════════
#  1. PIX LOCATION
# ═══════════════════════════════════════════════════════════════════


class TestPixLocation:
    """PixLocation — spatial metadata for document sections."""

    def test_defaults(self):
        loc = PixLocation()
        assert loc.page_start == 0
        assert loc.page_end == 0
        assert loc.offset_start == 0
        assert loc.offset_end == 0

    def test_custom_values(self):
        loc = PixLocation(page_start=3, page_end=5, offset_start=100, offset_end=500)
        assert loc.page_start == 3
        assert loc.offset_end == 500

    def test_to_dict(self):
        loc = PixLocation(page_start=1, page_end=2, offset_start=10, offset_end=20)
        d = loc.to_dict()
        assert d == {"page_start": 1, "page_end": 2, "offset_start": 10, "offset_end": 20}

    def test_from_dict_roundtrip(self):
        original = PixLocation(page_start=5, page_end=10, offset_start=50, offset_end=100)
        restored = PixLocation.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_with_defaults(self):
        loc = PixLocation.from_dict({})
        assert loc.page_start == 0
        assert loc.offset_end == 0

    def test_frozen(self):
        loc = PixLocation()
        with pytest.raises(AttributeError):
            loc.page_start = 99  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  2. PIX NODE
# ═══════════════════════════════════════════════════════════════════


class TestPixNode:
    """PixNode — tree node with title, summary, content, children."""

    def test_leaf_node(self):
        node = PixNode(node_id="n1", title="Leaf", content="Some content")
        assert node.is_leaf
        assert node.child_count == 0

    def test_internal_node(self):
        parent = PixNode(node_id="parent", title="Parent")
        child = PixNode(node_id="child", title="Child")
        parent.add_child(child)
        assert not parent.is_leaf
        assert parent.child_count == 1

    def test_add_child_sets_depth(self):
        parent = PixNode(node_id="root", title="Root", depth=0)
        child = PixNode(node_id="c1", title="Child")
        parent.add_child(child)
        assert child.depth == 1

    def test_nested_depth(self):
        root = PixNode(node_id="root", title="Root", depth=0)
        level1 = PixNode(node_id="l1", title="L1")
        level2 = PixNode(node_id="l2", title="L2")
        root.add_child(level1)
        level1.add_child(level2)
        assert level2.depth == 2

    def test_get_child_by_id_found(self):
        parent = PixNode(node_id="p", title="P")
        child = PixNode(node_id="c1", title="C1")
        parent.add_child(child)
        assert parent.get_child_by_id("c1") is child

    def test_get_child_by_id_not_found(self):
        parent = PixNode(node_id="p", title="P")
        assert parent.get_child_by_id("nonexistent") is None

    def test_find_node_in_subtree(self):
        tree = _sample_tree()
        found = tree.root.find_node("s1b")
        assert found is not None
        assert found.title == "Financial Terms"

    def test_find_node_not_found(self):
        tree = _sample_tree()
        assert tree.root.find_node("nonexistent") is None

    def test_find_node_self(self):
        node = PixNode(node_id="x", title="X")
        assert node.find_node("x") is node

    def test_to_dict_serialization(self):
        node = PixNode(node_id="n1", title="Test", summary="Summary", content="Data")
        d = node.to_dict()
        assert d["node_id"] == "n1"
        assert d["title"] == "Test"
        assert d["summary"] == "Summary"
        assert d["content"] == "Data"
        assert d["children"] == []

    def test_from_dict_roundtrip(self):
        original = PixNode(node_id="n1", title="Test", summary="Sum", content="Data")
        original.add_child(PixNode(node_id="c1", title="Child"))
        restored = PixNode.from_dict(original.to_dict())
        assert restored.node_id == "n1"
        assert len(restored.children) == 1
        assert restored.children[0].node_id == "c1"

    def test_repr(self):
        leaf = PixNode(node_id="leaf", title="Leaf Node")
        assert "[leaf]" in repr(leaf)
        parent = PixNode(node_id="parent", title="Parent")
        parent.add_child(PixNode(node_id="c1", title="C1"))
        assert "1 children" in repr(parent)


# ═══════════════════════════════════════════════════════════════════
#  3. DOCUMENT TREE
# ═══════════════════════════════════════════════════════════════════


class TestDocumentTree:
    """DocumentTree — structured document container."""

    def test_properties(self):
        tree = _sample_tree()
        assert tree.name == "contract_v2"
        assert tree.source == "contract.md"
        assert tree.version == "1.0"

    def test_height(self):
        tree = _sample_tree()
        assert tree.height() == 2  # root → s1 → s1a

    def test_node_count(self):
        tree = _sample_tree()
        assert tree.node_count() == 6  # root + s1 + s1a + s1b + s2 + s2a

    def test_leaf_count(self):
        tree = _sample_tree()
        assert tree.leaf_count() == 3  # s1a, s1b, s2a

    def test_bfs_order(self):
        tree = _sample_tree()
        ids = [n.node_id for n in tree.bfs()]
        assert ids == ["root", "s1", "s2", "s1a", "s1b", "s2a"]

    def test_dfs_order(self):
        tree = _sample_tree()
        ids = [n.node_id for n in tree.dfs()]
        assert ids == ["root", "s1", "s1a", "s1b", "s2", "s2a"]

    def test_leaves(self):
        tree = _sample_tree()
        leaf_ids = [n.node_id for n in tree.leaves()]
        assert set(leaf_ids) == {"s1a", "s1b", "s2a"}

    def test_path_to_leaf(self):
        tree = _sample_tree()
        path = tree.path_to("s2a")
        assert path is not None
        path_ids = [n.node_id for n in path]
        assert path_ids == ["root", "s2", "s2a"]

    def test_path_to_root(self):
        tree = _sample_tree()
        path = tree.path_to("root")
        assert path is not None
        assert len(path) == 1
        assert path[0].node_id == "root"

    def test_path_to_nonexistent(self):
        tree = _sample_tree()
        assert tree.path_to("missing") is None

    def test_find_node(self):
        tree = _sample_tree()
        found = tree.find_node("s1")
        assert found is not None
        assert found.title == "Definitions"

    def test_checksum_deterministic(self):
        tree = _sample_tree()
        c1 = tree.checksum
        c2 = tree.checksum
        assert c1 == c2
        assert len(c1) == 16

    def test_json_roundtrip(self):
        tree = _sample_tree()
        json_str = tree.to_json()
        restored = DocumentTree.from_json(json_str)
        assert restored.name == tree.name
        assert restored.node_count() == tree.node_count()
        assert restored.height() == tree.height()

    def test_dict_roundtrip(self):
        tree = _sample_tree()
        d = tree.to_dict()
        restored = DocumentTree.from_dict(d)
        assert restored.name == "contract_v2"
        assert restored.root.node_id == "root"

    def test_pretty_print(self):
        tree = _sample_tree()
        output = tree.pretty_print()
        assert "Master Agreement" in output
        assert "Definitions" in output
        assert "Liabilities" in output

    def test_repr(self):
        tree = _sample_tree()
        r = repr(tree)
        assert "contract_v2" in r
        assert "nodes=6" in r

    def test_single_node_tree(self):
        root = PixNode(node_id="only", title="Only Node")
        tree = DocumentTree("single", root=root)
        assert tree.height() == 0
        assert tree.node_count() == 1
        assert tree.leaf_count() == 1


# ═══════════════════════════════════════════════════════════════════
#  4. NAVIGATION STEP & REASONING PATH
# ═══════════════════════════════════════════════════════════════════


class TestNavigationStep:
    """NavigationStep — single evaluation record."""

    def test_creation(self):
        step = NavigationStep(
            node_id="n1", title="Test", score=0.85,
            reasoning="High relevance", depth=1,
        )
        assert step.node_id == "n1"
        assert step.score == 0.85
        assert step.depth == 1

    def test_to_dict(self):
        step = NavigationStep(
            node_id="n1", title="Test", score=0.8512345,
            reasoning="Match", depth=2,
        )
        d = step.to_dict()
        assert d["score"] == 0.8512  # rounded to 4 decimals
        assert d["node_id"] == "n1"


class TestReasoningPath:
    """ReasoningPath — ordered sequence of NavigationSteps (trail)."""

    def test_empty_path(self):
        path = ReasoningPath()
        assert path.depth == 0
        assert path.total_evaluations == 0
        assert path.selected_nodes == []

    def test_add_steps(self):
        path = ReasoningPath()
        path.add_step(NavigationStep("n1", "Root", 1.0, "Start", 0))
        path.add_step(NavigationStep("n2", "Child", 0.9, "Relevant", 1))
        assert path.total_evaluations == 2
        assert path.depth == 1
        assert path.selected_nodes == ["n1", "n2"]

    def test_summary_format(self):
        path = ReasoningPath()
        path.add_step(NavigationStep("n1", "Root", 1.0, "Start", 0))
        path.add_step(NavigationStep("n2", "Child", 0.7, "Some terms match", 1))
        summary = path.summary()
        assert "PIX Trail" in summary
        assert "Root" in summary
        assert "Child" in summary

    def test_to_dict(self):
        path = ReasoningPath()
        path.add_step(NavigationStep("n1", "Root", 1.0, "Start", 0))
        d = path.to_dict()
        assert "steps" in d
        assert d["total_evaluations"] == 1
        assert d["depth"] == 0


# ═══════════════════════════════════════════════════════════════════
#  5. THRESHOLD SCORER
# ═══════════════════════════════════════════════════════════════════


class TestThresholdScorer:
    """ThresholdScorer — keyword-overlap scorer for testing."""

    def test_full_overlap(self):
        scorer = ThresholdScorer()
        score, reason = scorer.score("legal terms", "Legal Terms", "Legal glossary")
        assert score >= 0.5

    def test_no_overlap(self):
        scorer = ThresholdScorer()
        score, reason = scorer.score("quantum physics", "Financial Terms", "Financial glossary")
        assert score == 0.0
        assert "No term overlap" in reason

    def test_empty_query(self):
        scorer = ThresholdScorer()
        score, reason = scorer.score("", "Title", "Summary")
        assert score == 0.0

    def test_partial_overlap(self):
        scorer = ThresholdScorer()
        score, reason = scorer.score("legal damages limit", "Direct Damages", "Damage limits")
        assert 0.0 < score <= 1.0

    def test_score_capped_at_one(self):
        scorer = ThresholdScorer()
        score, _ = scorer.score("hello", "hello hello hello", "hello")
        assert score <= 1.0


# ═══════════════════════════════════════════════════════════════════
#  6. PIX NAVIGATOR
# ═══════════════════════════════════════════════════════════════════


class TestPixNavigator:
    """PixNavigator — LLM-guided tree navigation."""

    def test_navigate_returns_result(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("legal terms")
        assert isinstance(result, NavigationResult)
        assert result.query == "legal terms"
        assert result.elapsed_secs >= 0

    def test_navigate_finds_leaves(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("legal terms definitions")
        assert len(result.leaves) > 0
        assert any(leaf.content for leaf in result.leaves)

    def test_navigate_with_trail(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("financial terms")
        assert result.path.total_evaluations > 0
        assert result.path.steps[0].node_id == "root"

    def test_navigate_depth_limit(self):
        tree = _sample_tree()
        config = NavigationConfig(max_depth=1)
        nav = PixNavigator(tree, ThresholdScorer(), config)
        result = nav.navigate("legal terms")
        assert all(leaf.depth <= 1 for leaf in result.leaves)

    def test_navigate_branch_limit(self):
        tree = _sample_tree()
        config = NavigationConfig(max_branch=1)
        nav = PixNavigator(tree, ThresholdScorer(), config)
        result = nav.navigate("legal terms glossary")
        # With branching=1, should explore only the top-scoring branch
        assert len(result.leaves) >= 1

    def test_navigate_high_threshold(self):
        tree = _sample_tree()
        config = NavigationConfig(threshold=0.99)
        nav = PixNavigator(tree, ThresholdScorer(), config)
        result = nav.navigate("legal terms definitions")
        # With high threshold (0.99), fallback path still selects
        # best-scoring branch; evaluations are recorded even if
        # no node meets the threshold exactly
        assert result.path.total_evaluations > 0

    def test_navigate_content_extraction(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("direct damages")
        contents = result.content
        assert isinstance(contents, list)

    def test_navigate_sources(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("damages")
        sources = result.sources
        assert isinstance(sources, list)

    def test_drill_specific_subtree(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.drill("s2", "direct damages limit")
        assert result.query == "direct damages limit"
        leaf_ids = [leaf.node_id for leaf in result.leaves]
        assert "s2a" in leaf_ids

    def test_drill_nonexistent_node(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        with pytest.raises(ValueError, match="not found"):
            nav.drill("nonexistent", "query")

    def test_drill_leaf_node(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.drill("s1a", "legal")
        assert len(result.leaves) == 1
        assert result.leaves[0].node_id == "s1a"

    def test_navigation_result_to_dict(self):
        tree = _sample_tree()
        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("test query")
        d = result.to_dict()
        assert d["query"] == "test query"
        assert "leaf_count" in d
        assert "path" in d
        assert "elapsed_secs" in d


# ═══════════════════════════════════════════════════════════════════
#  7. MARKDOWN EXTRACTOR
# ═══════════════════════════════════════════════════════════════════


class TestMarkdownExtractor:
    """MarkdownExtractor — structure detection from Markdown."""

    def test_basic_extraction(self):
        extractor = MarkdownExtractor()
        sections = extractor.extract(_sample_markdown())
        assert len(sections) > 0
        assert sections[0].title == "Master Agreement"

    def test_nested_headings(self):
        extractor = MarkdownExtractor()
        sections = extractor.extract(_sample_markdown())
        master = sections[0]
        assert len(master.subsections) >= 2

    def test_heading_levels(self):
        extractor = MarkdownExtractor()
        sections = extractor.extract("# H1\n## H2\n### H3\n")
        assert sections[0].level == 1
        assert sections[0].subsections[0].level == 2
        assert sections[0].subsections[0].subsections[0].level == 3

    def test_no_headings(self):
        extractor = MarkdownExtractor()
        sections = extractor.extract("Just plain text without any headings.")
        assert len(sections) == 1
        assert sections[0].title == "Document"

    def test_content_between_headings(self):
        md = "# Title\nContent here\n## Sub\nSub content"
        extractor = MarkdownExtractor()
        sections = extractor.extract(md)
        assert sections[0].content != ""

    def test_empty_document(self):
        extractor = MarkdownExtractor()
        sections = extractor.extract("")
        assert len(sections) == 1
        assert sections[0].title == "Document"

    def test_section_offsets(self):
        md = "# First\nContent 1\n# Second\nContent 2"
        extractor = MarkdownExtractor()
        sections = extractor.extract(md)
        assert sections[0].start_offset < sections[1].start_offset

    def test_full_content_with_subsections(self):
        section = Section(
            title="Parent", content="Parent content", level=1,
            subsections=[Section(title="Child", content="Child content", level=2)],
        )
        full = section.full_content
        assert "Parent content" in full
        assert "Child content" in full


# ═══════════════════════════════════════════════════════════════════
#  8. TRUNCATION SUMMARIZER
# ═══════════════════════════════════════════════════════════════════


class TestTruncationSummarizer:
    """TruncationSummarizer — simple test summarizer."""

    def test_short_content(self):
        summarizer = TruncationSummarizer()
        result = summarizer.summarize("Short text")
        assert result == "Short text"

    def test_long_content(self):
        summarizer = TruncationSummarizer()
        words = " ".join([f"word{i}" for i in range(100)])
        result = summarizer.summarize(words, max_words=10)
        assert result.endswith("...")
        assert len(result.split()) <= 11  # 10 words + "..."

    def test_exact_limit(self):
        summarizer = TruncationSummarizer()
        text = "one two three four five"
        result = summarizer.summarize(text, max_words=5)
        assert result == text


# ═══════════════════════════════════════════════════════════════════
#  9. PIX INDEXER
# ═══════════════════════════════════════════════════════════════════


class TestPixIndexer:
    """PixIndexer — document-to-tree construction."""

    def test_index_produces_tree(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract", source="test.md")
        assert isinstance(tree, DocumentTree)
        assert tree.name == "contract"
        assert tree.source == "test.md"

    def test_index_tree_structure(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract")
        assert tree.node_count() > 1
        assert tree.height() >= 1
        assert tree.leaf_count() >= 1

    def test_root_has_children(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract")
        assert tree.root.child_count > 0

    def test_leaf_nodes_have_content(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract")
        leaves = list(tree.leaves())
        assert len(leaves) > 0
        assert any(leaf.content for leaf in leaves)

    def test_node_ids_unique(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract")
        ids = [n.node_id for n in tree.dfs()]
        assert len(ids) == len(set(ids)), "Node IDs must be unique"

    def test_depth_limit(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer(), max_depth=2)
        tree = indexer.index(_sample_markdown(), name="contract")
        assert tree.height() <= 3

    def test_index_empty_document(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index("", name="empty")
        assert tree.node_count() >= 1

    def test_plain_text_document(self):
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index("Just plain text, no headings.", name="plain")
        assert tree.node_count() >= 2

    def test_index_and_navigate_integration(self):
        """End-to-end: index → navigate."""
        indexer = PixIndexer(MarkdownExtractor(), TruncationSummarizer())
        tree = indexer.index(_sample_markdown(), name="contract")

        nav = PixNavigator(tree, ThresholdScorer())
        result = nav.navigate("damages direct")
        assert isinstance(result, NavigationResult)
        assert result.path.total_evaluations > 0
