"""
Fase 13.k — Cross-process exactly-once via ReplayLog
====================================================
Closes the deferred case in ``TypedEventBus._dispatch``: pre-13.k the
exactly_once QoS branch deduplicated by ``event_id`` only inside a
single process. Cross-process exactly-once required Fase 11.c
ReplayLog integration — the comment at typed.py noted this as
deferred. 13.k wires it: ``TypedEventBus`` accepts an optional
``replay_log: ReplayLog`` and on the exactly_once path mints a
deterministic ReplayToken keyed on ``(channel, event_id)`` (nonce
derived from event_id, timestamp fixed at the Unix epoch). That gives
both replicas the same ``token_hash_hex`` so the second replica's
``log.get(hash)`` resolves and the duplicate publish is skipped.

The InMemoryReplayLog is sufficient to exercise the contract — two
buses sharing the same in-memory log behave like two processes
sharing a Postgres-backed log. The Postgres backend that adopters
plug into production is a drop-in replacement.
"""

from __future__ import annotations

import asyncio

import pytest

from axon.runtime.channels.typed import (
    TypedChannelHandle, TypedChannelRegistry, TypedEventBus,
)
from axon.runtime.event_bus import Event
from axon.runtime.replay.log import InMemoryReplayLog


def _async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _bus_with_log(channels, log: InMemoryReplayLog) -> TypedEventBus:
    """Build a TypedEventBus pre-loaded with the given exactly_once
    channels and wired to the shared log."""
    registry = TypedChannelRegistry()
    for name in channels:
        registry.register(TypedChannelHandle(
            name=name, message="Bytes", qos="exactly_once",
        ))
    return TypedEventBus(registry, replay_log=log)


# ═══════════════════════════════════════════════════════════════════
#  13.k.1 — Token determinism: same (channel, event_id) → same hash
# ═══════════════════════════════════════════════════════════════════


class TestReplayTokenDeterminism:
    def test_same_channel_event_id_yields_identical_token_hash(self):
        log = InMemoryReplayLog()
        bus_a = _bus_with_log(["Orders"], log)
        bus_b = _bus_with_log(["Orders"], log)
        # Synthesise two distinct Event instances with identical
        # event_ids — simulates two replicas observing the same
        # upstream event.
        event = Event(topic="Orders", payload={"x": 1}, event_id="evt-42")
        tok_a = bus_a._replay_token_for("Orders", event)
        tok_b = bus_b._replay_token_for("Orders", event)
        assert tok_a.token_hash_hex == tok_b.token_hash_hex

    def test_different_event_ids_yield_different_token_hashes(self):
        log = InMemoryReplayLog()
        bus = _bus_with_log(["Orders"], log)
        e1 = Event(topic="Orders", payload={}, event_id="evt-1")
        e2 = Event(topic="Orders", payload={}, event_id="evt-2")
        h1 = bus._replay_token_for("Orders", e1).token_hash_hex
        h2 = bus._replay_token_for("Orders", e2).token_hash_hex
        assert h1 != h2

    def test_different_channels_same_event_id_yield_different_hashes(self):
        log = InMemoryReplayLog()
        bus = _bus_with_log(["Orders", "Audit"], log)
        e = Event(topic="ignored", payload={}, event_id="evt-shared")
        h_orders = bus._replay_token_for("Orders", e).token_hash_hex
        h_audit = bus._replay_token_for("Audit", e).token_hash_hex
        # Different channel → different token even with same event_id.
        assert h_orders != h_audit

    def test_token_excludes_payload_from_hash(self):
        """Adopters can re-emit with a different payload bound to the
        same event_id — exactly-once is a (channel, event_id) contract,
        not a (channel, event_id, payload) contract. The token hash
        must not depend on the payload (also keeps the audit log free
        of payload leakage)."""
        log = InMemoryReplayLog()
        bus = _bus_with_log(["Orders"], log)
        e1 = Event(topic="Orders", payload={"x": 1}, event_id="same")
        e2 = Event(topic="Orders", payload={"y": 2}, event_id="same")
        h1 = bus._replay_token_for("Orders", e1).token_hash_hex
        h2 = bus._replay_token_for("Orders", e2).token_hash_hex
        assert h1 == h2


# ═══════════════════════════════════════════════════════════════════
#  13.k.2 — In-process: explicit dedup via the log path is correct
# ═══════════════════════════════════════════════════════════════════


class TestSingleProcessExactlyOnceWithLog:
    def test_first_emit_publishes_and_records(self):
        log = InMemoryReplayLog()
        bus = _bus_with_log(["Orders"], log)
        _async(bus.emit("Orders", {"id": 1}))
        # Event reached the underlying transport.
        assert len(log) == 1
        # Receive succeeds.
        ev = _async(bus.receive("Orders"))
        assert ev.payload == {"id": 1}

    def test_dedup_predicate_prevents_double_record_for_same_event_id(self):
        """If the bus is asked to re-deliver an Event with an event_id
        already in the log, the dispatch path skips the publish and
        does not append a duplicate token. Verifies both halves of
        the contract together."""
        log = InMemoryReplayLog()
        bus = _bus_with_log(["Orders"], log)
        synth_event = Event(topic="Orders", payload={"id": 7}, event_id="fixed")
        handle = bus.registry.get("Orders")
        _async(bus._dispatch(handle, synth_event))
        assert len(log) == 1
        # Replay the same event — second call must be a no-op.
        _async(bus._dispatch(handle, synth_event))
        assert len(log) == 1, "log must not grow on duplicate event_id"


# ═══════════════════════════════════════════════════════════════════
#  13.k.3 — Cross-process: two buses sharing one log dedup events
# ═══════════════════════════════════════════════════════════════════


class TestCrossProcessExactlyOnceViaSharedLog:
    """Two TypedEventBus instances sharing the same InMemoryReplayLog
    behave like two replicas sharing a Postgres-backed ReplayLog. If
    replica A delivers the event first, replica B's dispatch with the
    same event_id must be skipped."""

    def test_replica_b_skips_duplicate_after_replica_a_records(self):
        log = InMemoryReplayLog()
        bus_a = _bus_with_log(["Orders"], log)
        bus_b = _bus_with_log(["Orders"], log)
        synth = Event(topic="Orders", payload={"id": 99}, event_id="evt-X")
        # Replica A delivers and records.
        _async(bus_a._dispatch(bus_a.registry.get("Orders"), synth))
        assert len(log) == 1
        # Replica B sees the same event — must skip.
        _async(bus_b._dispatch(bus_b.registry.get("Orders"), synth))
        assert len(log) == 1, "shared log must reject duplicate from replica B"
        # And replica B's own underlying transport received nothing.
        # (We cannot easily peek at internal queue lengths, but we can
        # assert that a receive on replica B blocks indefinitely without
        # the duplicate having been dispatched.)
        try:
            ev = _async(asyncio.wait_for(bus_b.receive("Orders"), timeout=0.05))
            pytest.fail(f"replica B should not have received anything, got {ev}")
        except asyncio.TimeoutError:
            pass  # expected — no event delivered to bus_b

    def test_distinct_event_ids_are_both_delivered(self):
        """Different event_ids on the same channel are not duplicates;
        both replicas can each deliver one and the log holds two."""
        log = InMemoryReplayLog()
        bus_a = _bus_with_log(["Orders"], log)
        bus_b = _bus_with_log(["Orders"], log)
        e1 = Event(topic="Orders", payload={"id": 1}, event_id="evt-1")
        e2 = Event(topic="Orders", payload={"id": 2}, event_id="evt-2")
        _async(bus_a._dispatch(bus_a.registry.get("Orders"), e1))
        _async(bus_b._dispatch(bus_b.registry.get("Orders"), e2))
        assert len(log) == 2

    def test_no_log_falls_back_to_in_process_dedup(self):
        """When ``replay_log`` is not wired, exactly_once retains the
        legacy in-process behaviour (event_id set per channel). Tests
        in v1.5.x continue to pass."""
        registry = TypedChannelRegistry()
        registry.register(TypedChannelHandle(
            name="Orders", message="Bytes", qos="exactly_once",
        ))
        bus = TypedEventBus(registry)  # no replay_log
        synth = Event(topic="Orders", payload={"id": 1}, event_id="evt")
        handle = bus.registry.get("Orders")
        _async(bus._dispatch(handle, synth))
        # Second dispatch with the same event_id is dropped via the
        # in-process dedup set; receive yields exactly one event.
        _async(bus._dispatch(handle, synth))
        ev = _async(bus.receive("Orders"))
        assert ev.event_id == "evt"
        # No second event queued.
        try:
            _async(asyncio.wait_for(bus.receive("Orders"), timeout=0.05))
            pytest.fail("in-process dedup failed — duplicate delivered")
        except asyncio.TimeoutError:
            pass
