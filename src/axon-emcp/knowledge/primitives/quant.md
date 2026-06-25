---
name: quant
summary: A flow-body block that lifts a continuous carrier tensor into a finite Hilbert space, evolves it, and yields the expectation of a declared observable (the cognitive↔quantum bridge; OSS simulator capped at n≤10).
category: operators
top_level: false
since: Fase 51 (v2.19.0)
grammar: |
  # Flow-body block (canonical):
  quant {
      encode: amplitude | angle        # how the carrier maps to amplitudes
      observable: <ObservableName>     # the Hermitian operator to measure
      yield <expr>                     # the measured expectation, back to classical
  }
---

# `quant`

`quant` is AXON's **bridge between sub-symbolic embeddings and the
algebra of quantum-kernel methods**. Inside a flow, it lifts a
continuous carrier tensor into a finite-dimensional Hilbert space,
optionally evolves it under a variational circuit, and **collapses it
back to classical silicon** by measuring a declared
[`observable`](axon://primitives/observable) — yielding a single real
expectation a downstream step can consume.

It is a *cognitive* primitive: the quantum machinery is a means to a
geometry (the projected-kernel route to a provable convex advantage),
not an end. The honest claim is **convexity** — a valid quantum kernel
Gram is PSD, so the downstream classical SVM dual has a global optimum —
not "tunneling through barriers."

## Charter split (free syntax / paid scale)

The keyword, the static rules, and a **usable CPU reference simulator**
ship in OSS `axon-lang`. That simulator is **hard-capped at `n ≤ 10`
qubits** (`axon-E0783` past that). The *efficient* execution substrate —
the Q32.32 bit-exact arithmetic, the QuIDD decision-diagram compression
for `n ≫ 10`, per-tenant VRAM control, and locked hardware / QPU-native
backends — is **Axon Enterprise** only. The standard is unified; the
scale is the paid privilege.

## Surface

`quant` is a **flow-body block** (nested, like `transact` or `forge`).

```axon
observable Energy = 1.0 * Z

flow Classify(embedding: Tensor) -> Float {
    quant {
        encode: amplitude
        observable: Energy
        yield ⟨Energy⟩          # the expectation ⟨ψ| Energy |ψ⟩, as a Float
    }
}
```

## Anatomy

### `encode:` — the lift

- **`amplitude`** — the carrier becomes the state's amplitude vector
  (must be unit-norm; the runtime asserts `‖x‖₂ = 1`). `n = ⌈log₂ d⌉`
  qubits for a length-`d` carrier.
- **`angle`** — each carrier component drives a rotation angle (one
  qubit per component). Resists the amplitude form's normalization
  constraint.

### `observable:` — the measurement

Resolves (closed-catalogue, `axon-E0784`) to a declared `observable`
Pauli-sum. Its width fixes the qubit count `n`.

### `yield` — the collapse

`yield <expr>` is **only legal inside a `quant` block** (`axon-E0787`
otherwise). It emits the measured expectation back into the classical
flow as the block's value.

## Runtime behaviour

`quant` lowers to a `QuantBlock` IR node. At execution:

1. **Encode** the carrier into a state vector under the chosen scheme.
2. **Evolve** (optional variational circuit; gate application).
3. **Measure** the observable: `⟨ψ| M |ψ⟩`, real by Hermiticity.
4. **Yield** the expectation as a classical value.

In the enterprise backend the whole path is **bit-reproducible** on the
Q32.32 substrate (Pauli measurement is exact), audited
(`quant:started → measured → completed`, the raw carrier never written
to the chain — only its SHA-256 digest), RBAC-gated (`quant:execute`),
shielded, and VRAM-quota'd per tenant.

## Static guarantees

- **`axon-E0782`** — Continuous Type Invariant: the carrier must be a
  continuous tensor (a discrete value is rejected).
- **`axon-E0783`** — capacity: `n > 10` on the OSS simulator is a
  compile error (enterprise lifts it).
- **`axon-E0784`** — the `observable:` must resolve to a declared
  observable.
- **`axon-E0787`** — `yield` outside a `quant` block is rejected.
- **`axon-W005`** — a circuit-depth advisory (soft barren-plateau note).

## What this primitive is NOT

- **Not a `tool`.** A tool binds an external capability; `quant` is an
  in-language transform over a Hilbert space.
- **Not a `compute`.** Compute selects an LLM backend + effort; `quant`
  performs a quantum-kernel measurement.
- **Not infinite-precision.** The substrate is deterministic
  (bit-reproducible) but quantized at `Δ = 2⁻³²` — determinism is not
  exactness.
- **Not a tunneling optimizer.** The advantage is the convexity of the
  kernel-SVM dual, validated by the geometric-difference witness — a
  *potential*-advantage signal, necessary but not sufficient.

## See also

- `axon://primitives/observable` — the Hermitian operator a quant block
  measures.
- `axon://primitives/flow` — the parent of every quant block.
- `axon://primitives/compute` — backend selection (a different axis).
