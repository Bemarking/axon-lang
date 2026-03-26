"""
AXON Engine — PIX Topological Indexer
=========================================
Image-to-tree indexation: transforms images into a PIX VisualTree
for navigational retrieval via topological structure.

DESIGN DECISION (for devs):
    This module is the VISUAL analogue of indexer.py:
        MarkdownExtractor  →  ImageExtractor
        TruncationSumm.    →  TopologicalSummarizer
        PixIndexer         →  TopologicalIndexer

    The pipeline: Image → Diffusion → Gabor → TDA → Quadtree → VisualTree

    Both indexers follow the same protocol-based architecture:
        Extractor (protocol) → Indexer → Tree

Architecture:
    ImageExtractor (StructureExtractor-like) → TopologicalIndexer → VisualTree

    The ImageExtractor defines how to detect structural regions in an image:
    1. Perona-Malik regularized diffusion (noise reduction, edge preservation)
    2. Gabor filter bank (orientation + frequency encoding)
    3. Persistent Homology on cubical complex (topological features)
    4. Adaptive quadtree partitioning (hierarchical regions)

Computational complexity:
    O(N · F + N·log(N)) for full pipeline
    where N = pixels (W×H), F = Gabor filters (N_λ × N_θ)

Dependencies:
    numpy — for array operations (required)
    scipy — optional, for convolution acceleration
    gudhi — optional, for production-grade PH computation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from axon.engine.pix.visual_tree import (
    VisualLocation,
    VisualNode,
    VisualTree,
    TopologicalSignature,
)


# ═══════════════════════════════════════════════════════════════════
#  VISUAL SECTION — analogue of Section
# ═══════════════════════════════════════════════════════════════════


@dataclass
class VisualSection:
    """A detected visual region with its computed features.

    FOR DEVS: This is the visual analogue of indexer.Section:
        Section.title          →  VisualSection.label
        Section.content        →  VisualSection.pixels (numpy array)
        Section.level          →  VisualSection.level (quadtree depth)
        Section.start_offset   →  VisualSection.bbox (VisualLocation)
        Section.subsections    →  VisualSection.subregions
    """

    label: str
    bbox: VisualLocation
    pixels: np.ndarray | None = None  # HxW float64 [0,1]
    level: int = 0
    signature: TopologicalSignature | None = None
    phase_energy: float = 0.0
    curvature_stats: dict[str, float] = field(default_factory=dict)
    subregions: list[VisualSection] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  PERONA-MALIK REGULARIZED DIFFUSION
# ═══════════════════════════════════════════════════════════════════


def _gaussian_kernel_2d(sigma: float, size: int | None = None) -> np.ndarray:
    """Generate a 2D Gaussian kernel for Catté regularization.

    The kernel G_σ is convolved with the image before computing
    the gradient for the diffusion coefficient. This is what makes
    the Perona-Malik equation well-posed (Catté et al. 1992).
    """
    if size is None:
        size = max(3, int(6 * sigma) | 1)  # Ensure odd
    if size % 2 == 0:
        size += 1
    half = size // 2
    x = np.arange(-half, half + 1, dtype=np.float64)
    y = x[:, np.newaxis]
    x = x[np.newaxis, :]
    kernel = np.exp(-(x**2 + y**2) / (2 * sigma**2))
    return kernel / kernel.sum()


def _convolve_2d(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """2D convolution with zero-padding (pure numpy, no scipy dependency)."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(image, ((ph, ph), (pw, pw)), mode="reflect")
    h, w = image.shape
    result = np.zeros_like(image)
    for i in range(h):
        for j in range(w):
            result[i, j] = np.sum(padded[i:i + kh, j:j + kw] * kernel)
    return result


def perona_malik_diffusion(
    image: np.ndarray,
    sigma: float = 1.0,
    lam: float = 0.1,
    iterations: int = 10,
    dt: float = 0.2,
) -> np.ndarray:
    """Regularized Perona-Malik anisotropic diffusion.

    FOR DEVS: This implements the PDE from paper_vision.md §2.2:
        ∂I/∂t = ∇·(c(||∇(G_σ * I)||) · ∇I)
        c(s) = 1 / (1 + (s/λ)²)

    The Catté regularization (σ > 0) ensures well-posedness.
    Without it (σ = 0), the equation is ill-posed (backward diffusion).

    Stability requires: dt ≤ 1 / (4 · max(c)) = 1/4 for 4-connectivity.
    We default to dt=0.2 which is safely below 0.25.

    Args:
        image:      Input image, float64 [0, 1], shape (H, W).
        sigma:      Gaussian smoothing σ for Catté regularization.
        lam:        Conductivity threshold λ (edges above lam are preserved).
        iterations: Number of diffusion time steps.
        dt:         Time step (must be ≤ 0.25 for stability).

    Returns:
        Diffused image, same shape as input.

    Complexity: O(W × H × iterations)
    """
    if dt > 0.25:
        raise ValueError(f"dt={dt} exceeds CFL stability limit 0.25")

    I = image.astype(np.float64).copy()
    gauss = _gaussian_kernel_2d(sigma)

    for _ in range(iterations):
        # Step 1: Regularized gradient (Catté)
        I_smooth = _convolve_2d(I, gauss)

        # Compute gradients (4-connectivity)
        grad_n = np.roll(I_smooth, -1, axis=0) - I_smooth  # north
        grad_s = np.roll(I_smooth, 1, axis=0) - I_smooth   # south
        grad_e = np.roll(I_smooth, -1, axis=1) - I_smooth  # east
        grad_w = np.roll(I_smooth, 1, axis=1) - I_smooth   # west

        # Step 2: Conductivity c(s) = 1 / (1 + (s/λ)²)
        c_n = 1.0 / (1.0 + (grad_n / lam) ** 2)
        c_s = 1.0 / (1.0 + (grad_s / lam) ** 2)
        c_e = 1.0 / (1.0 + (grad_e / lam) ** 2)
        c_w = 1.0 / (1.0 + (grad_w / lam) ** 2)

        # Step 3: Apply diffusion on ORIGINAL (non-smoothed) gradients
        nabla_n = np.roll(I, -1, axis=0) - I
        nabla_s = np.roll(I, 1, axis=0) - I
        nabla_e = np.roll(I, -1, axis=1) - I
        nabla_w = np.roll(I, 1, axis=1) - I

        I += dt * (c_n * nabla_n + c_s * nabla_s +
                   c_e * nabla_e + c_w * nabla_w)

    return np.clip(I, 0.0, 1.0)


# ═══════════════════════════════════════════════════════════════════
#  GABOR FILTER BANK
# ═══════════════════════════════════════════════════════════════════


def _gabor_kernel(
    wavelength: float,
    theta: float,
    sigma: float = 3.0,
    gamma: float = 0.5,
    psi: float = 0.0,
    size: int = 21,
) -> np.ndarray:
    """Generate a single 2D Gabor filter kernel.

    FROM PAPER §2.3:
        ψ(x,y) = exp(-(x'² + γ²y'²) / 2σ²) · exp(i(2πx'/λ + φ))

    This models V1 simple cell receptive fields (Hubel & Wiesel, 1962).
    Gabor functions achieve the Heisenberg uncertainty limit: Δx·Δξ ≥ 1/4π.
    """
    half = size // 2
    y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float64)

    # Rotated coordinates
    x_theta = x * np.cos(theta) + y * np.sin(theta)
    y_theta = -x * np.sin(theta) + y * np.cos(theta)

    # Gabor function (real part)
    envelope = np.exp(-(x_theta**2 + gamma**2 * y_theta**2) / (2 * sigma**2))
    carrier = np.cos(2 * np.pi * x_theta / wavelength + psi)

    return envelope * carrier


def gabor_filter_bank(
    image: np.ndarray,
    n_orientations: int = 8,
    n_frequencies: int = 8,
    freq_range: tuple[float, float] = (0.05, 0.4),
) -> tuple[np.ndarray, float]:
    """Apply a bank of Gabor filters and return energy + mean energy.

    FOR DEVS: The output is a phase energy map (max response across
    all filters at each pixel) and a scalar mean energy for the region.

    Args:
        image:          Input image (H, W), float64 [0, 1].
        n_orientations: Number of orientations θ ∈ {0, π/N, ..., (N-1)π/N}.
        n_frequencies:  Number of spatial frequencies.
        freq_range:     (min_freq, max_freq) in cycles/pixel.

    Returns:
        Tuple of (energy_map: (H,W), mean_energy: float).

    Complexity: O(W × H × N_θ × N_λ)
    """
    h, w = image.shape
    energy_map = np.zeros((h, w), dtype=np.float64)

    frequencies = np.linspace(freq_range[0], freq_range[1], n_frequencies)
    orientations = np.linspace(0, np.pi, n_orientations, endpoint=False)

    for freq in frequencies:
        wavelength = 1.0 / freq
        kernel_size = max(5, int(wavelength * 3) | 1)
        for theta in orientations:
            kernel = _gabor_kernel(
                wavelength=wavelength,
                theta=theta,
                sigma=wavelength * 0.56,
                size=kernel_size,
            )
            response = _convolve_2d(image, kernel)
            energy_map = np.maximum(energy_map, np.abs(response))

    mean_energy = float(np.mean(energy_map))
    return energy_map, mean_energy


# ═══════════════════════════════════════════════════════════════════
#  PERSISTENT HOMOLOGY ON CUBICAL COMPLEX
# ═══════════════════════════════════════════════════════════════════


def compute_persistence_cubical(
    image: np.ndarray,
    threshold: float = 0.05,
) -> TopologicalSignature:
    """Compute persistent homology on the cubical complex of an image.

    FOR DEVS: This is a pure-Python implementation for H_0 using
    Union-Find. For production, replace with GUDHI CubicalComplex
    or CubicalRipser for O(N log N) performance.

    FROM PAPER §2.4:
        The cubical complex K_I has O(N) simplices vs O(N³) for
        Vietoris-Rips, making it tractable for images.

    H_0 (connected components) via Union-Find:
        - Sort pixels by intensity (sublevel filtration)
        - For each pixel, union with lower-valued neighbors
        - Track birth/death of components

    Args:
        image:     Input image (H, W), float64.
        threshold: Persistence threshold τ for noise filtering.

    Returns:
        TopologicalSignature with H_0 pairs (and simplified H_1).

    Complexity: O(N · α(N)) for H_0 via Union-Find (Tarjan 1975)
    """
    h, w = image.shape
    n = h * w

    # ── Union-Find for H_0 ──
    parent = list(range(n))
    rank = [0] * n
    birth = [0.0] * n
    alive = [False] * n

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int, death_val: float) -> tuple[float, float] | None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return None  # already connected

        # The component born later dies (elder rule)
        if birth[ra] > birth[rb]:
            ra, rb = rb, ra
        # ra is elder (born earlier), rb dies
        pair = (birth[rb], death_val)

        if rank[ra] < rank[rb]:
            parent[ra] = rb
            birth[rb] = min(birth[ra], birth[rb])  # keep elder birth
            # Fix: elder should be root
            ra, rb = rb, ra
        elif rank[ra] > rank[rb]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

        return pair

    # Sort pixels by intensity (sublevel filtration)
    flat = image.flatten()
    sorted_indices = np.argsort(flat)

    pairs_h0: list[tuple[float, float]] = []
    neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for idx in sorted_indices:
        i, j = divmod(int(idx), w)
        alive[idx] = True
        birth[idx] = float(flat[idx])

        for di, dj in neighbors:
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w:
                nidx = ni * w + nj
                if alive[nidx]:
                    pair = union(idx, nidx, float(flat[idx]))
                    if pair is not None:
                        pairs_h0.append(pair)

    # Add surviving components (born but never die → death = max intensity)
    max_val = float(flat.max()) if n > 0 else 1.0
    roots = set()
    for idx in range(n):
        if alive[idx]:
            r = find(idx)
            if r not in roots:
                roots.add(r)
                # Only add if not already the global component
                if len(roots) > 1:
                    pairs_h0.append((birth[r], max_val))

    # ── Simplified H_1 estimation ──
    # True H_1 requires boundary matrix reduction. This heuristic
    # estimates loops from local intensity minima surrounded by ridges.
    pairs_h1: list[tuple[float, float]] = []
    # Detect potential loops via Euler characteristic heuristic:
    #   χ = V - E + F → β_1 = β_0 - χ + β_2
    # For a connected 2D region: β_1 ≈ 1 - χ (since β_2 = 0)
    # We defer full H_1 to GUDHI integration (TODO).

    return TopologicalSignature(
        pairs_h0=pairs_h0,
        pairs_h1=pairs_h1,
        threshold=threshold,
    )


# ═══════════════════════════════════════════════════════════════════
#  GAUSSIAN CURVATURE
# ═══════════════════════════════════════════════════════════════════


def compute_curvature_stats(image: np.ndarray) -> dict[str, float]:
    """Compute Gaussian curvature statistics of the image surface.

    FROM PAPER §2.1 Proposition 2.1:
        K(x,y) = det(Hess(I)) / (1 + ||∇I||²)²

    K > 0 → extrema (peaks/valleys)
    K < 0 → saddle points (edge crossings)
    K ≈ 0 → locally flat regions

    Returns dict with keys: min, max, mean, std
    """
    if image.size < 9:  # too small for gradients
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}

    # First derivatives
    Ix = np.gradient(image, axis=1)
    Iy = np.gradient(image, axis=0)

    # Second derivatives (Hessian)
    Ixx = np.gradient(Ix, axis=1)
    Iyy = np.gradient(Iy, axis=0)
    Ixy = np.gradient(Ix, axis=0)

    # Gaussian curvature: K = (Ixx·Iyy - Ixy²) / (1 + Ix² + Iy²)²
    grad_sq = Ix**2 + Iy**2
    denom = (1.0 + grad_sq) ** 2
    K = (Ixx * Iyy - Ixy**2) / (denom + 1e-10)

    return {
        "min": float(np.min(K)),
        "max": float(np.max(K)),
        "mean": float(np.mean(K)),
        "std": float(np.std(K)),
    }


# ═══════════════════════════════════════════════════════════════════
#  IMAGE EXTRACTOR — analogue of MarkdownExtractor
# ═══════════════════════════════════════════════════════════════════


class ImageExtractor:
    """Extract hierarchical visual structure from images.

    FOR DEVS: This is the visual analogue of MarkdownExtractor.

    MarkdownExtractor does:
        Markdown text → detect headings → list[Section]

    ImageExtractor does:
        Pixel array → diffusion → Gabor → TDA → quadtree → list[VisualSection]

    Both implement the same conceptual contract: take raw data and
    produce a hierarchical list of sections with content and metadata.

    Pipeline:
        1. Perona-Malik regularized diffusion → noise reduction
        2. Gabor filter bank → phase energy encoding
        3. Persistent Homology on cubical complex → topological features
        4. Adaptive quadtree → hierarchical region decomposition

    The quadtree splits regions that have high topological complexity
    (lots of features) and stops splitting simple regions.
    """

    def __init__(
        self,
        diffusion_sigma: float = 1.0,
        diffusion_lambda: float = 0.1,
        diffusion_iters: int = 10,
        gabor_orientations: int = 8,
        gabor_frequencies: int = 8,
        persistence_threshold: float = 0.05,
        min_region_size: int = 32,
        max_depth: int = 4,
    ) -> None:
        self._diff_sigma = diffusion_sigma
        self._diff_lambda = diffusion_lambda
        self._diff_iters = diffusion_iters
        self._gabor_orientations = gabor_orientations
        self._gabor_frequencies = gabor_frequencies
        self._persistence_threshold = persistence_threshold
        self._min_region_size = min_region_size
        self._max_depth = max_depth

    def extract(self, image: np.ndarray) -> list[VisualSection]:
        """Extract hierarchical visual sections from an image.

        Args:
            image: Input image as numpy array.
                   Shape (H, W) for grayscale or (H, W, 3) for RGB.
                   Values should be float64 in [0, 1].

        Returns:
            List of top-level VisualSection objects with nested subregions.
        """
        # Convert to grayscale if needed
        if image.ndim == 3:
            gray = np.mean(image, axis=2)
        else:
            gray = image.astype(np.float64)

        # Normalize to [0, 1]
        vmin, vmax = gray.min(), gray.max()
        if vmax > vmin:
            gray = (gray - vmin) / (vmax - vmin)

        h, w = gray.shape

        # Step 1: Diffusion
        filtered = perona_malik_diffusion(
            gray,
            sigma=self._diff_sigma,
            lam=self._diff_lambda,
            iterations=self._diff_iters,
        )

        # Step 2: Gabor energy
        energy_map, _ = gabor_filter_bank(
            filtered,
            n_orientations=self._gabor_orientations,
            n_frequencies=self._gabor_frequencies,
        )

        # Step 3: Build quadtree
        root_bbox = VisualLocation(x=0, y=0, w=w, h=h)
        sections = self._build_quadtree(
            filtered, energy_map, root_bbox, level=0,
        )

        return sections

    def _build_quadtree(
        self,
        image: np.ndarray,
        energy_map: np.ndarray,
        bbox: VisualLocation,
        level: int,
    ) -> list[VisualSection]:
        """Recursively partition image into quadtree regions.

        Split criteria: a region is split if it has high topological
        complexity (many persistence features) AND is large enough.
        """
        region = image[bbox.y:bbox.y + bbox.h, bbox.x:bbox.x + bbox.w]
        energy_region = energy_map[bbox.y:bbox.y + bbox.h, bbox.x:bbox.x + bbox.w]

        if region.size == 0:
            return []

        # Compute topological signature for this region
        signature = compute_persistence_cubical(
            region, threshold=self._persistence_threshold,
        )
        phase_energy = float(np.mean(energy_region))
        curvature = compute_curvature_stats(region)

        # Label based on position
        label = self._region_label(bbox, image.shape[1], image.shape[0], level)

        section = VisualSection(
            label=label,
            bbox=bbox,
            pixels=region,
            level=level,
            signature=signature,
            phase_energy=phase_energy,
            curvature_stats=curvature,
        )

        # Decide whether to split
        should_split = (
            level < self._max_depth
            and bbox.w >= self._min_region_size * 2
            and bbox.h >= self._min_region_size * 2
            and signature.betti_0 > 1  # more than one component → complex
        )

        if should_split:
            mid_x = bbox.x + bbox.w // 2
            mid_y = bbox.y + bbox.h // 2
            half_w = bbox.w // 2
            half_h = bbox.h // 2
            remaining_w = bbox.w - half_w
            remaining_h = bbox.h - half_h

            quadrants = [
                VisualLocation(x=bbox.x, y=bbox.y, w=half_w, h=half_h),        # NW
                VisualLocation(x=mid_x, y=bbox.y, w=remaining_w, h=half_h),    # NE
                VisualLocation(x=bbox.x, y=mid_y, w=half_w, h=remaining_h),    # SW
                VisualLocation(x=mid_x, y=mid_y, w=remaining_w, h=remaining_h), # SE
            ]

            for q_bbox in quadrants:
                sub_sections = self._build_quadtree(
                    image, energy_map, q_bbox, level + 1,
                )
                section.subregions.extend(sub_sections)

        return [section]

    @staticmethod
    def _region_label(
        bbox: VisualLocation, img_w: int, img_h: int, level: int,
    ) -> str:
        """Generate a human-readable label for a region."""
        if level == 0:
            return "Full Image"

        cx, cy = bbox.center
        h_pos = "West" if cx < img_w / 2 else "East"
        v_pos = "North" if cy < img_h / 2 else "South"
        return f"Region {v_pos}{h_pos} L{level}"


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SUMMARIZER — analogue of TruncationSummarizer
# ═══════════════════════════════════════════════════════════════════


class TopologicalSummarizer:
    """Compress TopologicalSignature into a navigational summary string.

    FOR DEVS: This is the visual analogue of TruncationSummarizer.

    TruncationSummarizer does:
        "Long text content..." → "First 50 words..."

    TopologicalSummarizer does:
        TopologicalSignature{pairs...} → "β0=3, β1=1, E=0.72"

    Both produce compressed summaries for tree navigation.
    The navigator reads summaries to decide which branches to explore.
    """

    def summarize(self, signature: TopologicalSignature, energy: float = 0.0) -> str:
        """Produce a navigational summary of the topological signature.

        Args:
            signature: TopologicalSignature to summarize.
            energy:    Mean Gabor phase energy for the region.

        Returns:
            Compressed summary string, e.g. "β0=3, β1=1, P=0.45, E=0.72"
        """
        parts = [
            f"β0={signature.betti_0}",
            f"β1={signature.betti_1}",
            f"P={signature.total_persistence:.2f}",
        ]
        if energy > 0:
            parts.append(f"E={energy:.2f}")
        return ", ".join(parts)


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL INDEXER — analogue of PixIndexer
# ═══════════════════════════════════════════════════════════════════


class TopologicalIndexer:
    """Orchestrates visual tree construction from images.

    FOR DEVS: This is the visual analogue of PixIndexer.

    PixIndexer does:
        MarkdownExtractor.extract(text) → list[Section]
        → recursively build PixNode tree → DocumentTree

    TopologicalIndexer does:
        ImageExtractor.extract(image) → list[VisualSection]
        → recursively build VisualNode tree → VisualTree

    Same orchestration pattern, different data types.

    Example:
        extractor = ImageExtractor(max_depth=3)
        summarizer = TopologicalSummarizer()
        indexer = TopologicalIndexer(extractor, summarizer)

        tree = indexer.index(
            image=my_image_array,     # numpy (H, W) or (H, W, 3)
            name="scene_001",
            source="photo.jpg"
        )

        # Now navigate the image like a document:
        from axon.engine.pix.navigator import PixNavigator
        nav = PixNavigator(tree_adapter, BettiScorer())
        result = nav.navigate("find complex structures")
    """

    def __init__(
        self,
        extractor: ImageExtractor | None = None,
        summarizer: TopologicalSummarizer | None = None,
        max_depth: int = 4,
    ) -> None:
        self._extractor = extractor or ImageExtractor()
        self._summarizer = summarizer or TopologicalSummarizer()
        self._max_depth = max_depth
        self._node_counter = 0

    def index(
        self,
        image: np.ndarray,
        name: str = "image",
        source: str = "",
    ) -> VisualTree:
        """Index an image into a PIX VisualTree.

        Args:
            image:  Numpy array (H, W) or (H, W, 3), float64 [0, 1].
            name:   Name for the visual tree.
            source: Source file path.

        Returns:
            A fully constructed VisualTree.
        """
        self._node_counter = 0

        # Determine image dimensions
        if image.ndim == 3:
            img_h, img_w = image.shape[:2]
        else:
            img_h, img_w = image.shape

        total_area = img_w * img_h

        # Extract visual structure
        sections = self._extractor.extract(image)

        # Build root
        root_sig = TopologicalSignature()
        if sections:
            root_sig = sections[0].signature or TopologicalSignature()
        root_summary = self._summarizer.summarize(root_sig)

        root = VisualNode(
            node_id=self._next_id(),
            label=name,
            betti_summary=root_summary,
            bbox=VisualLocation(x=0, y=0, w=img_w, h=img_h),
            area_fraction=1.0,
            depth=0,
        )

        # Build child nodes recursively
        for section in sections:
            for sub in section.subregions:
                child = self._build_node(sub, depth=1, total_area=total_area)
                root.add_child(child)

        # If no subregions, make root a leaf with signature
        if root.is_leaf and sections:
            root.signature = root_sig
            root.phase_energy = sections[0].phase_energy
            root.curvature_stats = sections[0].curvature_stats

        return VisualTree(
            name=name,
            root=root,
            source=source,
            image_width=img_w,
            image_height=img_h,
        )

    def _build_node(
        self,
        section: VisualSection,
        depth: int,
        total_area: int,
    ) -> VisualNode:
        """Recursively build a VisualNode from a VisualSection."""
        node_id = self._next_id()
        sig = section.signature or TopologicalSignature()
        summary = self._summarizer.summarize(sig, section.phase_energy)

        node = VisualNode(
            node_id=node_id,
            label=section.label,
            betti_summary=summary,
            bbox=section.bbox,
            phase_energy=section.phase_energy,
            curvature_stats=section.curvature_stats,
            area_fraction=section.bbox.area / total_area if total_area > 0 else 0.0,
            depth=depth,
        )

        if section.subregions and depth < self._max_depth:
            for sub in section.subregions:
                child = self._build_node(sub, depth + 1, total_area)
                node.add_child(child)
        else:
            # Leaf node: store full signature
            node.signature = sig

        return node

    def _next_id(self) -> str:
        """Generate a unique node ID (prefixed vpix_ to distinguish from pix_)."""
        self._node_counter += 1
        return f"vpix_{self._node_counter:04d}"
