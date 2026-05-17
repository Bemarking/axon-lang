//! §Fase 36.a — Axonendpoint backend-gap diagnostic anchor.
//!
//! Pins the v1.33.0 state that Fase 36 closes: a deployed `axonendpoint`
//! executes its flow against the no-op `stub` backend, and there is no
//! declarative way to wire a real LLM. This test is the committed
//! baseline — each later sub-fase (36.b–36.l) inverts a piece of it.
//!
//! The three conspiring breaks + one piece of dead code (verified
//! 2026-05-17, see `docs/fase/fase_36_axonendpoint_production_execution.md`):
//!
//!   A. `dynamic_endpoint_handler` hardcodes `backend: "auto"`; `"auto"`
//!      scores ONLY `state.backend_registry`, which is empty unless an
//!      operator ran `PUT /v1/backends` — so `auto` falls back to
//!      `stub`. It never consults the provider API keys in the env.
//!   B. `DeployRequest.backend` is discarded; `DynamicEndpointRoute`
//!      has no `backend` field.
//!   C. The `axonendpoint` declaration has no `backend:` field; the
//!      server has no `--backend` flag. Backend selection has no
//!      declarative input at all.
//!   Dead code — `DispatchCtx::with_tool_registry` has zero production
//!   callers; `run_streaming_via_dispatcher` never wires a tool
//!   registry, so an `apply: <streaming-tool>` never reaches its
//!   streaming path and the declared `provider:` is ignored.
//!
//! What this file asserts is the externally-observable PUB surface
//! that frames the gap; the per-sub-fase behavioural tests live with
//! their sub-fases.

use axon::backends::{resolve_streaming_backend, CANONICAL_PROVIDERS};

/// §1 — `"auto"` is not itself a resolvable backend. It is a routing
/// token the server is supposed to RESOLVE; today that resolution
/// dead-ends at `stub`. Fase 36's D1 ladder replaces the dead-end.
#[test]
fn auto_is_not_a_resolvable_backend() {
    assert!(
        resolve_streaming_backend("auto").is_none(),
        "`auto` must be resolved by the D1 ladder, never treated as a backend"
    );
}

/// §2 — `stub` IS a real, resolvable backend — which is precisely why
/// the empty-registry `auto` fallback can silently land on it.
/// Fase 36 D5 forbids reaching `stub` except by an explicit request.
#[test]
fn stub_is_resolvable_the_silent_fallback_target() {
    assert!(
        resolve_streaming_backend("stub").is_some(),
        "stub resolves — the silent no-op the gap report observed"
    );
}

/// §3 — the closed catalog of real providers. This is the universe
/// `auto` SHOULD consult (via their API-key env vars) and does not —
/// Fase 36 D6 closes that. Every canonical provider resolves.
#[test]
fn the_canonical_providers_are_a_closed_resolvable_catalog() {
    assert_eq!(
        CANONICAL_PROVIDERS.len(),
        7,
        "the closed catalog is exactly 7 providers"
    );
    for provider in CANONICAL_PROVIDERS {
        assert!(
            resolve_streaming_backend(provider).is_some(),
            "canonical provider `{provider}` must resolve to a real backend"
        );
    }
}

/// §4 — an unknown backend resolves to nothing (not silently to stub).
/// The resolver itself is honest; the gap is upstream, in the `auto`
/// fallback + the absence of a declared backend.
#[test]
fn an_unknown_backend_resolves_to_none_not_stub() {
    assert!(resolve_streaming_backend("gpt-9-ultra").is_none());
    assert!(resolve_streaming_backend("").is_none());
}

/// §5 — the diagnostic narrative, emitted for the record.
#[test]
fn gap_diagnostic_narrative() {
    eprintln!(
        "§Fase 36.a — axonendpoint backend gap (v1.33.0 baseline):\n\
         A. dynamic_endpoint_handler hardcodes backend=\"auto\";\n\
            compute_backend_scores reads only backend_registry (empty\n\
            unless PUT /v1/backends) -> auto falls back to `stub`.\n\
         B. DeployRequest.backend discarded; DynamicEndpointRoute has\n\
            no backend field.\n\
         C. `axonendpoint` has no `backend:` declaration; `axon serve`\n\
            has no --backend flag. Backend selection has zero\n\
            declarative input.\n\
         Dead code: DispatchCtx::with_tool_registry has no production\n\
            caller -> apply:<streaming-tool> never executes its tool.\n\
         POST-36: a deterministic D1 precedence ladder resolves the\n\
         backend; no silent stub (D5); the declared tool provider is\n\
         executed (D4)."
    );
    // The closed catalog is the anchor invariant later sub-fases build on.
    assert_eq!(CANONICAL_PROVIDERS.len(), 7);
}
