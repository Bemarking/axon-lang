"""
AXON Runtime — Stream[T] + closed backpressure catalogue (§λ-L-E Fase 11.a).
===========================================================================

Python reference implementation of the Rust ``Stream<T>`` runtime in
``axon-rs/src/stream_runtime.rs``. Keeps parity with the four closed
backpressure policies: ``DropOldest``, ``DegradeQuality``,
``PauseUpstream``, ``Fail``.

Distinct from ``axon/runtime/streaming.py`` (which is the semantic /
epistemic LLM-token streaming engine). This module is the **byte /
frame / event-level** primitive consumed by websocket ingest,
microphone taps, multipart uploads, etc.

Every ``Stream[T]`` declaration MUST carry a
``BackpressureAnnotation``. The Axon compiler rejects constructions
without one; the runtime additionally asserts at instantiation time
so adopter code that bypasses the compiler still fails closed.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generic, Optional, TypeVar

# ── Closed backpressure catalogue ─────────────────────────────────────


class BackpressurePolicy(str, Enum):
    """Mirror of ``axon::stream_effect::BackpressurePolicy`` in Rust."""

    DROP_OLDEST = "drop_oldest"
    DEGRADE_QUALITY = "degrade_quality"
    PAUSE_UPSTREAM = "pause_upstream"
    FAIL = "fail"


BACKPRESSURE_CATALOG: tuple[str, ...] = (
    BackpressurePolicy.DROP_OLDEST.value,
    BackpressurePolicy.DEGRADE_QUALITY.value,
    BackpressurePolicy.PAUSE_UPSTREAM.value,
    BackpressurePolicy.FAIL.value,
)


def is_backpressure_policy(slug: str) -> bool:
    return slug in BACKPRESSURE_CATALOG


@dataclass(frozen=True, slots=True)
class BackpressureAnnotation:
    """Declared policy + adopter-specific options (e.g. ``buffer_size``,
    ``resample_to``). Mirror of the Rust annotation struct."""

    policy: BackpressurePolicy
    options: tuple[tuple[str, str], ...] = ()


def parse_backpressure_annotation(
    body: str,
) -> Optional[BackpressureAnnotation]:
    """Parse a ``@backpressure(...)`` annotation body. Returns ``None``
    when the policy slug is unknown, so the checker can emit a
    targeted error message."""
    parts = [p.strip() for p in body.split(",")]
    if not parts:
        return None
    slug = parts[0]
    if slug not in BACKPRESSURE_CATALOG:
        return None
    try:
        policy = BackpressurePolicy(slug)
    except ValueError:
        return None
    options: list[tuple[str, str]] = []
    for raw in parts[1:]:
        if not raw:
            continue
        if "=" not in raw:
            return None
        k, _, v = raw.partition("=")
        options.append((k.strip(), v.strip()))
    return BackpressureAnnotation(policy=policy, options=tuple(options))


# ── Errors + metrics ──────────────────────────────────────────────────


class StreamError(Exception):
    """Raised when a push fails or the stream is cancelled."""


@dataclass
class StreamMetrics:
    """Counter-only metrics; snapshot via :meth:`snapshot`."""

    items_pushed: int = 0
    items_delivered: int = 0
    drop_oldest_hits: int = 0
    degrade_quality_hits: int = 0
    pause_upstream_blocks: int = 0
    fail_overflows: int = 0

    def snapshot(self) -> "StreamMetrics":
        return StreamMetrics(
            items_pushed=self.items_pushed,
            items_delivered=self.items_delivered,
            drop_oldest_hits=self.drop_oldest_hits,
            degrade_quality_hits=self.degrade_quality_hits,
            pause_upstream_blocks=self.pause_upstream_blocks,
            fail_overflows=self.fail_overflows,
        )


# ── The stream itself ─────────────────────────────────────────────────

T = TypeVar("T")
DegradationFn = Callable[[T], T]


class Stream(Generic[T]):
    """Bounded async stream with a declared backpressure policy.

    Instantiate via :meth:`new` (three of the four policies) or
    :meth:`with_degrader` (``DegradeQuality``). The constructor is
    intentionally not part of the public surface; the classmethod
    shortcuts enforce the policy-vs-degrader invariant.
    """

    __slots__ = (
        "_buffer",
        "_capacity",
        "_closed",
        "_annotation",
        "_policy",
        "_degrader",
        "_not_empty",
        "_not_full",
        "metrics",
    )

    def __init__(
        self,
        capacity: int,
        annotation: BackpressureAnnotation,
        degrader: Optional[DegradationFn] = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("Stream capacity must be positive")
        if annotation.policy == BackpressurePolicy.DEGRADE_QUALITY and degrader is None:
            raise ValueError(
                "Stream(DegradeQuality) requires a `degrader` callable"
            )
        self._buffer: deque[T] = deque()
        self._capacity = capacity
        self._closed = False
        self._annotation = annotation
        self._policy = annotation.policy
        self._degrader = degrader
        self._not_empty = asyncio.Event()
        self._not_full = asyncio.Event()
        self._not_full.set()  # buffer starts empty → producers may push
        self.metrics = StreamMetrics()

    # ── Constructors ──────────────────────────────────────────────

    @classmethod
    def new(
        cls, capacity: int, annotation: BackpressureAnnotation
    ) -> "Stream[T]":
        if annotation.policy == BackpressurePolicy.DEGRADE_QUALITY:
            raise ValueError(
                "use Stream.with_degrader(...) for DegradeQuality"
            )
        return cls(capacity, annotation)

    @classmethod
    def with_degrader(
        cls,
        capacity: int,
        annotation: BackpressureAnnotation,
        degrader: DegradationFn,
    ) -> "Stream[T]":
        if annotation.policy != BackpressurePolicy.DEGRADE_QUALITY:
            raise ValueError(
                "with_degrader(...) requires policy == degrade_quality"
            )
        return cls(capacity, annotation, degrader=degrader)

    # ── Accessors ─────────────────────────────────────────────────

    @property
    def policy(self) -> BackpressurePolicy:
        return self._policy

    @property
    def annotation(self) -> BackpressureAnnotation:
        return self._annotation

    async def depth(self) -> int:
        return len(self._buffer)

    # ── Push / pop ────────────────────────────────────────────────

    async def push(self, item: T) -> None:
        self.metrics.items_pushed += 1
        if self._closed:
            raise StreamError("stream cancelled")
        if self._policy == BackpressurePolicy.DROP_OLDEST:
            await self._push_drop_oldest(item)
        elif self._policy == BackpressurePolicy.DEGRADE_QUALITY:
            await self._push_degrade_quality(item)
        elif self._policy == BackpressurePolicy.PAUSE_UPSTREAM:
            await self._push_pause_upstream(item)
        elif self._policy == BackpressurePolicy.FAIL:
            await self._push_fail(item)
        else:  # pragma: no cover — exhaustive enum
            raise StreamError(f"unknown policy {self._policy!r}")

    async def _push_drop_oldest(self, item: T) -> None:
        if len(self._buffer) >= self._capacity:
            self._buffer.popleft()
            self.metrics.drop_oldest_hits += 1
        self._buffer.append(item)
        self._not_empty.set()

    async def _push_degrade_quality(self, item: T) -> None:
        assert self._degrader is not None  # constructor invariant
        if len(self._buffer) >= self._capacity:
            self.metrics.degrade_quality_hits += 1
            self._buffer.popleft()
            item = self._degrader(item)
        self._buffer.append(item)
        self._not_empty.set()

    async def _push_pause_upstream(self, item: T) -> None:
        while len(self._buffer) >= self._capacity:
            self.metrics.pause_upstream_blocks += 1
            self._not_full.clear()
            await self._not_full.wait()
            if self._closed:
                raise StreamError("stream cancelled")
        self._buffer.append(item)
        self._not_empty.set()

    async def _push_fail(self, item: T) -> None:
        if len(self._buffer) >= self._capacity:
            self.metrics.fail_overflows += 1
            raise StreamError(
                f"stream overflow under policy {self._policy.value} "
                f"(capacity={self._capacity})"
            )
        self._buffer.append(item)
        self._not_empty.set()

    async def pop(self) -> Optional[T]:
        while not self._buffer:
            if self._closed:
                return None
            self._not_empty.clear()
            await self._not_empty.wait()
        item = self._buffer.popleft()
        self.metrics.items_delivered += 1
        if len(self._buffer) < self._capacity:
            self._not_full.set()
        return item

    async def close(self) -> None:
        self._closed = True
        self._not_empty.set()
        self._not_full.set()


__all__ = [
    "BACKPRESSURE_CATALOG",
    "BackpressureAnnotation",
    "BackpressurePolicy",
    "DegradationFn",
    "Stream",
    "StreamError",
    "StreamMetrics",
    "is_backpressure_policy",
    "parse_backpressure_annotation",
]
