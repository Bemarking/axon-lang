---
title: "Plan vivo: Fase 19 — Production hardening of Fase 18 dispatchers"
status: PLANNED — sub-fases 19.a–19.n por shippear
owner: AXON Language Team
created: 2026-05-04
updated: 2026-05-04
target: axon-lang v1.14.0 (PyPI + crates.io) — coordinated cross-stack
depends_on: Fase 15 / 16 / 17 / 18 DONE
---

# FASE 19 — PRODUCTION HARDENING OF FASE 18 DISPATCHERS

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** Fase 18 closed all 10 IR runtime gaps but shipped MVP placeholders for three primitives (Hibernate, Drill, Trail), kept the new Par dispatcher with shared-context concurrency (race risk under high write contention), and left the Rust runtime without parity for the 9 newly-wired primitives. Fase 19 is the production-hardening pass: replace MVPs with real subsystem integration, fix the Par concurrency contract, mirror every dispatcher in the Rust runner, add per-primitive Prometheus + OTel observability, and extend the drift gate to track MVP vs FULL implementation status so the matrix never silently regresses.
- **Why:** v1.13.0 is honest about what it ships — the Hibernate / Drill / Trail MVP placeholders are marked `_stub: True` in their bound payloads, and the matrix says "MVP; full integration deferred." Fase 19 closes that deferral, restores Rust parity, and adds the observability + property-testing layer needed for production deployments. After Fase 19, the AXON runtime is honestly production-ready, not just dispatch-correct.
- **Impact on adopters:** programs that use `hibernate` get real CPS state serialization (resumable across process restarts); programs that use `drill`/`trail` get real PIX subtree queries (not placeholder dicts); `par { a; b }` no longer suffers concurrent-write races on shared ctx variables; Rust adopters running `axon run` get the same control-flow + memory + domain-primitive semantics as Python adopters.
- **Scope:** OSS-only. The enterprise `axon-enterprise` package is unaffected (no new pin floor required); production observability hooks integrate with the existing enterprise telemetry adapters introduced in Fase 16, but do not require them.
- **Robustness target:** ship Property Tests (Hypothesis) for every new dispatcher's contract; fuzz the control-flow nesting (random `if/for/par` trees up to depth 5) to surface deadlocks or scope leaks; add chaos-style probes for Hibernate (mid-checkpoint cancellation, signing key rotation, lease expiry); achieve ≥+150 new tests with ≥85% coverage of the new code.

---

## 2. Audit findings — what Fase 18 left on the table

Empirical inspection of v1.13.0 (commit `98b9526`):

| Concern | Pre-Fase-19 state | Risk |
|---|---|---|
| Hibernate dispatcher | Binds `__hibernation_token__` dict with `(event_name, timeout, continuation_id, flow_name, checkpoint_at)`. **No actual state serialization.** No resume path. | Adopters who hibernate + restart get a dead token; the cognitive state, BDI matrix, replay log offset, ContextManager variables are all lost. |
| Drill dispatcher | Binds placeholder `DrillResult` dict with `_stub: True` marker and `matches: []`. **PIX engine never queried.** | Programs that drill into a PIX get empty results regardless of query. The compiler accepts the syntax; the runtime returns nothing. |
| Trail dispatcher | Binds placeholder `TrailResult` dict with `_stub: True`, `path: []`. **No corroboration walker.** | Programs requesting reasoning paths get empty arrays — explainability surface broken. |
| Par dispatcher | `asyncio.gather` over branches sharing the same `ContextManager`. **No per-branch isolation.** Last-writer-wins on shared variable names. | Two parallel branches writing to the same variable race; the result depends on event-loop interleaving (non-deterministic). Compile-time warning for collisions documented but not implemented. |
| ForIn dispatcher | No `break` / `continue` semantics. Body always runs to completion per iteration. | Real-world `for` loops need early-exit. Adopters wrap in conditional + `return`, which exits the *flow*, not just the loop. |
| Rust runtime parity | Only `lambda_data_apply`, `let_binding`, `use_tool` have Rust dispatchers. **9 Fase-18 primitives have ZERO Rust counterpart.** | Cross-stack semantic gap: Python and Rust runners disagree on what `if/for/par/return/remember/recall/hibernate/drill/trail` do. Adopters running `axon run` (Rust) get LLM fall-through; same program under the Python runner gets correct semantics. |
| Production observability | The dispatchers emit `tracer.emit(STEP_START/END)` events but no Prometheus counters / gauges, no OTel spans wrapping nested control flow, no structured audit events for memory ops or returns. | Production deployments cannot graph "how many times did this flow execute the else branch?" or "how long did this hibernate window stay open?" — opaque under load. |
| Property + fuzz coverage | Per-primitive scenarios (43 tests across 4 files) are sample-based. No Hypothesis property tests. No fuzz tests for nested control-flow combinations. | Edge cases (deep nesting, large iterables, simultaneous parallel writes, malformed continuation tokens) discovered reactively in production. |

Severity is uniform: every item above is a **production-readiness concern**, not a correctness bug. v1.13.0 is correct for the MVP scope it documented; Fase 19 raises the bar to "production-grade" by closing the MVP markers + adding the observability + testing layer.

---

## 3. Architecture — three concerns, one release

### 3.1 Replace MVP placeholders with real subsystem integration

The three MVP dispatchers from Fase 18 (Hibernate / Drill / Trail) bind placeholder payloads with `_stub: True` markers. Fase 19 replaces each with the corresponding production subsystem already living in the codebase:

```text
Hibernate  →  axon/runtime/pem/continuity_token.py::ContinuityTokenSigner
Drill      →  axon/engine/pix/navigator.py::PixNavigator
Trail      →  axon/engine/pix/navigator.py (trail / corroboration API)
```

The PIX engine and CPS continuity-token signer **already exist** in the codebase. Fase 18 deferred wiring them to the dispatchers in favor of shipping the LLM-fall-through fix early. Fase 19 closes the deferral.

### 3.2 Control-flow polish

Two dispatcher contracts get hardened:

- **Par concurrency**: introduce per-branch `ContextView` (shielded dict view that records writes locally; merges back into the parent ctx on completion via a configurable strategy: `last_writer_wins`, `first_writer_wins`, `reject_conflicts`, or `merge_dicts`). Default = `last_writer_wins` to preserve current behavior for adopters who rely on it; `reject_conflicts` becomes the recommended setting for production deployments.
- **ForIn break/continue**: introduce `_FlowBreakSignal` and `_FlowContinueSignal` sentinel exceptions, mirror of `_FlowReturnSignal` from Fase 18.d. The `for_in` dispatcher catches them; `_execute_step` does not. New IR nodes `IRBreak` and `IRContinue` (added to the catalogue as part of 19.e) raise the corresponding sentinel.

### 3.3 Rust runtime parity

The 9 Fase-18 primitives need stub-correct dispatchers in `axon-rs/src/runner.rs::execute_stub` (mirror of the Fase 15.c / 17.c pattern). Each dispatcher:

- Carries its payload via a dedicated struct field on `CompiledStep` (e.g., `conditional_payload`, `for_in_payload`, `par_payload`, …).
- The Phase-2 lowering in `axon-rs/src/runner.rs::build_compiled_steps` populates the payload from the corresponding `IRFlowNode` variant.
- The `execute_stub` arm performs the binding and emits a typed `TraceEvent`.

Cross-stack parity goldens land under `axon-rs/tests/parity/fase19_*.{spec,golden}.json` per primitive, mirror of Fase 15.f / 17.f / 18.f patterns.

### 3.4 Production observability

Per-primitive Prometheus metrics (Counter / Gauge / Histogram) added to `axon/runtime/observability.py` (or equivalent module — created if absent):

```text
axon_dispatcher_invocations_total{primitive, outcome}      Counter
axon_dispatcher_duration_seconds{primitive}                Histogram
axon_control_flow_branches_taken_total{primitive, branch}  Counter
axon_par_branch_count{flow, par_step}                      Histogram
axon_memory_ops_total{op, backend, outcome}                Counter
axon_hibernate_token_lifetime_seconds                      Histogram
```

OTel spans wrap each dispatcher invocation; control-flow nesting produces parent-child span trees. Structured `audit_log` events for memory ops + return semantics integrate with the enterprise audit-chain from Fase 16 when the enterprise hook is present (graceful no-op when absent).

### 3.5 Property + fuzz testing

Hypothesis-based property tests for each dispatcher contract:

- **Conditional**: `for any condition + branches: exactly one branch runs, never both, never neither`
- **ForIn**: `for any iterable: body runs exactly len(iterable) times; loop variable holds last element after loop`
- **Par**: `for any branch set: every branch's terminal state is observable in ctx; gather completes when all branches do`
- **Remember/Recall**: `recall(remember(k, v).k) == v for any storable v`
- **Return**: `for any flow: subsequent steps after return do not execute`

Fuzz tests for control-flow nesting: generate random `if/for/par` trees up to depth 5, execute, assert no deadlock + no scope leaks + no orphan tasks.

### 3.6 Drift defense extension

The Fase 18 drift gate asserts every IRFlowNode variant has a classified status. Fase 19 extends it:

```text
test_no_remaining_mvp_markers_for_tier_a — asserts the matrix does
not contain "MVP" markers for Hibernate/Drill/Trail rows once 19.a/b/c
ship.

test_rust_parity_for_every_wired_primitive — parses the Rust
runner.rs and asserts every `step_type ==` arm in execute_stub
matches a row in the matrix. Adding a Python dispatcher without a
Rust counterpart fails CI.
```

---

## 4. Sub-phases

### 19.a — Hibernate full CPS integration `[PLANNED]`

`_execute_hibernate_step` upgraded:
- Construct a `ContinuityToken` via `ContinuityTokenSigner.new_token(session_id, ttl)` where `session_id = unit.flow_name + ':' + continuation_id` and `ttl = parse(timeout)`.
- Snapshot the unit's full state into the token's payload: `ContextManager` variables (excluding `__return_value__`), step results, discovered handles, hibernation context. Use a stable JSON encoding (sort keys, default=str) for byte-identical round-trips.
- Sign the token with the configured `_continuity_signer` (injected at Executor construction; default = an `InMemoryContinuitySigner` for tests, swapped for an enterprise-hardened signer in production).
- Bind `__hibernation_token__` to the **signed token string**, not the placeholder dict.
- Add a `resume_from_token(token_str)` Executor method that verifies the signature, deserializes the state, rehydrates the ContextManager, and continues the flow from the next step after the hibernate marker.

Tests: 12 scenarios — basic round-trip, expired token, forged signature, key rotation mid-flight, large state payload (1MB), nested hibernate + resume, partial state restore, malformed token rejection, multi-tenant signer scoping, replay attack prevention, ContextManager variable filter, audit-chain integration.

### 19.b — Drill full PIX integration `[PLANNED]`

`_execute_drill_step` upgraded:
- Resolve `pix_ref` against `unit.pix_specs` (already in the IR; needs threading through the compile chain).
- Instantiate `PixNavigator` against the resolved spec; call `.drill(subtree_path, query)` for the actual query.
- Bind the **real** `DrillResult` (matches list, score, navigation steps) under `output_name` (defaults to `drill:<pix_ref>`). Drop the `_stub: True` marker.

Tests: 8 scenarios — basic drill, deep subtree (3+ levels), missing pix_ref, malformed query, score thresholding, top-k bounds, navigation steps recorded, integration with downstream `trail`.

### 19.c — Trail full corroboration walker `[PLANNED]`

`_execute_trail_step` upgraded:
- Look up the prior `navigate` / `drill` step result by `navigate_ref`.
- Walk the corroboration path via `PixNavigator.trail(navigate_result)` — the existing engine has the API.
- Bind the real `TrailResult` (sequence of `NavigationStep` records with scores, justifications, selected nodes) under `trail:<navigate_ref>` AND under the bare ref name.

Tests: 6 scenarios — valid trail, missing reference, multi-hop, score consistency, integration with prior `drill`, audit-grade integrity.

### 19.d — Par per-branch context isolation `[PLANNED]`

New `ContextView` class in `axon/runtime/context_mgr.py`:

```python
class ContextView:
    """Isolated read-write view over a parent ContextManager.
    
    Reads delegate to the parent (variables, step results, discovered
    handles); writes are recorded locally in `self._writes`. On
    `merge(strategy)`, the writes are applied to the parent according
    to the chosen merge policy.
    """
    def __init__(self, parent: ContextManager): ...
    def get_variable(self, name): ...
    def set_variable(self, name, value): ...  # writes to self._writes
    def merge(self, parent: ContextManager, strategy: str): ...
```

`_execute_par_step` upgraded to spawn each branch with a fresh `ContextView`; after `asyncio.gather`, merge views back according to a metadata-configurable strategy (default `last_writer_wins`, recommended `reject_conflicts` for production).

Tests: 10 scenarios — non-conflicting writes, conflicting writes under each strategy, branch failure mid-write, view isolation (writes invisible to siblings until merge), large branch count (50 parallel writes).

### 19.e — ForIn break/continue semantics `[PLANNED]`

New IR nodes `IRBreak` / `IRContinue` added to `axon/compiler/ir_nodes.py`. Parser support for `break` / `continue` statements in flow bodies (top-level error if used outside a loop).

Sentinel exceptions `_FlowBreakSignal` / `_FlowContinueSignal` raised by their dispatchers. `_execute_for_in_step` catches both: continue → next iteration; break → exit loop. `_execute_step` does NOT catch them (they bubble up to the loop dispatcher).

Type-checker: `break`/`continue` outside a `for` loop → compile error. The `for` loop's body symbol table tracks "inside loop" so inner `break/continue` are accepted while outer ones are rejected.

Tests: 8 scenarios — break exits loop, continue skips iteration, break inside if inside for, nested for with inner break (only inner exits), break + remaining steps in same iteration, type-check rejection at flow level, type-check rejection in if outside for, type-check rejection in par branches that don't enclose a for.

### 19.f — Rust dispatchers for control flow `[PLANNED]`

In `axon-rs/src/runner.rs`:
- New payload structs: `ConditionalPayload`, `ForInPayload`, `ParPayload`, `ReturnPayload`.
- Corresponding `_payload` fields on `CompiledStep` (mirror Fase 15.c pattern).
- `build_compiled_steps` populates them from `IRFlowNode::{Conditional, ForIn, Par, Return}`.
- `execute_stub` arms handle `step.step_type ==` for each — recursive child dispatch via the same `execute_stub` loop.
- `_FlowReturnSignal` ↔ Rust equivalent via `Result<(), FlowControlSignal>` propagation up the loop.

Tests: parity goldens under `axon-rs/tests/parity/fase19_control_flow.*.json`.

### 19.g — Rust dispatchers for memory + hibernate + domain `[PLANNED]`

Same pattern for the remaining 5 primitives:
- `RememberPayload`, `RecallPayload` (memory subsystem — Rust gets a `MemoryStore` trait impl with an in-memory default).
- `HibernatePayload` (continuity token stub — full crypto signing deferred to a Rust-enterprise sub-phase if/when adopters need it).
- `DrillPayload`, `TrailPayload` (PIX subsystem stubs — full Rust PIX engine deferred to its own Fase).

The Rust dispatchers DO NOT need to reach feature parity with the Python full implementations from 19.a/b/c — they need to be **stub-correct** (no LLM fall-through, semantic placeholder bound, trace event emitted) so cross-stack execution gives consistent observable behavior even when the Rust runner is used with `--stub`.

### 19.h — Cross-stack parity goldens `[PLANNED]`

For each of the 9 newly-wired primitives, add `axon-rs/tests/parity/fase19_<primitive>.{spec,golden}.json`. Rust gate verifies the dispatcher reads the spec correctly; Python gate parses the same files and verifies the post-execution context state matches the golden.

### 19.i — Prometheus metrics + OTel spans `[PLANNED]`

New module `axon/runtime/observability.py` defining the per-primitive metrics (see §3.4). Each dispatcher emits one `Counter.inc` + one `Histogram.observe` + one OTel span. Control-flow primitives emit nested spans (parent = the flow's unit span; children = each iteration / branch).

The metrics module has zero hard dependencies on Prometheus client (graceful import via `try: from prometheus_client import Counter, Histogram, Gauge / except ImportError: <no-op stubs>`) so OSS adopters who don't install observability extras still work.

Tests: 8 scenarios — metric increments on dispatch, span hierarchy under nested control flow, no-op behavior when client unavailable.

### 19.j — Hypothesis property tests `[PLANNED]`

New `tests/test_fase19_properties.py` with Hypothesis strategies for:
- Random conditional with random literal types → exactly-one-branch invariant
- Random iterable + random body → iteration count invariant
- Random parallel branch set + random write keys → no-orphan-tasks invariant
- Random remember/recall sequence → round-trip invariant
- Random return depth → no-subsequent-step invariant

Each property runs ≥100 examples (Hypothesis default). Fuzzing interval bounded so the test suite stays under 10 seconds for the property file.

### 19.k — Random-nesting fuzz tests `[PLANNED]`

`tests/test_fase19_control_flow_fuzz.py`: Hypothesis strategy that generates random `if/for/par` trees up to depth 5. For each generated tree:
- Compile, dispatch, assert no deadlock (`asyncio.wait_for(timeout=5s)`).
- Assert no orphan tasks (`asyncio.all_tasks()` returns to baseline after dispatch).
- Assert no scope leaks (variables bound in inner scopes don't leak to outer).
- Assert exception semantics (`return` exits the flow; `break` exits the innermost loop; `continue` skips the iteration).

### 19.l — Drift gate extension `[PLANNED]`

Extends `tests/test_ir_runtime_coverage.py`:
- `test_no_remaining_mvp_markers_for_tier_a` — asserts matrix rows for Hibernate/Drill/Trail do NOT contain "MVP" once 19.a/b/c land.
- `test_rust_parity_for_every_wired_primitive` — parses `axon-rs/src/runner.rs` for `step.step_type ==` arms in `execute_stub`; asserts every WIRED primitive in the matrix has a Rust counterpart.
- Updates the matrix table in `docs/fase_18_ir_runtime_audit.md` with a new "Rust" column (✅ wired / 🔵 LLM-fallback / N/A).

### 19.m — Documentation honesty + memory `[PLANNED]`

- IR docstrings updated to remove "MVP" markers as primitives upgrade (Hibernate, Drill, Trail).
- Plan doc (this file) status flipped to SHIPPED with sub-phase markers.
- README updated with a "Production runtime guarantees" section listing the 9+3 wired primitives + the drift-gate guarantee.
- Memory file `project_fase_19_plan.md` updated to SHIPPED state.
- Tracker issue closed with summary + cross-links.

### 19.n — Coordinated release `[PLANNED]`

- `axon-lang v1.13.0 → v1.14.0` minor bump (additive: production-quality dispatchers + Rust parity + observability + property tests).
- `axon-frontend v0.5.0 → v0.6.0` minor bump (new IR nodes `IRBreak`, `IRContinue` if added).
- bump-my-version coordinated commit + tag.
- `cargo publish --allow-dirty` for both crates.
- PyPI publish via release workflow.
- GH Release with binaries + comprehensive release notes.

---

## 5. Out of scope

- **Full Rust PIX engine implementation** (parity for `Drill`/`Trail` semantic depth). The Rust dispatchers in 19.g are stub-correct only; the full Rust PIX engine is its own undertaking, deferred to Fase 20+ if adopters need it.
- **Distributed Hibernate** (resume across multiple AxonServer instances). The Fase 19 hibernate stays single-instance; multi-instance resume requires the enterprise distributed-state surface from Fase 16 + a separate continuation-token namespace, deferred to a follow-up.
- **Performance optimization** of the dispatchers. The implementations are correctness-first + observability-first; profiling + tight inner-loop tuning is post-release work driven by production telemetry.
- **Type-narrowing in conditionals** (TypeScript-style "if x is string then x: string"). The conditional dispatcher's evaluator is value-based; the type system doesn't propagate the narrowing back to subsequent steps. Future Fase if epistemic-lattice work surfaces it.
- **Custom merge strategies for Par beyond the four built-in ones**. Adopters with bespoke merge needs can subclass `ContextView`; standard library stays focused on the four common policies.
- **Enterprise extension**: no enterprise version bump required. The observability metrics integrate with existing enterprise telemetry adapters (Fase 16) but do not require them.

---

## 6. Acceptance criteria (for declaring Fase 19 SHIPPED)

1. Every sub-phase 19.a–19.n marked `[DONE]` ✓ with a release reference.
2. **MVP markers eliminated**: matrix rows for Hibernate/Drill/Trail describe full subsystem integration; `_stub: True` markers absent from runtime dispatcher payloads.
3. **Rust parity gate** (19.l) passes — every WIRED primitive in the matrix has a Rust dispatcher counterpart.
4. **Property tests** ≥100 examples per primitive, no failures across 5 random seeds.
5. **Fuzz tests** generate ≥50 random control-flow nestings per run, no deadlocks, no orphan tasks.
6. **No regression** in v1.13.0 baselines: Python 4368 → ≥4518; Rust 1043 → ≥1080.
7. **Observability gate**: every dispatcher emits ≥1 Prometheus metric + ≥1 OTel span. Verified by counter assertions in tests.
8. **Continuity token round-trip** verified end-to-end: hibernate → serialize → restart Executor → deserialize → resume same flow → identical step-result history.
9. **Documentation honesty** verified by the existing Fase 17.h regression test pattern + a new test that asserts no `_stub` marker appears in production code paths (only in the deprecated MVP markers documented in the plan history).
10. **Tagged + released** as `axon-lang v1.14.0` on PyPI + crates.io; `axon-frontend v0.6.0` on crates.io; GH Release with 5 platform binaries; coordinated bump commit + tags pushed.

---

## 7. Pattern recognition — closing the production-readiness loop

| Fase | Scope |
|---|---|
| Fase 15 | Closed 1 reactive gap (lambda apply) |
| Fase 16 | Closed enterprise daemon supervision (10/10) |
| Fase 17 | Closed 1 reactive gap (let) |
| Fase 18 | Closed 9 remaining gaps + drift gate (no more reactive bug-hunting) |
| **Fase 19** | **Closes the MVP markers + adds Rust parity + adds production observability + property/fuzz testing** |

After Fase 19 ships, the AXON OSS runtime is honestly production-ready: every flow primitive has full subsystem integration, Rust + Python runners agree on semantics, observability + audit hooks are in place for ops teams, and property + fuzz tests catch the edge cases adopters would otherwise discover in production.
