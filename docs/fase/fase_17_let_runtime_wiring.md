---
title: "Plan vivo: Fase 17 — `let` runtime wiring"
status: PLANNED — sub-fases 17.a–17.h por shippear
owner: AXON Language Team
created: 2026-05-04
updated: 2026-05-04
target: axon-lang v1.12.0 (PyPI + crates.io) — coordinated cross-stack
depends_on: Fase 15 (lambda apply runtime) DONE; Fase 16 (Daemon Supervisor) DONE
---

# FASE 17 — `let` RUNTIME WIRING

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** the `let X = value` flow-body statement is fully wired through the front-end (lexer → parser → type-checker → IR `IRLetBinding` with `node_type="let_binding"`) but **no runtime executor dispatches it** in v1.11.0. Phase-2 backend compilation drops it through to the default `compile_step` path (which produces an LLM-bound prompt), the Python `Executor` has no `let_binding` metadata arm, and the Rust `runner.rs` only mentions `let` in its trace-only `extract_step_info`. Programs that use `let` for variable initialization compile green and produce green IR JSON, then **silently route the binding to the LLM**: the variable is never bound in the unit's `ContextManager`, and any downstream `${X}` interpolation finds nothing (or junk from the LLM's response).
- **Why:** this is the third instance of the same gap pattern Fase 15 (`lambda apply`) and Fase 16 (`on_stuck` daemon policies) closed. A pure, deterministic primitive (the IR docstring explicitly says *"a deterministic, serializable value for runtime macro substitution"*) that the front-end lowers to IR but no executor implements. The docstring is a documented promise; the executor is the lie. Closing the gap takes <300 LOC + ~25 tests.
- **Impact on adopters:** any `.axon` program that uses `let` for variable bookkeeping is broken at runtime today. The compile gate hides the bug — adopters discover it only when downstream `${X}` interpolation produces unexpected text. This phase makes the docstring an honest promise.
- **Robustness target:** ship not just the dispatcher but also the type-checker hardening (no shadowing of flow params, step names, reserved primitives), the interpolation resolution path (uniform precedence across `${X}` / `$X` / dotted access), the cross-stack parity golden (Python + Rust produce byte-identical bindings), and 25+ tests covering literal kinds (str/int/float/bool/list), dotted-path values, interpolation in user_prompts, scope (let inside if/for bodies), SSA rebind rejection, and replay-token round-trip.

---

## 2. Audit findings (the gap)

Definitive grep evidence collected on commit `82504e6` (axon-lang v1.11.0):

| Layer | Wired? | Evidence |
|---|---|---|
| Lexer + parser → AST `LetStatement` | ✅ | [axon/compiler/ast_nodes.py:699-712](axon/compiler/ast_nodes.py#L699-L712), [axon/compiler/parser.py:2245+](axon/compiler/parser.py#L2245) |
| IR generator → `IRLetBinding` (`node_type="let_binding"`) | ✅ | [axon/compiler/ir_nodes.py:529-543](axon/compiler/ir_nodes.py#L529-L543), [axon/compiler/ir_generator.py:995-1007](axon/compiler/ir_generator.py#L995-L1007) |
| Type checker — SSA enforcement | ✅ | [axon/compiler/type_checker.py:1076-1101](axon/compiler/type_checker.py#L1076-L1101) — `SymbolTable.declare()` rejects rebind |
| Phase-2 backend lowering (`axon/backends/base_backend.py`) | ❌ | **0 matches** for `IRLetBinding` or `let_binding` beyond imports — no `_LET_IR_TYPES` constant, no `_compile_let_step` method, no isinstance arm in `compile_program`'s 12-branch dispatch chain. Falls through to `else: compile_step(step, ctx)`. |
| Backend-specific `compile_step` (anthropic / gemini / openai / ollama) | ❌ no special-case | All four impls produce LLM-bound `CompiledStep`s indistinguishable from a regular step. |
| Python runtime executor (`axon/runtime/executor.py`) | ❌ | **0 matches** for `let_binding` — no `_execute_let_step` method, no `step.metadata.get("let_binding")` arm. The compiled step falls into `_call_model` (~line 789). |
| Rust runtime (`axon-rs/src/runner.rs`) | ❌ | Only appears in `extract_step_info` (`IRFlowNode::Let(s) => (s.target, "let", format!("Let {} = {}"))` at line 269) — string for trace formatting only; no `ExecContext.set()` call. |
| Docstring honesty | ❌ | [axon/compiler/ir_generator.py:996-1000](axon/compiler/ir_generator.py#L996-L1000) `_visit_let` says *"deterministic, serializable value for runtime macro substitution"* — **no such substitution exists in the runtime.** Same lying-docstring pattern that Fase 15 (`IRLambdaDataApply`) and Fase 16 (`StateBackend`) had. |

---

## 3. Architecture — same playbook as Fase 15.a/15.b

The fix structure mirrors Fase 15 exactly. No new design decisions needed — apply the established pattern.

### 3.1 Phase-2 lowering (17.a)

`axon/backends/base_backend.py`:

```python
_LET_IR_TYPES = (IRLetBinding,)   # NEW

# In compile_program's isinstance dispatch chain (insertion point: after
# _LAMBDA_APPLY_IR_TYPES, before _DAEMON_IR_TYPES — alphabetical
# convention in this codebase):
elif isinstance(step, _LET_IR_TYPES):
    let_step = self._compile_let_step(step)
    compiled_steps.append(let_step)

@staticmethod
def _compile_let_step(step: IRLetBinding) -> CompiledStep:
    return CompiledStep(
        step_name=f"let:{step.target}",
        user_prompt="",
        metadata={
            "let_binding": {
                "target": step.target,
                "value": step.value,
                "value_kind": _classify_value_kind(step.value),
            },
        },
    )
```

`value_kind` discriminates literal-vs-reference at compile time so the dispatcher knows whether to resolve via `ctx.resolve_value_ref` (dotted-path reference) or just bind directly (literal).

### 3.2 Python dispatcher (17.b)

`axon/runtime/executor.py`:

```python
# In _execute_step's metadata dispatch chain (insertion point: after
# lambda_data_apply for the same alphabetical-ish convention):
if step.metadata.get("let_binding"):
    return await self._execute_let_step(
        step=step, unit=unit, ctx=ctx, tracer=tracer,
    )

async def _execute_let_step(...) -> StepResult:
    meta = step.metadata["let_binding"]
    target = meta["target"]
    value = meta["value"]
    kind = meta.get("value_kind", "literal")

    if kind == "reference":
        # Dotted-path resolution against the unit context: e.g.
        # `let X = step_a.output.field` resolves through the same
        # value_ref machinery as Fase 15's lambda apply target.
        try:
            resolved = ctx.resolve_value_ref(value)
        except KeyError as exc:
            raise AxonRuntimeError(
                f"let '{target}' = '{value}': reference not found in unit context — {exc}"
            ) from exc
    else:
        resolved = value  # literal — pass through

    ctx.set_variable(target, resolved)
    tracer.emit(STEP_END, ..., data={
        "type": "let_binding", "target": target,
        "value_kind": kind, "value_repr": repr(resolved)[:120],
    })
    # Pure binding — no LLM, no I/O. Return ModelResponse-shaped
    # placeholder so downstream validation / refine logic doesn't
    # special-case it.
    return StepResult(...)
```

### 3.3 Rust dispatcher (17.c)

`axon-rs/src/runner.rs::execute_stub` — promote the `IRFlowNode::Let` arm from trace-string-only to stub-correct binding:

```rust
if step.step_type == "let" {
    if let Some(payload) = &step.let_payload {
        let resolved = if payload.is_reference {
            stub_ctx.get(&payload.value).map(str::to_string)
                .unwrap_or_else(|| payload.value.clone())
        } else {
            payload.value.clone()
        };
        stub_ctx.set(&payload.target, &resolved);
        // Emit trace event identical shape to Python's STEP_END
        ...
        continue;
    }
}
```

New `LetPayload` struct + `let_payload: Option<LetPayload>` field on `CompiledStep` (mirror of Fase 15.c's `lambda_apply_payload`).

### 3.4 Why not just inline-substitute at compile time

A compile-time macro substitution would resolve `let X = "v"` and rewrite all subsequent `${X}` occurrences to the literal value during IR generation, eliminating the runtime concern entirely. **This is the wrong design** for AXON because:

1. `let X = step_a.output` resolves to a value that doesn't exist at compile time (the step result is runtime-only).
2. Replay tokens canonical-hash the IR — inlining would change the IR shape and break golden replay determinism.
3. Per-step trace events for `let` are useful for adopters debugging "where did X come from" — inlining would hide them.

Runtime macro substitution (the docstring's claim) is the right design; we just need to actually implement it.

---

## 4. Sub-phases

### 17.a — Phase-2 lowering (Python + Rust) `[PLANNED]`

- `axon/backends/base_backend.py`: `_LET_IR_TYPES = (IRLetBinding,)` constant + isinstance arm + `_compile_let_step` static method that produces `CompiledStep` with `metadata["let_binding"] = {target, value, value_kind}`.
- `axon-rs/src/runner.rs`: `LetPayload` struct + `let_payload` field on `CompiledStep`; `build_compiled_steps` populates it from `IRFlowNode::Let` nodes.
- `value_kind` classification helper: returns `"literal"` for str/int/float/bool/list-of-literals, `"reference"` for dotted-identifier strings (matching `^[A-Za-z_]\w*(\.\w+)*$` and not a known string literal). The classifier is shared between Python and Rust (vocab parity test).

**Tests (17.h covers in detail):** `test_phase2_let_lowering` — verifies a 3-step flow with one `let` produces 3 CompiledSteps (today it produces 3, but the let one routes to the model — post-fix it routes to the let dispatcher).

### 17.b — Python runtime dispatcher `[PLANNED]`

- `axon/runtime/executor.py`: dispatch arm `if step.metadata.get("let_binding"): return await self._execute_let_step(...)`.
- `_execute_let_step`: resolves via `ctx.resolve_value_ref` for references (reusing Fase 15's machinery); literals pass through. Binds via `ctx.set_variable(target, resolved)`. Emits `STEP_END` trace with type=let_binding, target, value_kind, truncated value_repr. Returns `ModelResponse`-shaped `StepResult` so downstream validation doesn't special-case.
- `_call_model` is NEVER invoked for let steps. Verified by `test_let_dispatcher_no_model_call` (mirror of the lambda apply equivalent).

### 17.c — Rust runtime dispatcher (stub-correct) `[PLANNED]`

- `axon-rs/src/runner.rs::execute_stub`: when `step.step_type == "let"`, build resolved value from `LetPayload`, write to `ExecContext` under `target`, emit `let_binding` trace event, `continue`.
- The Rust runtime is otherwise stub for everything except Fase 15 lambda apply; this promotion is structurally identical to 15.c.
- `_real_executor` (LLM path) gets the same dispatcher inserted at the corresponding step iteration site.

### 17.d — Type-checker hardening (Python + Rust) `[PLANNED]`

The OSS check at `_check_let` already enforces SSA via `SymbolTable.declare`. Robustness adds:

1. **Shadowing of reserved primitive type names** — `let int = ...`, `let string = ...`, etc. rejected. Reuses `_RESERVED_OUTPUT_TYPE_NAMES` from Fase 15.d (renamed to `_RESERVED_BINDING_NAMES` to widen scope).
2. **Shadowing of flow parameters** — if the enclosing flow declares parameter `data`, `let data = ...` inside the body is rejected. Today this is silently allowed (the let wins), which is confusing.
3. **Self-referential binding** — `let X = X` rejected (would resolve to undefined at runtime; better to catch at compile).
4. **Reference value points to a known symbol** — `let X = ghost_step` where `ghost_step` is undefined. Today this passes the type checker; would surface at runtime via KeyError. Move it earlier.

Rust mirror: same checks added to `axon-frontend/src/type_checker.rs`. Reuse the `RESERVED_OUTPUT_TYPE_NAMES` constant added in Fase 15.d.

### 17.e — Interpolation resolution `[PLANNED]`

`ctx.resolve_value_ref` (Python) and `ExecContext::interpolate` (Rust) already handle bare ident, dotted access, step results, variables, discovered handles. After 17.b lands, `ctx.set_variable(target, resolved)` puts the let-bound value in the same namespace as flow parameters, so `${X}` and `$X` resolve uniformly.

This sub-phase is mostly verification work:
- Audit precedence: discovered handle > flow variable > step result. Verify let-bound vars sit in the "flow variable" tier.
- Document the precedence in the interpolation method docstring (currently undocumented).
- Add tests asserting that let-bound vars beat step results (when names collide — though SSA + 17.d.2 should make collisions impossible, a defense-in-depth test is cheap).

### 17.f — Cross-stack parity golden `[PLANNED]`

Mirror of Fase 15.e parity gate:

- `axon-rs/tests/parity/fase17_let_binding.spec.json` — the input let spec (target + value + value_kind).
- `axon-rs/tests/parity/fase17_let_binding.golden.json` — the expected post-bind context state (`{"X": "value"}`).
- `axon-rs/tests/fase17_let_binding_parity.rs` — Rust gate.
- Python gate in `tests/test_let_runtime.py::TestCrossStackParity` — reads the same files.

Both gates produce a serialized post-bind ContextManager snapshot and assert byte-identical JSON. Cardinality contract: the snapshot is a flat `{name: value}` dict with stable key ordering.

### 17.g — Test matrix `[PLANNED]`

Target: 25+ Python tests + 8 Rust unit tests covering:

| # | Scenario |
|---|---|
| 1 | `let X = "literal"` — string binding |
| 2 | `let X = 42` — int binding |
| 3 | `let X = 3.14` — float binding |
| 4 | `let X = true` — bool binding |
| 5 | `let X = ["a", "b", 3]` — heterogeneous list |
| 6 | `let X = step_a` — step-result reference |
| 7 | `let X = step_a.output` — dotted-path reference |
| 8 | `let X = step_a.output.field` — multi-level dotted |
| 9 | `let X = ghost` (undefined symbol) — type-checker rejects |
| 10 | `let X = "v"` then `let X = "w"` (rebind in same scope) — type-checker rejects (preserved from current SymbolTable.declare) |
| 11 | `let int = ...` (reserved type name) — type-checker rejects |
| 12 | `let X = X` (self-reference) — type-checker rejects |
| 13 | Flow param `X`, then `let X = ...` — type-checker rejects |
| 14 | `${X}` interpolation in next step's user_prompt resolves correctly |
| 15 | `$X` (no braces) interpolation also resolves |
| 16 | `let` inside `if` body — scope check |
| 17 | `let` inside `for` body — scope check (probably also rejected by SSA per loop iteration) |
| 18 | Replay token snapshot includes let-bound vars in canonical context |
| 19 | Trace event fired with type=let_binding + correct fields |
| 20 | Dispatcher does NOT invoke the model client (assert call_count == 0) |
| 21 | Reference resolves at runtime (not compile time) |
| 22 | Reference to undefined runtime var raises AxonRuntimeError with descriptive message |
| 23 | Cross-stack parity (17.f) — Python + Rust agree |
| 24 | Vocab parity — `_RESERVED_BINDING_NAMES` identical Python ↔ Rust |
| 25 | Doc honesty — `_visit_let` docstring asserted to NOT contain the word "macro substitution" without a corresponding implementation reference (regression gate against future drift) |

Rust unit tests cover scenarios 1-8 + 19-23 against `axon-rs/src/runner.rs::execute_stub`.

### 17.h — Documentation honesty + version bump + release `[PLANNED]`

- **Fix the lying docstring**: [axon/compiler/ir_generator.py:996-1000](axon/compiler/ir_generator.py#L996-L1000) `_visit_let` rewritten to describe the actual shipped behavior with cross-references to Fase 17.b/17.c.
- **Fix the IR node docstring**: [axon/compiler/ir_nodes.py:529-543](axon/compiler/ir_nodes.py#L529-L543) `IRLetBinding` updated similarly.
- **README**: no row to qualify (let isn't called out separately in the phase table — it's part of the language baseline). If a dedicated row exists for "Variables / let bindings" it gets the standard `✅ Done` mark.
- **Plan doc**: this file's status flipped to `SHIPPED` with sub-phase `[DONE]` markers.
- **Tracker**: GH issue closed with a summary linking to the release commit.
- **Version bump**: `axon-lang v1.11.0 → v1.12.0` (minor — runtime dispatcher addition is backward-compat). Coordinated cross-stack via bump-my-version (same flow as v1.10.0 / v1.11.0).
- **Release**: GH Release with binaries; PyPI publish; crates.io publish.
- **Enterprise impact**: zero. `let` is OSS-only; no enterprise feature consumes it. The `axon-enterprise` pin floor stays at `>=1.11.0` until enterprise has a reason to pick up v1.12.0.

---

## 5. Out of scope

- **Typed `let` annotations** (`let X: string = "..."`). The IR's `value: str | int | float | bool | list` is dynamic-typed; adding compile-time type annotations is a separate language feature that interacts with the broader epistemic-lattice work in Fases 7+. Future phase if adopters request it.
- **Mutable bindings** — the SSA invariant in `_check_let` is intentional and stays. If adopters need mutability they have flow variables via step outputs; let stays immutable.
- **`let` inside `daemon` reactive bodies** — daemons have their own scope rules that interact with the supervisor; covered by tests (scenarios 16-17) but the actual runtime semantics there might surface a follow-up if adopters report issues.
- **Compile-time constant folding** — see §3.4 above; deliberately deferred / never desired.
- **Enterprise hardening** — no enterprise-side work needed; `let` is a language baseline primitive, not an enterprise feature.

---

## 6. Acceptance criteria (for declaring Fase 17 SHIPPED)

1. Every sub-phase 17.a–17.h marked `[DONE]` ✓ with a release reference.
2. **Python regression gate**: existing test count strictly preserved + 25 new tests for the matrix in 17.g.
3. **Rust regression gate**: existing test count strictly preserved (1043 → 1043+) + 8 new unit tests in `axon-rs/src/runner.rs::tests` or a new `let_runtime` module.
4. **Cross-stack parity golden** present in `axon-rs/tests/parity/fase17_let_binding.*.json` and matched byte-for-byte by the Python + Rust gates.
5. **No regression** in v1.11.0 baselines: Python 4240 → ≥4265; Rust 1043 → ≥1051.
6. **Docstring honesty** verified by 25.25 (the doc-honesty regression test) — the test file's content does not contain the phrase "runtime macro substitution" without a paired implementation reference.
7. **Cross-vocab parity**: `_RESERVED_BINDING_NAMES` identical Python ↔ Rust (asserted by `test_reserved_binding_names_parity`).
8. **Tagged + released** as `axon-lang v1.12.0` on PyPI + crates.io; GH Release with 5 platform binaries; coordinated bump commit + tags pushed.
9. **Trace observability**: every let dispatch emits exactly one `STEP_END` trace event with `type=let_binding`, `target`, `value_kind`, `value_repr` (truncated). No model call. Verified by counter assertions in tests.
10. **Plan doc + memory updated**: status flipped from PLANNED to SHIPPED; tracker issue closed.

---

## 7. Pattern recognition — three of three

This is the third instance of the same gap pattern in the AXON runtime:

| Primitive | Pre-fix state | Closed by |
|---|---|---|
| `lambda apply X to Y` | front-end ✅ / runtime ❌ / docstring lied | Fase 15 (axon-lang v1.10.0) |
| Daemon `on_stuck` policies | front-end ✅ / runtime ❌ / docstring lied | Fase 16 (axon-enterprise v1.6.0) |
| `let X = value` | front-end ✅ / runtime ❌ / docstring lies | **Fase 17 (this plan)** |

The fix shape is identical each time: Phase-2 lowering, dispatcher, type-checker hardening, parity, tests, docstring honesty, version bump. After Fase 17 ships, **the next sweep should be a comprehensive audit of all `IR*` node types** in `axon/compiler/ir_nodes.py` against `axon/runtime/executor.py` to catch any other compiler-only-runtime-stub mismatches before adopters discover them. That meta-audit is itself a candidate for Fase 18.
