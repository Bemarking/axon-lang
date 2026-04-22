"""
Unit tests — §λ-L-E Fase 11.a Stream<T> + backpressure catalogue.
"""

from __future__ import annotations

import asyncio

import pytest

from axon.runtime.stream_primitive import (
    BACKPRESSURE_CATALOG,
    BackpressureAnnotation,
    BackpressurePolicy,
    Stream,
    StreamError,
    is_backpressure_policy,
    parse_backpressure_annotation,
)


# ── Catalogue invariants ──────────────────────────────────────────────


def test_catalog_contains_exactly_the_four_policies() -> None:
    assert set(BACKPRESSURE_CATALOG) == {
        "drop_oldest",
        "degrade_quality",
        "pause_upstream",
        "fail",
    }
    # Stable order — Rust mirror depends on it.
    assert BACKPRESSURE_CATALOG == (
        "drop_oldest",
        "degrade_quality",
        "pause_upstream",
        "fail",
    )


def test_is_backpressure_policy() -> None:
    for slug in BACKPRESSURE_CATALOG:
        assert is_backpressure_policy(slug)
    assert not is_backpressure_policy("retry_forever")
    assert not is_backpressure_policy("DROP_OLDEST")  # case-sensitive


# ── Annotation parser ────────────────────────────────────────────────


def test_parse_annotation_minimal() -> None:
    ann = parse_backpressure_annotation("drop_oldest")
    assert ann is not None
    assert ann.policy is BackpressurePolicy.DROP_OLDEST
    assert ann.options == ()


def test_parse_annotation_with_options() -> None:
    ann = parse_backpressure_annotation(
        "degrade_quality, resample_to=8000, codec=mulaw"
    )
    assert ann is not None
    assert ann.policy is BackpressurePolicy.DEGRADE_QUALITY
    assert ann.options == (
        ("resample_to", "8000"),
        ("codec", "mulaw"),
    )


def test_parse_annotation_rejects_unknown_policy() -> None:
    assert parse_backpressure_annotation("retry_forever") is None


def test_parse_annotation_rejects_malformed_option() -> None:
    # Option without '=' is rejected so the checker can complain.
    assert parse_backpressure_annotation("drop_oldest, no_equals") is None


# ── Stream constructor invariants ────────────────────────────────────


def test_constructor_rejects_degrade_quality_without_degrader() -> None:
    ann = BackpressureAnnotation(policy=BackpressurePolicy.DEGRADE_QUALITY)
    with pytest.raises(ValueError, match="degrader"):
        Stream(capacity=2, annotation=ann)


def test_new_rejects_degrade_quality_policy() -> None:
    ann = BackpressureAnnotation(policy=BackpressurePolicy.DEGRADE_QUALITY)
    with pytest.raises(ValueError, match="with_degrader"):
        Stream.new(capacity=2, annotation=ann)


def test_with_degrader_rejects_non_degrade_policy() -> None:
    ann = BackpressureAnnotation(policy=BackpressurePolicy.DROP_OLDEST)
    with pytest.raises(ValueError, match="degrade_quality"):
        Stream.with_degrader(capacity=2, annotation=ann, degrader=lambda x: x)


# ── Policy behaviour under saturation ────────────────────────────────


def _ann(slug: str) -> BackpressureAnnotation:
    parsed = parse_backpressure_annotation(slug)
    assert parsed is not None
    return parsed


@pytest.mark.asyncio
async def test_drop_oldest_replaces_oldest_under_pressure() -> None:
    s: Stream[int] = Stream.new(capacity=2, annotation=_ann("drop_oldest"))
    await s.push(1)
    await s.push(2)
    await s.push(3)  # triggers drop_oldest -> removes 1
    assert await s.pop() == 2
    assert await s.pop() == 3
    m = s.metrics.snapshot()
    assert m.drop_oldest_hits == 1
    assert m.items_pushed == 3
    assert m.items_delivered == 2


@pytest.mark.asyncio
async def test_degrade_quality_applies_degrader_on_overflow() -> None:
    ann = _ann("degrade_quality")
    s: Stream[int] = Stream.with_degrader(
        capacity=2, annotation=ann, degrader=lambda x: x // 2
    )
    await s.push(100)
    await s.push(200)
    await s.push(300)  # overflow -> 300 // 2 pushed
    assert await s.pop() == 200
    assert await s.pop() == 150
    assert s.metrics.snapshot().degrade_quality_hits == 1


@pytest.mark.asyncio
async def test_pause_upstream_blocks_until_consumer_drains() -> None:
    s: Stream[int] = Stream.new(capacity=1, annotation=_ann("pause_upstream"))
    await s.push(1)

    async def consumer() -> int | None:
        await asyncio.sleep(0.05)
        return await s.pop()

    task = asyncio.create_task(consumer())
    await s.push(2)  # blocks until consumer drains
    assert await task == 1
    assert await s.pop() == 2
    assert s.metrics.snapshot().pause_upstream_blocks >= 1


@pytest.mark.asyncio
async def test_fail_policy_raises_on_overflow() -> None:
    s: Stream[int] = Stream.new(capacity=1, annotation=_ann("fail"))
    await s.push(1)
    with pytest.raises(StreamError, match="overflow"):
        await s.push(2)
    assert s.metrics.snapshot().fail_overflows == 1


@pytest.mark.asyncio
async def test_close_drains_then_signals_end() -> None:
    s: Stream[int] = Stream.new(capacity=4, annotation=_ann("fail"))
    await s.push(1)
    await s.push(2)
    await s.close()
    assert await s.pop() == 1
    assert await s.pop() == 2
    assert await s.pop() is None  # closed + drained


@pytest.mark.asyncio
async def test_push_after_close_errors() -> None:
    s: Stream[int] = Stream.new(capacity=4, annotation=_ann("fail"))
    await s.close()
    with pytest.raises(StreamError, match="cancelled"):
        await s.push(99)
