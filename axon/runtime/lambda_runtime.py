"""
AXON Runtime — Lambda Data (ΛD) Apply
=======================================
Runtime types and helpers for the `lambda apply X to Y` flow-body
statement (Fase 15).

This module materialises ψ = ⟨T, V, E⟩ at execution time, where:

    T : str               — Ontology (semantic type)
    V : Any               — Bound value (target expression's resolved value)
    E : LambdaTensor      — Epistemic tensor ⟨c, τ_start, τ_end, ρ, δ⟩

The vocabulary follows the ΛD formalism (paper_lambda_data.md) and the
type checker's `_VALID_DERIVATIONS` frozenset:

    δ ∈ {raw, derived, inferred, aggregated, transformed}

This is intentionally distinct from `axon.runtime.handlers.base.LambdaEnvelope`
which uses the handler-internal vocabulary {axiomatic, observed, inferred,
mutated} for handler-emitted outputs. Merging the two vocabularies is a
separate concern out of scope for Fase 15 — see plan §5.

Theorem 5.1 (Epistemic Degradation) is enforced at runtime by
`enforce_theorem_5_1`, mirroring the compile-time guard in
`axon.compiler.type_checker._check_lambda_data`. The runtime guard
defends against IR-JSON tampering between compile and execute (the IR
is the trust boundary in multi-tenant deployments).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from axon.runtime.runtime_errors import EpistemicDegradationError, ErrorContext


# Mirror of axon.compiler.type_checker._VALID_DERIVATIONS — kept inline
# to avoid a runtime → compiler import. Drift between the two is
# detected by tests/test_lambda_data_runtime.py::test_derivation_vocab_parity.
VALID_DERIVATIONS: frozenset[str] = frozenset({
    "raw", "derived", "inferred", "aggregated", "transformed",
})


@dataclass(frozen=True)
class LambdaTensor:
    """E = ⟨c, τ_start, τ_end, ρ, δ⟩ — the epistemic tensor.

    Distinct from ``axon.runtime.handlers.base.LambdaEnvelope`` (which
    carries a single τ and the handler-internal δ vocabulary). This
    tensor follows the ΛD formalism vocabulary and carries the open
    temporal range `[τ_start, τ_end]` from the spec.
    """

    c: float                          # certainty in [0.0, 1.0]
    tau_start: str = ""               # ISO-8601 lower bound
    tau_end: str = ""                 # ISO-8601 upper bound (open if "")
    rho: str = ""                     # provenance (EntityRef)
    delta: str = "raw"                # derivation ∈ VALID_DERIVATIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "c": self.c,
            "tau_start": self.tau_start,
            "tau_end": self.tau_end,
            "rho": self.rho,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class LambdaPsi:
    """ψ = ⟨T, V, E⟩ — the epistemic state vector produced by `lambda apply`.

    Bound by the executor after resolving the target expression and
    constructing the tensor from the spec snapshot carried in the
    CompiledStep metadata.

    Downstream consumers (shield gating, persist, signed-envelope
    chaining) destructure either the dataclass directly or the
    serialised dict from `to_dict()`.
    """

    T: str                            # ontology
    V: Any                            # bound value
    E: LambdaTensor                   # epistemic tensor
    spec_name: str = ""               # source spec name (for traceability)

    def to_dict(self) -> dict[str, Any]:
        return {
            "T": self.T,
            "V": self.V,
            "E": self.E.to_dict(),
            "spec_name": self.spec_name,
        }


def enforce_theorem_5_1(
    *,
    spec_name: str,
    certainty: float,
    derivation: str,
    step_name: str = "",
    flow_name: str = "",
) -> None:
    """Runtime mirror of the Epistemic Degradation Theorem compile-time check.

    Defends against IR-JSON tampering: a tampered IR could carry a
    `lambda_data_apply` whose snapshot violates the theorem the front-end
    rejected. This guard catches that at apply time, before the bad
    envelope propagates downstream.

    Mirrors axon.compiler.type_checker._check_lambda_data exactly:
        derivation ∈ {derived, inferred, aggregated, transformed} ∧ c == 1.0
            ⇒ EpistemicDegradationError

    Raw data (δ = raw) is the only derivation that may carry c = 1.0.
    Empty derivation strings pass — the compile-time check treats an
    unset δ as legacy/observed and skips the assertion. We preserve
    that behaviour to keep the runtime guard a strict mirror.
    """
    if not 0.0 <= certainty <= 1.0:
        raise EpistemicDegradationError(
            f"lambda '{spec_name}' has out-of-range certainty {certainty} "
            f"(must be in [0.0, 1.0])",
            ErrorContext(
                step_name=step_name,
                flow_name=flow_name,
                details=f"certainty={certainty}, derivation='{derivation}'",
            ),
        )

    if derivation and derivation not in VALID_DERIVATIONS:
        raise EpistemicDegradationError(
            f"lambda '{spec_name}' has unknown derivation '{derivation}' "
            f"(valid: {', '.join(sorted(VALID_DERIVATIONS))})",
            ErrorContext(
                step_name=step_name,
                flow_name=flow_name,
                details=f"derivation='{derivation}'",
            ),
        )

    if certainty == 1.0 and derivation and derivation != "raw":
        raise EpistemicDegradationError(
            f"Theorem 5.1 violation at apply time: lambda '{spec_name}' "
            f"has certainty=1.0 with derivation='{derivation}'. Only 'raw' "
            f"data may carry absolute certainty (c=1.0) — derived/inferred/"
            f"aggregated/transformed must have c < 1.0. The compile-time "
            f"guard caught this for honest programs; reaching the runtime "
            f"guard means the IR was tampered with after compile.",
            ErrorContext(
                step_name=step_name,
                flow_name=flow_name,
                details=f"certainty={certainty}, derivation='{derivation}'",
            ),
        )


def build_psi(
    *,
    spec_snapshot: dict[str, Any],
    target_value: Any,
    step_name: str = "",
    flow_name: str = "",
) -> LambdaPsi:
    """Construct ψ from a spec snapshot and a resolved target value.

    The spec snapshot carries the keys produced by
    ``BaseBackend._compile_lambda_apply_step``. Any missing key is
    treated as an empty/zero default — the type checker guarantees
    well-formed snapshots for honest programs, so missing fields signal
    IR tampering and surface as EpistemicDegradationError via the
    bounds check.
    """
    spec_name = spec_snapshot.get("name", "")
    enforce_theorem_5_1(
        spec_name=spec_name,
        certainty=float(spec_snapshot.get("certainty", 0.0)),
        derivation=str(spec_snapshot.get("derivation", "")),
        step_name=step_name,
        flow_name=flow_name,
    )

    tensor = LambdaTensor(
        c=float(spec_snapshot.get("certainty", 0.0)),
        tau_start=str(spec_snapshot.get("temporal_frame_start", "")),
        tau_end=str(spec_snapshot.get("temporal_frame_end", "")),
        rho=str(spec_snapshot.get("provenance", "")),
        delta=str(spec_snapshot.get("derivation", "raw")) or "raw",
    )

    return LambdaPsi(
        T=str(spec_snapshot.get("ontology", "")),
        V=target_value,
        E=tensor,
        spec_name=spec_name,
    )
