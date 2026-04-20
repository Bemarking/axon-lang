"""
AXON Runtime — DryRunHandler
==============================
Deterministic, in-memory interpreter of the Intention Tree.

The DryRunHandler performs no external I/O.  It records every provisioning
and observation request and returns outcomes whose certainty is always 1.0
because the handler is omniscient over its own synthetic world.  This is
the primary test vehicle for the CPS machinery and the default demo
handler for `.axon` programs that exercise the I/O cognitivo primitives.

Decision anchors:
  • D1 — the handler is the `h : F_Σ(X) → X` natural transformation from
         the Intention Tree into a pure, deterministic result type.
  • D4 — partitions are impossible in-memory, so on_partition is only
         observable via the DryRun "partition_mode" knob used by tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
    Continuation,
    Handler,
    HandlerOutcome,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
)


@dataclass
class DryRunState:
    """Captured side-effects for inspection in tests."""
    provisioned: dict[str, dict[str, Any]] = field(default_factory=dict)
    observations: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[HandlerOutcome] = field(default_factory=list)


class DryRunHandler(Handler):
    """
    Deterministic, in-memory handler — pure function from Intention Tree
    to recorded side-effects.  No SDKs, no subprocesses, no network.

    Parameters
    ----------
    simulate_partition : bool
        If True, `observe` raises `NetworkPartitionError` (CT-3) instead of
        returning a successful outcome.  Used by tests to verify the D4
        partition-as-void semantics end-to-end.
    """

    name: str = "dry_run"

    def __init__(self, *, simulate_partition: bool = False) -> None:
        self.simulate_partition = simulate_partition
        self.state = DryRunState()

    # ── Handler protocol ──────────────────────────────────────────

    def supports(self, node: IRNode) -> bool:
        return isinstance(node, (IRManifest, IRObserve))

    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        fabric_snapshot = None
        if manifest.fabric_ref and manifest.fabric_ref in fabrics:
            f = fabrics[manifest.fabric_ref]
            fabric_snapshot = {
                "name": f.name,
                "provider": f.provider,
                "region": f.region,
                "zones": f.zones,
                "ephemeral": f.ephemeral,
            }

        resolved_resources = []
        for res_name in manifest.resources:
            r = resources.get(res_name)
            resolved_resources.append({
                "name": res_name,
                "kind": r.kind if r else "unknown",
                "lifetime": r.lifetime if r else "affine",
                "endpoint": r.endpoint if r else "",
                "capacity": r.capacity if r else None,
                "certainty_floor": r.certainty_floor if r else None,
            })

        record = {
            "manifest": manifest.name,
            "resources": resolved_resources,
            "fabric": fabric_snapshot,
            "region": manifest.region,
            "zones": manifest.zones,
            "compliance": list(manifest.compliance),
        }
        self.state.provisioned[manifest.name] = record

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=1.0, rho=self.name, delta="axiomatic"),
            data=record,
            handler=self.name,
        )
        self.state.outcomes.append(outcome)
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        if self.simulate_partition:
            # Decision D4: partition = ⊥ void, NEVER downgraded to `doubt`.
            raise NetworkPartitionError(
                f"simulated partition while observing '{obs.name}' from "
                f"'{manifest.name}' (sources: {list(obs.sources)})"
            )

        quorum = obs.quorum if obs.quorum is not None else len(obs.sources)
        record = {
            "observe": obs.name,
            "manifest": manifest.name,
            "sources": list(obs.sources),
            "quorum": quorum,
            "timeout": obs.timeout,
            "on_partition": obs.on_partition,
            "resources_observed": list(manifest.resources),
        }
        self.state.observations.append(record)

        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=1.0, rho=self.name, delta="observed"),
            data=record,
            handler=self.name,
        )
        self.state.outcomes.append(outcome)
        return continuation(outcome)

    def close(self) -> None:
        # Nothing to release; the dry-run state persists for inspection.
        return None


__all__ = ["DryRunHandler", "DryRunState"]
