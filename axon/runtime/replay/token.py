"""
ReplayToken — canonical hashing in Python (mirror of the Rust crate).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


RS = b"\x1e"


@dataclass(frozen=True, slots=True)
class SamplingParams:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    seed: Optional[int] = None
    max_tokens: Optional[int] = None
    extras: Any = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop `extras=None` so the canonical form matches the Rust
        # serde default-skip behaviour.
        if d.get("extras") is None:
            d.pop("extras", None)
        return d


@dataclass(frozen=True, slots=True)
class ReplayToken:
    effect_name: str
    inputs: Any
    inputs_hash_hex: str
    outputs: Any
    outputs_hash_hex: str
    model_version: str
    sampling: SamplingParams
    timestamp: datetime
    nonce_hex: str
    token_hash_hex: str


class ReplayTokenBuilder:
    """Ergonomic builder mirroring the Rust :class:`ReplayTokenBuilder`."""

    def __init__(self) -> None:
        self._effect_name: Optional[str] = None
        self._inputs: Any = None
        self._outputs: Any = None
        self._model_version: Optional[str] = None
        self._sampling: SamplingParams = SamplingParams()
        self._timestamp: Optional[datetime] = None
        self._nonce: Optional[bytes] = None

    def effect_name(self, name: str) -> "ReplayTokenBuilder":
        self._effect_name = name
        return self

    def inputs(self, value: Any) -> "ReplayTokenBuilder":
        self._inputs = value
        return self

    def outputs(self, value: Any) -> "ReplayTokenBuilder":
        self._outputs = value
        return self

    def model_version(self, v: str) -> "ReplayTokenBuilder":
        self._model_version = v
        return self

    def sampling(self, s: SamplingParams) -> "ReplayTokenBuilder":
        self._sampling = s
        return self

    def timestamp(self, ts: datetime) -> "ReplayTokenBuilder":
        self._timestamp = ts
        return self

    def nonce(self, bytes_: bytes) -> "ReplayTokenBuilder":
        if len(bytes_) != 16:
            raise ValueError("nonce must be 16 bytes")
        self._nonce = bytes_
        return self

    def mint(self) -> ReplayToken:
        if self._effect_name is None:
            raise ValueError("effect_name required")
        timestamp = self._timestamp or datetime.now(timezone.utc)
        nonce = self._nonce or secrets.token_bytes(16)
        inputs = self._inputs
        outputs = self._outputs
        model_version = self._model_version or "unset"
        inputs_hash_hex = canonical_hash(inputs).hex()
        outputs_hash_hex = canonical_hash(outputs).hex()
        nonce_hex = nonce.hex()
        token_hash_hex = _derive_token_hash(
            self._effect_name,
            inputs,
            outputs,
            model_version,
            self._sampling,
            timestamp,
            nonce,
        ).hex()
        return ReplayToken(
            effect_name=self._effect_name,
            inputs=inputs,
            inputs_hash_hex=inputs_hash_hex,
            outputs=outputs,
            outputs_hash_hex=outputs_hash_hex,
            model_version=model_version,
            sampling=self._sampling,
            timestamp=timestamp,
            nonce_hex=nonce_hex,
            token_hash_hex=token_hash_hex,
        )


# ── Canonical JSON hashing ──────────────────────────────────────────


def canonical_hash(value: Any) -> bytes:
    """SHA-256 of the canonical JSON encoding of ``value``."""
    encoded = _canonical_json(value)
    return hashlib.sha256(encoded.encode("utf-8")).digest()


def _canonical_json(value: Any) -> str:
    """Key-sorted JSON, no whitespace, ASCII-safe. Mirror of the
    Rust canonicaliser."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _derive_token_hash(
    effect_name: str,
    inputs: Any,
    outputs: Any,
    model_version: str,
    sampling: SamplingParams,
    timestamp: datetime,
    nonce: bytes,
) -> bytes:
    h = hashlib.sha256()
    h.update(effect_name.encode("utf-8"))
    h.update(RS)
    h.update(_canonical_json(inputs).encode("utf-8"))
    h.update(RS)
    h.update(_canonical_json(outputs).encode("utf-8"))
    h.update(RS)
    h.update(model_version.encode("utf-8"))
    h.update(RS)
    h.update(_canonical_json(sampling.as_dict()).encode("utf-8"))
    h.update(RS)
    # Normalise timestamp to RFC 3339 with offset.
    h.update(_timestamp_rfc3339(timestamp).encode("utf-8"))
    h.update(RS)
    h.update(nonce)
    return h.digest()


def _timestamp_rfc3339(ts: datetime) -> str:
    """Match chrono's to_rfc3339 output (second precision with offset)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    # chrono prints `+00:00` for UTC, not `Z`.
    iso = ts.isoformat()
    if iso.endswith("+00:00"):
        return iso
    return iso


__all__ = [
    "ReplayToken",
    "ReplayTokenBuilder",
    "SamplingParams",
    "canonical_hash",
]
