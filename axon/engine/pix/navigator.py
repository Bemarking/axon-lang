"""
AXON Engine — PIX Navigator
==============================
LLM-guided tree navigation implementing bounded breadth-first
search with heuristic pruning.

The navigator treats the LLM as a rational information forager
(Pirolli & Card, 1999): it follows "information scent" encoded
in node summaries, pruning branches with low relevance scores.

Mathematical basis:
  - Monotonic Entropy Reduction: H(R|Q, n₁..nₜ) ≤ H(R|Q, n₁..nₜ₋₁)
  - Bayesian belief updating at each navigation step
  - Bounded rationality via b_max and d_max

Complexity:
  - Worst case: O(b^d · C_LLM)
  - Expected:   O(b̄·d̄ · C_LLM) ≈ 10-30 evaluations per query
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from axon.engine.pix.document_tree import DocumentTree, PixNode


@dataclass(frozen=True)
class NavigationConfig:
    """Configuration for PIX navigation.

    Attributes:
        max_depth:     Maximum traversal depth (default: 4).
        max_branch:    Maximum children selected per node (default: 3).
        threshold:     Minimum relevance score to explore a child (default: 0.3).
        timeout_secs:  Maximum time for navigation before returning best-effort (default: 30).
        model:         LLM model identifier for navigation scoring (default: "fast").
    """

    max_depth: int = 4
    max_branch: int = 3
    threshold: float = 0.3
    timeout_secs: float = 30.0
    model: str = "fast"


@dataclass
class NavigationStep:
    """A single step in the navigation trajectory.

    Records the decision made at each tree level:
    which node was evaluated, its score, and the reasoning.
    """

    node_id: str
    title: str
    score: float
    reasoning: str
    depth: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "score": round(self.score, 4),
            "reasoning": self.reasoning,
            "depth": self.depth,
            "timestamp": self.timestamp,
        }


@dataclass
class ReasoningPath:
    """Ordered sequence of NavigationSteps — the PIX "trail".

    This is the explainability backbone: every retrieval produces
    a complete trace of navigational decisions, enabling
    "why was this retrieved?" auditing.

    Theorem 4 guarantees: ∀ step (nᵢ → nᵢ₊₁) ∈ π :
      ∃ reasoning_text explaining why nᵢ₊₁ was selected.
    """

    steps: list[NavigationStep] = field(default_factory=list)

    def add_step(self, step: NavigationStep) -> None:
        self.steps.append(step)

    @property
    def depth(self) -> int:
        """Maximum depth reached during navigation."""
        if not self.steps:
            return 0
        return max(s.depth for s in self.steps)

    @property
    def total_evaluations(self) -> int:
        """Total number of LLM scoring evaluations performed."""
        return len(self.steps)

    @property
    def selected_nodes(self) -> list[str]:
        """List of node IDs in the path."""
        return [s.node_id for s in self.steps]

    @property
    def total_time(self) -> float:
        """Total navigation time in seconds."""
        if len(self.steps) < 2:
            return 0.0
        return self.steps[-1].timestamp - self.steps[0].timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "depth": self.depth,
            "total_evaluations": self.total_evaluations,
            "total_time_secs": round(self.total_time, 3),
        }

    def summary(self) -> str:
        """Human-readable summary of the reasoning path."""
        lines = [f"PIX Trail ({self.total_evaluations} steps, depth {self.depth}):"]
        for step in self.steps:
            indent = "  " * step.depth
            lines.append(
                f"{indent}→ [{step.score:.2f}] {step.title} — {step.reasoning}"
            )
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"ReasoningPath(steps={self.total_evaluations}, depth={self.depth})"


@runtime_checkable
class ScoringFunction(Protocol):
    """Protocol for LLM-based relevance scoring.

    Implementations must evaluate how relevant a node's summary
    is to the given query, returning a score ∈ [0, 1].

    The scoring function approximates mutual information:
        I(R; nᵢ | Q) ≈ f_LLM(query, nᵢ.summary, nᵢ.title)
    """

    def score(
        self, query: str, title: str, summary: str
    ) -> tuple[float, str]:
        """Score a node's relevance to the query.

        Args:
            query:   The user's question.
            title:   The node's title.
            summary: The node's compressed summary.

        Returns:
            Tuple of (score ∈ [0,1], reasoning_text).
        """
        ...


class ThresholdScorer:
    """Simple threshold-based scorer for testing.

    Scores based on keyword overlap between query and title/summary.
    Not intended for production — use an LLM-based scorer instead.
    """

    def score(
        self, query: str, title: str, summary: str
    ) -> tuple[float, str]:
        query_terms = set(query.lower().split())
        text_terms = set(f"{title} {summary}".lower().split())
        overlap = query_terms & text_terms
        if not query_terms:
            return 0.0, "Empty query"
        score = len(overlap) / len(query_terms)
        reasoning = f"Matched {len(overlap)}/{len(query_terms)} terms: {overlap}" if overlap else "No term overlap"
        return min(score, 1.0), reasoning


@dataclass
class NavigationResult:
    """Result of a PIX navigation operation.

    Contains the retrieved leaf nodes, reasoning path,
    and metadata about the navigation process.
    """

    leaves: list[PixNode] = field(default_factory=list)
    path: ReasoningPath = field(default_factory=ReasoningPath)
    query: str = ""
    elapsed_secs: float = 0.0
    timed_out: bool = False

    @property
    def content(self) -> list[str]:
        """Extracted content from all retrieved leaf nodes."""
        return [leaf.content for leaf in self.leaves if leaf.content]

    @property
    def sources(self) -> list[dict[str, int]]:
        """Location metadata for all retrieved leaves."""
        return [leaf.location.to_dict() for leaf in self.leaves]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "leaf_count": len(self.leaves),
            "content": self.content,
            "sources": self.sources,
            "path": self.path.to_dict(),
            "elapsed_secs": round(self.elapsed_secs, 3),
            "timed_out": self.timed_out,
        }


class PixNavigator:
    """LLM-guided tree navigator — the core of PIX retrieval.

    Implements Algorithm IndAxon-Navigate:
      1. Start at root
      2. Score children with ScoringFunction
      3. Select top-k above threshold
      4. Recurse into selected children
      5. Collect leaf nodes as results

    Example:
        tree = DocumentTree("contract", root_node)
        scorer = MyLLMScorer(model="gpt-4o-mini")
        navigator = PixNavigator(tree, scorer)

        result = navigator.navigate("What are the liability limits?")
        print(result.path.summary())
        for leaf in result.leaves:
            print(leaf.content)
    """

    def __init__(
        self,
        tree: DocumentTree,
        scorer: ScoringFunction,
        config: NavigationConfig | None = None,
    ) -> None:
        self._tree = tree
        self._scorer = scorer
        self._config = config or NavigationConfig()

    @property
    def tree(self) -> DocumentTree:
        return self._tree

    @property
    def config(self) -> NavigationConfig:
        return self._config

    def navigate(self, query: str) -> NavigationResult:
        """Navigate the tree to find relevant content for the query.

        Returns a NavigationResult containing retrieved leaves,
        the reasoning path (trail), and performance metadata.
        """
        start_time = time.time()
        path = ReasoningPath()
        leaves: list[PixNode] = []

        # Add root as the starting step
        path.add_step(NavigationStep(
            node_id=self._tree.root.node_id,
            title=self._tree.root.title,
            score=1.0,
            reasoning="Root node — navigation starting point",
            depth=0,
        ))

        # Navigate recursively
        self._navigate_recursive(
            query=query,
            node=self._tree.root,
            depth=0,
            path=path,
            leaves=leaves,
            start_time=start_time,
        )

        elapsed = time.time() - start_time
        timed_out = elapsed >= self._config.timeout_secs

        return NavigationResult(
            leaves=leaves,
            path=path,
            query=query,
            elapsed_secs=elapsed,
            timed_out=timed_out,
        )

    def _navigate_recursive(
        self,
        query: str,
        node: PixNode,
        depth: int,
        path: ReasoningPath,
        leaves: list[PixNode],
        start_time: float,
    ) -> None:
        """Recursive navigation with pruning and depth bounds."""
        # Check timeout
        if time.time() - start_time >= self._config.timeout_secs:
            if node.is_leaf:
                leaves.append(node)
            return

        # Base case: leaf node or max depth reached
        if node.is_leaf or depth >= self._config.max_depth:
            leaves.append(node)
            return

        # Score all children
        scored_children: list[tuple[PixNode, float, str]] = []
        for child in node.children:
            score, reasoning = self._scorer.score(
                query, child.title, child.summary
            )
            scored_children.append((child, score, reasoning))

            # Record the evaluation step
            path.add_step(NavigationStep(
                node_id=child.node_id,
                title=child.title,
                score=score,
                reasoning=reasoning,
                depth=depth + 1,
            ))

        # Sort by score descending
        scored_children.sort(key=lambda x: x[1], reverse=True)

        # Select top-k above threshold
        selected = [
            (child, score, reason)
            for child, score, reason in scored_children
            if score >= self._config.threshold
        ][: self._config.max_branch]

        # Fallback: if no child passes threshold, take the best one
        if not selected and scored_children:
            best = scored_children[0]
            if best[1] > 0:
                selected = [best]

        # Recurse into selected children
        for child, _score, _reason in selected:
            self._navigate_recursive(
                query=query,
                node=child,
                depth=depth + 1,
                path=path,
                leaves=leaves,
                start_time=start_time,
            )

    def drill(self, subtree_id: str, query: str) -> NavigationResult:
        """Navigate a specific subtree — PIX `drill` primitive.

        Starts navigation from a named node instead of root.
        Useful when the user already knows which section is relevant.
        """
        subtree_root = self._tree.find_node(subtree_id)
        if subtree_root is None:
            raise ValueError(
                f"Node '{subtree_id}' not found in tree '{self._tree.name}'"
            )

        start_time = time.time()
        path = ReasoningPath()
        leaves: list[PixNode] = []

        path.add_step(NavigationStep(
            node_id=subtree_root.node_id,
            title=subtree_root.title,
            score=1.0,
            reasoning=f"Drill target — direct descent into '{subtree_root.title}'",
            depth=subtree_root.depth,
        ))

        self._navigate_recursive(
            query=query,
            node=subtree_root,
            depth=0,
            path=path,
            leaves=leaves,
            start_time=start_time,
        )

        elapsed = time.time() - start_time
        return NavigationResult(
            leaves=leaves,
            path=path,
            query=query,
            elapsed_secs=elapsed,
            timed_out=False,
        )
