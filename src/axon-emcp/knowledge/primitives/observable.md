---
name: observable
summary: Declares a Hermitian observable — a Pauli-sum M = Σ cₖ Pₖ — measured by a quant block to collapse a Hilbert-space state back to a classical expectation.
category: operators
top_level: true
since: Fase 51 (v2.19.0)
grammar: |
  # Top-level declaration:
  observable <Name> = <coeff> * <PauliString> [ + <coeff> * <PauliString> ]*

  # <PauliString> is one Pauli letter per qubit, MSB-first:
  #   I (identity) | X | Y | Z      e.g. "Z", "ZZ", "XI"
  # <coeff> is a real scalar (the Hermitian weight cₖ).
---

# `observable`

`observable` declares a **Hermitian operator** as a weighted sum of
Pauli strings — `M = Σₖ cₖ Pₖ` — the quantity a [`quant`](axon://primitives/quant)
block measures to collapse a Hilbert-space state back to a single
classical expectation `⟨ψ| M |ψ⟩`.

Because every term is a real coefficient times a tensor product of
Pauli matrices (each Hermitian and involutory), the sum is **Hermitian
by construction** — so its expectation is always real, and it is a
valid quantum-mechanical measurement. The compiler proves this
(`axon-E0785`); a malformed observable never reaches the runtime.

## Surface

`observable` is a **top-level declaration**, like `type` or `anchor`.
It is referenced by name from a `quant` block's `observable:` field.

```axon
# A single-qubit energy observable: ⟨Z⟩.
observable Energy = 1.0 * Z

# A two-qubit correlation observable: ½⟨ZZ⟩ − 1.2⟨XI⟩.
observable Correlation = 0.5 * ZZ + -1.2 * XI
```

## Anatomy

### Pauli strings

Each term names one Pauli factor **per qubit**, most-significant qubit
first:

| Letter | Matrix | Meaning |
|--------|--------|---------|
| `I` | identity | qubit untouched |
| `X` | `[[0,1],[1,0]]` | bit-flip basis |
| `Y` | `[[0,−i],[i,0]]` | |
| `Z` | `[[1,0],[0,−1]]` | computational basis |

The string length fixes the qubit count `n` the observable acts on; a
`quant` block measuring it must encode a state of the same width.

### Coefficients

Real scalars. They set each term's Hermitian weight; the operator norm
of the sum bounds the achievable expectation (a single Pauli string has
`‖P‖ = 1`, so `⟨P⟩ ∈ [−1, 1]`).

## Runtime behaviour

A declared `observable` lowers to a `PauliSum` value (the closed list of
`(coeff, pauli_string)` terms). At measurement the runtime computes
`⟨ψ| M |ψ⟩ = Σₖ cₖ ⟨ψ| Pₖ |ψ⟩` — Pauli action is exact on the Q32.32
substrate (entries `{0, ±1, ±i}` never round), so a Pauli-sum
expectation is **bit-reproducible** in the enterprise backend.

## Static guarantees

- **`axon-E0785`** — the Pauli-sum must be well-formed: every term a
  real coefficient times a valid Pauli string of consistent width.
- **`axon-E0784`** — a `quant` block's `observable:` must resolve to a
  declared `observable` (closed-catalogue resolution).
- **`axon-E0786`** — a declared density matrix companion must have
  dimension `D = 2ⁿ`.

## What this primitive is NOT

- **Not a `type`.** A `type` declares a data shape; an `observable`
  declares a measurement operator over a Hilbert space.
- **Not an `anchor`.** An anchor is a grounding constraint on a flow's
  outputs; an observable is the physical quantity a `quant` block reads.
- **Not executable on its own.** It is inert until a `quant` block
  names it — like a `type` is inert until a value inhabits it.

## See also

- `axon://primitives/quant` — the block that measures an observable.
- `axon://primitives/flow` — the parent of every `quant` block.
