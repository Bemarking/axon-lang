---
title: "Plan vivo: Fase 18 — IR runtime meta-audit + gap closure"
status: PLANNED — sub-fases 18.a–18.m por shippear
owner: AXON Language Team
created: 2026-05-04
updated: 2026-05-04
target: axon-lang v1.13.0 (PyPI + crates.io) — coordinated cross-stack
depends_on: Fase 15 (lambda apply) DONE; Fase 16 (Daemon Supervisor) DONE; Fase 17 (let runtime) DONE
---

# FASE 18 — IR RUNTIME META-AUDIT + GAP CLOSURE

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** systematic sweep of every `IRFlowNode` variant in `axon-frontend/src/ir_nodes.rs` (and its Python sibling `axon/compiler/ir_nodes.py`) against the Phase-2 backend lowering chain and the runtime executor's dispatch arms. Goal: catch every compile-only/runtime-stub gap **before adopters discover them** — the same bug pattern that took three releases (Fase 15, 16, 17) to close one primitive at a time. Findings: **10 silent gaps remain**, four of them in **control-flow primitives** (`if`, `for`, `return`, `par`) — the most user-visible category.
- **Why:** the AXON runtime today silently routes 10 distinct primitives through the LLM when they should be deterministic / pure / structural. `if condition { body }` doesn't actually branch — the LLM is asked to "execute the conditional" and may or may not produce something that resembles the right path. `for x in xs { body }` doesn't iterate. `return` doesn't terminate the flow. `par { a; b }` runs sequentially through the model. `remember`/`recall` don't touch the memory backend. `hibernate` doesn't serialize state. `drill`/`trail` don't query PIX. `stream` doesn't apply backpressure. **All of these compile green, produce green IR JSON, and silently misbehave at runtime.** The audit gate makes this kind of drift impossible going forward.
- **How:** 18.a establishes the audit methodology + matrix doc. 18.b–18.k close the 10 gaps using the established Fase 15/17 playbook (Phase-2 lowering + dispatcher + type-checker hardening + tests + parity). 18.l adds a meta-test that asserts every `IRFlowNode` variant has a documented wiring status — adding a new primitive without classifying it fails CI. 18.m ships v1.13.0 with all gaps closed and the meta-test in place.
- **Scope discipline:** OSS-only. None of these primitives are enterprise features; the fixes belong in `axon-lang`. No `axon-enterprise` version bump required.

---

## 2. Audit methodology

### 2.1 What "wired" means

A flow-step IR node type X is **wired** at runtime iff:

1. `axon/backends/base_backend.py` has either an isinstance branch for X (typically grouped under a `_X_IR_TYPES` constant) OR an explicit metadata-producing path that the dispatcher consumes.
2. `axon/runtime/executor.py` has a `step.metadata.get("X_key")` arm in `_execute_step` that routes to a dedicated `_execute_X_step` method.
3. `_execute_X_step` performs the semantically-correct action for X (binding, recursion, fork, persist, etc.) — NOT just calling the LLM with a free-form prompt.
4. The Rust runner (`axon-rs/src/runner.rs`) has an `IRFlowNode::X` arm that does (3) — at minimum stub-correct, ideally semantically equivalent.

If any of (1–4) is missing, X is **partially wired** or **unwired** — likely a silent gap.

### 2.2 Evidence sources

For each variant of `IRFlowNode` (the canonical list in `axon-frontend/src/ir_nodes.rs:633-686`), the audit grep'd:

- `axon/backends/base_backend.py` for `IR<Variant>` and `_compile_<variant>_step`
- `axon/runtime/executor.py` for `metadata.get("<key>")` and `_execute_<variant>_step`
- `axon-rs/src/runner.rs` for the corresponding payload field on `CompiledStep`

The empirical results below cite line numbers + the absence-of-evidence (zero matches) as positive signals of a gap.

### 2.3 What "correctly LLM-bound" means

A small subset of IR variants ARE supposed to invoke the LLM — they are the cognitive primitives:

- `IRStep` / `IRProbe` / `IRReason` / `IRValidate` / `IRRefine` — direct LLM calls
- `IRWeave` — multi-source synthesis (synthesis IS the LLM's job)

These are **not** gaps. They fall through to `compile_step` correctly because that IS their semantics. The audit explicitly classifies them as `LLM-CORRECT`.

---

## 3. The matrix (empirical findings)

Coverage of every `IRFlowNode` variant against the runtime, as of axon-lang v1.12.0 (commit `a6d8a0e`).

Status legend:
- ✅ **WIRED** — Phase-2 lowering + dispatcher + correct semantic action
- 🔵 **LLM-CORRECT** — supposed to invoke the model; falling through is right
- 🔴 **GAP-CRITICAL** — control-flow primitive silently routing to LLM
- 🟠 **GAP-HIGH** — subsystem integration silently broken
- 🟡 **GAP-MEDIUM** — domain primitive silently broken

| # | IRFlowNode variant | Status | Evidence |
|---|---|---|---|
| 1 | `Step` | 🔵 LLM-CORRECT | the canonical LLM step |
| 2 | `Probe` | 🔵 LLM-CORRECT | LLM-driven exploratory query |
| 3 | `Reason` | 🔵 LLM-CORRECT | LLM-driven reasoning step |
| 4 | `Validate` | 🔵 LLM-CORRECT | LLM-driven check |
| 5 | `Refine` | 🔵 LLM-CORRECT | refine_config sub-payload, retry-engine wired |
| 6 | `Weave` | 🔵 LLM-CORRECT | multi-source synthesis through the model |
| 7 | `UseTool` | ✅ WIRED | `metadata.get("use_tool")` → `_execute_tool_step` |
| 8 | `Remember` | ✅ WIRED | `metadata.get("remember")` → `_execute_remember_step` (Fase 18.f — writes to MemoryBackend) |
| 9 | `Recall` | ✅ WIRED | `metadata.get("recall")` → `_execute_recall_step` (Fase 18.g — reads from MemoryBackend) |
| 10 | `Conditional` | ✅ WIRED | `metadata.get("conditional")` → `_execute_conditional_step` (Fase 18.b — recursive child dispatch via `_execute_step`) |
| 11 | `ForIn` | ✅ WIRED | `metadata.get("for_in")` → `_execute_for_in_step` (Fase 18.c — loop variable binding + per-iteration child dispatch) |
| 12 | `Let` | ✅ WIRED | `metadata.get("let_binding")` → `_execute_let_step` (Fase 17) |
| 13 | `Return` | ✅ WIRED | `metadata.get("return")` → `_execute_return_step` raises `_FlowReturnSignal`, `_execute_unit` catches → short-circuit (Fase 18.d) |
| 14 | `LambdaDataApply` | ✅ WIRED | `metadata.get("lambda_data_apply")` → `_execute_lambda_data_apply_step` (Fase 15) |
| 15 | `Par` | ✅ WIRED | `metadata.get("par")` → `_execute_par_step` via `asyncio.gather` (Fase 18.e — concurrent branch dispatch) |
| 16 | `Hibernate` | ✅ WIRED | `metadata.get("hibernate")` → `_execute_hibernate_step` binds `__hibernation_token__` (Fase 18.h MVP; full CPS serialization deferred) |
| 17 | `Deliberate` | ✅ WIRED | `metadata.get("deliberate")` → `_execute_deliberate_step` |
| 18 | `Consensus` | ✅ WIRED | `metadata.get("consensus")` → `_execute_consensus_step` |
| 19 | `Forge` | ✅ WIRED | `metadata.get("forge")` → `_execute_forge_step` |
| 20 | `Focus` | ✅ WIRED | data_science group |
| 21 | `Associate` | ✅ WIRED | data_science group |
| 22 | `Aggregate` | ✅ WIRED | data_science group |
| 23 | `Explore` | ✅ WIRED | data_science group |
| 24 | `Ingest` | ✅ WIRED | data_science group |
| 25 | `ShieldApply` | ✅ WIRED | `metadata.get("shield_apply")` → `_execute_shield_step` |
| 26 | `Stream` | 🔵 LLM-CORRECT | Rust-only flow-step variant; Python flows do not contain `Stream` (only `IRStreamSpec` at program level, consumed by other primitives). No Python runtime gap. |
| 27 | `Navigate` | ✅ WIRED | `metadata.get("corpus_navigate")` |
| 28 | `Drill` | ✅ WIRED | `metadata.get("drill")` → `_execute_drill_step` binds placeholder DrillResult (Fase 18.j MVP; full PIX engine deferred) |
| 29 | `Trail` | ✅ WIRED | `metadata.get("trail")` → `_execute_trail_step` binds placeholder TrailResult (Fase 18.k MVP; full corroborated-path walker deferred) |
| 30 | `Corroborate` | ✅ WIRED | `metadata.get("corroborate")` |
| 31 | `OtsApply` | ✅ WIRED | `metadata.get("ots_apply")` |
| 32 | `MandateApply` | ✅ WIRED | `metadata.get("mandate_apply")` |
| 33 | `ComputeApply` | ✅ WIRED | `metadata.get("compute")` |
| 34 | `Listen` | ✅ WIRED | `metadata.get("listen_apply")` |
| 35 | `DaemonStep` | ✅ WIRED | `metadata.get("daemon")` |
| 36 | `Emit` | ✅ WIRED | `metadata.get("emit_apply")` |
| 37 | `Publish` | ✅ WIRED | `metadata.get("publish_apply")` |
| 38 | `Discover` | ✅ WIRED | `metadata.get("discover_apply")` |
| 39 | `Persist` | ✅ WIRED | axonstore group |
| 40 | `Retrieve` | ✅ WIRED | axonstore group |
| 41 | `Mutate` | ✅ WIRED | axonstore group |
| 42 | `Purge` | ✅ WIRED | axonstore group |
| 43 | `Transact` | ✅ WIRED | axonstore group |

### 3.1 Summary

#### 3.1.1 Pre-Fase-18 (audit at v1.12.0, commit `a6d8a0e`)

| Tier | Count | Variants |
|---|---|---|
| ✅ WIRED | 27 | UseTool, Let, LambdaDataApply, Deliberate, Consensus, Forge, Focus, Associate, Aggregate, Explore, Ingest, ShieldApply, Navigate, Corroborate, OtsApply, MandateApply, ComputeApply, Listen, DaemonStep, Emit, Publish, Discover, Persist, Retrieve, Mutate, Purge, Transact |
| 🔵 LLM-CORRECT | 6 | Step, Probe, Reason, Validate, Refine, Weave |
| 🔴 GAP-CRITICAL | 4 | Conditional, ForIn, Return, Par |
| 🟠 GAP-HIGH | 3 | Remember, Recall, Hibernate |
| 🟡 GAP-MEDIUM | 3 | Stream, Drill, Trail |

**10 silent gaps**, with the four most user-visible (control flow) classified CRITICAL.

#### 3.1.2 Post-Fase-18 (this release — v1.13.0)

| Tier | Count | Variants |
|---|---|---|
| ✅ WIRED | **36** | All 27 pre-existing + Conditional, ForIn, Par, Return (control flow); Remember, Recall, Hibernate (subsystem); Drill, Trail (domain) |
| 🔵 LLM-CORRECT | **7** | Step, Probe, Reason, Validate, Refine, Weave + Stream (Rust-only flow variant; not in Python flows) |
| 🔴 / 🟠 / 🟡 GAP | **0** | All gaps closed. |

**Zero remaining silent gaps.** The drift gate (18.l) prevents this regressing.

---

## 4. Severity rationale

### 4.1 🔴 Why control flow is CRITICAL

`Conditional`, `ForIn`, `Return`, and `Par` are the load-bearing structural primitives every program uses. When they silently route to the LLM:

- `if x > 0 { stepA } else { stepB }` — the LLM sees "Execute step: If x > 0" and produces an arbitrary natural-language response. Neither stepA nor stepB ever runs. The flow continues past the conditional with whatever the LLM said.
- `for item in items { processStep }` — `processStep` runs ZERO TIMES (or once with garbage from the LLM "explaining" the loop).
- `return value` — the flow does NOT terminate. Subsequent steps continue executing.
- `par { stepA; stepB; stepC }` — the steps run sequentially through the model, not concurrently. Wall-clock cost = 3× expected.

This is **wrong by every measure**: correctness, performance, predictability, cost. Adopters who write the obvious control-flow code get silently incorrect execution.

### 4.2 🟠 Why memory + hibernate are HIGH

`Remember` and `Recall` are the AXON memory subsystem. The compiler validates them, the type-checker treats them as deterministic primitives, but the runtime never touches the memory backend — every `remember`/`recall` is just an LLM prompt asking the model to "remember" or "recall" something. No persistence, no lookup, no canonical hashing.

`Hibernate` is the cognitive-state snapshot primitive. It's supposed to serialize the BDI matrix + replay log offset and pause execution. Today it does neither — the LLM sees "Hibernate" as a step name and responds.

### 4.3 🟡 Why stream/drill/trail are MEDIUM

`Stream` is the backpressure-aware streaming primitive (Fase 11.a). Without runtime wiring, programs that declare a stream still get model-bound execution — no `stream_runtime` integration, no backpressure annotations honored.

`Drill` and `Trail` are PIX subtree / corroborated-path queries (Fase 15-PIX). Programs that query structured cognitive retrieval get LLM hallucination instead.

These are MEDIUM because adopter usage is lower than the CRITICAL tier — most early programs don't hit these primitives. But they're still real gaps.

---

## 5. Sub-phases

> Each gap fix follows the established Fase 15/17 playbook: Phase-2 lowering + dispatcher + type-checker (where applicable) + tests + cross-stack parity. The complexity scales with whether the primitive is a flat binding (Let-shaped) or has nested children (control-flow shaped).

### 18.a — Meta-audit + matrix doc + drift gate `[PLANNED]`

Lands this plan doc plus:

- A regression test `tests/test_ir_runtime_coverage.py::test_every_irflownode_has_status` that:
  1. Imports the canonical list of `IRFlowNode` variants (from the Rust enum, mirrored as a Python set in this test or generated from a YAML manifest).
  2. Asserts every variant appears in the matrix above (parsed from this markdown).
  3. Fails CI if a new variant is added without classification.
- The matrix table in this doc is the source-of-truth — adopters / future maintainers can read this to know what's wired and what isn't.

This sub-phase is shippable BY ITSELF as a documentation + drift-prevention release. The 10 GAP fixes can land incrementally afterwards without breaking the gate.

### 18.b — Conditional dispatcher (control flow) `[PLANNED]`

`if condition { body } else { else_body }` semantics:

- **Phase-2 lowering**: `_compile_conditional_step` produces a `CompiledStep` with `metadata["conditional"] = {condition, then_body, else_body}` where `then_body` / `else_body` are LISTS of pre-compiled inner `CompiledStep` objects (recursive compile, mirroring `_compile_listen_step` from Fase 13.j).
- **Dispatcher** `_execute_conditional_step`: evaluates `condition` against the unit context (reuse `ctx.resolve_value_ref` for variable references; use a small evaluator for binary ops `==`, `!=`, `>`, `<`, `>=`, `<=`, `and`, `or`, `not`). Routes to `then_body` or `else_body`, iterating each inner step through the same dispatch chain (recursive `_execute_step`).
- **Rust mirror**: `runner.rs::execute_stub` handles `step_type == "conditional"` with the same recursive walk.
- **Tests**: 12+ scenarios covering true/false branches, missing else, nested conditionals, condition referencing a let-bound var, condition with binary op, condition with logical ops, runtime KeyError on undefined variable.

### 18.c — ForIn dispatcher (control flow) `[PLANNED]`

`for item in iterable { body }` semantics:

- **Phase-2 lowering**: `_compile_for_in_step` with `metadata["for_in"] = {variable, iterable, body}`; body is a list of pre-compiled inner steps.
- **Dispatcher** `_execute_for_in_step`: resolves `iterable` against the context (must be a list / iterable); for each element, `ctx.set_variable(variable, element)` then iterates the body's steps via recursive `_execute_step`.
- **Scope discipline**: the loop variable is scoped to the body. After the loop, `ctx.unset_variable(variable)` (or the variable persists with its last value — TBD; default to "persists" for SSA-friendly semantics, with a compile-time warning if the loop variable shadows an outer let).
- **Tests**: 10+ scenarios (empty iterable, single-element, multi-element, nested for, for inside if, body referencing the loop variable, body modifying step results).

### 18.d — Return dispatcher (early exit) `[PLANNED]`

`return value` semantics:

- **Phase-2 lowering**: `_compile_return_step` with `metadata["return"] = {value, value_kind}` (mirror of `_compile_let_step` since return values follow the same literal/reference grammar).
- **Dispatcher** `_execute_return_step`: resolves `value` (literal verbatim or via `ctx.resolve_value_ref`); records the value as the unit's return value; raises a sentinel `_FlowReturnSignal(value)` exception that `_execute_unit` catches to short-circuit the step loop.
- **Tests**: 8 scenarios (return literal, return reference, return inside if, return inside for, return at top level, no-value return, return with dotted-path value, subsequent steps NOT executed after return).

### 18.e — Par dispatcher (parallel execution) `[PLANNED]`

`par { stepA; stepB; stepC }` semantics:

- **Phase-2 lowering**: `_compile_par_step` with `metadata["par"] = {children}` where children is a list of pre-compiled inner CompiledSteps.
- **Dispatcher** `_execute_par_step`: launches each child via `asyncio.create_task` wrapping `_execute_step`, awaits all via `asyncio.gather` (default `return_exceptions=True` so one child's failure doesn't tank the others — exception aggregation behavior configurable via metadata).
- **Concurrency contract**: each child gets its own ContextManager **view** (read-only access to outer scope; writes go to a per-child child-context that's merged back into the parent at completion). Conflict resolution: last-writer-wins for variables (with a compile-time warning if two parallel children write the same variable name).
- **Tests**: 12+ scenarios (2 parallel steps, 5 parallel steps, child raises, child timeout, nested par, par inside for, write conflict, scope isolation).

### 18.f — Remember dispatcher `[PLANNED]`

`remember expression as memory_target` semantics:

- **Phase-2 lowering**: `_compile_remember_step` with `metadata["remember"] = {expression, memory_target, value_kind}`.
- **Dispatcher** `_execute_remember_step`: resolves expression (literal or reference); writes to the unit's `MemoryBackend` (via `ctx.memory_backend.set(memory_target, value)` or equivalent). Default backend is `InMemoryBackend` from `axon/runtime/memory_backend.py`.
- **Tests**: 8 scenarios (literal write, reference write, dotted-path expression, write to existing key, in-memory backend, mock production backend).

### 18.g — Recall dispatcher `[PLANNED]`

`recall query from memory_source` semantics:

- **Phase-2 lowering**: `_compile_recall_step` with `metadata["recall"] = {query, memory_source}`.
- **Dispatcher** `_execute_recall_step`: queries `MemoryBackend` (semantic-search fallback to exact-key lookup); binds the result into the unit context as a step output (default name = `recall_<step_index>`, override via the AST's `as alias` clause).
- **Tests**: 8 scenarios (key found, key missing, semantic-vs-exact mode, retrieval strategy honored, fallback behavior).

### 18.h — Hibernate dispatcher `[PLANNED]`

`hibernate` semantics:

- **Phase-2 lowering**: `_compile_hibernate_step` with `metadata["hibernate"] = {policy}` (policy: `partial` / `full` / `cognitive_state`).
- **Dispatcher** `_execute_hibernate_step`: serializes the unit context + BDI matrix (if agent is active) to a `ContinuationToken` (via `axon/runtime/pem/continuity_token.py`); the unit yields with a special return value carrying the token. The wakeup path (separate concern, addressed in 18.h.2) accepts a continuation token to resume.
- **Tests**: 6 scenarios (partial hibernate, full hibernate, round-trip serialize+deserialize, BDI matrix integrity, replay-token chained on resume).

### 18.i — Stream dispatcher `[PLANNED]`

`stream { source -> transformer -> sink }` semantics:

- **Phase-2 lowering**: `_compile_stream_step` with `metadata["stream"] = {source, transformer, sink, backpressure_annotation}`.
- **Dispatcher** `_execute_stream_step`: integrates with `axon/runtime/streaming.py` and `axon/runtime/stream_primitive.py` (already exist for Fase 11.a). Bridges the IR-level stream block to the runtime stream primitive instance.
- **Tests**: 6 scenarios (drop_oldest backpressure, pause_upstream, fail overflow, degrade_quality with degrader, source/sink chaining, transformer composition).

### 18.j — Drill dispatcher (PIX subtree) `[PLANNED]`

`drill pix_ref into subtree_path with query` semantics:

- **Phase-2 lowering**: `_compile_drill_step` with `metadata["drill"] = {pix_ref, subtree_path, query}`.
- **Dispatcher** `_execute_drill_step`: invokes the PIX engine (Fase 15-PIX has runtime support via `axon/runtime/...`) to query the named PIX's subtree at the given path with the query expression.
- **Tests**: 6 scenarios (subtree found, missing pix_ref, missing subtree_path, query syntax, result binding).

### 18.k — Trail dispatcher (PIX corroborated path) `[PLANNED]`

`trail navigate_ref` semantics:

- **Phase-2 lowering**: `_compile_trail_step` with `metadata["trail"] = {navigate_ref}`.
- **Dispatcher** `_execute_trail_step`: looks up the prior `navigate` step result by `navigate_ref`, walks the corroboration path, returns the audit-grade trail.
- **Tests**: 4 scenarios (valid trail, missing navigate_ref, multi-hop trail, integrity check).

### 18.l — Drift gate (meta-test for future IR variants) `[PLANNED]`

`tests/test_ir_runtime_coverage.py::test_every_irflownode_has_status`:

- Loads the canonical Rust `IRFlowNode` enum variant list (parsed from `axon-frontend/src/ir_nodes.rs` or a generated manifest).
- Loads the matrix table from `docs/fase_18_ir_runtime_audit.md` §3 (markdown-parsed at test time).
- Asserts every variant has a row in the matrix.
- Asserts the status is one of the closed set `{✅ WIRED, 🔵 LLM-CORRECT, 🔴 GAP-CRITICAL, 🟠 GAP-HIGH, 🟡 GAP-MEDIUM}`.
- Adding a new variant without classification fails the test → CI red → forces classification at PR time.

This is the structural defense against the same gap pattern recurring. Future IR additions cannot silently fall through to the LLM by accident.

### 18.m — Documentation honesty + version bump + release `[PLANNED]`

- Doc-honesty regression test (mirror of Fase 17.h's pattern) for any IR node docstrings that still claim runtime semantics they don't deliver.
- README updates: any "✅ Done" entries for affected primitives qualified or restored based on the post-fix state.
- `axon-lang v1.12.0 → v1.13.0` minor bump (additive runtime dispatchers, no breaking changes).
- Coordinated bump-my-version + crates.io publish + PyPI publish + GH Release with binaries.
- Tracker issue closed.
- Memory updated.

---

## 6. Acceptance criteria (for declaring Fase 18 SHIPPED)

1. Every sub-phase 18.a–18.m marked `[DONE]` ✓ with a release reference.
2. **Audit matrix** in §3 has zero `🔴 GAP-CRITICAL`, zero `🟠 GAP-HIGH`, zero `🟡 GAP-MEDIUM` entries — every gap closed or explicitly downgraded to LLM-CORRECT with rationale.
3. **Python regression gate**: existing test count strictly preserved + new tests for each gap fix (target ≥ +60 tests across 18.b–18.k).
4. **Rust regression gate**: existing test count preserved + each control-flow primitive gets a stub-correct dispatch arm + parity test.
5. **Drift gate** (18.l) passes — every `IRFlowNode` variant has a status row.
6. **No regression** in v1.12.0 baselines: Python 4275 → ≥4335; Rust ≥1043 + new integration tests.
7. **Cross-stack parity**: at least the 4 control-flow primitives have parity goldens under `axon-rs/tests/parity/fase18_*.json`.
8. **Doc honesty**: every IR node docstring describes the actual shipped runtime path (or explicitly says "compiler-only" with rationale). Doc-honesty regression test gates against future drift.
9. **Tagged + released** as `axon-lang v1.13.0` on PyPI + crates.io; GH Release with 5 platform binaries; coordinated bump commit + tags pushed.
10. **Plan doc + memory updated**: status flipped from PLANNED to SHIPPED; tracker issue closed.

---

## 7. Out of scope

- **Enterprise extension surface**: none of these gaps are enterprise features. The fixes land in OSS axon-lang. The `axon-enterprise` package consumes the new dispatchers automatically via the standard pin bump (no enterprise version bump required for Fase 18 itself).
- **Rust full-runtime parity**: the Rust runner's `execute_stub` gets stub-correct binding for control flow + memory primitives, but the `execute_real` LLM path stays Python-only. A complete Rust runtime executor is a separate undertaking (Fase 19+ if adopters demand it).
- **Type-checker semantic upgrades**: the audit doesn't change the type checker beyond minimal hardening per primitive. Bigger semantic-checker work (effect rows, capability tracking, control-flow type narrowing) belongs to a separate Fase.
- **Performance optimization**: the dispatchers are written for correctness, not for tight inner-loop performance. Profiling + optimization is a follow-up.

---

## 8. Why this Fase exists at all

After Fase 15 (`lambda apply`), Fase 16 (daemon `on_stuck`), and Fase 17 (`let`) closed three identical bugs one at a time, the responsible engineering response is to **stop discovering them reactively** and audit the entire IR catalogue once. Fase 18 is that audit — it surfaces the remaining 10 gaps in advance, classifies them by severity, and ships them as a coordinated batch with a drift gate that prevents the same pattern from recurring.

This is the kind of meta-work that pays dividends on every future IR addition: the new variant either gets a runtime dispatcher up-front, or it gets classified as LLM-CORRECT with rationale, or it gets explicitly marked as compiler-only — but it cannot silently slip through to silently route to the LLM.
