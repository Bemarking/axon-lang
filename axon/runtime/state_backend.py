"""
AXON Runtime — State Backend (Continuation-Passing Style Persistence)
=====================================================================
Protocol and implementations for serializing and resuming cognitive state.

The StateBackend protocol enables the ``hibernate`` paradigm:
  1. Executor encounters an IRHibernate node
  2. Serializes the execution state (call stack, step results, context vars)
  3. Stores it via StateBackend.save_state(continuation_id, state_bytes)
  4. Returns HibernateResult to the caller
  5. On resume(continuation_id), loads state and continues execution

Two implementations:
  - InMemoryStateBackend  — testing / development (dict-based)
  - (Future) RedisStateBackend — production persistence
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════
#  EXECUTION STATE — the serializable snapshot
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ExecutionState:
    """
    A complete snapshot of a cognitive execution at a hibernate point.

    This is the continuation in CPS — everything needed to resume
    execution from exactly where it paused.
    """
    continuation_id: str = ""
    flow_name: str = ""
    event_name: str = ""
    step_index: int = 0                          # index into the flow's step list
    step_results: dict[str, Any] = field(default_factory=dict)
    context_vars: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""
    persona_name: str = ""
    context_name: str = ""
    effort: str = ""
    # ── Daemon CPS fields (AxonServer — co-inductive state) ──────
    daemon_name: str = ""                        # daemon identifier (empty for flows)
    channel_topic: str = ""                      # active listen channel topic
    event_index: int = 0                         # events processed count
    daemon_state: str = "idle"                   # idle | listening | processing | hibernating

    def serialize(self) -> bytes:
        """Serialize to JSON bytes for storage."""
        return json.dumps(asdict(self), default=str).encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> ExecutionState:
        """Deserialize from JSON bytes."""
        raw = json.loads(data.decode("utf-8"))
        return cls(**raw)


# ═══════════════════════════════════════════════════════════════════
#  STATE BACKEND PROTOCOL
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class StateBackend(Protocol):
    """
    Protocol for state persistence backends.

    All methods are async to support both in-memory and networked
    backends (Redis, Postgres, etc.) uniformly.
    """

    async def save_state(self, continuation_id: str, state: bytes) -> None:
        """Persist a serialized execution state."""
        ...

    async def load_state(self, continuation_id: str) -> bytes | None:
        """Load a previously saved state. Returns None if not found."""
        ...

    async def delete_state(self, continuation_id: str) -> None:
        """Remove a state after successful resume."""
        ...

    async def list_pending(self) -> list[str]:
        """List all continuation IDs with pending states."""
        ...


# ═══════════════════════════════════════════════════════════════════
#  IN-MEMORY BACKEND — testing and development
# ═══════════════════════════════════════════════════════════════════

class InMemoryStateBackend:
    """
    Dictionary-backed state backend for testing.

    All states are stored in a plain dict — no persistence,
    no networking. Implements StateBackend protocol.
    """

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def save_state(self, continuation_id: str, state: bytes) -> None:
        self._store[continuation_id] = state

    async def load_state(self, continuation_id: str) -> bytes | None:
        return self._store.get(continuation_id)

    async def delete_state(self, continuation_id: str) -> None:
        self._store.pop(continuation_id, None)

    async def list_pending(self) -> list[str]:
        return list(self._store.keys())
