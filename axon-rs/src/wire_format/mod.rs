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

use crate::flow_execution_event::FlowExecutionEvent;
use axum::response::sse::Event;

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
    fn translate(&mut self, event: &FlowExecutionEvent) -> Vec<Event>;

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
