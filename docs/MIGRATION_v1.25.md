# AXON Migration Guide — v1.24.0 → v1.25.0

> **Scope:** the Fase 33.x *Runtime activation of algebraic
> streaming* cycle introduced in v1.25.0. Adopters upgrading from
> v1.24.0 (Fase 33 SSE-as-cognitive-primitive primitives) read
> this doc to decide which migration scenario applies + execute
> the recipe.
>
> **TL;DR:** v1.25.0 is **strictly additive** (D4 wire byte-compat
> ratified across the 33.x cycle). If you don't change anything,
> nothing changes — your v1.24.0 SSE wire bodies are preserved
> byte-identically for stub-backed flows + the canonical
> `Stream<T>` shape. What v1.25.0 activates: real per-chunk
> `Backend::stream()` driven by the production SSE handler (33.x.b
> bridge); `StreamPolicyEnforcer` running in production on
> declared `<stream:<policy>>` effects (33.x.d); cancel-inside-
> reqwest-body with **p95 ≤ 100ms wall-clock** (33.x.e, measured
> 12.6µs against local-loopback); per-step audit trail in
> `/v1/replay/<trace_id>` for SSE routes with `replay: true`
> (33.x.f); closed-catalog `axon-W002 streaming-not-supported`
> warning on `axon.complete.warnings[*]` (33.x.g); opt-in BPE-
> tokenized fallback chunking via runtime flag (33.x.h); mono-file
> `crate::backend` retirement Phase 1 with `#[deprecated]` markers
> + consolidated single source of truth (33.x.i); real-provider
> E2E gated lane against Anthropic / OpenAI / Gemini + 4 vertical
> canonical patterns (33.x.j); D12 fuzz across 11 surfaces with
> ~2050 deterministic LCG iters (33.x.k); dedicated 10-job CI
> workflow pinning the cycle's contract (33.x.k).

---

## What changed in v1.25.0

| Surface | v1.24.0 | v1.25.0 |
|---|---|---|
| SSE wire body for stub backend + canonical `Stream<T>` | 1 axon.token "(stub)" + 1 axon.complete | **Byte-identical** (D4) |
| SSE wire body for real backends (Anthropic / OpenAI / Gemini) | `crate::backend::call_multi` (sync, blocking) → final String → `split_whitespace().chunks(3)` synthetic groups | **Per upstream provider chunk** via `Backend::stream()` (33.x.b bridge); real wall-clock incrementality |
| `StreamPolicyEnforcer` for declared `<stream:<policy>>` | Wire field populated (Fase 33.e); enforcer NEVER runs in production | **Runs in production** on the per-step `Stream<ChatChunk>`; `enforcement_summary` counters published on `axon.complete` (33.x.d) |
| Client-disconnect cancel propagation | Between event emissions only (Fase 33.f baseline) | **Inside reqwest body** (33.x.e); **p95 cancel→None ≤ 100ms** invariant (measured 12.6µs against local mock) |
| `/v1/replay/<uuid>` for SSE routes with `replay: true` | Returns 404 (Fase 32.h SSE bypasses replay) | **Returns entry with `step_audit: Vec<StepAuditRecord>`** (33.x.f D6 per-step audit) |
| `axon.complete.warnings` field | Does not exist | New optional array; carries `axon-W002 streaming-not-supported` when LEGACY path fires (33.x.g D5) |
| Chunking for legacy-path fallback | Whitespace 3-word groups, always | Same default; opt-in to BPE per-token via `axon::runtime_flags::set_tokenizer_fallback(true)` (33.x.h D9) |
| `crate::backend::SUPPORTED_BACKENDS` + `get_api_key` | Mono-file local consts | **Re-export shims** of `crate::backends::CANONICAL_PROVIDERS` + `crate::backends::get_api_key` (single source of truth, 33.x.i D7 Phase 1) |
| `crate::backend::call/call_multi/call_stream/call_multi_stream` | Synchronous LLM-call surface | `#[deprecated(since="1.25.0")]` — use `crate::backends::Registry::get(name)?.complete()/.stream()`; 4 caller files carry `#![allow(deprecated)]` while Fase 33.x.i.2 closes the async migration |
| Real-provider E2E CI lane | Manual / not gated | **Gated workflow** `fase_33x_real_provider.yml` activated by `AXON_RUN_REAL_PROVIDER_TEST=1` (33.x.j D10) |
| D12 robustness fuzz for 33.x surfaces | (cycle didn't ship until now) | 15 tests, **~2050 deterministic LCG iters** across 11 surfaces, runs in 0.35s (33.x.k) |
| Dedicated CI workflow for the 33.x cycle | (none) | `.github/workflows/fase_33x_runtime_activation.yml` 10 parallel jobs, ~3-5 min wall-clock (33.x.k) |

Every NEW wire field (`enforcement_summary`, `warnings`,
`step_audit` on the replay payload) is **OPTIONAL** + **elided
when empty**. Existing JSON parsers ignoring unknown fields see
no observable wire change for adopters that don't declare
`<stream:<policy>>` effects or `replay: true`.

---

## Scenario A — You upgraded the server; nothing else changed

**Symptom:** None. Your existing client code keeps working.

**What you observe:**

| Adopter shape | v1.25.0 behavior |
|---|---|
| Adopter source uses canonical `step S { ask: "hi" output: Stream<Token> }` + stub backend (no real LLM key) | Wire body is byte-identical with v1.24.0 (1 axon.token "(stub)" + 1 axon.complete) |
| Adopter source uses canonical shape + a real LLM key (Anthropic / OpenAI / Gemini) | Wire body emits **one `axon.token` event per upstream provider chunk** (real wall-clock incrementality); v1.24.0 emitted synthetic 3-word groups after a burst at end-of-flow |
| Adopter source declares `effects: <stream:<policy>>` on its tool | `axon.complete.stream_policies` unchanged (carry-over from Fase 33.e); v1.25.0 ADDS `axon.complete.enforcement_summary` with the production counters |
| Adopter source uses anchors / lambda / let / use_tool / hibernate / pix / un-modeled IRFlowNode | Wire body is byte-identical with v1.24.0 (LEGACY path activates) + `axon.complete.warnings[*]` adds a single `axon-W002 streaming-not-supported` entry with `fallback_mode: "unsupported_flow_shape"` |
| Adopter source uses `axonendpoint ... transport: sse replay: true` | `GET /v1/replay/<uuid>` previously returned 404 for SSE; v1.25.0 returns the entry with the new `step_audit` array populated |

**Recipe:**

```bash
# 1. Bump the dep pin to 1.25.0 in your project's Cargo.toml / pyproject.toml.
# 2. Build + restart.
cargo build --release            # or pip install -U axon-lang
systemctl restart axon-server    # or your equivalent
```

That's it. No source change, no client code change, no auth
surface change. Verified by the cycle's regression sweep: 1614
axon-rs lib + 49 integration suites + 23 Python Fase 24.j parity
tests, ALL green.

---

## Scenario B — You want to index per-step replay rows for compliance audit

**Symptom:** You ship a regulated-vertical adopter (Banking PCI
DSS Req 10, Government FedRAMP AU-2, Legal FRE 502, Medicine
21 CFR Part 11) and need the per-step LLM-call trail in your
audit datastore.

**What v1.25.0 ships:** SSE routes whose axonendpoint declared
`replay: true` (or POST without explicit `replay:`, which defaults
to enabled per Fase 32.h D9) record an
`AxonendpointReplayEntry` with the new `step_audit` field
populated. Each entry in `step_audit` is an 8-field record:

```jsonc
{
  "step_name": "DifferentialReasoning",
  "step_index": 1,                  // 0-based; monotonic within flow
  "success": true,
  "tokens_emitted": 134,             // non-empty chunks consumed
  "output_hash_hex": "0b1c2d3e...",  // SHA-256 of accumulated step output
  "effect_policy_applied": "drop_oldest",  // closed-catalog slug or null
  "chunks_dropped": 0,               // DropOldest counter
  "chunks_degraded": 0,              // DegradeQuality counter
  "timestamp_ms": 1715517605456
}
```

**Recipe:**

```axon
// In your adopter source:
tool clinical_reasoning {
    description: "Step-by-step CDS reasoning"
    effects: <stream:drop_oldest>
}

flow CDSAssessment() -> Unit {
    step TriageVitals    { ask: "..." output: Stream<Token> }
    step DifferentialReasoning { ask: "..." apply: clinical_reasoning }
}

axonendpoint ClinicalDecisionSupport {
    method: POST
    path: "/cds/decision"
    execute: CDSAssessment
    transport: sse
    replay: true              // ← critical: enables the step_audit recording
    requires: [clinician.assess]
}
```

```python
# In your audit-indexing script:
import httpx

# 1. The POST response carries the trace UUID in the
#    X-Axon-Trace-Id header (set up-front by Fase 33.x.f's
#    dispatch-handler-level UUID generation, BEFORE the
#    route_wire match):
resp = httpx.post("https://axon.example.com/cds/decision", json={"patient": "..."})
trace_id = resp.headers["x-axon-trace-id"]

# 2. After the SSE stream closes (consume axon.complete on the
#    client side), GET the replay entry:
replay = httpx.get(
    f"https://axon.example.com/v1/replay/{trace_id}",
    headers={"Authorization": "Bearer <read-only-token>"},
).json()

# 3. Index each step's audit record into your compliance store:
for step in replay["step_audit"]:
    audit_store.insert({
        "trace_id": trace_id,
        "step_name": step["step_name"],
        "step_index": step["step_index"],
        "tokens_emitted": step["tokens_emitted"],
        "output_hash_hex": step["output_hash_hex"],
        "effect_policy_applied": step["effect_policy_applied"],
        "chunks_dropped": step["chunks_dropped"],
        "chunks_degraded": step["chunks_degraded"],
        "timestamp_ms": step["timestamp_ms"],
        # Vertical-specific compliance fields:
        "regulation": "21_CFR_Part_11",  # or PCI DSS / FedRAMP / FRE 502
        "endpoint_name": replay["endpoint_name"],
        "client_id": replay["client_id"],
        "capabilities_used": replay["capabilities_used"],
    })
```

**Per-token chain signature is NOT in this scope.** v1.25.0
records **per-step** granularity; per-`axon.token` cryptographic
chaining (byte-exact replay-as-original at the event level) ships
as Fase 34 if/when regulated adopters need it. For most regulated
verticals the per-step trail satisfies the controlling standard:

| Standard | Granularity needed | v1.25.0 provides |
|---|---|---|
| PCI DSS Req 10 | Per LLM-call hash chain | ✅ Yes (`output_hash_hex` per step) |
| FedRAMP AU-2 | Per reasoning step retention | ✅ Yes (`step_audit` array) |
| FRE 502 waiver-doctrine | Per privilege-assessment trail | ✅ Yes (per-step reasoning capture) |
| 21 CFR Part 11 §11.10 | Per CDS recommendation provenance | ✅ Yes (`output_hash_hex` + `effect_policy_applied`) |

---

## Scenario C — You want BPE-tokenized chunking for legacy-path flows

**Symptom:** Your adopter source uses a flow shape the 33.x.b
streaming planner doesn't yet model (anchors / lambda apply / let
bindings / mid-stream `use_tool` / hibernate / pix / un-modeled
IRFlowNode variants), so the runtime falls back to the synchronous
LEGACY path. The default whitespace 3-word grouping gives chunky
delivery; you want finer per-token granularity for better adopter
UX.

**What v1.25.0 ships:** an opt-in BPE-tokenized fallback chunker
behind `axon::runtime_flags::set_tokenizer_fallback(true)`.
Defaults OFF so v1.24.0 wire byte-compat is preserved for
adopters that don't opt in. When ON + the LEGACY path activates,
each step's full output goes through
`axon_csys::tokens::cl100k_base()` and one StepToken event is
emitted per BPE token.

**Recipe (Rust adopter):**

```rust
// In your main.rs (process-startup):
fn main() {
    // Opt in to BPE chunking for LEGACY-path flows.
    // Defaults OFF; safe to call before tokio runtime starts.
    axon::runtime_flags::set_tokenizer_fallback(true);

    // ... rest of axon-server boot sequence ...
}
```

**Recipe (Python adopter, if you ship the Rust runtime + Python
clients):**

The flag is process-wide on the server side. Adopter clients
don't need to set anything — the change is observable on the
SSE wire as one `axon.token` event per BPE token instead of per
3-word group. Adopters that already parse `axon.token.token`
field see the same JSON schema with finer-grained deltas.

**Caveat (UTF-8 boundary safety):** BPE tokens can split mid-
codepoint (e.g., a single Chinese character may take multiple
tokens). The chunker uses `String::from_utf8_lossy` which
substitutes U+FFFD for invalid sequences. English prose is
unaffected; non-Latin scripts may see replacement chars in some
chunks. For regulated non-English adopters consult the
axon-enterprise vertical BPE roadmap (HIPAA-PHI-aware /
legal-doctrine-aware / fintech-regulator-aware tokenizers).

**Graceful degrade:** if the tokenizer fails to construct or
encode (rare — cl100k_base is embedded via c23-embed at build
time), the chunker returns an empty Vec and the caller
automatically falls back to whitespace 3-word grouping. The wire
body is **always well-formed** regardless of tokenizer state.

---

## Scenario D — You want to validate client-disconnect cancel budget

**Symptom:** You ship a high-traffic adopter (e.g., a chat UI
where users frequently close tabs mid-stream) and need to verify
that client disconnects propagate to the upstream LLM provider
within an SLA. Wasted token quota on stale streams is a real
cost concern.

**What v1.25.0 ships:** D3 measurable invariant — **p95 cancel→
None ≤ 100ms wall-clock**. The chain end-to-end:

```
EventSource.close() in browser
  → axum drops the Sse response
  → CancelOnDrop guard fires (33.f baseline)
  → cancel.cancel()
  → sse_streaming::cancel_aware adapter's biased tokio::select!
    fires the cancelled() arm INSIDE the reqwest body iterator
  → wrapper yields None to the consumer (p95 12.6µs measured
    against local-loopback mock; budget 100ms wall-clock against
    real upstream)
  → consumer drops the wrapper
  → reqwest Response::bytes_stream() drops
  → upstream HTTP request aborted
  → no further token quota spent
```

**Recipe (validation with curl + tcpdump):**

```bash
# Terminal 1 — capture the wire:
sudo tcpdump -i lo0 -w /tmp/axon_sse.pcap port 8080

# Terminal 2 — start an SSE stream, then SIGINT after ~500ms:
curl --max-time 5 -N -X POST http://localhost:8080/chat \
  -H 'content-type: application/json' \
  -d '{}' &
CURL_PID=$!
sleep 0.5
kill -INT $CURL_PID

# Stop tcpdump (ctrl-C in terminal 1).

# Open the pcap in Wireshark or use tshark:
tshark -r /tmp/axon_sse.pcap -Y 'tcp.flags.fin == 1' \
       -T fields -e frame.time_relative -e tcp.srcport -e tcp.dstport

# Expected: the FIN packet from the server to the upstream
# provider (e.g., api.anthropic.com:443) arrives within ~100ms
# of the FIN from curl to axon-server. Variance ≥ 100ms suggests
# either:
#   - The route went through the LEGACY synchronous path
#     (check axon.complete.warnings for axon-W002).
#   - A custom adopter backend lacks Backend::stream() (D3 then
#     only fires on Backend::complete() responses, not chunks).
#   - Network jitter on the runner (run the test on the deploy
#     host directly).
```

**Recipe (validation via opt-in CI lane):**

The `fase_33x_real_provider.yml` workflow asserts p95 inter-chunk
arrival ≤100ms against real upstream providers. To run for your
fork:

```bash
# 1. Set repository variable: AXON_RUN_REAL_PROVIDER_TEST=1
# 2. Set provider key secrets (any subset of):
#    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
# 3. Trigger via GitHub Actions UI or:
gh workflow run fase_33x_real_provider.yml
```

Lanes for unset keys skip cleanly with `eprintln!` in the CI log
— a fork with only `ANTHROPIC_API_KEY` validates Anthropic + all
4 vertical lanes while OpenAI/Gemini lanes skip.

**Recipe (local synthetic-stream validation):**

For a deterministic test of the cancel-budget invariant against a
local-loopback slow-drip mock (no real provider keys needed):

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33x_e_cancel_inside_body \
  d3_p95_cancel_to_none_within_100ms_30_trials \
  -- --nocapture
```

The test runs 30 trials against an OpenAI-compat SSE mock that
drips one chunk per second; it fires `cancel.cancel()` after the
first chunk arrives + measures `next().await` latency. Verified
output: `p50=8.2µs p95=12.6µs max=13.6µs` (7950× under the 100ms
budget).

---

## Honest scope statement (carried verbatim from the plan vivo)

**What v1.25.0 ships in the 33.x cycle:**

- 33.x.a — plan vivo + diagnostic anchor + D1-D11 ratification
- 33.x.b — async bridge: `server_execute_streaming` calls
  `Backend::stream()` per step
- 33.x.c — unified `.axon` source compilation pipeline +
  `flow_plan` shared helpers
- 33.x.d — `StreamPolicyEnforcer` activation in production +
  `enforcement_summary` wire field
- 33.x.e — cancel-inside-reqwest-body, p95 ≤100ms invariant
- 33.x.f — per-step `step_audit` on `/v1/replay/<uuid>` for SSE
  routes
- 33.x.g — closed-catalog `axon-W002 streaming-not-supported`
  warning surface
- 33.x.h — opt-in BPE-tokenized fallback chunking via runtime flag
- 33.x.i — mono-file `crate::backend` retirement Phase 1
  (consolidation + deprecation + drift gate)
- 33.x.j — real-provider E2E gated lane against
  Anthropic / OpenAI / Gemini + 4 vertical canonical patterns
- 33.x.k — D12 robustness fuzz across 11 surfaces + dedicated
  10-job CI workflow
- 33.x.l — this document + ADOPTER_STREAMING.md extension
- 33.x.m — coordinated release v1.25.0 cross-stack +
  axon-enterprise v1.16.0 catch-up

**What is explicitly DEFERRED:**

| Followup | Scope |
|---|---|
| **Fase 33.x.i.2** | Full sync→async migration of the 4 callers of `crate::backend::*` (runner.rs CLI sync path + axon_server.rs legacy JSON `/v1/execute` path + resilient_backend.rs circuit-breaker wrapper + tenant_secrets.rs env-fallback step). Multi-thousand-LOC refactor converting `reqwest::blocking` to `reqwest::Client` async + threading tokio runtime through previously-blocking helpers. Independent of the 33.x wire-activation deliverables. |
| **Fase 34** | Per-token cryptographic chain signature — each `axon.token` event individually signed + hash-chained for byte-exact replay-as-original. v1.25.0's `step_audit` records per-step granularity which satisfies the regulated-vertical audit standards for most adopters; per-token chain ships if/when adopters need byte-exact stream replay. |
| **Fase 33-followon-2** | Mid-stream tool calling — when a flow's stream emits a tool-call request, the tool result is interleaved into the stream + execution resumes. v1.25.0 keeps tool-call orchestration on the legacy synchronous path. |
| **gRPC streaming binding** | Future Fase orthogonal to SSE. |
| **WebSocket upgrade from SSE** | Out of scope per Fase 30 D2. |

---

## Verification matrix

After upgrading to v1.25.0, run this matrix in your adopter
environment to verify the migration:

| Check | Command | Expected |
|---|---|---|
| OSS lib + integration suites | `cargo test --manifest-path axon-rs/Cargo.toml --tests` | All 49 integration suites + 1614 lib tests pass; 7 ignored (real-provider lanes, gated) |
| Python parity | `python -m pytest tests/test_fase24_backend_parity.py -q` | 23 passed |
| 33.x cycle CI | Push to a topic branch + check the new `Fase 33.x — Runtime activation` workflow | 10 parallel jobs green in ~3-5 min |
| Wire body byte-compat for stub | POST to any `transport: sse` route deployed with `backend: stub`; capture body | 1 axon.token "(stub)" + 1 axon.complete (identical to v1.24.0) |
| Real-provider p95 ≤100ms | Set `AXON_RUN_REAL_PROVIDER_TEST=1` + a provider key secret; trigger `fase_33x_real_provider.yml` | All set-key lanes report p95 ≤100ms; unset-key lanes skip cleanly |
| Per-step replay binding | Deploy an SSE flow with `replay: true`; POST it; GET `/v1/replay/<x-axon-trace-id>` | Response 200 with `step_audit` array populated |
| W002 surface on legacy fallback | Deploy a flow with `for x in [...]` or other unsupported shape; POST it; inspect `axon.complete.warnings` | Single W002 entry with `fallback_mode: "unsupported_flow_shape"` |

---

## See also

- [ADOPTER_STREAMING.md § Production-path activation (Fase 33.x, v1.25.0+)](ADOPTER_STREAMING.md#production-path-activation-fase-33x-v1250) — the canonical adopter guide.
- [Fase 33.x plan vivo](fase_33x_runtime_activation.md) — internal sub-fase tracker + D-letter ratifications.
- [MIGRATION_v1.24.md](MIGRATION_v1.24.md) — previous-version migration guide; covers the Fase 33 primitive activation that 33.x builds on.
- [axon-rs `tests/fase33x_*.rs`](../axon-rs/tests/) — canonical test pack for the 33.x cycle (9 test files: b/c integration + d enforcer + e cancel + f replay + g warning + h tokenizer + i drift + j real-provider + k fuzz + diagnostic anchor).
- [Fase 11.a — Stream<T> algebraic effect](fase_11_neuro_symbolic_axon.md) — the algebraic-effect foundation the 33.x cycle activates at runtime.

---

*This document is part of the axon-lang public adopter surface.
PRs welcome — see `CONTRIBUTING.md`.*
