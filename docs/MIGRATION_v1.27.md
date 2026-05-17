# AXON Migration Guide — v1.26.0 → v1.27.0

> **Scope:** the Fase 33.z *Dispatcher production wiring* cycle —
> the lift of the 33.y per-IRFlowNode async dispatcher from the
> test surface into the production SSE producer
> (`server_execute_streaming`). v1.27.0 ratifies the dispatcher as
> the **single, unconditional production hot path** for every
> adopter shape and retires the legacy synchronous fallback +
> v1.25.0 canonical async path in lockstep.
>
> **TL;DR:** v1.27.0 is **adopter-visible on the wire** for shapes
> that fell back to the synchronous `axon-W002` path in v1.26.0 —
> `Conditional` / `ForIn` / `Par` / `ShieldApply` / `Hibernate` /
> `Remember` / `Recall` / `LambdaDataApply` / `Emit` / `Publish` /
> `Discover` / `Persist` / `Retrieve` / `Mutate` / `Purge` /
> `Transact` / `Navigate` / `Drill` / `Trail` / `Corroborate` /
> `OtsApply` / `MandateApply` / `ComputeApply` / `Listen` /
> `Daemon` / `Focus` / `Associate` / `Aggregate` / `Explore` /
> `Ingest` / `Deliberate` / `Consensus` / `Forge` and the rest of
> the 45-variant catalog. **Canonical** `step S { ask: "..." }`
> stays **byte-identical** with v1.25.0/v1.26.0 (D4 anchor
> preserved end-to-end). The legacy `axon-W002 unsupported_flow_shape`
> warning is **structurally unreachable** — no shape is
> unsupported anymore. **There is no opt-out feature flag**: the
> dispatcher is the total production path. Adopters who depended on
> internal symbols `PlanError::LegacyOrchestrationRequired` /
> `set_streaming_via_dispatcher` / `streaming_via_dispatcher_enabled`
> / `StreamingViaDispatcherGuard` / `flow_plan::unsupported_feature_reason`
> / `axon_server::run_streaming_async_path` /
> `axon_server::run_streaming_legacy_path` /
> `construct_enforcer_for_policy` / `FallbackMode::UnsupportedFlowShape`
> hit explicit compile errors at upgrade — this is **intentional**
> and part of the 33.y.l → 33.z.e deprecation cycle.

---

## What changed in v1.27.0

| Surface | v1.26.0 | v1.27.0 |
|---|---|---|
| SSE wire body for stub backend + canonical `step S { ask: "..." }` | 1 axon.token "(stub)" + 1 axon.complete | **Byte-identical** (D4 wire byte-compat preserved end-to-end through the dispatcher graft) |
| SSE wire body for canonical Step on real backends | Per upstream provider chunk via `Backend::stream()` (33.x.b) | **Byte-identical** (33.x.b production path absorbed into the dispatcher's `pure_shape` handler unchanged) |
| SSE wire body for non-canonical shapes (orchestration / PIX / algebraic / wire-integration / multi-agent / lambda) | LEGACY synchronous fallback — flow materialized end-to-end then projected synthetic 3-word `axon.token` events as a post-hoc burst; `axon-W002 streaming-not-supported` warning fired on `axon.complete.warnings[*]` | **Per-chunk live streaming** via `flow_dispatcher::dispatch_node` — every IRFlowNode variant's handler emits `StepStart` → per-token `StepToken` → `StepComplete` on the SSE wire in arrival order. **No `axon-W002`** for shape mismatches — the variant `FallbackMode::UnsupportedFlowShape` was DELETED |
| `FlowExecutionEvent::ToolCall` SSE wire surface | Silent consume in the production consumer (33.y.l silent arm: `FlowExecutionEvent::ToolCall { .. } => {}`) | **Live wire emission** — closed-catalog 5-field SSE event `axon.tool_call` with `{ step, trace_id, tool_name, content, timestamp_ms }`. Event ID counter continues monotonically with the rest of the SSE stream |
| `FallbackMode` closed catalog | 4 variants: `UnknownBackend` / `SourceCompilationFailed` / `BackendLacksStream` / `UnsupportedFlowShape` | **3 variants**: `UnknownBackend` / `SourceCompilationFailed` / `BackendLacksStream`; `UnsupportedFlowShape` DELETED |
| `axon-W002` warning catalog | Fires on 4 fallback modes (unknown backend / source compile / backend lacks stream / unsupported flow shape) | Fires on 3 fallback modes (unknown backend / source compile / backend lacks stream); **`unsupported_flow_shape` slug structurally unreachable** |
| `PlanError::LegacyOrchestrationRequired` | `#[deprecated(since = "1.26.0")]` with retirement note | **DELETED** — compile error at any non-comment reference |
| `flow_plan::unsupported_feature_reason` | `#[deprecated(since = "1.26.0")]` | **DELETED** |
| `axon_server::run_streaming_legacy_path` | `#[deprecated(since = "1.26.0")]` | **DELETED** |
| `axon_server::run_streaming_async_path` | Internal v1.25.0 canonical async path (still active) | **DELETED** — dispatcher's `pure_shape` handler absorbs the canonical Step path uniformly |
| `construct_enforcer_for_policy` helper | Internal helper (sole caller `run_streaming_async_path`) | **DELETED** — dispatcher's `pure_shape` handler builds enforcers inline |
| `runtime_flags::streaming_via_dispatcher_enabled` getter | Returned the `AXON_STREAMING_VIA_DISPATCHER` flag state | **DELETED** — flag does not exist; dispatcher is unconditional |
| `runtime_flags::set_streaming_via_dispatcher` setter | Adopter-callable toggle for the dispatcher path | **DELETED** |
| `runtime_flags::StreamingViaDispatcherGuard` RAII helper | Test-side scoped flag manipulation | **DELETED** |
| Per-step audit `StepAuditRecord.branch_path` field | Available since 33.x.f for canonical-Step SSE flows | **Populated by every dispatched node** — orchestration handlers thread the branch path through `DispatchCtx` so adopter `GET /v1/replay/<trace_id>` returns the full execution branch path for ForIn/Conditional/Par-nested shapes |
| `axon.complete.enforcement_summary` + `axon.complete.step_audit` + `axon.complete.runtime_warnings` side-channels | Populated by `run_streaming_async_path` for canonical Step + by `run_streaming_legacy_path` for non-canonical shapes | **Populated uniformly by the dispatcher's per-variant handlers** through `DispatchCtx::with_external_side_channels` (33.z.c side-channel threading) — adopter wire fields preserved byte-equal for canonical Step + newly-populated for orchestration shapes |
| 33.z dedicated CI workflow | (none) | **New** — `.github/workflows/fase_33z_dispatcher_production.yml` (33.z.h; 6 lanes + summary aggregator) running on every push/PR |
| 33.z parity gate | (none) | **New** — `axon-rs/tests/fase33z_e_parity_gate.rs` greps `axon-rs/src/**/*.rs` for any non-comment reference to the 9 retired symbols + pins `FallbackMode` catalog size to 3 |
| 33.z production-grade fuzz | (33.y.n covered the test-surface dispatcher) | **New** — `axon-rs/tests/fase33z_production_fuzz.rs` ships ~5 100 deterministic LCG iters end-to-end through `run_streaming_via_dispatcher` (12 template clusters × 375 + 100 cancel-depth + 250 tool-call zero-emission + 50 fixtures × 5 determinism stress) |

Every NEW behavior (per-chunk streaming for non-canonical shapes,
`axon.tool_call` SSE emission, branch_path on every nested step
audit, unified side-channel population) is **observable at the wire
layer** for adopters whose flows exercise those shapes. **No source
change is required** — your existing `.axon` files keep compiling
unchanged and your existing SSE consumer keeps working.

---

## The architectural arc — why this release matters

Pre-v1.27.0, the production SSE producer (`server_execute_streaming`)
forked at runtime between **two** hot paths:

1. `run_streaming_async_path` — for canonical `step S { ask: "..." output: Stream<Token> }`
   flows on backends that ship `Backend::stream()` (the 33.x.b
   v1.25.0 graduation).
2. `run_streaming_legacy_path` — for every other shape (orchestration /
   PIX / algebraic / wire-integration / multi-agent / lambda); it
   materialized the full flow output synchronously then projected
   synthetic 3-word `axon.token` events as a post-hoc burst and
   fired an `axon-W002 streaming-not-supported` warning.

This fork was **architectural debt** from the v1.21.0 SSE landing:
canonical Step shipped per-chunk because that was the easy case;
every other shape stayed on the legacy fallback because the runtime
walker didn't know how to dispatch them async. Adopters whose flows
used orchestration (which is the norm for any non-trivial regulated-
vertical pattern — banking AML scoring uses ForIn + Par; healthcare
CDS uses ShieldApply + Conditional; legal privilege scanner uses
ForIn + ShieldApply; government decision support uses Hibernate +
Trail) saw burst-style wire output that defeated the entire purpose
of having SSE in the first place.

The Fase 33.y cycle (v1.26.0) **structurally closed the gap on the
dispatcher side** — every one of the 45 IRFlowNode variants gained
a NAMED async handler with compiler-enforced exhaustive matching,
plus the closed-catalog `FlowExecutionEvent::ToolCall` event variant,
plus per-step `StepAuditRecord` discipline.

**Fase 33.z (v1.27.0) lifts that structurally-complete dispatcher
into the production SSE producer.** A single unconditional invocation
of `run_streaming_via_dispatcher` inside `server_execute_streaming`
replaces both legacy hot paths. Adopters whose flows used non-canonical
shapes immediately observe per-chunk live wire output for the FULL
flow body — not just canonical leaves. The `axon-W002 unsupported_flow_shape`
warning is structurally unreachable: the variant was deleted from
`FallbackMode`; no source can fire it because no code path exists to
fire it.

This is the v1.21.0 SSE promise honored end-to-end. Per the founder
principle "*SSE es una primitiva cognitiva*", real-time streaming is
now the universal wire shape for every shape adopters actually deploy.

---

## Scenario A — You upgraded the server; nothing else changed

**Symptom:** Your SSE consumer suddenly receives a richer event
stream from flows that previously emitted a 3-event burst.

**What you observe:**

| Adopter shape | v1.26.0 wire body | v1.27.0 wire body |
|---|---|---|
| Canonical `step S { ask: "hi" output: Stream<Token> }` + stub backend | 1 axon.token "(stub)" + 1 axon.complete (no warnings) | **Identical** (D4 anchor) |
| Canonical Step + real backend (Anthropic / OpenAI / Gemini / Kimi / GLM / Ollama / OpenRouter) | Per-upstream-chunk delivery via `Backend::stream()` | **Identical** (the 33.x.b production path is absorbed into the dispatcher's `pure_shape` handler unchanged) |
| `for tx in transactions { step Screen { ... } }` over a 5-element collection | 1 axon.token (synthetic 3-word burst) + 1 axon.complete + `axon-W002 unsupported_flow_shape` warning | **5× (StepStart + per-token StepToken + StepComplete) + 1 axon.complete + NO warnings** — every iteration emits its full step lifecycle on the wire in arrival order |
| `par { step A {...} step B {...} step C {...} }` | 1 synthetic burst token + W002 | **3× full step lifecycles + 1 axon.complete + NO warnings** — concurrent branches dispatch concurrently; arrival ordering is dispatcher-deterministic |
| `if x == "premium" { step Approve {...} }` | 1 synthetic burst token + W002 | **1 full step lifecycle (when branch fires) + 1 axon.complete + NO warnings** |
| `shield Hipaa on response -> ...` wrapping a Step | 1 synthetic burst token + W002 | **Per-token chunk delivery + enforcement_summary populated + NO warnings** |
| `hibernate event 30s` followed by a Step | 1 synthetic burst + W002 | **Step lifecycle after event resolution + NO warnings** |
| `remember beneficial_owner in cdd_case` followed by Step + `recall beneficial_owner from cdd_case` | 1 synthetic burst + W002 | **Memory ops dispatched as their own audit-recorded nodes + Step's full lifecycle + NO warnings** |
| Flow with `axonendpoint ... transport: sse replay: true` | Replay row's `step_audit` populated for canonical Step only; non-canonical shapes had empty `step_audit` | **`step_audit` populated for every dispatched IRFlowNode in the flow body** — including branch_path entries for ForIn/Conditional/Par-nested children |

**Recipe:**

```bash
# 1. Bump the dep pin to 1.27.0.
cargo build --release       # or pip install -U axon-lang
systemctl restart axon-server
```

That's it. No `.axon` source change, no client-side code change, no
auth surface change. Your existing SSE consumers will receive a
richer event stream for non-canonical shapes — if they were
EventSource-based and treated the synthetic burst as "1 message",
the new per-chunk stream arrives across multiple `onmessage`
invocations as the dispatcher walks each node.

**Verification:**

```bash
# Run the 33.z.e parity gate to confirm legacy retirement landed:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_e_parity_gate
# Expected: 10 passed; 0 failed (9 retired symbols absent +
# FallbackMode pinned to 3 variants).

# Run the 33.z.g production fuzz to confirm hot-path totality:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_production_fuzz
# Expected: 16 passed; 0 failed (~5 100 LCG iters across 12 source-
# template clusters + cancel-depth + tool-call zero-emission + parity
# determinism stress).
```

---

## Scenario B — You want to consume the new `axon.tool_call` SSE event family

**Symptom:** Your flow uses `step S { ask: "..." apply: <tool> output: Stream<Token> }`
with a real backend that signals `FinishReason::ToolUse`, and you
want your client to react to tool-call requests as they arrive.

**What v1.27.0 ships:** the production SSE consumer now emits a
new wire event family `event: axon.tool_call` whenever the
dispatcher's `pure_shape` handler observes a `FlowExecutionEvent::ToolCall`
from upstream. The payload is a closed-catalog 5-field JSON:

```
event: axon.tool_call
id: 7
data: {"step":"Generate","trace_id":"550e8400-e29b-41d4-a716-446655440000","tool_name":"apply_search","content":"{\"query\":\"axon language\"}","timestamp_ms":1715648400123}

```

Field shape:

| Field | Type | Semantics |
|---|---|---|
| `step` | `string` | Name of the dispatched Step that produced the tool call |
| `trace_id` | `string` | UUID v4 reserved at SSE producer start (33.x.c contract); same ID is exposed via `X-Axon-Trace-Id` HTTP response header on dynamic-route endpoints (Fase 32.h) |
| `tool_name` | `string` | The tool slug from `step.apply_ref` (matched against `axon-frontend`'s tool registry) |
| `content` | `string` | Tool-call delta (provider-specific shape — Anthropic ships the JSON-serialized tool-input dict; OpenAI ships the arguments string) |
| `timestamp_ms` | `u64` | Unix milliseconds when the dispatcher observed the upstream `ChatChunk.finish_reason = ToolUse` |

**Wire ordering invariant:** `axon.tool_call` events arrive
BEFORE the trailing `axon.token` events for the same step — the
dispatcher emits the tool-call request as upstream signals it,
then continues draining any text content the provider produced
before/after the tool-use finish reason. Event IDs are monotonic
across the entire SSE stream (no separate counter per event type).

**Recipe (JavaScript EventSource client):**

```javascript
const es = new EventSource('/sse/my-tool-using-flow');

es.addEventListener('axon.token', (msg) => {
  const evt = JSON.parse(msg.data);
  console.log(`[token] step=${evt.step}: ${evt.token}`);
});

es.addEventListener('axon.tool_call', (msg) => {
  const evt = JSON.parse(msg.data);
  console.log(`[tool-call] step=${evt.step} tool=${evt.tool_name}`);
  console.log(`            content=${evt.content}`);
  console.log(`            arrival_ms=${evt.timestamp_ms}`);
  console.log(`            trace_id=${evt.trace_id}`);
  // Dispatch your own tool-execution shim here. The next axon.token
  // events for this step will follow after the provider finishes
  // its tool-call response stream.
});

es.addEventListener('axon.complete', (msg) => {
  console.log('[complete]', JSON.parse(msg.data));
  es.close();
});
```

**Recipe (Python `httpx` client):**

```python
import httpx, json

async with httpx.AsyncClient(timeout=None) as client:
    async with client.stream("POST", "https://axon.example.com/sse/my-flow",
                              json={"input": "Search for X"}) as resp:
        cur_event = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                cur_event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if cur_event == "axon.tool_call":
                    print(f"[tool-call] {data['tool_name']}: {data['content']}")
                elif cur_event == "axon.token":
                    print(f"[token] {data['token']}", end="", flush=True)
```

**Stub-backend behavior:** stub never signals `FinishReason::ToolUse`
(it always returns `FinishReason::Stop`); `axon.tool_call` events
will never fire on stub-backed flows. Production fuzz pins this:
`fase33z_production_fuzz.rs:§3` runs 250 iters confirming `tool_call_count == 0`
across every stub invocation.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_c_default_on_and_tool_call
# Expected: 16 passed (closed-catalog payload + slug + wire-emission
# unit tests + 4 vertical canonical patterns).
```

---

## Scenario C — You depend on `StepAuditRecord.branch_path` for regulated-vertical replay

**Symptom:** Your flow uses orchestration shapes (`ForIn` / `Conditional` /
`Par`) and you read the audit trail via `GET /v1/replay/<trace_id>`
for compliance (HIPAA / 21 CFR Part 11 / FRE 502 / PCI DSS Req 10).
In v1.26.0 the `step_audit` array was populated only for canonical
Step entries; orchestration shapes produced empty `step_audit`
arrays. In v1.27.0 every dispatched node populates `step_audit`
with a per-node entry including `branch_path`.

**What v1.27.0 ships:** the dispatcher's `DispatchCtx.branch_path`
threads through every orchestration handler. When `dispatch_node`
walks a `ForIn` body, the per-iteration audit entry's `branch_path`
includes the loop variable + iteration index (e.g.,
`["ForIn:tx=tx_42[2]", "Step:Screen"]`). For `Conditional`, the
selected branch is recorded (e.g., `["Conditional:tier==premium[true]", "Step:PremiumReview"]`).
For `Par`, each concurrent branch records its sibling index (e.g.,
`["Par[0]", "Step:Kyc"]` / `["Par[1]", "Step:Sanctions"]`).

**`StepAuditRecord` shape on the audit row:**

```json
{
  "step_audit": [
    {
      "step_name": "Screen",
      "branch_path": ["ForIn:tx=tx_1[0]", "Step:Screen"],
      "tokens_input": 23,
      "tokens_output": 5,
      "latency_ms": 18,
      "enforcement_summary": null,
      "warnings": []
    },
    {
      "step_name": "Screen",
      "branch_path": ["ForIn:tx=tx_2[1]", "Step:Screen"],
      "tokens_input": 23,
      "tokens_output": 5,
      "latency_ms": 17,
      "enforcement_summary": null,
      "warnings": []
    }
  ]
}
```

**Recipe (audit consumer):**

```python
import httpx

response = httpx.get(f"https://axon.example.com/v1/replay/{trace_id}",
                     headers={"authorization": f"Bearer {token}"})
audit = response.json()

# Group entries by branch_path prefix for per-iteration analytics.
from collections import defaultdict
per_iteration = defaultdict(list)
for entry in audit["step_audit"]:
    bp = entry["branch_path"]
    # First element identifies the orchestration scope
    if bp and bp[0].startswith("ForIn:"):
        loop_iter = bp[0]
        per_iteration[loop_iter].append(entry)

for loop_iter, entries in per_iteration.items():
    print(f"{loop_iter}: {len(entries)} step(s) executed, "
          f"{sum(e['tokens_output'] for e in entries)} tokens emitted")
```

**Why this matters for regulated verticals:**

- **HIPAA + 21 CFR Part 11 §11.10(e)** — every adjudication branch
  recorded for "secure, computer-generated, time-stamped audit
  trails". Pre-v1.27.0 only canonical-Step entries had per-step
  audit; orchestration-heavy CDS flows (ShieldApply + Conditional +
  Step) had partial audit. v1.27.0 closes the gap.
- **PCI DSS Req 10.2** — "implement automated audit trails for all
  system components". Banking AML flows using ForIn over transactions
  + Par over checks now produce per-iteration + per-branch audit
  entries.
- **FRE 502 + waiver-doctrine** — legal privilege scanner flows
  using `for doc in corpus { shield Privilege on review -> ...
  step Adjudicate {...} }` produce per-document branch_path so an
  external review can reconstruct which documents were flagged at
  which point in the analysis.
- **FedRAMP AU-2** — government benefits-eligibility flows using
  `if applicant_tier == "veteran" { ... } else { ... }` record the
  selected branch on every audit entry for FOIA + appeal review.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_d_parity_corpus
# Expected: 2 passed (50-fixture corpus × strict/multiset/count_only
# sync↔async parity gate; orchestration shapes confirm branch_path
# threading across both paths).
```

---

## Scenario D — Your downstream crate referenced `PlanError::LegacyOrchestrationRequired`

**Symptom:** You ship a downstream crate, enterprise integration,
or alternative wire format that consumed the v1.26.0 deprecated
internal routing primitives. At `cargo build` against axon-lang
1.27.0 you see compile errors like:

```
error[E0599]: no variant or associated item named `LegacyOrchestrationRequired` found for enum `PlanError`
  --> downstream/src/router.rs:42:21
   |
42 |     match plan_error {
   |                     ^
43 |         PlanError::LegacyOrchestrationRequired { .. } => …
   |         ----------^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

**What v1.27.0 ships:** the variant + its sibling helpers
(`flow_plan::unsupported_feature_reason`, `axon_server::run_streaming_legacy_path`,
`axon_server::run_streaming_async_path`, `construct_enforcer_for_policy`)
were **deleted** from the `axon-rs` source tree in 33.z.e. The
33.z.e grep parity gate (`fase33z_e_parity_gate.rs`) enforces no
non-comment reference can exist anywhere in `axon-rs/src/**/*.rs`
— a re-introduction in a future release would fail CI immediately.

**Recipe (downstream crate migration):**

Replace any match arm or call site that referenced these symbols
with the dispatcher-based API. For an enterprise integration that
previously detected "this shape needs orchestration" via
`PlanError::LegacyOrchestrationRequired`:

```rust
// PRE-v1.27.0:
match axon::flow_plan::build_streaming_plan(&source, &source_file) {
    Ok(plan) => dispatch_canonical_step(plan),
    Err(axon::flow_plan::PlanError::LegacyOrchestrationRequired { .. }) => {
        // Fall back to a custom synchronous executor
        run_my_sync_path(&source)
    }
    Err(other) => log::error!("plan failed: {other}"),
}

// POST-v1.27.0 — there is no fallback path; the dispatcher is total.
let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
let cancel = axon::cancel_token::CancellationFlag::new();
let enforcement = std::sync::Arc::new(tokio::sync::Mutex::new(Default::default()));
let audit = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
let warnings = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));

axon::streaming_via_dispatcher::run_streaming_via_dispatcher(
    source.to_string(),
    source_file.to_string(),
    flow_name.to_string(),
    backend.to_string(),
    cancel,
    tx,
    enforcement,
    audit,
    warnings,
).await;

while let Some(event) = rx.recv().await {
    // Every shape dispatches through the same producer — no
    // canonical-vs-orchestration distinction at this layer.
    handle_event(event);
}
```

The dispatcher's per-variant handlers cover **every IRFlowNode
variant** (45/45) — there is no "shape that requires orchestration
fallback" anymore. Adopters who maintained a parallel sync executor
can delete it; the dispatcher path is the production-ready unified
hot path.

**Why these symbols were deleted (not just marked `#[deprecated]`):**

Per the 33.y.l → 33.z.e deprecation cycle, the `#[deprecated(since = "1.26.0")]`
markers in v1.26.0 signaled "use the dispatcher". v1.27.0 ratifies
the dispatcher as the unconditional production path; keeping the
deprecated symbols around as `#[allow(deprecated)]` shims would
defeat the entire purpose of the cycle (which is to eliminate the
dual-path architectural debt). The 33.z.e grep parity gate
(`fase33z_e_parity_gate.rs`) is the structural enforcement: any
re-introduction in a future axon-rs PR fails CI.

---

## Scenario E — You used the v1.26.0-only feature flag

**Symptom:** You called `set_streaming_via_dispatcher(false)` /
`streaming_via_dispatcher_enabled()` / used `StreamingViaDispatcherGuard`
during the v1.26.0 → v1.27.0 alpha cycle for deployment hardening.
At `cargo build` against 1.27.0 you see:

```
error[E0432]: unresolved import `axon::runtime_flags::set_streaming_via_dispatcher`
error[E0432]: unresolved import `axon::runtime_flags::streaming_via_dispatcher_enabled`
error[E0432]: unresolved import `axon::runtime_flags::StreamingViaDispatcherGuard`
```

**What v1.27.0 ships:** the flag was DELETED. There is no opt-out
from the dispatcher path; the dispatcher is the total production
hot path for every adopter shape.

**Why no opt-out:** the 33.y cycle's structural totality (45/45
IRFlowNode variants with compiler-enforced exhaustive matching) +
the 33.z.b/c graft + the 33.z.d 50-fixture parity corpus + the
33.z.g ~5 100-iter production fuzz collectively close the rollback
scenario. Every shape that worked in v1.26.0's legacy path now
works in v1.27.0's dispatcher path with semantic equivalence
(D7 sync↔async parity ratified across the corpus). There is no
shape that needs to fall back to a non-existent legacy path.

**Recipe:**

```rust
// PRE-v1.27.0 — adopter test setup or deployment-hardening guard:
let _guard = axon::runtime_flags::StreamingViaDispatcherGuard::set(false);
serve_sse_endpoint().await;

// POST-v1.27.0 — delete the guard. The dispatcher is the only path.
serve_sse_endpoint().await;
```

For **test isolation** (the most common reason adopters used the
guard), the dispatcher's deterministic execution against the stub
backend is sufficient — there is no per-test flag state to reset
because there is no flag. The 33.z.d 50-fixture parity corpus + 33.z.g
production fuzz collectively confirm zero non-determinism in
dispatcher invocations.

For **deployment hardening** (adopters who wanted a feature-flag
based rollback during the v1.26.0-alpha → v1.27.0 lift), the
roll-forward path is: keep the previous axon-lang version pinned
(`>=1.26.0,<1.27.0`) until you've validated the per-chunk wire
behavior in your environment. Once validated, bump to `>=1.27.0`
and ship. There is no in-process flag-based switch in v1.27.0+.

**If you need to detect "is the dispatcher path active":**

It always is. The 33.z.e parity gate enforces that
`server_execute_streaming` has exactly one streaming code path
(the dispatcher invocation). A downstream crate that wants to
assert this at build time can use a `cargo test --test fase33z_e_parity_gate`
invocation as a pre-deploy check:

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_e_parity_gate \
  --no-fail-fast
# Expected: 10 passed; 0 failed (9 retired symbols absent +
# FallbackMode catalog size pinned to 3).
```

If any of the 10 sub-tests fail, the dispatcher path is NOT total —
which would indicate axon-lang regressed (file a bug against
`Bemarking/axon-lang` immediately).

---

## Verification checklist

Run the full 33.z lane suite locally before deploying v1.27.0:

```bash
cd axon-rs

# 1. Diagnostic anchor — forensic baseline pin
cargo test --test fase33z_dispatcher_production_diagnostic
#   Expected: 10 passed

# 2. Default-on dispatcher + tool_call SSE
cargo test --test fase33z_c_default_on_and_tool_call
#   Expected: 16 passed

# 3. 50-fixture parity corpus (sync↔async drift gate)
cargo test --test fase33z_d_parity_corpus
#   Expected: 2 passed (50 fixtures across 5 verticals)

# 4. Legacy retirement grep gate
cargo test --test fase33z_e_parity_gate
#   Expected: 10 passed

# 5. Production-grade fuzz (~5 100 LCG iters / 16 tests)
cargo test --test fase33z_production_fuzz
#   Expected: 16 passed (~0.3s)

# 6. Cross-stack Python ↔ Rust parity (from repo root)
cd .. && python -m pytest tests/test_fase33z_f_cross_stack_dispatcher_parity.py
#   Expected: 10 passed
```

CI surface: `.github/workflows/fase_33z_dispatcher_production.yml`
runs the 6 lanes above on every push/PR; the `summary` aggregator
is the single-source-of-truth status check.

---

## See also

- [fase/fase_33z_dispatcher_production_wiring.md](fase_33z_dispatcher_production_wiring.md)
  — the plan vivo with D1-D11 spec + sub-fase sequencing.
- [docs/ADOPTER_STREAMING.md](ADOPTER_STREAMING.md) §"Total production
  streaming (Fase 33.z, v1.27.0+)" — adopter-observable D-letter
  mapping for the production wire surface.
- [docs/MIGRATION_v1.26.md](MIGRATION_v1.26.md) — the v1.25.0 → v1.26.0
  structural-foundation guide (Fase 33.y per-IRFlowNode dispatcher).
- [docs/MIGRATION_v1.25.md](MIGRATION_v1.25.md) — the v1.24.0 → v1.25.0
  production async path guide (Fase 33.x activation cycle).
