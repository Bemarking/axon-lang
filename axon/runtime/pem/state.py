"""
CognitiveState + Q32.32 fixed-point floats (Python mirror).

The wire format is JSON so `CognitiveState.encode()` in Rust and
Python produce byte-identical output for identical inputs — the
parity harness asserts this.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


Q32_32_SCALE: float = 4_294_967_296.0  # 1 << 32


@dataclass(frozen=True, slots=True)
class FixedPoint:
    """Q32.32 fixed-point scalar. Serialises as a bare integer."""

    value: int

    @classmethod
    def from_f64(cls, v: float) -> "FixedPoint":
        scaled = v * Q32_32_SCALE
        # Clamp to i64 range; matches Rust's `.clamp(i64::MIN, i64::MAX)`.
        clamped = max(-(2**63), min(scaled, 2**63 - 1))
        return cls(int(clamped))

    def to_f64(self) -> float:
        return self.value / Q32_32_SCALE

    @classmethod
    def vec_from_f64(cls, vs: list[float]) -> list["FixedPoint"]:
        return [cls.from_f64(v) for v in vs]

    @classmethod
    def vec_to_f64(cls, vs: list["FixedPoint"]) -> list[float]:
        return [v.to_f64() for v in vs]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    key: str
    payload: Any
    symbolic_refs: list[str]
    stored_at: datetime


class StateDecodeError(Exception):
    """Raised when :meth:`CognitiveState.decode` can't parse the payload."""


@dataclass
class CognitiveState:
    """Snapshot-able agent posture. See :mod:`axon.runtime.pem`."""

    session_id: str
    tenant_id: str
    flow_id: str
    subject_user_id: Optional[str] = None
    density_matrix: list[list[FixedPoint]] = field(default_factory=list)
    belief_state: Any = None
    short_term_memory: list[MemoryEntry] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Encode / decode ─────────────────────────────────────────

    def encode(self) -> bytes:
        """Canonical JSON bytes — key-sorted, no whitespace, same
        settings as the 10.g audit-chain canonicaliser so consumers
        that already parse audit events can parse snapshots too."""
        return json.dumps(
            _to_wire(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "CognitiveState":
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateDecodeError(
                f"cognitive state decode failed: {exc}"
            ) from exc
        return _from_wire(raw)


# ── Wire translation ──────────────────────────────────────────────────


def _to_wire(s: CognitiveState) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "tenant_id": s.tenant_id,
        "flow_id": s.flow_id,
        "subject_user_id": s.subject_user_id,
        "density_matrix": [
            [q.value for q in row] for row in s.density_matrix
        ],
        "belief_state": s.belief_state,
        "short_term_memory": [
            {
                "key": m.key,
                "payload": m.payload,
                "symbolic_refs": list(m.symbolic_refs),
                "stored_at": int(m.stored_at.timestamp() * 1000),
            }
            for m in s.short_term_memory
        ],
        "created_at": int(s.created_at.timestamp() * 1000),
        "last_updated_at": int(s.last_updated_at.timestamp() * 1000),
    }


def _from_wire(raw: dict[str, Any]) -> CognitiveState:
    try:
        return CognitiveState(
            session_id=raw["session_id"],
            tenant_id=raw["tenant_id"],
            flow_id=raw["flow_id"],
            subject_user_id=raw.get("subject_user_id"),
            density_matrix=[
                [FixedPoint(int(v)) for v in row]
                for row in raw.get("density_matrix", [])
            ],
            belief_state=raw.get("belief_state"),
            short_term_memory=[
                MemoryEntry(
                    key=m["key"],
                    payload=m.get("payload"),
                    symbolic_refs=list(m.get("symbolic_refs", [])),
                    stored_at=datetime.fromtimestamp(
                        m["stored_at"] / 1000, tz=timezone.utc
                    ),
                )
                for m in raw.get("short_term_memory", [])
            ],
            created_at=datetime.fromtimestamp(
                raw["created_at"] / 1000, tz=timezone.utc
            ),
            last_updated_at=datetime.fromtimestamp(
                raw["last_updated_at"] / 1000, tz=timezone.utc
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StateDecodeError(
            f"cognitive state decode failed: {exc}"
        ) from exc


__all__ = [
    "CognitiveState",
    "FixedPoint",
    "MemoryEntry",
    "Q32_32_SCALE",
    "StateDecodeError",
]
