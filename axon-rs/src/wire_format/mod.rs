//! §Fase 33.z.k (v1.28.0) — Wire-format adapter framework.
//!
//! Closed-catalog dispatcher for SSE wire-format dialects. Three
//! dialects ship as first-class adapters per Q3 ratification:
//!
//! - **axon**: W3C named events (`event: axon.token` /
//!   `event: axon.complete` / `event: axon.tool_call` /
//!   `event: axon.error`). D6 backwards-compat baseline.
//! - **openai**: `data: {"choices": [{"delta": {"content": "..."}}]}`
//!   frames terminated by `data: [DONE]`. Matches OpenAI Chat
//!   Completions API streaming wire (OpenAI Reference Docs §Chat /
//!   Create chat completion / Streaming).
//! - **anthropic**: `event: content_block_delta` /
//!   `event: message_stop`. Matches Anthropic Messages API
//!   streaming wire (Anthropic API Reference §Messages / Streaming).
//!
//! # Architecture
//!
//! The producer drives a translation loop:
//!
//! ```text
//! for event in flow_execution_event_stream {
//!     for wire_event in adapter.translate(&event) {
//!         tx.send(Ok(wire_event)).await?;
//!     }
//! }
//! for terminator in adapter.flush_terminator() {
//!     tx.send(Ok(terminator)).await?;
//! }
//! ```
//!
//! Each adapter is **stateful** — it tracks per-request state (event
//! ID counter, current step index for content_block boundaries,
//! per-dialect tool-call indices, etc.). A fresh adapter is
//! constructed per request via `select_adapter(dialect, trace_id)`.
//!
//! # D-letter coverage
//!
//! - **D3 semantic equivalence**: every dialect emits the SAME
//!   per-token content + step-name + arrival ordering. Only framing
//!   differs.
//! - **D4 algebraic-policy preservation**: each adapter exposes a
//!   dedicated path for `enforcement_summary` / `runtime_warnings` /
//!   `step_audit` surfacing — axon embeds them on `axon.complete`,
//!   openai emits a `data: {"axon_metadata": {...}}` frame BEFORE
//!   `data: [DONE]`, anthropic emits `event: axon.metadata` BEFORE
//!   `event: message_stop`.
//! - **D5 closed-dialect terminators**: each adapter's
//!   `flush_terminator()` emits the dialect's native terminator
//!   (axon: `axon.complete`; openai: `data: [DONE]`; anthropic:
//!   `event: message_stop`).
//! - **D9 wire byte-compat for canonical Step**: the axon-dialect
//!   adapter MUST produce byte-identical output to the v1.27.1
//!   inline emission. Test pack
//!   `tests/fase33z_k_d_axon_adapter_byte_compat.rs` pins this.
//!
//! # Pillar trace (D10)
//!
//! - MATHEMATICS — each `translate` is a pure projection from one
//!   `FlowExecutionEvent` to a `Vec<Event>`. Trait method invariant.
//! - LOGIC — closed catalog of 3 dialects; `select_adapter`
//!   dispatch is exhaustive; unknown dialect defaults to axon.
//! - PHILOSOPHY — adopters' SDKs consume the wire format their
//!   ecosystem documents; the language adapts to the adopter
//!   layer, not the other way around (`Axon for Axon` discipline
//!   per the founder principle).
//! - COMPUTING — adapter selection is O(1) at request time;
//!   per-request adapter state is unbounded but small (~3-5
//!   counters); no allocation per token translation.

pub mod anthropic_dialect;
pub mod axon_dialect;
pub mod openai_dialect;

use crate::axon_server::EnforcementSummaryWire;
use crate::flow_execution_event::FlowExecutionEvent;
use crate::runtime_warnings::RuntimeWarning;
use axum::response::sse::Event;

/// §Fase 33.z.k.g (v1.28.0) — Envelope carrying all the side-channel
/// + summary data the SSE producer accumulates over the lifetime of
/// a flow. Passed to `adapter.build_complete_envelope_event()` at
/// FlowComplete time so dialect adapters can surface the data per
/// their wire-format conventions:
///
/// - **axon**: embeds the fields directly on `axon.complete` (D4
///   wire byte-compat with v1.27.1 inline `build_complete_event`).
/// - **openai**: emits a separate `data: {"axon_metadata": {...}}`
///   frame BEFORE `data: [DONE]` (Q7 ratification).
/// - **anthropic**: emits a separate `event: axon.metadata` frame
///   BEFORE `event: message_stop` (Q7).
///
/// Built by the producer from the same side-channels v1.27.1
/// `build_complete_event` consumed:
/// - `enforcement_summaries`: per-step enforcement counters from
///   the dispatcher's `StreamPolicyEnforcer` (Fase 33.x.d).
/// - `runtime_warnings`: closed-catalog axon-W002 etc. warnings
///   (Fase 33.x.g).
/// - `effect_policies`: per-step `<stream:<policy>>` declarations
///   (Fase 33.e).
/// - Flow envelope: trace_id, flow_name, backend, success, counters,
///   latency.
#[derive(Debug, Clone)]
pub struct CompleteEnvelope {
    pub trace_id: u64,
    pub flow_name: String,
    pub backend: String,
    pub success: bool,
    pub steps_executed: usize,
    pub tokens_input: u64,
    pub tokens_output: u64,
    pub latency_ms: u64,
    pub effect_policies: Vec<(String, String)>,
    pub enforcement_summaries: Vec<(String, EnforcementSummaryWire)>,
    pub runtime_warnings: Vec<RuntimeWarning>,
}

/// Wire-format adapter trait — translates internal flow-execution
/// events into per-dialect SSE wire events.
///
/// Adapters are **stateful** — a fresh adapter is constructed per
/// request via [`select_adapter`]. The adapter tracks per-request
/// state (event ID counter, step index, per-tool-call index, etc.)
/// internally.
///
/// All methods are `&mut self` to permit internal counter updates.
/// Adapters MUST be `Send` so the SSE producer can move them across
/// the spawn boundary.
pub trait WireFormatAdapter: Send {
    /// Closed-catalog dialect identifier this adapter implements.
    /// One of `"axon"`, `"openai"`, `"anthropic"`.
    fn dialect(&self) -> &'static str;

    /// Translate a single internal flow-execution event into zero
    /// or more wire SSE events.
    ///
    /// Returning an empty Vec is valid — some dialects swallow
    /// certain internal events (e.g., openai doesn't have a per-step
    /// `step_start` concept; AxonDialectAdapter emits one).
    ///
    /// NOTE: the producer calls `build_complete_envelope_event()`
    /// instead of `translate()` for `FlowComplete` so the adapter
    /// receives the full algebraic-policy side-channel data. The
    /// `translate(FlowComplete)` path is retained for adapters /
    /// callers that don't have the full envelope available; it
    /// produces a minimal envelope without enforcement_summaries /
    /// runtime_warnings / effect_policies.
    fn translate(&mut self, event: &FlowExecutionEvent) -> Vec<Event>;

    /// §Fase 33.z.k.g (v1.28.0) — Build the dialect-specific
    /// "complete" event with the full algebraic-policy side-channel
    /// data accumulated over the flow's lifetime. The producer calls
    /// this in place of `translate(FlowComplete)` so adapters can
    /// surface enforcement_summaries / runtime_warnings /
    /// effect_policies per their wire-format conventions.
    ///
    /// Default impl: produces the same output as
    /// `translate(FlowComplete{...})` reconstructed from the envelope
    /// — adapters that don't override see the envelope's flow-level
    /// fields but no side-channel data.
    fn build_complete_envelope_event(&mut self, envelope: &CompleteEnvelope) -> Vec<Event> {
        // Default fallback: build a FlowComplete event from the
        // envelope's flow-level fields + translate it normally.
        let event = FlowExecutionEvent::FlowComplete {
            flow_name: envelope.flow_name.clone(),
            backend: envelope.backend.clone(),
            success: envelope.success,
            steps_executed: envelope.steps_executed,
            tokens_input: envelope.tokens_input,
            tokens_output: envelope.tokens_output,
            latency_ms: envelope.latency_ms,
            timestamp_ms: 0,
        };
        self.translate(&event)
    }

    /// Emit any final terminator frames after the internal
    /// `FlowComplete` / `FlowError` event has been translated.
    ///
    /// - axon: emits no extra terminator (the `axon.complete` event
    ///   from `translate()` is itself the terminator).
    /// - openai: emits `data: [DONE]`.
    /// - anthropic: emits `event: message_stop` if not already
    ///   emitted as part of FlowComplete translation.
    fn flush_terminator(&mut self) -> Vec<Event>;
}

/// Closed-catalog factory for wire-format adapters.
///
/// `dialect` is one of `"axon"` / `"openai"` / `"anthropic"` (Q3
/// ratified catalog). Unknown dialect strings default to
/// `axon` (defensive — caller already validated via
/// `AXONENDPOINT_TRANSPORT_DIALECTS` at parse time, but we never
/// panic on a stale input).
///
/// `trace_id` is reserved per-request (Fase 33.x.c contract); the
/// adapter embeds it in every emitted event for correlation.
pub fn select_adapter(
    dialect: &str,
    trace_id: u64,
) -> Box<dyn WireFormatAdapter> {
    match dialect {
        "axon" => Box::new(axon_dialect::AxonDialectAdapter::new(trace_id)),
        // §Fase 33.z.k.e — OpenAI Chat Completions streaming wire.
        "openai" => Box::new(openai_dialect::OpenAIDialectAdapter::new(trace_id)),
        // §Fase 33.z.k.f — Anthropic Messages streaming wire.
        "anthropic" => Box::new(anthropic_dialect::AnthropicDialectAdapter::new(trace_id)),
        _ => Box::new(axon_dialect::AxonDialectAdapter::new(trace_id)),
    }
}
