"""
AXON Engine — PEM Density Matrix Module
==========================================
§2 — Epistemic Conditioning: Quantum Cognitive Probability.

Replaces classical Bayesian inference (softmax) with quantum
cognitive probability theory using density operators and Born's
rule projections.

Core equation (Eq. 2 from the PEM paper):

    P(D | ψ) = Tr(Π_D · ρ_ψ · Π_D)

where:
    ρ_ψ ∈ ℝ^{k×k}  — density matrix (pos. semi-definite, Tr(ρ) = 1)
    Π_D ∈ ℝ^{k×k}  — orthogonal projector for evidence D

Key property: NON-COMMUTATIVITY

    Π_A · Π_B ≠ Π_B · Π_A

    The order in which evidence is presented CHANGES the final
    psychological state. This matches empirical findings from
    cognitive science (order effects, conjunction fallacy).

Design decision (v0.18.0):
    Real-valued density matrices ℝ^{k×k} instead of ℂ^{k×k}.
    This preserves non-commutativity (the key insight) while
    avoiding complex arithmetic. Upgrade path to ℂ is trivial
    (replace float → complex, transpose → conjugate transpose).

Implementation notes:
    - Pure Python matrix operations (no numpy dependency)
    - k=5 default dimensionality → 5×5 matrices (cheap)
    - All operations maintain PSD + Tr(ρ) = 1 invariants

Mathematical references:
    - Busemeyer & Bruza (2012), "Quantum Models of Cognition and Decision"
    - See docs/psychological_epistemic_modeling.md §2

"""

from __future__ import annotations

import math
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  PURE PYTHON MATRIX OPERATIONS — For k×k real matrices
# ═══════════════════════════════════════════════════════════════════


def _zeros(k: int) -> list[list[float]]:
    """Create a k×k zero matrix."""
    return [[0.0] * k for _ in range(k)]


def _identity(k: int) -> list[list[float]]:
    """Create a k×k identity matrix."""
    m = _zeros(k)
    for i in range(k):
        m[i][i] = 1.0
    return m


def _trace(m: list[list[float]]) -> float:
    """Compute Tr(M) = Σ M[i][i]."""
    return sum(m[i][i] for i in range(len(m)))


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Compute A · B for k×k matrices."""
    k = len(a)
    result = _zeros(k)
    for i in range(k):
        for j in range(k):
            s = 0.0
            for l in range(k):
                s += a[i][l] * b[l][j]
            result[i][j] = s
    return result


def _mat_add(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Compute A + B element-wise."""
    k = len(a)
    return [[a[i][j] + b[i][j] for j in range(k)] for i in range(k)]


def _mat_scale(m: list[list[float]], scalar: float) -> list[list[float]]:
    """Compute scalar · M."""
    k = len(m)
    return [[m[i][j] * scalar for j in range(k)] for i in range(k)]


def _transpose(m: list[list[float]]) -> list[list[float]]:
    """Compute M^T."""
    k = len(m)
    return [[m[j][i] for j in range(k)] for i in range(k)]


def _outer_product(v: list[float]) -> list[list[float]]:
    """Compute |v⟩⟨v| = v · vᵀ (outer product)."""
    k = len(v)
    return [[v[i] * v[j] for j in range(k)] for i in range(k)]


def _mat_copy(m: list[list[float]]) -> list[list[float]]:
    """Deep copy a matrix."""
    return [row[:] for row in m]


def _is_symmetric(m: list[list[float]], tol: float = 1e-10) -> bool:
    """Check if M is symmetric: M[i][j] ≈ M[j][i]."""
    k = len(m)
    for i in range(k):
        for j in range(i + 1, k):
            if abs(m[i][j] - m[j][i]) > tol:
                return False
    return True


def _symmetrize(m: list[list[float]]) -> list[list[float]]:
    """Force symmetry: M → (M + Mᵀ) / 2."""
    k = len(m)
    return [
        [(m[i][j] + m[j][i]) / 2.0 for j in range(k)]
        for i in range(k)
    ]


def _eigenvalues_2x2(m: list[list[float]]) -> list[float]:
    """Exact eigenvalues for 2×2 symmetric matrix."""
    a, b = m[0][0], m[0][1]
    d = m[1][1]
    # Characteristic polynomial: λ² - (a+d)λ + (ad - b²) = 0
    tr = a + d
    det = a * d - b * b
    disc = tr * tr - 4 * det
    if disc < 0:
        disc = 0.0  # Numerical correction for PSD
    sqrt_disc = math.sqrt(disc)
    return [(tr + sqrt_disc) / 2, (tr - sqrt_disc) / 2]


def _eigenvalues_power_method(
    m: list[list[float]],
    max_iter: int = 100,
    tol: float = 1e-10,
) -> list[float]:
    """Compute eigenvalues via deflation with power iteration.

    For small k (≤ 5), this is accurate and efficient.
    """
    k = len(m)
    if k == 0:
        return []
    if k == 1:
        return [m[0][0]]
    if k == 2:
        return _eigenvalues_2x2(m)

    eigenvalues: list[float] = []
    work = _mat_copy(m)

    for _ in range(k):
        # Power iteration for dominant eigenvalue
        v = [1.0 / math.sqrt(k)] * k
        eigenvalue = 0.0

        for _it in range(max_iter):
            # w = M · v
            w = [sum(work[i][j] * v[j] for j in range(k)) for i in range(k)]
            # Rayleigh quotient: λ = vᵀ·w / vᵀ·v
            new_eigenvalue = sum(v[i] * w[i] for i in range(k))
            # Normalize w
            norm = math.sqrt(sum(x * x for x in w))
            if norm < tol:
                eigenvalue = 0.0
                break
            v = [x / norm for x in w]
            if abs(new_eigenvalue - eigenvalue) < tol:
                eigenvalue = new_eigenvalue
                break
            eigenvalue = new_eigenvalue

        eigenvalues.append(eigenvalue)

        # Deflate: M' = M - λ · v · vᵀ
        outer = _outer_product(v)
        for i in range(k):
            for j in range(k):
                work[i][j] -= eigenvalue * outer[i][j]

    return eigenvalues


# ═══════════════════════════════════════════════════════════════════
#  DENSITY MATRIX — ρ_ψ ∈ ℝ^{k×k}
# ═══════════════════════════════════════════════════════════════════


class DensityMatrix:
    """ρ_ψ — density operator representing cognitive-epistemic state.

    From §2 of the PEM paper:
        ρ_ψ ∈ ℝ^{k×k}, positive semi-definite, Tr(ρ) = 1

    A density matrix generalizes a probability vector. While a
    classical probability vector can only represent one hypothesis
    at a time, a density matrix can represent:
        - Pure states: |ψ⟩⟨ψ| (definite cognitive configuration)
        - Mixed states: Σ pᵢ |ψᵢ⟩⟨ψᵢ| (epistemic uncertainty)
        - Superposition: off-diagonal coherence terms

    The off-diagonal terms are crucial: they encode correlations
    between cognitive dimensions that classical vectors cannot.

    Invariants (enforced):
        1. Symmetry:  ρ = ρᵀ
        2. Trace-one: Tr(ρ) = 1
        3. PSD:       all eigenvalues ≥ 0

    Args:
        matrix: k×k list-of-lists representing the density matrix.
                Must be symmetric, PSD, and trace-one.
    """

    def __init__(self, matrix: list[list[float]]) -> None:
        self._k = len(matrix)
        if self._k == 0:
            raise ValueError("Density matrix cannot be empty")

        # Verify square
        for row in matrix:
            if len(row) != self._k:
                raise ValueError(
                    f"Matrix must be square, got {self._k}×{len(row)}"
                )

        # Force symmetry (numerical stability)
        self._matrix = _symmetrize(matrix)

        # Verify trace ≈ 1
        tr = _trace(self._matrix)
        if abs(tr - 1.0) > 1e-6:
            raise ValueError(
                f"Density matrix must have Tr(ρ) = 1, got {tr:.6f}"
            )

    # ── Properties ────────────────────────────────────────────────

    @property
    def k(self) -> int:
        """Dimensionality of the Hilbert space."""
        return self._k

    @property
    def matrix(self) -> list[list[float]]:
        """The raw k×k matrix (copy)."""
        return _mat_copy(self._matrix)

    # ── Factory methods ───────────────────────────────────────────

    @staticmethod
    def from_pure_state(state_vector: list[float]) -> DensityMatrix:
        """Create pure state: ρ = |ψ⟩⟨ψ|.

        A pure state represents complete certainty about the
        cognitive configuration. It has exactly one eigenvalue = 1
        and all others = 0.

        Args:
            state_vector: Normalized vector |ψ⟩ (must have ||ψ|| = 1).
        """
        norm = math.sqrt(sum(x * x for x in state_vector))
        if norm < 1e-10:
            raise ValueError("State vector cannot be zero")
        # Normalize
        normalized = [x / norm for x in state_vector]
        return DensityMatrix(_outer_product(normalized))

    @staticmethod
    def from_cognitive_state(
        values: list[float],
    ) -> DensityMatrix:
        """Convert cognitive state values to a density matrix.

        Maps the k-dimensional cognitive state to a pure-state
        density matrix ρ = |ψ⟩⟨ψ| where |ψ⟩ is the normalized
        cognitive state vector.

        Args:
            values: The cognitive state vector (will be normalized).
        """
        return DensityMatrix.from_pure_state(values)

    @staticmethod
    def maximally_mixed(k: int) -> DensityMatrix:
        """Create maximally mixed state: ρ = I/k.

        Represents maximum ignorance — no information about
        the cognitive state. Von Neumann entropy = log(k).
        """
        m = _zeros(k)
        inv_k = 1.0 / k
        for i in range(k):
            m[i][i] = inv_k
        return DensityMatrix(m)

    @staticmethod
    def from_mixture(
        states: list[tuple[float, list[float]]],
    ) -> DensityMatrix:
        """Create mixed state: ρ = Σ pᵢ |ψᵢ⟩⟨ψᵢ|.

        Represents classical uncertainty over pure states.

        Args:
            states: List of (probability, state_vector) pairs.
                    Probabilities must sum to 1.
        """
        if not states:
            raise ValueError("Cannot create mixture from empty list")

        p_sum = sum(p for p, _ in states)
        if abs(p_sum - 1.0) > 1e-6:
            raise ValueError(
                f"Mixture probabilities must sum to 1, got {p_sum:.6f}"
            )

        k = len(states[0][1])
        result = _zeros(k)

        for prob, vec in states:
            norm = math.sqrt(sum(x * x for x in vec))
            if norm < 1e-10:
                continue
            normalized = [x / norm for x in vec]
            outer = _outer_product(normalized)
            for i in range(k):
                for j in range(k):
                    result[i][j] += prob * outer[i][j]

        return DensityMatrix(result)

    # ── Quantum operations ────────────────────────────────────────

    def project(self, projector: list[list[float]]) -> DensityMatrix:
        """Apply Lüders projection: ρ' = Π·ρ·Π / Tr(Π·ρ·Π).

        This is the quantum update rule for evidence assimilation.
        The key property is that projections do NOT commute:

            project(Π_A).project(Π_B) ≠ project(Π_B).project(Π_A)

        Args:
            projector: Π — orthogonal projector (Π² = Π, Πᵀ = Π).

        Returns:
            New density matrix after Lüders projection.

        Raises:
            ValueError: If projection probability is zero
                        (evidence is impossible given state).
        """
        # Π · ρ · Π
        temp = _mat_mul(projector, self._matrix)
        projected = _mat_mul(temp, projector)

        # Tr(Π · ρ · Π) — the Born probability
        tr = _trace(projected)
        if tr < 1e-12:
            raise ValueError(
                "Projection probability is zero — evidence is "
                "impossible given the current state"
            )

        # Normalize: ρ' = Π·ρ·Π / Tr(Π·ρ·Π)
        normalized = _mat_scale(projected, 1.0 / tr)
        return DensityMatrix(normalized)

    def born_probability(self, projector: list[list[float]]) -> float:
        """P(D | ψ) = Tr(Π_D · ρ_ψ · Π_D) — Born's rule.

        Computes the probability of observing evidence D given
        the current cognitive state.

        This is the quantum analog of P(D | ψ) in classical
        Bayesian inference, but with the crucial difference that
        the order of previous projections affects this probability.

        Args:
            projector: Π_D — projector for evidence D.

        Returns:
            Probability ∈ [0, 1].
        """
        temp = _mat_mul(projector, self._matrix)
        projected = _mat_mul(temp, projector)
        prob = _trace(projected)
        return max(0.0, min(1.0, prob))

    # ── Information-theoretic measures ────────────────────────────

    def von_neumann_entropy(self) -> float:
        """S(ρ) = -Tr(ρ · log(ρ)) — Von Neumann entropy.

        Computed via eigenvalues: S = -Σ λᵢ · log(λᵢ)
        where λᵢ are eigenvalues of ρ.

        Bounds:
            S = 0       for pure states (complete certainty)
            S = log(k)  for maximally mixed states (max uncertainty)
        """
        eigenvalues = _eigenvalues_power_method(self._matrix)
        entropy = 0.0
        for lam in eigenvalues:
            if lam > 1e-12:
                entropy -= lam * math.log(lam)
        return max(0.0, entropy)

    def purity(self) -> float:
        """Tr(ρ²) — purity of the state.

        Bounds:
            1/k  for maximally mixed states
            1    for pure states
        """
        rho_sq = _mat_mul(self._matrix, self._matrix)
        return max(0.0, min(1.0, _trace(rho_sq)))

    def is_pure(self, tol: float = 1e-6) -> bool:
        """Check if ρ is a pure state (Tr(ρ²) ≈ 1)."""
        return abs(self.purity() - 1.0) < tol

    def coherence(self) -> float:
        """Off-diagonal coherence: C(ρ) = Σ_{i≠j} |ρ_{ij}|.

        Measures quantum-like correlations between dimensions.
        Zero for classical (diagonal) states, positive for
        states with cognitive interference.
        """
        total = 0.0
        for i in range(self._k):
            for j in range(self._k):
                if i != j:
                    total += abs(self._matrix[i][j])
        return total

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "k": self._k,
            "matrix": _mat_copy(self._matrix),
            "purity": round(self.purity(), 6),
            "entropy": round(self.von_neumann_entropy(), 6),
            "coherence": round(self.coherence(), 6),
        }

    def __repr__(self) -> str:
        return (
            f"DensityMatrix(k={self._k}, "
            f"purity={self.purity():.4f}, "
            f"entropy={self.von_neumann_entropy():.4f})"
        )


# ═══════════════════════════════════════════════════════════════════
#  EVIDENCE PROJECTOR — Π_D for evidence D
# ═══════════════════════════════════════════════════════════════════


class EvidenceProjector:
    """Π_D — orthogonal projector factory for evidence types.

    Maps evidence categories to projection operators in the
    cognitive Hilbert space. The projectors satisfy:

        Π² = Π        (idempotent)
        Πᵀ = Π        (symmetric / self-adjoint)
        0 ≤ Tr(Π) ≤ k (rank bounded)

    Non-commutativity demonstration:

        Suppose Π_A projects onto the "affect" subspace
        and Π_B projects onto the "certainty" subspace.

        If these subspaces overlap (non-orthogonal evidence),
        then Π_A · Π_B ≠ Π_B · Π_A, and the order in which
        evidence A and B are presented matters.

    Predefined evidence categories:
        - EMOTIONAL:  primarily affects 'affect' dimension
        - COGNITIVE:  primarily affects 'cognitive_load' dimension
        - EPISTEMIC:  primarily affects 'certainty' dimension
        - SOCIAL:     primarily affects 'trust' + 'openness' dimensions
        - COMPOSITE:  custom multi-dimensional evidence

    Args:
        k: Dimensionality of the Hilbert space.
    """

    def __init__(self, k: int = 5) -> None:
        self._k = k

    def create_projector(
        self,
        direction: list[float],
    ) -> list[list[float]]:
        """Create rank-1 projector along a direction.

        Π = |d⟩⟨d| / ⟨d|d⟩

        The direction vector determines which cognitive subspace
        the evidence projects onto.

        Args:
            direction: Direction vector (will be normalized).

        Returns:
            k×k projector matrix.
        """
        norm = math.sqrt(sum(x * x for x in direction))
        if norm < 1e-10:
            raise ValueError("Direction vector cannot be zero")
        normalized = [x / norm for x in direction]
        return _outer_product(normalized)

    def create_subspace_projector(
        self,
        directions: list[list[float]],
    ) -> list[list[float]]:
        """Create rank-r projector onto a subspace.

        Π = Σ |dᵢ⟩⟨dᵢ| for orthonormalized {dᵢ}

        Uses Gram-Schmidt to orthonormalize the directions.

        Args:
            directions: List of direction vectors spanning the subspace.

        Returns:
            k×k projector matrix (rank = number of independent directions).
        """
        if not directions:
            raise ValueError("Need at least one direction")

        # Gram-Schmidt orthonormalization
        orthonormal = self._gram_schmidt(directions)
        if not orthonormal:
            raise ValueError("All directions are linearly dependent")

        # Sum of rank-1 projectors
        k = self._k
        result = _zeros(k)
        for vec in orthonormal:
            outer = _outer_product(vec)
            for i in range(k):
                for j in range(k):
                    result[i][j] += outer[i][j]

        return result

    def _gram_schmidt(
        self,
        vectors: list[list[float]],
    ) -> list[list[float]]:
        """Gram-Schmidt orthonormalization."""
        orthonormal: list[list[float]] = []

        for vec in vectors:
            # Project out components along existing basis
            projected = list(vec)
            for basis in orthonormal:
                dot = sum(projected[i] * basis[i] for i in range(len(vec)))
                projected = [projected[i] - dot * basis[i] for i in range(len(vec))]

            # Normalize
            norm = math.sqrt(sum(x * x for x in projected))
            if norm > 1e-10:
                orthonormal.append([x / norm for x in projected])

        return orthonormal

    # ── Predefined projectors (for k=5 standard dimensions) ───────

    def emotional(self) -> list[list[float]]:
        """Π_emotional: projects primarily onto affect dimension.

        Evidence that carries emotional content (positive or negative
        sentiment) influences the affect dimension most strongly,
        with secondary effects on openness.
        """
        if self._k < 2:
            return self.create_projector([1.0])
        # Primarily affect (dim 0), secondarily openness (dim 3)
        direction = [0.0] * self._k
        direction[0] = 0.9   # affect
        if self._k > 3:
            direction[3] = 0.3  # openness (secondary)
        return self.create_projector(direction)

    def cognitive(self) -> list[list[float]]:
        """Π_cognitive: projects primarily onto cognitive_load dimension.

        Complex, dense, or technical evidence increases cognitive
        load, with secondary effects on certainty.
        """
        if self._k < 2:
            return self.create_projector([1.0])
        direction = [0.0] * self._k
        direction[1] = 0.9   # cognitive_load
        if self._k > 2:
            direction[2] = 0.3  # certainty (secondary)
        return self.create_projector(direction)

    def epistemic(self) -> list[list[float]]:
        """Π_epistemic: projects primarily onto certainty dimension.

        Factual evidence, citations, and proofs directly affect
        the certainty dimension.
        """
        if self._k < 3:
            return self.create_projector([0.0, 1.0][:self._k])
        direction = [0.0] * self._k
        direction[2] = 1.0   # certainty
        return self.create_projector(direction)

    def social(self) -> list[list[float]]:
        """Π_social: projects onto trust + openness subspace.

        Social proof, consensus, and authority signals affect
        both trust and openness simultaneously.
        """
        if self._k < 4:
            direction = [0.0] * self._k
            direction[-1] = 1.0
            return self.create_projector(direction)
        # Trust (dim 4) and openness (dim 3)
        return self.create_subspace_projector([
            [0.0, 0.0, 0.0, 0.0, 1.0][:self._k],  # trust
            [0.0, 0.0, 0.0, 1.0, 0.0][:self._k],  # openness
        ])


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE STATE ↔ DENSITY MATRIX BRIDGE
# ═══════════════════════════════════════════════════════════════════


def cognitive_state_to_density(values: list[float]) -> DensityMatrix:
    """Convert cognitive state vector to density matrix.

    Maps ψ ∈ ℝᵏ → ρ_ψ = |ψ⟩⟨ψ| / ⟨ψ|ψ⟩

    The resulting density matrix is a pure state representing
    the cognitive configuration with full certainty.

    For mixed states (epistemic uncertainty about the user's
    cognitive state), use DensityMatrix.from_mixture().
    """
    return DensityMatrix.from_cognitive_state(values)


def density_to_probabilities(
    density: DensityMatrix,
    projectors: list[list[list[float]]],
) -> list[float]:
    """Compute Born probabilities for multiple evidence types.

    P(Dᵢ | ψ) = Tr(Π_Dᵢ · ρ_ψ · Π_Dᵢ) for each i

    Args:
        density:    The current density matrix ρ_ψ.
        projectors: List of projector matrices [Π_D₁, Π_D₂, ...].

    Returns:
        List of probabilities [P(D₁|ψ), P(D₂|ψ), ...].
    """
    return [density.born_probability(p) for p in projectors]
