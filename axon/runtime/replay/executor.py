"""
ReplayExecutor — re-run a token through an adopter-supplied invoker,
report match / divergence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Union

from axon.runtime.replay.log import ReplayLog, ReplayLogError
from axon.runtime.replay.token import (
    ReplayToken,
    SamplingParams,
    canonical_hash,
)


class EffectInvokerError(Exception):
    """Raised when the adopter's invoker cannot replay the effect."""


class EffectInvoker(ABC):
    """Adopter implements this trait with their dispatcher of choice
    (LangChain, custom HTTP client, DB driver, …)."""

    @abstractmethod
    def invoke(
        self,
        effect_name: str,
        inputs: Any,
        model_version: str,
        sampling: SamplingParams,
    ) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class ReplayDivergence:
    expected_outputs_hash_hex: str
    actual_outputs_hash_hex: str
    actual_outputs: Any


@dataclass(frozen=True, slots=True)
class ReplayMatch:
    token_hash_hex: str


@dataclass(frozen=True, slots=True)
class ReplayMismatch:
    token_hash_hex: str
    divergence: ReplayDivergence


#: Outcome of a single replay. ``ReplayMatch`` iff the recomputed
#: outputs hash to the same value the token recorded.
ReplayOutcome = Union[ReplayMatch, ReplayMismatch]


class ReplayExecutorError(Exception):
    """Raised when replay cannot complete (log / invoker failure)."""


@dataclass
class ReplayExecutor:
    log: ReplayLog
    invoker: EffectInvoker

    def replay_token(self, token_hash_hex: str) -> ReplayOutcome:
        try:
            token = self.log.get(token_hash_hex)
        except ReplayLogError as exc:
            raise ReplayExecutorError(str(exc)) from exc
        return self.verify_token(token)

    def replay_flow(self, flow_id: str) -> list[ReplayOutcome]:
        outcomes: list[ReplayOutcome] = []
        for t in self.log.tokens_for_flow(flow_id):
            outcome = self.verify_token(t)
            outcomes.append(outcome)
            if isinstance(outcome, ReplayMismatch):
                break
        return outcomes

    def verify_token(self, token: ReplayToken) -> ReplayOutcome:
        try:
            actual = self.invoker.invoke(
                token.effect_name,
                token.inputs,
                token.model_version,
                token.sampling,
            )
        except EffectInvokerError as exc:
            raise ReplayExecutorError(str(exc)) from exc
        actual_hash = canonical_hash(actual).hex()
        if actual_hash == token.outputs_hash_hex:
            return ReplayMatch(token_hash_hex=token.token_hash_hex)
        return ReplayMismatch(
            token_hash_hex=token.token_hash_hex,
            divergence=ReplayDivergence(
                expected_outputs_hash_hex=token.outputs_hash_hex,
                actual_outputs_hash_hex=actual_hash,
                actual_outputs=actual,
            ),
        )


ReplayOutcome = Union[ReplayMatch, ReplayMismatch]  # type: ignore[misc]


__all__ = [
    "EffectInvoker",
    "EffectInvokerError",
    "ReplayDivergence",
    "ReplayExecutor",
    "ReplayExecutorError",
    "ReplayMatch",
    "ReplayMismatch",
    "ReplayOutcome",
]
