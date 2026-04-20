"""
AXON Runtime — Handler Base Interface
=======================================
The Free Monad interpreter for the I/O Cognitivo Intention Tree.

This module defines the abstract Handler protocol used to β-reduce the
`IRIntentionTree` (Fase 1) into physical side effects.  A Handler receives
pure intentions (`IRManifest`, `IRObserve`) and produces concrete outcomes
wrapped in the Lambda Data envelope E = ⟨c, τ, ρ, δ⟩.

Design anchors (from docs/plan_io_cognitivo.md):
  • D1 — Free Monads + Handlers (CPS).  The Axon program returns a pure
         Intention Tree F_Σ(X); a Handler interprets it into the physical
         world via Continuation-Passing Style.
  • D4 — Partition semantics.  A network partition is the bottom of the
         epistemic lattice (⊥, c=0.0) and raises a structural CT-3
         exception — it is NEVER silently downgraded to `doubt`.
  • D5 — Curry-Howard (λ-L-E).  Every HandlerOutcome is the phenomenal
         evaluation of a constructive proof of resource existence.

Pipeline position:
  Source → Parser → Type Checker → IR Generator → **Handler** → physical I/O
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from axon.compiler.ir_nodes import (
    IRFabric,
    IRIntentionTree,
    IRManifest,
    IRNode,
    IRObserve,
    IRProgram,
    IRResource,
)


# ═══════════════════════════════════════════════════════════════════
#  ΛD ENVELOPE — Lambda Data epistemic vector
# ═══════════════════════════════════════════════════════════════════

DerivationKind = str
"""One of: 'axiomatic' | 'observed' | 'inferred' | 'mutated'."""

_VALID_DERIVATIONS = frozenset({"axiomatic", "observed", "inferred", "mutated"})


@dataclass(frozen=True)
class LambdaEnvelope:
    """
    E = ⟨c, τ, ρ, δ⟩ — the epistemic envelope wrapping every handler output.

    Fields
    ------
    c : float
        Certainty in [0.0, 1.0]. 1.0 = `know`, 0.0 = `void` (⊥).
    tau : str
        Temporal frame — ISO-8601 UTC timestamp of the observation.
        Materializes Decision D2: if a lease's τ expires, c → 0.0.
    rho : str
        Provenance — the handler identifier plus optional cryptographic
        signature (cryptographic signing is scoped to Fase 6.2).
    delta : str
        Derivation — axiomatic | observed | inferred | mutated.
    """
    c: float = 1.0
    tau: str = ""
    rho: str = ""
    delta: DerivationKind = "observed"

    def __post_init__(self) -> None:
        if not 0.0 <= self.c <= 1.0:
            raise ValueError(
                f"LambdaEnvelope.c must be in [0.0, 1.0]; got {self.c}"
            )
        if self.delta not in _VALID_DERIVATIONS:
            raise ValueError(
                f"LambdaEnvelope.delta must be one of {sorted(_VALID_DERIVATIONS)}; "
                f"got '{self.delta}'"
            )

    def decayed(self, to_certainty: float = 0.0) -> "LambdaEnvelope":
        """Return a copy with certainty reduced — used when a lease expires."""
        return LambdaEnvelope(c=to_certainty, tau=self.tau, rho=self.rho, delta=self.delta)

    def to_dict(self) -> dict[str, Any]:
        return {"c": self.c, "tau": self.tau, "rho": self.rho, "delta": self.delta}


def now_iso() -> str:
    """Current UTC timestamp in ISO-8601 for ΛD τ frames."""
    return datetime.now(timezone.utc).isoformat()


def make_envelope(
    c: float = 1.0,
    rho: str = "",
    delta: DerivationKind = "observed",
    tau: str | None = None,
) -> LambdaEnvelope:
    """Construct a ΛD envelope with either the supplied τ or the current one."""
    return LambdaEnvelope(c=c, tau=tau or now_iso(), rho=rho, delta=delta)


# ═══════════════════════════════════════════════════════════════════
#  BLAME CALCULUS — Findler-Felleisen CT-1/CT-2/CT-3 error taxonomy
# ═══════════════════════════════════════════════════════════════════

BLAME_CALLEE = "CT-1"
"""CT-1: the handler/runtime itself is broken (bug on Axon side)."""

BLAME_CALLER = "CT-2"
"""CT-2: the Axon program made an invalid request (anchor breach, lease expired, invalid manifest)."""

BLAME_INFRASTRUCTURE = "CT-3"
"""CT-3: the physical world cannot answer (partition, quota, missing credentials)."""


class HandlerError(Exception):
    """Base class for every handler-emitted error. Always carries a blame tag."""

    blame: str = "unknown"

    def __init__(
        self,
        message: str,
        *,
        blame: str = "unknown",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.blame = blame
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"[{self.blame}] {super().__str__()}"


class CalleeBlameError(HandlerError):
    """CT-1: the handler implementation is broken. Always a bug."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, blame=BLAME_CALLEE, cause=cause)


class CallerBlameError(HandlerError):
    """
    CT-2: the Axon program made an invalid request.
    Triggered by anchor breaches, lease expirations, invalid manifest references.
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, blame=BLAME_CALLER, cause=cause)


class InfrastructureBlameError(HandlerError):
    """
    CT-3: the physical world cannot answer.
    Triggered by network partitions, missing credentials, provider quotas.
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, blame=BLAME_INFRASTRUCTURE, cause=cause)


class NetworkPartitionError(InfrastructureBlameError):
    """
    Decision D4: a network partition is the void ⊥ = c=0.0, NEVER a `doubt`.
    Raised when a handler cannot reach the physical substrate.
    """


class LeaseExpiredError(CallerBlameError):
    """
    Decision D2: if the τ on a lease has elapsed, the resource token decayed
    to c=0.0 and any use is an Anchor Breach (CT-2).
    """


class HandlerUnavailableError(InfrastructureBlameError):
    """
    CT-3: the handler's backing SDK/binary is not installed or configured.
    Raised with an install hint so the operator can remediate.
    """


# ═══════════════════════════════════════════════════════════════════
#  HANDLER OUTCOME — the CPS return type
# ═══════════════════════════════════════════════════════════════════

OutcomeStatus = str
"""One of: 'ok' | 'partial' | 'failed'."""

_VALID_STATUSES = frozenset({"ok", "partial", "failed"})


@dataclass(frozen=True)
class HandlerOutcome:
    """
    The result of β-reducing one Intention Tree node through a Handler.

    The envelope carries the ΛD vector; `data` contains handler-specific
    artifacts (resource IDs, state snapshots, diagnostics).  The outcome is
    immutable so it can safely be shared across continuations.
    """
    operation: str
    target: str
    status: OutcomeStatus
    envelope: LambdaEnvelope
    data: dict[str, Any] = field(default_factory=dict)
    handler: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"HandlerOutcome.status must be one of {sorted(_VALID_STATUSES)}; "
                f"got '{self.status}'"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target": self.target,
            "status": self.status,
            "handler": self.handler,
            "envelope": self.envelope.to_dict(),
            "data": dict(self.data),
        }


# ═══════════════════════════════════════════════════════════════════
#  HANDLER INTERFACE — the abstract Free-Monad interpreter
# ═══════════════════════════════════════════════════════════════════

Continuation = Callable[[HandlerOutcome], HandlerOutcome]
"""A CPS continuation: receives an outcome, returns (possibly transformed) outcome."""


def identity_continuation(outcome: HandlerOutcome) -> HandlerOutcome:
    """Default continuation: pass through."""
    return outcome


class Handler(abc.ABC):
    """
    Abstract interpreter of the Intention Tree (Free Monad F_Σ(X)).

    Concrete subclasses implement `provision` (manifest → physical resources)
    and `observe` (manifest → epistemic state snapshot).  The default
    `interpret` method walks an `IRIntentionTree` and drives the CPS
    evaluation deterministically in declaration order.

    Contract
    --------
    • Every method MUST return a `HandlerOutcome` (never `None`).
    • CT-1 errors signal handler bugs — never swallow them.
    • CT-3 errors signal infrastructure failures — propagate as exceptions,
      do NOT encode as low-certainty outcomes (decision D4).
    • `close()` MUST be idempotent.
    """

    name: str = "abstract"
    """Unique handler identifier, used by HandlerRegistry and provenance ρ."""

    @abc.abstractmethod
    def supports(self, node: IRNode) -> bool:
        """Return True iff this handler can interpret the given IR node."""

    @abc.abstractmethod
    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        """Materialize the resources listed in the manifest. Returns the outcome."""

    @abc.abstractmethod
    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        """Take a quorum-gated snapshot of the manifest's real state."""

    def close(self) -> None:
        """Release handler-level resources (connections, subprocess pools)."""
        return None

    # ── Free-Monad interpretation ─────────────────────────────────

    def interpret(
        self,
        tree: IRIntentionTree,
        *,
        resources: dict[str, IRResource] | None = None,
        fabrics: dict[str, IRFabric] | None = None,
        manifests: dict[str, IRManifest] | None = None,
        continuation: Continuation = identity_continuation,
    ) -> list[HandlerOutcome]:
        """
        β-reduce F_Σ(X) → X by walking the Intention Tree in declaration order.

        Each operation is dispatched to `provision` or `observe`; both receive
        a `collect_continuation` that chains the caller-supplied continuation.
        """
        resources = resources or {}
        fabrics = fabrics or {}
        manifests = manifests or {}

        outcomes: list[HandlerOutcome] = []

        def collect(outcome: HandlerOutcome) -> HandlerOutcome:
            transformed = continuation(outcome)
            outcomes.append(transformed)
            return transformed

        for op in tree.operations:
            if isinstance(op, IRManifest):
                self.provision(op, resources, fabrics, collect)
            elif isinstance(op, IRObserve):
                target_manifest = manifests.get(op.target)
                if target_manifest is None:
                    raise CallerBlameError(
                        f"observe '{op.name}' targets unknown manifest "
                        f"'{op.target}' — did you forget a declaration?"
                    )
                self.observe(op, target_manifest, collect)
            else:
                raise CalleeBlameError(
                    f"handler '{self.name}' cannot interpret IR node "
                    f"{type(op).__name__}; supported: IRManifest, IRObserve"
                )

        return outcomes

    def interpret_program(
        self,
        program: IRProgram,
        continuation: Continuation = identity_continuation,
    ) -> list[HandlerOutcome]:
        """Convenience: extract tree + tables from an IRProgram and interpret."""
        if program.intention_tree is None:
            return []
        return self.interpret(
            program.intention_tree,
            resources={r.name: r for r in program.resources},
            fabrics={f.name: f for f in program.fabrics},
            manifests={m.name: m for m in program.manifests},
            continuation=continuation,
        )


# ═══════════════════════════════════════════════════════════════════
#  HANDLER REGISTRY — plugin registration & dispatch
# ═══════════════════════════════════════════════════════════════════

class HandlerRegistry:
    """
    Keyed registry of available handlers.

    Used by the CLI/runtime to look up a handler by name (e.g. from a
    `--handler terraform` flag).  The registry is the single dispatch point
    so that a single .axon program can be interpreted under multiple
    handlers without any source-level change — fulfilling the Fase 2
    acceptance criterion.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, handler: Handler, *, replace: bool = False) -> None:
        if handler.name in self._handlers and not replace:
            raise CalleeBlameError(
                f"handler '{handler.name}' already registered; pass "
                f"replace=True to override"
            )
        self._handlers[handler.name] = handler

    def unregister(self, name: str) -> None:
        handler = self._handlers.pop(name, None)
        if handler is not None:
            handler.close()

    def get(self, name: str) -> Handler:
        if name not in self._handlers:
            available = ", ".join(self.names()) or "(none)"
            raise CallerBlameError(
                f"no handler registered with name '{name}'. "
                f"Available: {available}"
            )
        return self._handlers[name]

    def names(self) -> list[str]:
        return sorted(self._handlers.keys())

    def close_all(self) -> None:
        for handler in list(self._handlers.values()):
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                # close() must never propagate; log only if we had logging here.
                pass
        self._handlers.clear()

    def __contains__(self, name: str) -> bool:
        return name in self._handlers

    def __iter__(self) -> Iterable[Handler]:
        return iter(self._handlers.values())


__all__ = [
    "BLAME_CALLEE",
    "BLAME_CALLER",
    "BLAME_INFRASTRUCTURE",
    "CalleeBlameError",
    "CallerBlameError",
    "Continuation",
    "DerivationKind",
    "Handler",
    "HandlerError",
    "HandlerOutcome",
    "HandlerRegistry",
    "HandlerUnavailableError",
    "InfrastructureBlameError",
    "LambdaEnvelope",
    "LeaseExpiredError",
    "NetworkPartitionError",
    "OutcomeStatus",
    "identity_continuation",
    "make_envelope",
    "now_iso",
]
