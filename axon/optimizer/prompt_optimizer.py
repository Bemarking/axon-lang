"""
AXON — Mathematical Prompt Optimization Engine
=================================================
An algorithmic implementation of the mathematical frameworks described in
docs/mathematical_prompt_optimization.md.

This module provides a composable optimization pipeline that treats prompt
engineering as a formal optimization problem with:

  1. Information-Theoretic Scoring  (entropy, mutual information, KL divergence)
  2. Bayesian Surrogate Modeling    (Gaussian Process with semantic kernel)
  3. Kolmogorov-Inspired Compression (MDL principle for prompt efficiency)
  4. Constraint Satisfaction         (anchor verification as CSP)
  5. Control-Theoretic Refinement    (PID-style adaptive feedback)
  6. Multi-Objective Pareto Selection (scalarized quality + cost tradeoff)
  7. Best-of-N Statistical Bounds    (consensus quality estimation)

Usage::

    from axon.optimizer.prompt_optimizer import PromptOptimizer, OptimizationConfig

    config = OptimizationConfig(
        objective_weights={"precision": 0.5, "recall": 0.3, "creativity": 0.0, "efficiency": 0.2},
        max_iterations=20,
        n_candidates=5,
        epistemic_mode="know",
    )

    optimizer = PromptOptimizer(config)
    result = optimizer.optimize(
        task="Extract key clauses from legal contracts",
        seed_prompts=["Extract the clauses", "List all clauses and obligations"],
        evaluator=my_evaluator_fn,
    )

    print(result.best_prompt)
    print(result.pareto_front)
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1 — Core Types and Configuration
# ═══════════════════════════════════════════════════════════════════


class EpistemicMode(Enum):
    """Epistemic modes from AXON's constraint calculus.

    Each mode maps to a distinct optimization regime via the
    constraint function C(mode) → (τ, p, A).
    """
    KNOW = "know"
    BELIEVE = "believe"
    SPECULATE = "speculate"
    DOUBT = "doubt"


@dataclass(frozen=True)
class EpistemicConstraints:
    """Resolved constraint set for an epistemic mode.

    Implements the homorphism C: Mode → (τ, p, A) from the
    epistemic lattice to the LLM parameter space.
    """
    temperature: float
    top_p: float
    anchors: tuple[str, ...]

    @staticmethod
    def from_mode(mode: EpistemicMode) -> EpistemicConstraints:
        """Constraint function C(mode) — compile-time resolution.

        Lattice ordering: know ≤ believe ≤ speculate
        Temperature is monotonically non-decreasing.
        Anchor set is monotonically non-increasing.
        """
        return _CONSTRAINT_MAP[mode]


_CONSTRAINT_MAP: dict[EpistemicMode, EpistemicConstraints] = {
    EpistemicMode.KNOW: EpistemicConstraints(
        temperature=0.1, top_p=0.3,
        anchors=("RequiresCitation", "NoHallucination"),
    ),
    EpistemicMode.BELIEVE: EpistemicConstraints(
        temperature=0.3, top_p=0.5,
        anchors=("NoHallucination",),
    ),
    EpistemicMode.SPECULATE: EpistemicConstraints(
        temperature=0.9, top_p=0.95,
        anchors=(),
    ),
    EpistemicMode.DOUBT: EpistemicConstraints(
        temperature=0.2, top_p=0.4,
        anchors=("RequiresCitation", "SyllogismChecker"),
    ),
}


@dataclass
class PromptCandidate:
    """A prompt under evaluation with all associated metrics."""
    text: str
    tokens: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    scalar_score: float = 0.0
    entropy: float = 0.0
    information_density: float = 0.0
    compression_ratio: float = 1.0
    constraint_satisfaction_rate: float = 0.0
    novelty_score: float = 0.0
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        """Approximate token count (whitespace-based estimate)."""
        return len(self.text.split()) if not self.tokens else len(self.tokens)

    @property
    def id(self) -> str:
        """Deterministic hash for deduplication."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]


@dataclass
class OptimizationConfig:
    """Configuration for the optimization pipeline.

    objective_weights maps quality dimensions to their importance
    in the scalarized multi-objective function (§7.2 of research).
    """
    objective_weights: dict[str, float] = field(default_factory=lambda: {
        "precision": 0.4,
        "recall": 0.3,
        "creativity": 0.1,
        "efficiency": 0.2,
    })
    max_iterations: int = 20
    n_candidates: int = 5
    epistemic_mode: str = "know"
    quality_threshold: float = 0.7
    exploration_weight: float = 1.5        # κ in UCB acquisition
    convergence_epsilon: float = 0.01      # early stopping threshold
    max_prompt_tokens: int = 2048
    novelty_target: float = 0.5            # for forge-style synthesis
    pid_kp: float = 0.6                    # proportional gain
    pid_ki: float = 0.15                   # integral gain
    pid_kd: float = 0.10                   # derivative gain

    def validate(self) -> None:
        """Ensure weights sum to 1.0 and parameters are in valid ranges."""
        total = sum(self.objective_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Objective weights must sum to 1.0, got {total:.4f}. "
                f"Weights: {self.objective_weights}"
            )
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be ≥ 1")
        if not 0.0 <= self.quality_threshold <= 1.0:
            raise ValueError("quality_threshold must be in [0, 1]")
        if not 0.0 <= self.novelty_target <= 1.0:
            raise ValueError("novelty_target must be in [0, 1]")


@dataclass
class OptimizationResult:
    """Complete result of a prompt optimization run."""
    best_prompt: PromptCandidate
    pareto_front: list[PromptCandidate]
    all_candidates: list[PromptCandidate]
    convergence_history: list[float]
    iterations_used: int
    converged: bool
    metadata: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2 — Information-Theoretic Scoring (§2 & §9 of research)
# ═══════════════════════════════════════════════════════════════════


class InformationTheoreticScorer:
    """Computes information-theoretic quality metrics for prompts.

    Implements:
    - Token-level entropy estimation (§2.2)
    - Information density ρ(p) = I(P;R) / |p| (§4.3)
    - Compression ratio (§4.3)
    - Entropy reduction ΔH = H(R) - H(R|P) (§2.1)
    """

    @staticmethod
    def estimate_entropy(token_probs: list[float]) -> float:
        """Estimate Shannon entropy from token probability distribution.

        H = -Σ p(v) log₂ p(v)

        Args:
            token_probs: Probability distribution over vocabulary.
                         Must sum to ≤ 1.0 (tail is implicit).

        Returns:
            Entropy in bits.
        """
        if not token_probs:
            return 0.0

        entropy = 0.0
        for p in token_probs:
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def estimate_prompt_entropy(prompt: str, vocab_size: int = 50_000) -> float:
        """Estimate the entropy of a prompt based on character-level
        frequency distribution (proxy when token probabilities are
        unavailable).

        Uses character n-gram frequencies as an approximation of the
        true token-level entropy.
        """
        if not prompt:
            return 0.0

        # Character frequency distribution as entropy proxy
        freq: dict[str, int] = {}
        total = 0
        for ch in prompt.lower():
            freq[ch] = freq.get(ch, 0) + 1
            total += 1

        entropy = 0.0
        for count in freq.values():
            p = count / total
            entropy -= p * math.log2(p)

        return entropy

    @staticmethod
    def information_density(
        prompt: str,
        quality_score: float,
    ) -> float:
        """Information density: ρ(p) = Q(p) / |p|

        Quality per token — maximized when prompt is both effective
        and concise (MDL principle, §4.3).

        Args:
            prompt:        The prompt text.
            quality_score: Overall quality score Q(p) ∈ [0, 1].

        Returns:
            Information density ρ ∈ [0, ∞).
        """
        token_count = len(prompt.split())
        if token_count == 0:
            return 0.0
        return quality_score / token_count

    @staticmethod
    def compression_ratio(
        prompt: str,
        naive_prompt: str,
    ) -> float:
        """Compression ratio: CR = |p| / |p_naive|

        Measures how much more efficient the optimized prompt is
        compared to a naive/verbose baseline.

        Args:
            prompt:       Optimized prompt.
            naive_prompt: Unoptimized baseline prompt.

        Returns:
            Compression ratio ∈ (0, ∞). Values < 1.0 indicate compression.
        """
        p_len = len(prompt.split())
        naive_len = len(naive_prompt.split())
        if naive_len == 0:
            return 1.0
        return p_len / naive_len

    @staticmethod
    def kl_divergence(
        p_target: list[float],
        p_model: list[float],
    ) -> float:
        """KL divergence: D_KL(R* || R_p) = Σ R*(r) log(R*(r)/R_p(r))

        Measures how far the model's output distribution is from
        the target distribution (§2.3).

        Args:
            p_target: Target (desired) distribution.
            p_model:  Model's actual distribution.

        Returns:
            KL divergence ≥ 0. Lower is better.
        """
        if len(p_target) != len(p_model):
            raise ValueError("Distributions must have equal length")

        kl = 0.0
        for pt, pm in zip(p_target, p_model):
            if pt > 0 and pm > 0:
                kl += pt * math.log(pt / pm)
            elif pt > 0 and pm <= 0:
                return float("inf")
        return kl


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3 — Bayesian Surrogate Model (§3 of research)
# ═══════════════════════════════════════════════════════════════════


class GaussianProcessSurrogate:
    """Lightweight Gaussian Process surrogate for prompt quality prediction.

    Uses a semantic kernel (§3.3):
        k(p, p') = exp(-||e(p) - e(p')||² / 2ℓ²)

    where e(p) is the prompt's embedding vector.

    This implementation uses a simplified textual distance as a proxy
    for semantic similarity (production would use Sentence-BERT embeddings).
    """

    def __init__(
        self,
        length_scale: float = 1.0,
        noise_variance: float = 0.01,
    ) -> None:
        self.length_scale = length_scale
        self.noise_variance = noise_variance
        self._observations: list[tuple[str, float]] = []  # (prompt, score)

    def observe(self, prompt: str, score: float) -> None:
        """Record an observation (prompt, quality score)."""
        self._observations.append((prompt, score))

    @property
    def n_observations(self) -> int:
        """Number of recorded observations."""
        return len(self._observations)

    def _text_distance(self, p1: str, p2: str) -> float:
        """Jaccard distance as a proxy for semantic distance.

        Production: replace with ||e(p1) - e(p2)|| using embeddings.
        """
        words1 = set(p1.lower().split())
        words2 = set(p2.lower().split())
        if not words1 and not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        jaccard_sim = len(intersection) / len(union) if union else 0.0
        return 1.0 - jaccard_sim

    def _kernel(self, p1: str, p2: str) -> float:
        """Semantic RBF kernel: k(p, p') = exp(-d²/2ℓ²)"""
        d = self._text_distance(p1, p2)
        return math.exp(-(d ** 2) / (2 * self.length_scale ** 2))

    def predict(self, prompt: str) -> tuple[float, float]:
        """Predict (mean, std) for a new prompt using GP posterior.

        Returns:
            (μ, σ) — predicted quality score and uncertainty.
        """
        if not self._observations:
            return 0.5, 1.0  # prior: uniform uncertainty

        # Kernel vector between candidate and all observations
        k_star = [self._kernel(prompt, obs[0]) for obs in self._observations]
        scores = [obs[1] for obs in self._observations]

        # GP posterior mean: weighted average by kernel similarity
        k_sum = sum(k_star) + 1e-8
        mu = sum(k * s for k, s in zip(k_star, scores)) / k_sum

        # GP posterior std: decreases with more similar observations
        max_k = max(k_star) if k_star else 0.0
        sigma = math.sqrt(max(1.0 - max_k, self.noise_variance))

        return mu, sigma

    def acquisition_ucb(
        self,
        prompt: str,
        kappa: float = 1.5,
    ) -> float:
        """Upper Confidence Bound acquisition function (§3.2).

        α_UCB(p) = μ(p) + κ · σ(p)

        Args:
            prompt: Candidate prompt.
            kappa:  Exploration-exploitation tradeoff coefficient.

        Returns:
            UCB score. Higher = more promising candidate.
        """
        mu, sigma = self.predict(prompt)
        return mu + kappa * sigma

    def acquisition_ei(
        self,
        prompt: str,
    ) -> float:
        """Expected Improvement acquisition function (§3.2).

        α_EI(p) = E[max(Q(p) - Q⁺, 0)]

        Uses a normal approximation.

        Returns:
            Expected improvement. Higher = more promising candidate.
        """
        if not self._observations:
            return 1.0

        mu, sigma = self.predict(prompt)
        best_score = max(obs[1] for obs in self._observations)

        if sigma <= 1e-8:
            return max(mu - best_score, 0.0)

        z = (mu - best_score) / sigma
        # Approximate Φ(z) and φ(z) for EI formula
        phi = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
        cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))

        return sigma * (z * cdf + phi)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4 — Constraint Satisfaction Engine (§5.3 of research)
# ═══════════════════════════════════════════════════════════════════


class Constraint(Protocol):
    """Protocol for an anchor-derived constraint.

    Each constraint is a predicate over a response that returns
    (satisfied: bool, violation_detail: str | None).
    """
    name: str

    def check(self, response: str, metadata: dict[str, Any]) -> tuple[bool, str | None]:
        ...


@dataclass
class CitationConstraint:
    """Anchor constraint: RequiresCitation.

    Checks that the response contains citation markers.
    """
    name: str = "RequiresCitation"

    def check(
        self, response: str, metadata: dict[str, Any],
    ) -> tuple[bool, str | None]:
        citation_markers = ["[", "]", "http", "source:", "ref:", "citation:"]
        has_citation = any(marker in response.lower() for marker in citation_markers)
        if has_citation:
            return True, None
        return False, "Response lacks citations. All factual claims must include source references."


@dataclass
class NoHallucinationConstraint:
    """Anchor constraint: NoHallucination.

    Checks for hedging language without supporting evidence.
    """
    name: str = "NoHallucination"

    def check(
        self, response: str, metadata: dict[str, Any],
    ) -> tuple[bool, str | None]:
        hedging = ["probably", "might be", "I think", "possibly", "perhaps"]
        confidence = metadata.get("confidence", 1.0)

        has_hedging = any(h in response.lower() for h in hedging)
        low_confidence = confidence < metadata.get("confidence_floor", 0.75)

        if has_hedging and low_confidence:
            return False, (
                f"Hedging detected with low confidence ({confidence:.2f}). "
                "Provide verifiable claims or state 'Insufficient information'."
            )
        return True, None


@dataclass
class SyllogismConstraint:
    """Anchor constraint: SyllogismChecker.

    Checks for explicit logical structure in reasoning.
    """
    name: str = "SyllogismChecker"

    def check(
        self, response: str, metadata: dict[str, Any],
    ) -> tuple[bool, str | None]:
        logic_markers = ["premise:", "conclusion:", "therefore:", "given that", "it follows"]
        has_structure = any(m in response.lower() for m in logic_markers)
        if has_structure:
            return True, None
        return False, "Response lacks explicit logical structure. Use Premise/Conclusion format."


class ConstraintSolver:
    """CSP solver that verifies response against anchor constraints.

    Implements the constraint satisfaction model from §5.3:
        CSP = (X, D, C) where C comes from AXON anchors.

    The solver returns the satisfaction rate and violation details,
    which feed into the PID controller for adaptive refinement.
    """

    def __init__(self, constraints: list[Any] | None = None) -> None:
        self._constraints: list[Any] = constraints or []

    def add_constraint(self, constraint: Any) -> None:
        """Register an anchor constraint."""
        self._constraints.append(constraint)

    def add_constraints_for_mode(self, mode: EpistemicMode) -> None:
        """Auto-inject constraints based on epistemic mode (§5.2)."""
        ec = EpistemicConstraints.from_mode(mode)
        for anchor_name in ec.anchors:
            constraint = _ANCHOR_REGISTRY.get(anchor_name)
            if constraint is not None:
                self._constraints.append(constraint)

    def verify(
        self,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[float, list[str]]:
        """Verify response against all constraints.

        Returns:
            (satisfaction_rate, list_of_violations)
            satisfaction_rate = |{c ∈ C : r ⊨ c}| / |C|
        """
        if not self._constraints:
            return 1.0, []

        metadata = metadata or {}
        satisfied = 0
        violations: list[str] = []

        for constraint in self._constraints:
            ok, detail = constraint.check(response, metadata)
            if ok:
                satisfied += 1
            elif detail:
                violations.append(f"[{constraint.name}] {detail}")

        rate = satisfied / len(self._constraints)
        return rate, violations

    @property
    def constraint_count(self) -> int:
        return len(self._constraints)


# Registry of built-in anchor constraints
_ANCHOR_REGISTRY: dict[str, Any] = {
    "RequiresCitation": CitationConstraint(),
    "NoHallucination": NoHallucinationConstraint(),
    "SyllogismChecker": SyllogismConstraint(),
}


# ═══════════════════════════════════════════════════════════════════
#  SECTION 5 — PID Controller for Refinement (§6 of research)
# ═══════════════════════════════════════════════════════════════════


class PIDController:
    """PID controller for adaptive prompt refinement.

    Implements the control-theoretic model from §6.2:
        u_t = Kp·e_t + Ki·Σe_j + Kd·(e_t - e_{t-1})

    The controller generates refinement signals based on the
    quality error trajectory, which are injected as feedback context
    into the next prompt iteration.
    """

    def __init__(
        self,
        kp: float = 0.6,
        ki: float = 0.15,
        kd: float = 0.10,
        target_quality: float = 0.9,
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.target = target_quality
        self._error_history: list[float] = []
        self._integral: float = 0.0

    def step(self, current_quality: float) -> dict[str, float]:
        """Compute one PID step and return control signals.

        Args:
            current_quality: Q(r_t) — quality of current response.

        Returns:
            Dict with control components and composite signal.
        """
        error = self.target - current_quality
        self._error_history.append(error)
        self._integral += error

        # Derivative (finite difference)
        if len(self._error_history) >= 2:
            derivative = error - self._error_history[-2]
        else:
            derivative = 0.0

        # Control signal
        proportional = self.kp * error
        integral = self.ki * self._integral
        derivative_term = self.kd * derivative
        control = proportional + integral + derivative_term

        return {
            "error": error,
            "proportional": proportional,
            "integral": integral,
            "derivative": derivative_term,
            "control_signal": control,
            "iteration": len(self._error_history),
        }

    def generate_feedback(
        self,
        control: dict[str, float],
        violations: list[str],
    ) -> str:
        """Generate natural-language feedback from control signal.

        Translates the numeric PID output into actionable refinement
        instructions for the next prompt iteration.
        """
        parts: list[str] = []

        # Proportional feedback — current error
        if control["error"] > 0.3:
            parts.append("CRITICAL: Response quality is significantly below target.")
        elif control["error"] > 0.1:
            parts.append("Response needs improvement in multiple areas.")
        elif control["error"] > 0:
            parts.append("Minor refinement needed for optimal quality.")

        # Integral feedback — accumulated failures
        if control["integral"] > 1.0:
            parts.append(
                f"PERSISTENT ISSUE: Quality has been below target for "
                f"{control['iteration']} iterations. Fundamental approach change needed."
            )

        # Derivative feedback — trend
        if control["derivative"] > 0.05:
            parts.append("Quality is DECLINING. Previous changes made things worse.")
        elif control["derivative"] < -0.05:
            parts.append("Quality is IMPROVING. Continue current direction.")

        # Constraint violations
        if violations:
            parts.append("CONSTRAINT VIOLATIONS:")
            for v in violations:
                parts.append(f"  • {v}")

        return "\n".join(parts) if parts else "Quality target met."

    @property
    def is_converged(self) -> bool:
        """Check if the system has converged (small error, stable)."""
        if len(self._error_history) < 3:
            return False
        recent = self._error_history[-3:]
        return all(abs(e) < 0.05 for e in recent)

    def reset(self) -> None:
        """Reset controller state for a new optimization run."""
        self._error_history.clear()
        self._integral = 0.0


# ═══════════════════════════════════════════════════════════════════
#  SECTION 6 — Multi-Objective Pareto Selector (§7 of research)
# ═══════════════════════════════════════════════════════════════════


class ParetoSelector:
    """Multi-objective optimization via Pareto dominance and scalarization.

    Implements §7.1 (Pareto front computation) and §7.2 (scalarization).
    """

    @staticmethod
    def dominates(
        a: dict[str, float],
        b: dict[str, float],
    ) -> bool:
        """Check if candidate `a` Pareto-dominates candidate `b`.

        a ≻ b iff a is ≥ b in all objectives AND strictly > in at least one.
        """
        keys = set(a.keys()) | set(b.keys())
        all_geq = all(a.get(k, 0) >= b.get(k, 0) for k in keys)
        any_gt = any(a.get(k, 0) > b.get(k, 0) for k in keys)
        return all_geq and any_gt

    @staticmethod
    def compute_pareto_front(
        candidates: list[PromptCandidate],
    ) -> list[PromptCandidate]:
        """Compute the Pareto front (set of non-dominated candidates).

        F* = {p ∈ P : ∄ p' ∈ P such that p' ≻ p}
        """
        front: list[PromptCandidate] = []

        for candidate in candidates:
            dominated = False
            for other in candidates:
                if other is candidate:
                    continue
                if ParetoSelector.dominates(other.scores, candidate.scores):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)

        return front

    @staticmethod
    def scalarize(
        scores: dict[str, float],
        weights: dict[str, float],
    ) -> float:
        """Scalarized multi-objective score (§7.2).

        Q_scalar(p) = Σᵢ wᵢ · Qᵢ(p) with Σwᵢ = 1

        Args:
            scores:  Quality scores per objective dimension.
            weights: Importance weights (must sum to 1.0).

        Returns:
            Scalar quality score ∈ [0, 1].
        """
        return sum(
            weights.get(key, 0.0) * scores.get(key, 0.0)
            for key in set(list(weights.keys()) + list(scores.keys()))
        )


# ═══════════════════════════════════════════════════════════════════
#  SECTION 7 — Best-of-N Quality Estimator (§8 of research)
# ═══════════════════════════════════════════════════════════════════


class BestOfNEstimator:
    """Statistical bounds for Best-of-N selection quality.

    Implements the quality bound theorem from §8.2:
        E[max(Q₁,...,Qₙ)] for various distributions.
    """

    @staticmethod
    def expected_best_uniform(n: int) -> float:
        """Expected best quality for N samples from U[0,1].

        E[max] = N/(N+1)

        This gives an upper bound on improvement from parallel runs
        when quality distribution is approximately uniform.
        """
        return n / (n + 1)

    @staticmethod
    def expected_best_beta(
        n: int,
        alpha: float = 2.0,
        beta: float = 5.0,
    ) -> float:
        """Expected best quality for N samples from Beta(α, β).

        Uses Monte Carlo estimation for non-uniform quality distributions.
        Beta(2,5) is a good model for real-world prompt quality
        (skewed toward lower values, few excellent results).

        Args:
            n:     Number of parallel branches.
            alpha: Beta distribution shape parameter (successes).
            beta:  Beta distribution shape parameter (failures).

        Returns:
            Expected best quality E[max(Q₁,...,Qₙ)].
        """
        n_simulations = 10_000
        total = 0.0

        for _ in range(n_simulations):
            samples = [random.betavariate(alpha, beta) for _ in range(n)]
            total += max(samples)

        return total / n_simulations

    @staticmethod
    def marginal_improvement(n_current: int, n_proposed: int) -> float:
        """Marginal improvement of adding more branches.

        Returns the relative improvement from n_current to n_proposed
        branches, as a fraction.

        This quantifies the diminishing returns documented in §8.2.
        """
        e_current = BestOfNEstimator.expected_best_uniform(n_current)
        e_proposed = BestOfNEstimator.expected_best_uniform(n_proposed)
        if e_current <= 0:
            return float("inf")
        return (e_proposed - e_current) / e_current

    @staticmethod
    def optimal_n(
        cost_per_branch: float,
        value_per_quality_point: float,
        quality_alpha: float = 2.0,
        quality_beta: float = 5.0,
        max_n: int = 20,
    ) -> int:
        """Find optimal N that maximizes value - cost.

        Solves: N* = argmax_N {V·E[max(Q₁,...,Qₙ)] - N·C}

        Args:
            cost_per_branch:          Cost C per LLM evaluation.
            value_per_quality_point:  Value V per quality unit.
            quality_alpha:            Beta distribution α.
            quality_beta:             Beta distribution β.
            max_n:                    Maximum branches to consider.

        Returns:
            Optimal number of branches N*.
        """
        best_n = 1
        best_net_value = float("-inf")

        for n in range(1, max_n + 1):
            expected_quality = BestOfNEstimator.expected_best_beta(
                n, quality_alpha, quality_beta,
            )
            net_value = (
                value_per_quality_point * expected_quality
                - n * cost_per_branch
            )
            if net_value > best_net_value:
                best_net_value = net_value
                best_n = n

        return best_n


# ═══════════════════════════════════════════════════════════════════
#  SECTION 8 — Forge Temperature Calculator (§8.3 of research)
# ═══════════════════════════════════════════════════════════════════


class ForgeTemperatureCalculator:
    """Computes effective temperature for the forge creative pipeline.

    Implements:
        τ_eff = τ_base × (0.5 + 0.5 × novelty)

    And the Boden creativity taxonomy mapping:
        B(mode) → (τ_base, freedom, rule_flexibility)
    """

    _BODEN_MAP: dict[str, tuple[float, float, float]] = {
        "combinatory":      (0.9, 0.8, 0.3),
        "exploratory":      (0.7, 0.6, 0.5),
        "transformational": (1.2, 1.0, 0.9),
    }

    @classmethod
    def effective_temperature(
        cls,
        mode: str,
        novelty: float,
    ) -> float:
        """Calculate τ_eff for a forge block.

        Args:
            mode:    Boden creativity mode.
            novelty: Novelty parameter ∈ [0.0, 1.0].

        Returns:
            Effective temperature τ_eff.
        """
        if mode not in cls._BODEN_MAP:
            raise ValueError(
                f"Unknown Boden mode '{mode}'. "
                f"Must be one of: {list(cls._BODEN_MAP.keys())}"
            )
        tau_base, _, _ = cls._BODEN_MAP[mode]
        return tau_base * (0.5 + 0.5 * novelty)

    @classmethod
    def boden_parameters(
        cls,
        mode: str,
    ) -> dict[str, float]:
        """Get full Boden parameter set for a creativity mode."""
        if mode not in cls._BODEN_MAP:
            raise ValueError(f"Unknown Boden mode: {mode}")
        tau, freedom, flex = cls._BODEN_MAP[mode]
        return {
            "temperature_base": tau,
            "freedom": freedom,
            "rule_flexibility": flex,
        }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 9 — The Optimizer (orchestrates all components)
# ═══════════════════════════════════════════════════════════════════


# Type for the evaluator callback
EvaluatorFn = Callable[[str, str], dict[str, float]]


class PromptOptimizer:
    """Main optimization engine that orchestrates all mathematical components.

    Pipeline:
        1. Initialize GP surrogate with seed prompts
        2. For each iteration:
           a. Generate candidate prompts (via acquisition function)
           b. Evaluate candidates (external evaluator)
           c. Score with information-theoretic metrics
           d. Verify against constraint solver
           e. Update PID controller
           f. Update GP surrogate
           g. Check convergence
        3. Compute Pareto front
        4. Return optimal prompt(s)

    The optimizer implements the complete formal framework from the
    mathematical research document.
    """

    def __init__(self, config: OptimizationConfig | None = None) -> None:
        self.config = config or OptimizationConfig()
        self.config.validate()

        self._mode = EpistemicMode(self.config.epistemic_mode)
        self._constraints = EpistemicConstraints.from_mode(self._mode)

        # Component initialization
        self._scorer = InformationTheoreticScorer()
        self._gp = GaussianProcessSurrogate(length_scale=1.0, noise_variance=0.01)
        self._pid = PIDController(
            kp=self.config.pid_kp,
            ki=self.config.pid_ki,
            kd=self.config.pid_kd,
            target_quality=self.config.quality_threshold,
        )
        self._constraint_solver = ConstraintSolver()
        self._constraint_solver.add_constraints_for_mode(self._mode)
        self._pareto = ParetoSelector()
        self._bon = BestOfNEstimator()

    def optimize(
        self,
        task: str,
        seed_prompts: list[str],
        evaluator: EvaluatorFn,
    ) -> OptimizationResult:
        """Run the full optimization pipeline.

        Args:
            task:         Natural-language description of the target task.
            seed_prompts: Initial prompt candidates (≥ 1).
            evaluator:    Callback fn(task, prompt) → {"precision": 0.8, ...}

        Returns:
            OptimizationResult with best prompt, Pareto front, history.
        """
        if not seed_prompts:
            raise ValueError("At least one seed prompt is required")

        all_candidates: list[PromptCandidate] = []
        convergence_history: list[float] = []
        best_score = 0.0
        converged = False

        # Phase 1: Evaluate seed prompts
        for prompt_text in seed_prompts:
            candidate = self._evaluate_candidate(
                prompt_text, task, evaluator, iteration=0,
            )
            all_candidates.append(candidate)
            self._gp.observe(prompt_text, candidate.scalar_score)
            best_score = max(best_score, candidate.scalar_score)

        convergence_history.append(best_score)

        # Phase 2: Iterative optimization
        iteration = 0
        for iteration in range(1, self.config.max_iterations + 1):
            # Generate candidates using acquisition function
            new_prompts = self._generate_candidates(
                task, all_candidates, iteration,
            )

            # Evaluate new candidates
            iteration_best = 0.0
            for prompt_text in new_prompts:
                candidate = self._evaluate_candidate(
                    prompt_text, task, evaluator, iteration,
                )
                all_candidates.append(candidate)
                self._gp.observe(prompt_text, candidate.scalar_score)
                iteration_best = max(iteration_best, candidate.scalar_score)

            # Update PID controller
            control = self._pid.step(iteration_best)

            # Track convergence
            best_score = max(best_score, iteration_best)
            convergence_history.append(best_score)

            # Check convergence
            if self._pid.is_converged:
                converged = True
                break

            if len(convergence_history) >= 3:
                delta = abs(convergence_history[-1] - convergence_history[-3])
                if delta < self.config.convergence_epsilon:
                    converged = True
                    break

        # Phase 3: Compute Pareto front
        pareto_front = ParetoSelector.compute_pareto_front(all_candidates)

        # Select best overall
        best_candidate = max(all_candidates, key=lambda c: c.scalar_score)

        return OptimizationResult(
            best_prompt=best_candidate,
            pareto_front=pareto_front,
            all_candidates=all_candidates,
            convergence_history=convergence_history,
            iterations_used=iteration,
            converged=converged,
            metadata={
                "epistemic_mode": self._mode.value,
                "constraints": self._constraints,
                "total_evaluations": len(all_candidates),
                "final_pid_state": {
                    "integral": self._pid._integral,
                    "error_history": self._pid._error_history[-5:],
                },
            },
        )

    def _evaluate_candidate(
        self,
        prompt_text: str,
        task: str,
        evaluator: EvaluatorFn,
        iteration: int,
    ) -> PromptCandidate:
        """Evaluate a single prompt candidate with all metrics."""
        # External evaluation
        scores = evaluator(task, prompt_text)

        # Information-theoretic metrics
        scalar = ParetoSelector.scalarize(scores, self.config.objective_weights)
        entropy = self._scorer.estimate_prompt_entropy(prompt_text)
        info_density = self._scorer.information_density(prompt_text, scalar)

        # Constraint satisfaction
        # In a full implementation, we'd pass the actual response;
        # here we use the prompt itself as a proxy for structure check
        csr, violations = self._constraint_solver.verify(
            prompt_text,
            metadata={"confidence": scores.get("confidence", 0.8)},
        )

        candidate = PromptCandidate(
            text=prompt_text,
            scores=scores,
            scalar_score=scalar,
            entropy=entropy,
            information_density=info_density,
            constraint_satisfaction_rate=csr,
            iteration=iteration,
            metadata={
                "violations": violations,
                "gp_prediction": self._gp.predict(prompt_text),
            },
        )

        return candidate

    def _generate_candidates(
        self,
        task: str,
        existing: list[PromptCandidate],
        iteration: int,
    ) -> list[str]:
        """Generate new candidate prompts using acquisition-guided strategy.

        This is the core exploration step. In a production system,
        this would call an LLM to generate new prompts (OPRO-style).
        Here we implement the mathematical selection logic.
        """
        # Sort existing by UCB score
        scored = [
            (c, self._gp.acquisition_ucb(c.text, self.config.exploration_weight))
            for c in existing
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Use top candidates as seeds for variation
        top_k = min(3, len(scored))
        seeds = [scored[i][0].text for i in range(top_k)]

        # Generate variations (production: use LLM meta-prompting)
        candidates: list[str] = []
        for seed in seeds:
            # Variation 1: Add specificity
            candidates.append(f"{seed} Be specific and cite sources.")
            # Variation 2: Add constraints
            candidates.append(f"{seed} Respond only with verified facts.")

        # Dedup
        seen: set[str] = {c.text for c in existing}
        unique = [c for c in candidates if c not in seen]

        return unique[: self.config.n_candidates]

    # ── Public utilities ────────────────────────────────────────

    def estimate_optimal_branches(
        self,
        cost_per_call: float = 0.01,
        value_per_quality: float = 1.0,
    ) -> int:
        """Estimate optimal N for consensus/forge Best-of-N (§8.2)."""
        return self._bon.optimal_n(
            cost_per_branch=cost_per_call,
            value_per_quality_point=value_per_quality,
        )

    def compute_forge_temperature(
        self,
        boden_mode: str = "combinatory",
        novelty: float = 0.7,
    ) -> float:
        """Calculate effective forge temperature (§8.3)."""
        return ForgeTemperatureCalculator.effective_temperature(
            boden_mode, novelty,
        )
