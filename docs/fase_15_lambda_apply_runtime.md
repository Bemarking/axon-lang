---
title: "Plan vivo: Fase 15 — Lambda Apply runtime wiring"
status: PLANNED — sub-fases 15.a–15.f por shippear
owner: AXON Language Team
created: 2026-05-03
updated: 2026-05-03
target: axon-lang v1.10.0 (PyPI + crates.io) — coordinated cross-stack
depends_on: Fase 14 (lossless lexing) DONE; ΛD compiler stages (Fase 20 legacy) DONE
---

# FASE 15 — LAMBDA APPLY RUNTIME WIRING

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** the `lambda apply X to Y` flow-body statement is fully wired through the front-end (lexer → parser → type-checker → IR node `IRLambdaDataApply` with `node_type="lambda_data_apply"`) but **no runtime executor dispatches it** in v1.9.1. Phase 2 (backends compilation) does not translate it into a `CompiledStep`; the Python `Executor` has no handler; the Rust `runner.rs` only mentions it inside the trace-only `extract_step_info`/`execute_stub` path. **15.a–15.f close that** — Phase 2 lowering, Python dispatcher, Rust dispatcher, type-checker hardening, runtime tests, and docstring honesty.
- **Why:** today every adopter program containing `lambda apply` compiles green and produces a green IR JSON, but at execution time the statement is a no-op. The certainty propagation guarantee promised by the docs (Theorem 5.1 — Epistemic Degradation) is enforced **at compile time** for `lambda` declarations, but the runtime application that should bind the envelope to a step output is missing. This is a silent semantic gap: programs that *appear* to enrich data with epistemic envelopes don't actually do it.
- **Surfaced by:** post-v1.9.1 audit triggered by the question *"esto es verdad? lambda (ΛD apply) tampoco está wireado runtime en 1.9.1"* — confirmed by grep over `axon/runtime/`, `axon/backends/`, and `axon-rs/src/` (zero dispatch sites; only one trace-string in the Rust stub executor).
- **Distinct from "ΛD as data envelope":** the envelope ⟨c, τ, ρ, δ⟩ IS pervasively wired in runtime — handlers, file_resource, provenance, immune health reports, lease kernel, reconcile loop all produce/consume it. The gap is specifically the **flow-body statement** that binds a declared `lambda` spec to a step output.

---

## 2. Design — Phase-2 lowering + executor dispatch on both stacks

The Phase-2 backend stage (Python: `axon/backends/base_backend.py`; Rust: `axon-rs/src/runner.rs::compile_steps`) currently produces a `CompiledStep` for every `IRFlowNode` variant **except** `LambdaDataApply` (which falls through to the `_ => None` arm in Rust and is simply ignored in Python). The executors then iterate over `CompiledStep` entries and dispatch by `step_type` — a step that never reaches them is never run.

Two-pronged fix:

1. **Phase-2 lowering** must produce a `CompiledStep` for every `LambdaDataApply` IR node, carrying:
   - `step_type = "lambda_data_apply"`
   - `step_name = lambda_data_name` (for trace correlation)
   - A typed payload struct (`LambdaApplyPayload`) holding `lambda_data_name`, `target`, `output_type`, **and the resolved spec** (so the runtime doesn't need to re-traverse the IR).

2. **Executor dispatch** matches on `step_type` and runs:
   ```text
   resolve target → V         (lookup in unit context, error if undefined)
   build envelope ψ = ⟨T, V, E⟩ from spec
     T = spec.ontology
     V = resolved value
     E = ⟨spec.certainty, spec.temporal_frame, spec.provenance, spec.derivation⟩
   enforce Theorem 5.1 at runtime:
     if δ ∈ {derived, inferred, aggregated, transformed} ∧ c = 1.0
       → RuntimeError (mirror compile-time check; defends against IR tampering)
   bind unit.context[output_type] := envelope
   emit TraceEvent (event="lambda_data_apply", spec=name, target=target, certainty=c)
   ```

The runtime check **mirrors** the compile-time check rather than replacing it. The compile-time guard catches honest programmer errors at the source; the runtime guard catches IR tampering and stays consistent with the formalism.

### LambdaEnvelope reuse

`axon/runtime/handlers/base.py:44-208` already defines a `LambdaEnvelope` dataclass and helpers (`current_tau()`, `make_envelope(value, ...)`). Fase 15 reuses these — no new envelope type. The Phase-2 payload can carry the un-bound spec, and the dispatcher constructs the bound envelope per-step.

### Symbol-table contract for `target` and `output_type`

- `target` is an expression that resolves at runtime against the unit's local context (which carries step outputs and `let`-bound vars).
- `output_type` names a new symbol introduced into the unit context. Naming collision with an existing symbol is a **runtime warning**, not an error (matches existing `let`-rebind behaviour). A future sub-phase may promote it to a compile-time check (15.d hardening).

---

## 3. Use cases unlocked

| Use case | What `lambda apply` runtime delivers |
|---|---|
| **End-to-end epistemic enrichment** | A flow can pull raw data from a tool, then `lambda apply` an `inferred`-derivation spec to the output — the resulting envelope carries the correct (capped) certainty downstream. Today the apply is silently dropped. |
| **Provenance chain extension** | The bound envelope's `ρ` field becomes the provenance origin for any `persist` / `signed-envelope` operation downstream. `axon/runtime/esk/provenance.py` already chains envelopes; today the chain has a hole at every `lambda apply` site. |
| **Theorem 5.1 runtime enforcement** | Catches IR-level tampering (third-party tools mutating the IR JSON) that the front-end caught. Important for the multi-tenant deployment model where the IR is the trust boundary. |
| **`shield` integration** | A shield's verdict can read the bound envelope's certainty to gate downstream steps. Today shields gate on tool/handler envelopes only, not on `lambda apply` outputs. |
| **Replay / cognitive state** | The `axon/runtime/replay/` machinery snapshots unit context for replay tokens. Without `lambda apply` writes, replay reproduces a context **missing** every applied envelope — silent replay drift. |

---

## 4. Sub-phases

### 15.a — Phase-2 lowering: IR → CompiledStep (Python + Rust) `[PLANNED]`

**Python — `axon/backends/base_backend.py`:**
- Add `LambdaApplyPayload` dataclass with `lambda_data_name`, `target`, `output_type`, `spec_snapshot: IRLambdaData` (frozen copy, not a reference, so executor never re-traverses IR).
- `compile_program` walks `IRFlowNode` siblings; on `IRLambdaDataApply` produces a `CompiledStep(step_type="lambda_data_apply", step_name=node.lambda_data_name, payload=LambdaApplyPayload(..., spec_snapshot=ir_lambdas[node.lambda_data_name]))`.
- IR program already exposes the registry of `IRLambdaData` definitions; lookup is O(1).
- Error if `lambda_data_name` is not a known `IRLambdaData` — should never trigger because the type-checker catches it, but the assertion documents the invariant.

**Rust — `axon-rs/src/runner.rs::compile_steps`:**
- Same payload shape; new `CompiledStepKind::LambdaDataApply { spec, target, output_type }`.
- The current `_ => None` arm in `compile_steps` becomes the catch-all for genuinely-unknown variants; `LambdaDataApply` gets its own arm.

**Tests:** `tests/test_phase2_lambda_apply_lowering.py` — verify a 3-step flow `[Step, LambdaDataApply, Step]` produces 3 `CompiledStep`s (today it produces 2, silently dropping the apply).

### 15.b — Python runtime dispatcher `[PLANNED]`

**`axon/runtime/executor.py`:**
- New `_execute_lambda_data_apply(self, step, unit_ctx) -> ExecutionResult`:
  ```python
  payload = step.payload  # LambdaApplyPayload
  spec = payload.spec_snapshot
  value = unit_ctx.resolve(payload.target)  # raises if undefined
  envelope = make_envelope(
      value=value,
      ontology=spec.ontology,
      certainty=spec.certainty,
      tau_start=spec.temporal_frame_start,
      tau_end=spec.temporal_frame_end,
      provenance=spec.provenance,
      derivation=spec.derivation,
  )
  _enforce_theorem_5_1(envelope)  # raises EpistemicDegradationError if violated
  unit_ctx.bind(payload.output_type, envelope)
  perform(EmitEvent(event="lambda_data_apply", spec=spec.name, target=payload.target, certainty=spec.certainty))
  return ExecutionResult.ok()
  ```
- `_enforce_theorem_5_1` is a new private helper (`raw → c=1.0 OK`, anything else → `c<1.0` required). Mirror logic of `axon/compiler/type_checker.py:_check_lambda_data_invariants` but without the AST node coupling.
- Wire into the main step-dispatch table (currently a long `match step.step_type` chain) immediately after the existing `compute_apply` arm.

**Tests:** `tests/test_lambda_data_runtime.py` — full coverage matrix (see 15.e).

### 15.c — Rust runtime dispatcher `[PLANNED]`

**`axon-rs/src/runner.rs::execute_stub`:**
- The Rust runtime is currently a stub for **all** primitives (it prints traces but doesn't execute LLM calls — that's by design; real execution is in the Python runtime via the FFI bridge). For `lambda apply` specifically, the stub should still produce the correct semantic effect because the apply is a **pure** binding (no LLM, no I/O, just envelope construction).
- Promote the `LambdaDataApply` arm in the stub from "print a trace" to "construct envelope + bind to context + emit trace event". This makes the Rust stub semantically correct for the apply primitive — programs that exercise `lambda apply` and inspect outputs via the stub get correct envelopes.
- Same Theorem 5.1 runtime check, mirroring the Python implementation. Both stacks must reject the same inputs identically (parity discipline established in Fase 13.k).

**Cross-stack parity test:** new `axon-rs/tests/parity/fase15_lambda_apply.{python,rust}.json` golden — a 3-step program with one `lambda apply` produces identical bound-envelope traces on both runtimes.

### 15.d — Type checker hardening (Python + Rust) `[PLANNED]`

The current `_check_lambda_data_apply` (Python `type_checker.py:3372`; Rust `type_checker.rs` analogous) only validates that `lambda_data_name` resolves to a `lambda_data` symbol kind. It does NOT check:

- **`target` must resolve to a known symbol** in the enclosing flow's scope (step output, `let`-bound var, parameter). Today an undefined target compiles green and would fail with `unit_ctx.resolve()` raising at runtime — moving this to compile-time is a strict improvement.
- **`output_type` should not shadow a primitive type name** (`int`, `string`, `bool`, ontology built-ins). Today shadowing is silently allowed.
- **`output_type` rebinding within the same flow** should warn (parallel to `let` rebind warning).

These three hardenings make the front-end errors arrive at the source location, not at the runtime call site.

### 15.e — Runtime test matrix `[PLANNED]`

**`tests/test_lambda_data_runtime.py`** (new) and **`axon-rs/tests/lambda_data_runtime.rs`** (new):

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | `lambda raw, certainty=1.0, derivation=raw` applied to a step output | Envelope bound, `c=1.0` preserved |
| 2 | `lambda inferred, certainty=0.7` applied to a step output | Envelope bound, `c=0.7`, derivation marker propagated |
| 3 | `lambda inferred, certainty=1.0` (T5.1 violation) — IR tampered post-compile | `EpistemicDegradationError` raised at runtime; no binding occurs |
| 4 | `lambda apply X to Y` where `X` undefined symbol | `UnknownSymbolError` (post-15.d this becomes a compile error and the runtime test moves to test_compile_errors) |
| 5 | `lambda apply X to Y` where `Y` already bound | Rebinding succeeds, warning emitted on trace |
| 6 | Chained `lambda apply` — `apply spec1 to step1.out → as e1; apply spec2 to e1.value → as e2` | `e2.certainty ≤ e1.certainty * η` (fidelity bound) |
| 7 | Replay token round-trip — execute, snapshot, replay | Every applied envelope present in the replayed context with byte-identical payload |
| 8 | Cross-stack parity — same `.axon` source executed by Python and Rust runtimes | Identical trace events; identical bound envelopes |

### 15.f — Documentation honesty + cleanup `[PLANNED]`

- **`axon/compiler/ir_nodes.py::IRLambdaDataApply`** docstring (lines 1428-1437): the current text *"At runtime, the executor binds the referenced ΛD's epistemic tensor to the target expression…"* describes Fase 15's target behaviour, not v1.9.1 reality. Replace with present-tense description matching what 15.b/c actually ship.
- **`README.md`** Phase 20 row already qualified to *"Compiler complete; runtime apply pending Fase 15"* in the bring-up commit. After 15.b/c ship, restore to `✅ Done` (cross-stack).
- **`docs/paper_lambda_data.md`** §Runtime — add a section describing the Phase-2 lowering and the executor dispatch, with the Theorem 5.1 runtime guard and the chained-apply fidelity proof.
- **`docs/paper_lambda_lineal_epistemico.md`** if it claims runtime apply, qualify or update.

---

## 5. Out of scope

- **Lambda-as-function** (anonymous λ in expressions). This phase is exclusively about `lambda` (top-level epistemic spec) + `lambda apply` (binding statement). Function lambdas are tracked separately (see legacy Fase 8 backlog if any work survives).
- **Non-blocking `lambda apply`** (concurrent / async binding). Today and post-15 `apply` is a synchronous step that completes before the next flow node executes. Async semantics would require π-calculus integration and belong with Fase 13 mobile-channel extensions.
- **Cross-tenant ΛD sharing.** A bound envelope is unit-local. Multi-tenant ψ exchange is an ESK / shield concern, not a Fase 15 deliverable.

---

## 6. Acceptance criteria (for declaring Fase 15 SHIPPED)

1. Every sub-phase 15.a–15.f marked `[DONE]` ✓ with a release reference.
2. Test counts: Python +30 minimum (8 scenarios × ~4 assertions), Rust +20 minimum (parity + native tests).
3. Cross-stack parity golden present in `axon-rs/tests/parity/fase15_lambda_apply.*.json` and matched byte-for-byte by `axon-rs/tests/parity_check.rs`.
4. No regression in v1.9.1 baselines: Python 4193 → ≥4223; Rust integration suite green (modulo pre-existing `fase_11f_cross_phase_integration` carryover).
5. README Phase 20 row restored to `✅ Done` (no qualifier).
6. `IRLambdaDataApply` docstring describes shipped behaviour in present tense.
7. Tagged + released as `axon-lang v1.10.0` on PyPI + crates.io; `axon-enterprise` consumes via pin bump (no enterprise code changes — same passthrough path as Fase 14 → enterprise v1.5.0).
