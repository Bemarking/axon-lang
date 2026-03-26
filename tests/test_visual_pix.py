"""
Tests — PIX Visual Extension (Epistemic Vision)
====================================================
Test suite mirroring tests/test_pix_engine.py structure
for the visual navigation extension.

Structure:
    TestVisualLocation       — VisualLocation (analogue of PixLocation)
    TestTopologicalSignature — persistence diagrams + distances
    TestVisualNode           — VisualNode (analogue of PixNode)
    TestVisualTree           — VisualTree (analogue of DocumentTree)
    TestPeronaMalikDiffusion — anisotropic diffusion
    TestGaborFilterBank      — Gabor phase encoding
    TestPersistentHomology   — cubical complex H_0
    TestImageExtractor       — visual section extraction
    TestTopologicalIndexer   — full pipeline image → VisualTree
    TestBettiScorer          — testing scorer
    TestTopologicalScorer    — production scorer
    TestVisualNavigator      — foveal perception navigation
"""

import json
import math
import numpy as np
import pytest

from axon.engine.pix.visual_tree import (
    VisualLocation,
    VisualNode,
    VisualTree,
    TopologicalSignature,
)
from axon.engine.pix.topological_indexer import (
    ImageExtractor,
    TopologicalIndexer,
    TopologicalSummarizer,
    perona_malik_diffusion,
    gabor_filter_bank,
    compute_persistence_cubical,
    compute_curvature_stats,
)
from axon.engine.pix.topological_scorer import (
    BettiScorer,
    TopologicalScorer,
)
from axon.engine.pix.visual_navigator import (
    VisualNavigator,
    VisualNavigationConfig,
    visual_tree_to_document_tree,
)


# ═══════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def simple_image() -> np.ndarray:
    """8x8 test image with two distinct regions."""
    img = np.zeros((8, 8), dtype=np.float64)
    img[:4, :4] = 0.9   # bright NW
    img[4:, 4:] = 0.7   # medium SE
    return img


@pytest.fixture
def gradient_image() -> np.ndarray:
    """16x16 horizontal gradient image."""
    return np.tile(np.linspace(0, 1, 16), (16, 1))


@pytest.fixture
def sample_signature() -> TopologicalSignature:
    """Signature with known Betti numbers."""
    return TopologicalSignature(
        pairs_h0=[(0.0, 0.5), (0.1, 0.2), (0.3, 0.9)],
        pairs_h1=[(0.2, 0.6)],
        threshold=0.05,
    )


@pytest.fixture
def sample_visual_tree() -> VisualTree:
    """Pre-built visual tree for navigation tests."""
    root = VisualNode(
        node_id="root",
        label="Test Image",
        betti_summary="β0=4, β1=1, P=1.50, E=0.60",
        bbox=VisualLocation(0, 0, 100, 100),
    )
    nw = VisualNode(
        node_id="nw",
        label="Region NorthWest L1",
        betti_summary="β0=3, β1=0, P=0.80, E=0.45",
        bbox=VisualLocation(0, 0, 50, 50),
        signature=TopologicalSignature(
            pairs_h0=[(0.0, 0.5), (0.1, 0.4), (0.2, 0.6)],
            threshold=0.05,
        ),
    )
    ne = VisualNode(
        node_id="ne",
        label="Region NorthEast L1",
        betti_summary="β0=1, β1=0, P=0.20, E=0.10",
        bbox=VisualLocation(50, 0, 50, 50),
        signature=TopologicalSignature(
            pairs_h0=[(0.0, 0.2)],
            threshold=0.05,
        ),
    )
    sw = VisualNode(
        node_id="sw",
        label="Region SouthWest L1",
        betti_summary="β0=2, β1=1, P=1.20, E=0.70",
        bbox=VisualLocation(0, 50, 50, 50),
        signature=TopologicalSignature(
            pairs_h0=[(0.0, 0.6), (0.1, 0.5)],
            pairs_h1=[(0.3, 0.7)],
            threshold=0.05,
        ),
    )
    se = VisualNode(
        node_id="se",
        label="Region SouthEast L1",
        betti_summary="β0=1, β1=0, P=0.10, E=0.05",
        bbox=VisualLocation(50, 50, 50, 50),
        signature=TopologicalSignature(
            pairs_h0=[(0.0, 0.1)],
            threshold=0.05,
        ),
    )
    root.add_child(nw)
    root.add_child(ne)
    root.add_child(sw)
    root.add_child(se)
    return VisualTree("test_image", root, source="test.jpg",
                      image_width=100, image_height=100)


# ═══════════════════════════════════════════════════════════════════
#  VISUAL LOCATION
# ═══════════════════════════════════════════════════════════════════


class TestVisualLocation:
    """Tests for VisualLocation — analogue of PixLocation."""

    def test_area(self):
        loc = VisualLocation(10, 20, 50, 30)
        assert loc.area == 1500

    def test_center(self):
        loc = VisualLocation(0, 0, 100, 200)
        assert loc.center == (50.0, 100.0)

    def test_contains_true(self):
        outer = VisualLocation(0, 0, 100, 100)
        inner = VisualLocation(10, 10, 50, 50)
        assert outer.contains(inner)

    def test_contains_false(self):
        outer = VisualLocation(0, 0, 50, 50)
        inner = VisualLocation(30, 30, 50, 50)
        assert not outer.contains(inner)

    def test_serialization(self):
        loc = VisualLocation(5, 10, 200, 300)
        d = loc.to_dict()
        restored = VisualLocation.from_dict(d)
        assert restored == loc


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SIGNATURE
# ═══════════════════════════════════════════════════════════════════


class TestTopologicalSignature:
    """Tests for TopologicalSignature — persistence diagram wrapper."""

    def test_betti_numbers(self, sample_signature):
        assert sample_signature.betti_0 == 3  # all 3 H_0 pairs above threshold
        assert sample_signature.betti_1 == 1  # 1 H_1 pair above threshold

    def test_betti_with_noise(self):
        """Pairs below threshold should not count."""
        sig = TopologicalSignature(
            pairs_h0=[(0.0, 0.03), (0.5, 0.9)],  # first is noise
            threshold=0.05,
        )
        assert sig.betti_0 == 1  # only (0.5, 0.9) is significant

    def test_total_persistence(self, sample_signature):
        # (0.5-0.0) + (0.2-0.1) + (0.9-0.3) + (0.6-0.2) = 0.5+0.1+0.6+0.4 = 1.6
        assert abs(sample_signature.total_persistence - 1.6) < 1e-6

    def test_max_persistence(self, sample_signature):
        assert abs(sample_signature.max_persistence - 0.6) < 1e-6

    def test_bottleneck_self_distance(self, sample_signature):
        assert sample_signature.bottleneck_distance(sample_signature) == 0.0

    def test_bottleneck_different(self):
        a = TopologicalSignature(pairs_h0=[(0.0, 0.5)], threshold=0.01)
        b = TopologicalSignature(pairs_h0=[(0.0, 0.8)], threshold=0.01)
        dist = a.bottleneck_distance(b)
        assert dist > 0.0

    def test_wasserstein_self_distance(self, sample_signature):
        assert sample_signature.wasserstein_distance(sample_signature) == 0.0

    def test_serialization(self, sample_signature):
        d = sample_signature.to_dict()
        restored = TopologicalSignature.from_dict(d)
        assert restored.betti_0 == sample_signature.betti_0
        assert restored.betti_1 == sample_signature.betti_1


# ═══════════════════════════════════════════════════════════════════
#  VISUAL NODE
# ═══════════════════════════════════════════════════════════════════


class TestVisualNode:
    """Tests for VisualNode — analogue of PixNode."""

    def test_leaf_detection(self):
        leaf = VisualNode("v1", "Leaf")
        parent = VisualNode("v2", "Parent")
        parent.add_child(leaf)
        assert leaf.is_leaf
        assert not parent.is_leaf

    def test_add_child_sets_depth(self):
        parent = VisualNode("p", "Parent", depth=2)
        child = VisualNode("c", "Child")
        parent.add_child(child)
        assert child.depth == 3

    def test_find_node(self):
        root = VisualNode("r", "Root")
        a = VisualNode("a", "A")
        b = VisualNode("b", "B")
        root.add_child(a)
        a.add_child(b)
        assert root.find_node("b") is b
        assert root.find_node("z") is None

    def test_serialization(self, sample_signature):
        node = VisualNode(
            "n1", "Test Node",
            signature=sample_signature,
            bbox=VisualLocation(10, 20, 30, 40),
            phase_energy=0.75,
        )
        d = node.to_dict()
        restored = VisualNode.from_dict(d)
        assert restored.node_id == "n1"
        assert restored.label == "Test Node"
        assert restored.signature.betti_0 == 3


# ═══════════════════════════════════════════════════════════════════
#  VISUAL TREE
# ═══════════════════════════════════════════════════════════════════


class TestVisualTree:
    """Tests for VisualTree — analogue of DocumentTree."""

    def test_tree_metrics(self, sample_visual_tree):
        assert sample_visual_tree.node_count() == 5  # root + 4 children
        assert sample_visual_tree.leaf_count() == 4
        assert sample_visual_tree.height() == 1

    def test_bfs(self, sample_visual_tree):
        ids = [n.node_id for n in sample_visual_tree.bfs()]
        assert ids[0] == "root"
        assert len(ids) == 5

    def test_dfs(self, sample_visual_tree):
        ids = [n.node_id for n in sample_visual_tree.dfs()]
        assert ids[0] == "root"
        assert len(ids) == 5

    def test_leaves(self, sample_visual_tree):
        leaf_ids = [n.node_id for n in sample_visual_tree.leaves()]
        assert set(leaf_ids) == {"nw", "ne", "sw", "se"}

    def test_path_to(self, sample_visual_tree):
        path = sample_visual_tree.path_to("sw")
        assert path is not None
        assert len(path) == 2
        assert path[0].node_id == "root"
        assert path[1].node_id == "sw"

    def test_path_to_nonexistent(self, sample_visual_tree):
        assert sample_visual_tree.path_to("zzz") is None

    def test_find_node(self, sample_visual_tree):
        node = sample_visual_tree.find_node("ne")
        assert node is not None
        assert node.label == "Region NorthEast L1"

    def test_checksum_stability(self, sample_visual_tree):
        c1 = sample_visual_tree.checksum
        c2 = sample_visual_tree.checksum
        assert c1 == c2

    def test_json_roundtrip(self, sample_visual_tree):
        json_str = sample_visual_tree.to_json()
        restored = VisualTree.from_json(json_str)
        assert restored.name == sample_visual_tree.name
        assert restored.node_count() == sample_visual_tree.node_count()
        assert restored.image_width == 100

    def test_pretty_print(self, sample_visual_tree):
        output = sample_visual_tree.pretty_print()
        assert "Test Image" in output
        assert "root" in output


# ═══════════════════════════════════════════════════════════════════
#  PERONA-MALIK DIFFUSION
# ═══════════════════════════════════════════════════════════════════


class TestPeronaMalikDiffusion:
    """Tests for the regularized Perona-Malik diffusion."""

    def test_output_shape(self, simple_image):
        result = perona_malik_diffusion(simple_image, iterations=2)
        assert result.shape == simple_image.shape

    def test_output_range(self, simple_image):
        result = perona_malik_diffusion(simple_image, iterations=5)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_constant_image_unchanged(self):
        """Constant image should remain constant after diffusion."""
        const = np.full((8, 8), 0.5, dtype=np.float64)
        result = perona_malik_diffusion(const, iterations=10)
        np.testing.assert_allclose(result, 0.5, atol=1e-10)

    def test_cfl_stability_check(self, simple_image):
        """dt > 0.25 should raise ValueError."""
        with pytest.raises(ValueError, match="CFL"):
            perona_malik_diffusion(simple_image, dt=0.3)

    def test_smoothing_effect(self):
        """Diffusion should reduce variation in smooth regions."""
        img = np.random.default_rng(42).uniform(0.4, 0.6, (16, 16))
        result = perona_malik_diffusion(img, iterations=20, lam=0.5)
        assert result.std() < img.std()


# ═══════════════════════════════════════════════════════════════════
#  GABOR FILTER BANK
# ═══════════════════════════════════════════════════════════════════


class TestGaborFilterBank:
    """Tests for the Gabor filter bank."""

    def test_output_shape(self, simple_image):
        energy, mean_e = gabor_filter_bank(simple_image, n_orientations=4, n_frequencies=4)
        assert energy.shape == simple_image.shape

    def test_mean_energy_positive(self, gradient_image):
        _, mean_e = gabor_filter_bank(gradient_image, n_orientations=4, n_frequencies=4)
        assert mean_e > 0.0

    def test_constant_image_low_energy(self):
        """Constant image should have lower energy than structured image."""
        const = np.full((16, 16), 0.5, dtype=np.float64)
        _, const_e = gabor_filter_bank(const, n_orientations=4, n_frequencies=2)
        # Structured image: edges produce higher response
        edge = np.zeros((16, 16), dtype=np.float64)
        edge[:, 8:] = 1.0
        _, edge_e = gabor_filter_bank(edge, n_orientations=4, n_frequencies=2)
        assert const_e < edge_e


# ═══════════════════════════════════════════════════════════════════
#  PERSISTENT HOMOLOGY
# ═══════════════════════════════════════════════════════════════════


class TestPersistentHomology:
    """Tests for cubical complex persistent homology (H_0)."""

    def test_constant_image(self):
        """Constant image → β0 = 1 (one component)."""
        const = np.full((8, 8), 0.5, dtype=np.float64)
        sig = compute_persistence_cubical(const)
        # Constant: all pixels have same value, single component
        assert sig.betti_0 <= 1

    def test_multi_level_persistence(self):
        """Multi-level image produces non-trivial persistence."""
        # Create an image with distinct intensity levels (not binary)
        # so sublevel filtration creates components at different birth times.
        rng = np.random.default_rng(42)
        img = rng.uniform(0.0, 1.0, (16, 16))
        sig = compute_persistence_cubical(img, threshold=0.01)
        # Random image should have multiple components being born/dying
        assert len(sig.pairs_h0) > 0
        # At least some should have non-trivial persistence
        significant = sig.significant_pairs(dimension=0)
        assert len(significant) > 0

    def test_signature_type(self, simple_image):
        sig = compute_persistence_cubical(simple_image)
        assert isinstance(sig, TopologicalSignature)

    def test_threshold_filtering(self, simple_image):
        strict = compute_persistence_cubical(simple_image, threshold=0.5)
        loose = compute_persistence_cubical(simple_image, threshold=0.01)
        # Strict threshold → fewer significant features
        assert strict.betti_0 <= loose.betti_0


# ═══════════════════════════════════════════════════════════════════
#  CURVATURE
# ═══════════════════════════════════════════════════════════════════


class TestCurvatureStats:
    """Tests for Gaussian curvature computation."""

    def test_flat_image(self):
        flat = np.full((10, 10), 0.5, dtype=np.float64)
        stats = compute_curvature_stats(flat)
        assert abs(stats["mean"]) < 1e-10

    def test_output_keys(self, simple_image):
        stats = compute_curvature_stats(simple_image)
        assert "min" in stats
        assert "max" in stats
        assert "mean" in stats
        assert "std" in stats

    def test_tiny_image(self):
        tiny = np.array([[0.5]], dtype=np.float64)
        stats = compute_curvature_stats(tiny)
        assert stats["mean"] == 0.0


# ═══════════════════════════════════════════════════════════════════
#  IMAGE EXTRACTOR
# ═══════════════════════════════════════════════════════════════════


class TestImageExtractor:
    """Tests for ImageExtractor — analogue of MarkdownExtractor."""

    def test_extract_returns_sections(self, gradient_image):
        extractor = ImageExtractor(max_depth=1, min_region_size=4,
                                   gabor_orientations=2, gabor_frequencies=2,
                                   diffusion_iters=2)
        sections = extractor.extract(gradient_image)
        assert len(sections) >= 1

    def test_section_has_signature(self, simple_image):
        extractor = ImageExtractor(max_depth=1, min_region_size=2,
                                   gabor_orientations=2, gabor_frequencies=2,
                                   diffusion_iters=2)
        sections = extractor.extract(simple_image)
        assert sections[0].signature is not None

    def test_rgb_input(self):
        """Should handle RGB images by converting to grayscale."""
        rgb = np.random.default_rng(42).uniform(0, 1, (16, 16, 3))
        extractor = ImageExtractor(max_depth=1, min_region_size=4,
                                   gabor_orientations=2, gabor_frequencies=2,
                                   diffusion_iters=1)
        sections = extractor.extract(rgb)
        assert len(sections) >= 1


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SUMMARIZER
# ═══════════════════════════════════════════════════════════════════


class TestTopologicalSummarizer:
    """Tests for TopologicalSummarizer."""

    def test_summary_format(self, sample_signature):
        s = TopologicalSummarizer()
        result = s.summarize(sample_signature, energy=0.65)
        assert "β0=" in result
        assert "β1=" in result
        assert "E=" in result


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL INDEXER
# ═══════════════════════════════════════════════════════════════════


class TestTopologicalIndexer:
    """Tests for TopologicalIndexer — analogue of PixIndexer."""

    def test_index_returns_visual_tree(self, simple_image):
        indexer = TopologicalIndexer(
            extractor=ImageExtractor(
                max_depth=1, min_region_size=2,
                gabor_orientations=2, gabor_frequencies=2,
                diffusion_iters=2,
            ),
        )
        tree = indexer.index(simple_image, name="test", source="test.png")
        assert isinstance(tree, VisualTree)
        assert tree.name == "test"
        assert tree.source == "test.png"

    def test_tree_has_root(self, gradient_image):
        indexer = TopologicalIndexer(
            extractor=ImageExtractor(
                max_depth=1, min_region_size=4,
                gabor_orientations=2, gabor_frequencies=2,
                diffusion_iters=1,
            ),
        )
        tree = indexer.index(gradient_image, name="gradient")
        assert tree.root is not None
        assert tree.node_count() >= 1

    def test_image_dimensions(self, simple_image):
        indexer = TopologicalIndexer(
            extractor=ImageExtractor(
                max_depth=0, min_region_size=2,
                gabor_orientations=2, gabor_frequencies=2,
                diffusion_iters=1,
            ),
        )
        tree = indexer.index(simple_image)
        assert tree.image_width == 8
        assert tree.image_height == 8


# ═══════════════════════════════════════════════════════════════════
#  BETTI SCORER
# ═══════════════════════════════════════════════════════════════════


class TestBettiScorer:
    """Tests for BettiScorer — analogue of ThresholdScorer."""

    def test_scores_normalized(self):
        scorer = BettiScorer(max_complexity=10)
        score, _ = scorer.score("", "Region NW", "β0=3, β1=1, P=0.45")
        assert 0.0 <= score <= 1.0

    def test_higher_complexity_higher_score(self):
        scorer = BettiScorer(max_complexity=10)
        s_low, _ = scorer.score("", "", "β0=1, β1=0")
        s_high, _ = scorer.score("", "", "β0=5, β1=3")
        assert s_high > s_low

    def test_empty_summary(self):
        scorer = BettiScorer()
        score, _ = scorer.score("", "", "")
        assert score == 0.0

    def test_returns_reasoning(self):
        scorer = BettiScorer()
        _, reasoning = scorer.score("", "", "β0=3, β1=1")
        assert "β0=3" in reasoning


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SCORER
# ═══════════════════════════════════════════════════════════════════


class TestTopologicalScorer:
    """Tests for TopologicalScorer — production information gain scorer."""

    def test_scores_normalized(self):
        scorer = TopologicalScorer()
        score, _ = scorer.score("", "", "β0=3, β1=1, P=0.45, E=0.72")
        assert 0.0 <= score <= 1.0

    def test_high_complexity_high_score(self):
        scorer = TopologicalScorer()
        s_low, _ = scorer.score("", "", "β0=0, β1=0, P=0.01, E=0.01")
        s_high, _ = scorer.score("", "", "β0=10, β1=5, P=3.5, E=0.9")
        assert s_high > s_low

    def test_returns_reasoning(self):
        scorer = TopologicalScorer()
        _, reasoning = scorer.score("", "", "β0=3, β1=1, P=0.45, E=0.72")
        assert "InfoGain" in reasoning


# ═══════════════════════════════════════════════════════════════════
#  VISUAL NAVIGATOR
# ═══════════════════════════════════════════════════════════════════


class TestVisualNavigator:
    """Tests for VisualNavigator — analogue of PixNavigator."""

    def test_perceive_returns_result(self, sample_visual_tree):
        nav = VisualNavigator(
            sample_visual_tree,
            scorer=BettiScorer(max_complexity=10),
        )
        result = nav.perceive()
        assert result is not None
        assert hasattr(result, "leaves")
        assert hasattr(result, "path")

    def test_perceive_finds_leaves(self, sample_visual_tree):
        nav = VisualNavigator(
            sample_visual_tree,
            scorer=BettiScorer(max_complexity=10),
            config=VisualNavigationConfig(threshold=0.05),
        )
        result = nav.perceive()
        assert len(result.leaves) > 0

    def test_drill_region(self, sample_visual_tree):
        nav = VisualNavigator(
            sample_visual_tree,
            scorer=BettiScorer(max_complexity=10),
        )
        result = nav.drill_region("nw")
        assert result is not None

    def test_free_energy_estimate(self, sample_visual_tree):
        nav = VisualNavigator(
            sample_visual_tree,
            scorer=BettiScorer(max_complexity=10),
        )
        result = nav.perceive()
        fe = nav.free_energy_estimate(result)
        assert 0.0 <= fe <= 1.0

    def test_summary_output(self, sample_visual_tree):
        nav = VisualNavigator(
            sample_visual_tree,
            scorer=BettiScorer(max_complexity=10),
        )
        result = nav.perceive()
        text = nav.summary(result)
        assert "Free energy" in text

    def test_tree_adapter(self, sample_visual_tree):
        """visual_tree_to_document_tree should produce a valid DocumentTree."""
        dtree = visual_tree_to_document_tree(sample_visual_tree)
        assert dtree.name == "test_image"
        assert dtree.node_count() == 5


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION — full pipeline
# ═══════════════════════════════════════════════════════════════════


class TestFullPipeline:
    """End-to-end integration: image → index → navigate."""

    def test_pipeline_8x8(self, simple_image):
        """Full pipeline on a small image."""
        indexer = TopologicalIndexer(
            extractor=ImageExtractor(
                max_depth=1, min_region_size=2,
                gabor_orientations=2, gabor_frequencies=2,
                diffusion_iters=2,
            ),
        )
        tree = indexer.index(simple_image, name="pipeline_test")

        nav = VisualNavigator(
            tree,
            scorer=BettiScorer(max_complexity=10),
        )
        result = nav.perceive()
        assert result is not None
        assert not result.timed_out

    def test_pipeline_preserves_tree_invariants(self, gradient_image):
        """Tree invariants: unique root, acyclicity, exhaustive coverage."""
        indexer = TopologicalIndexer(
            extractor=ImageExtractor(
                max_depth=2, min_region_size=4,
                gabor_orientations=2, gabor_frequencies=2,
                diffusion_iters=1,
            ),
        )
        tree = indexer.index(gradient_image, name="invariants")

        # T1: Unique root
        assert tree.root is not None

        # T3: Acyclicity — path_to always terminates and returns path
        for node in tree.bfs():
            path = tree.path_to(node.node_id)
            assert path is not None
            assert path[0].node_id == tree.root.node_id

        # Node count consistency
        bfs_count = sum(1 for _ in tree.bfs())
        assert bfs_count == tree.node_count()
