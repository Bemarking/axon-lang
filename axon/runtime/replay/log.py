"""
ReplayLog — append / get / tokens_for_flow (Python mirror).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Optional

from axon.runtime.replay.token import ReplayToken


class ReplayLogError(Exception):
    """Raised by the log on missing tokens or backend failure."""


class ReplayLog(ABC):
    """Abstract append-only sink. Adopters implement :class:`ReplayLog`
    with a Postgres + audit-chain backend; the in-memory impl is for
    unit tests + dev."""

    @abstractmethod
    def append(self, token: ReplayToken) -> None:
        ...

    @abstractmethod
    def get(self, token_hash_hex: str) -> ReplayToken:
        ...

    @abstractmethod
    def tokens_for_flow(self, flow_id: str) -> list[ReplayToken]:
        ...


class InMemoryReplayLog(ReplayLog):
    """Dictionary-backed log. Thread-safe; rejects missing tokens."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_hash: dict[str, ReplayToken] = {}
        self._by_flow: dict[str, list[str]] = {}

    def append(self, token: ReplayToken) -> None:
        flow_id = _extract_flow_id(token)
        with self._lock:
            self._by_hash[token.token_hash_hex] = token
            self._by_flow.setdefault(flow_id, []).append(token.token_hash_hex)

    def get(self, token_hash_hex: str) -> ReplayToken:
        with self._lock:
            t = self._by_hash.get(token_hash_hex)
        if t is None:
            raise ReplayLogError(
                f"replay token {token_hash_hex!r} not found"
            )
        return t

    def tokens_for_flow(self, flow_id: str) -> list[ReplayToken]:
        with self._lock:
            hashes = list(self._by_flow.get(flow_id, ()))
            tokens = [self._by_hash[h] for h in hashes if h in self._by_hash]
        tokens.sort(key=lambda t: t.timestamp)
        return tokens

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_hash)


def _extract_flow_id(token: ReplayToken) -> str:
    """Pull the flow identifier from the token's inputs.

    Mirror of the Rust convention: check ``flow_id`` and
    ``_flow_id`` keys on ``inputs``. Empty string when absent."""
    inputs = token.inputs
    if isinstance(inputs, dict):
        fid = inputs.get("flow_id") or inputs.get("_flow_id")
        if isinstance(fid, str):
            return fid
    return ""


__all__ = [
    "InMemoryReplayLog",
    "ReplayLog",
    "ReplayLogError",
]
