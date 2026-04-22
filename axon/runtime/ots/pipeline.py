"""
OTS pipeline primitives — mirror of ``axon-rs/src/ots/pipeline.rs``.
"""

from __future__ import annotations

import heapq
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer


class OtsError(Exception):
    """Base class for OTS failures."""


class NoPathError(OtsError):
    def __init__(self, source: BufferKind, sink: BufferKind) -> None:
        super().__init__(
            f"no OTS path from {source} to {sink} in the current registry"
        )
        self.source = source
        self.sink = sink


class TransformFailedError(OtsError):
    pass


class KindMismatchError(OtsError):
    def __init__(self, expected: BufferKind, actual: BufferKind) -> None:
        super().__init__(
            f"pipeline kind mismatch — expected {expected}, got {actual}"
        )
        self.expected = expected
        self.actual = actual


class TransformerBackend(str, Enum):
    NATIVE = "native"
    SUBPROCESS = "ffmpeg"


@dataclass(frozen=True, slots=True)
class TransformerId:
    value: str

    @classmethod
    def new(cls, source: BufferKind, sink: BufferKind) -> "TransformerId":
        return cls(f"{source}->{sink}")


class Transformer(ABC):
    """Base class every OTS transformer extends.

    Subclasses override :meth:`source_kind`, :meth:`sink_kind`,
    :meth:`backend`, and :meth:`transform`. :meth:`cost_hint`
    defaults to ``1``; Dijkstra picks the cheapest total path.
    """

    @abstractmethod
    def source_kind(self) -> BufferKind:
        ...

    @abstractmethod
    def sink_kind(self) -> BufferKind:
        ...

    @abstractmethod
    def backend(self) -> TransformerBackend:
        ...

    def cost_hint(self) -> int:
        return 1

    @abstractmethod
    def transform(self, buffer: ZeroCopyBuffer) -> ZeroCopyBuffer:
        ...


@dataclass(frozen=True, slots=True)
class PipelineStep:
    transformer_id: TransformerId
    backend: TransformerBackend


class TransformerRegistry:
    """Directed graph keyed by source kind. Safe for concurrent
    reads once construction is done; writes happen at startup."""

    def __init__(self) -> None:
        # edges: source_kind → list of Transformer
        self._edges: dict[BufferKind, list[Transformer]] = {}

    def install(self, transformer: Transformer) -> None:
        self._edges.setdefault(
            transformer.source_kind(), []
        ).append(transformer)

    def transformers_from(
        self, kind: BufferKind
    ) -> list[Transformer]:
        return list(self._edges.get(kind, ()))

    def has_path(
        self, source: BufferKind, sink: BufferKind
    ) -> bool:
        try:
            self.shortest_path(source, sink)
            return True
        except NoPathError:
            return False

    def shortest_path(
        self, source: BufferKind, sink: BufferKind
    ) -> list[Transformer]:
        if source == sink:
            return []

        # Dijkstra — min-heap keyed by cumulative cost. Parent map
        # reconstructs the path once sink is popped.
        best_cost: dict[BufferKind, int] = {source: 0}
        parent: dict[BufferKind, tuple[BufferKind, Transformer]] = {}
        heap: list[tuple[int, int, BufferKind]] = [(0, 0, source)]
        tiebreak = 0

        while heap:
            cost, _, kind = heapq.heappop(heap)
            if kind == sink:
                path: list[Transformer] = []
                while kind in parent:
                    prev_kind, transformer = parent[kind]
                    path.append(transformer)
                    kind = prev_kind
                path.reverse()
                return path
            if cost > best_cost.get(kind, 2**31):
                continue
            for transformer in self._edges.get(kind, ()):
                next_kind = transformer.sink_kind()
                new_cost = cost + transformer.cost_hint()
                if new_cost < best_cost.get(next_kind, 2**31):
                    best_cost[next_kind] = new_cost
                    parent[next_kind] = (kind, transformer)
                    tiebreak += 1
                    heapq.heappush(
                        heap, (new_cost, tiebreak, next_kind)
                    )

        raise NoPathError(source, sink)

    def known_sources(self) -> list[BufferKind]:
        return sorted(self._edges.keys(), key=lambda k: k.slug)


class Pipeline:
    """Executable chain. Clone is cheap — just a list copy."""

    __slots__ = ("_steps",)

    def __init__(self, steps: list[Transformer]) -> None:
        self._steps = list(steps)

    @classmethod
    def from_registry(
        cls,
        registry: TransformerRegistry,
        source: BufferKind,
        sink: BufferKind,
    ) -> "Pipeline":
        return cls(registry.shortest_path(source, sink))

    def __len__(self) -> int:
        return len(self._steps)

    def is_empty(self) -> bool:
        return not self._steps

    def steps(self) -> list[PipelineStep]:
        return [
            PipelineStep(
                transformer_id=TransformerId.new(
                    t.source_kind(), t.sink_kind()
                ),
                backend=t.backend(),
            )
            for t in self._steps
        ]

    def crosses_process_boundary(self) -> bool:
        return any(
            t.backend() is TransformerBackend.SUBPROCESS
            for t in self._steps
        )

    def execute(self, input: ZeroCopyBuffer) -> ZeroCopyBuffer:
        current = input
        for step in self._steps:
            expected = step.source_kind()
            if current.kind != expected:
                raise KindMismatchError(expected, current.kind)
            current = step.transform(current)
        return current


__all__ = [
    "KindMismatchError",
    "NoPathError",
    "OtsError",
    "Pipeline",
    "PipelineStep",
    "TransformFailedError",
    "Transformer",
    "TransformerBackend",
    "TransformerId",
    "TransformerRegistry",
]
