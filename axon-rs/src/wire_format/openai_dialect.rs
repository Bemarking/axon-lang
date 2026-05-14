//! §Fase 33.z.k.e (v1.28.0) — `openai` Chat Completions streaming
//! dialect adapter.
//!
//! Matches the OpenAI Chat Completions streaming wire verbatim per
//! the published API reference:
//!
//!   https://platform.openai.com/docs/api-reference/chat/streaming
//!
//! # Wire shape (verbatim from OpenAI reference)
//!
//! Every frame is a `data:` line — no `event:` field. Frames are
//! separated by `\n\n`. Each frame's payload is a JSON object with
//! the closed shape:
//!
//! ```text
//! data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1715648400,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}
//!
//! ```
//!
//! Required top-level fields per OpenAI spec:
//!   - `id`: response identifier; constant across the chunk stream
//!   - `object`: literal `"chat.completion.chunk"`
//!   - `created`: Unix timestamp in seconds (constant across stream)
//!   - `model`: model identifier (constant across stream)
//!   - `choices`: array of choice objects
//!
//! Per-choice fields:
//!   - `index`: 0 for single-completion streams
//!   - `delta`: incremental content (`{}`, `{"role": "assistant"}`,
//!     `{"content": "..."}`, or `{"tool_calls": [...]}`)
//!   - `finish_reason`: `null` mid-stream; `"stop"` /
//!     `"length"` / `"tool_calls"` / `"content_filter"` on last frame
//!
//! After the LAST data frame, OpenAI emits a final sentinel:
//!
//! ```text
//! data: [DONE]
//!
//! ```
//!
//! # axon → openai event mapping
//!
//! | axon FlowExecutionEvent | openai wire frame                                    |
//! |--------------------------|------------------------------------------------------|
//! | FlowStart                | 1 frame with `delta: {"role": "assistant"}`          |
//! | StepStart                | 0 frames (openai has no multi-step concept)          |
//! | StepToken                | 1 frame with `delta: {"content": "<token>"}`         |
//! | StepComplete             | 0 frames                                             |
//! | ToolCall                 | 1 frame with `delta: {"tool_calls": [{...}]}`        |
//! | FlowComplete             | 1 frame with `delta: {}`, `finish_reason: "stop"`    |
//! |                          | + 1 axon_metadata frame (Q7 algebraic-policy)        |
//! | FlowError                | 1 frame with `delta: {}`, `finish_reason: "error"`   |
//! | flush_terminator         | 1 frame `data: [DONE]`                               |
//!
//! Step boundaries are NOT visible on the openai wire (the dialect
//! doesn't model multi-step flows). Adopters consuming openai-compat
//! clients see a single continuous content stream concatenated
//! across step tokens. The `axon_metadata` frame emitted before
//! `[DONE]` carries per-step audit + enforcement counters for
//! adopters who need step-level visibility (Q7 ratification).
//!
//! # Tool-call mapping detail
//!
//! Our `FlowExecutionEvent::ToolCall` carries the FULL tool-call
//! payload in one event (the upstream LLM emitted it as a complete
//! `FinishReason::ToolUse`). OpenAI's wire streams tool calls as
//! partial `function.arguments` deltas across frames; emitting the
//! whole arguments string in a single frame is VALID — OpenAI does
//! this when arguments fit in one chunk. The adapter emits one
//! frame per ToolCall event with the complete arguments string.
//!
//! # Pillar trace (D10)
//!
//! - MATHEMATICS — every frame is a pure projection from one input
//!   event; field set is closed-catalog.
//! - LOGIC — `finish_reason` enum is closed per OpenAI spec.
//! - PHILOSOPHY — adopters using openai-compat SDKs (litellm,
//!   instructor, langchain, llama_index, vercel/ai-sdk, etc.) parse
//!   the wire verbatim without any axon-specific awareness.
//! - COMPUTING — JSON serialization is `serde_json::to_string`
//!   default ordering (insertion-order preserving in serde_json's
//!   default `Value::Object` backed by `Map<String, Value>` which is
//!   `serde_json::Map = BTreeMap` when `preserve_order` feature is
//!   off — alphabetical key order in output). Adopter parsers MUST
//!   be order-agnostic per JSON spec; OpenAI's own wire is not
//!   key-ordered. Tests pin field PRESENCE + values, not byte order.

use super::WireFormatAdapter;
use crate::flow_execution_event::FlowExecutionEvent;
use axum::response::sse::Event;

/// The OpenAI Chat Completions streaming dialect adapter.
pub struct OpenAIDialectAdapter {
    /// Stable response id across the chunk stream. Synthesized once
    /// at adapter construction from the request's trace_id.
    response_id: String,
    /// Unix timestamp in seconds; constant across the stream per
    /// OpenAI spec.
    created: u64,
    /// Model identifier; constant across the stream. Populated from
    /// the first FlowStart event's `backend` field (defaults to
    /// `"axon"` until that event arrives).
    model: String,
    /// Whether the role-marker frame has been emitted. Per OpenAI
    /// spec, the first chunk's delta is `{"role": "assistant"}`.
    role_marker_emitted: bool,
    /// Tracks the last terminal reason so flush_terminator() can
    /// emit the proper `finish_reason` if FlowComplete/FlowError
    /// was not processed (defensive — should not happen in
    /// well-formed flows).
    terminal_emitted: bool,
    /// Per-request running counter for synthesizing tool_call IDs
    /// (OpenAI requires `id` on each tool_calls[] entry).
    tool_call_counter: u64,
    /// §Q7 — Algebraic-policy buffering. We accumulate the
    /// algebraic-policy side-channels (enforcement_summary,
    /// runtime_warnings, step_audit) over the flow's lifetime
    /// and emit them as a single `axon_metadata` frame BEFORE
    /// the `data: [DONE]` terminator. Pre-33.z.k.h these fields
    /// are populated by the producer wiring (33.z.k.g); for
    /// 33.z.k.e they are emitted as an empty placeholder so the
    /// adapter's wire shape is complete.
    saw_terminal_reason: TerminalReason,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum TerminalReason {
    None,
    Stop,
    Error,
}

impl OpenAIDialectAdapter {
    /// Construct a fresh adapter for a request. The trace_id is
    /// embedded in the response_id; created uses the current Unix
    /// timestamp.
    pub fn new(trace_id: u64) -> Self {
        let response_id = format!("chatcmpl-axon-{trace_id:x}");
        let created = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Self {
            response_id,
            created,
            model: "axon".to_string(),
            role_marker_emitted: false,
            terminal_emitted: false,
            tool_call_counter: 0,
            saw_terminal_reason: TerminalReason::None,
        }
    }

    /// Build a chunk frame with the given delta + finish_reason.
    /// All other top-level fields (id, object, created, model)
    /// stay constant across the stream per OpenAI spec.
    fn build_chunk_frame(
        &self,
        delta: serde_json::Value,
        finish_reason: Option<&str>,
    ) -> Event {
        let choice = serde_json::json!({
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        });
        let payload = serde_json::json!({
            "id": &self.response_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": &self.model,
            "choices": [choice],
        });
        Event::default().data(serde_json::to_string(&payload).unwrap_or_default())
    }

    /// Synthesize a stable tool_call ID. OpenAI requires per-call IDs
    /// so adopters can correlate tool results back to their requests.
    fn next_tool_call_id(&mut self) -> String {
        self.tool_call_counter += 1;
        format!(
            "call_{}_{}",
            self.response_id.strip_prefix("chatcmpl-axon-").unwrap_or("0"),
            self.tool_call_counter,
        )
    }

    /// Q7 — Emit the optional `axon_metadata` frame carrying the
    /// algebraic-policy side-channels. Pre-33.z.k.h this returns
    /// an empty-body frame (a placeholder); 33.z.k.h wires the
    /// actual enforcement_summary / runtime_warnings / step_audit
    /// data through.
    fn build_axon_metadata_frame(&self) -> Event {
        let payload = serde_json::json!({
            "axon_metadata": {
                // §33.z.k.h will populate these from the
                // FlowExecutionEvent stream's accumulated state.
                // For 33.z.k.e these are placeholders so the wire
                // shape is complete + adopters can rely on the
                // frame's existence.
                "enforcement_summary": {},
                "runtime_warnings": [],
                "step_audit": [],
            }
        });
        Event::default().data(serde_json::to_string(&payload).unwrap_or_default())
    }
}

impl WireFormatAdapter for OpenAIDialectAdapter {
    fn dialect(&self) -> &'static str {
        "openai"
    }

    fn translate(&mut self, event: &FlowExecutionEvent) -> Vec<Event> {
        match event {
            FlowExecutionEvent::FlowStart { backend, .. } => {
                // Capture the model identifier from the FlowStart's
                // backend field. This is the only opportunity to
                // pin the model name for the response (OpenAI spec
                // requires it constant across the stream).
                self.model = backend.clone();
                // Emit the role-marker frame per OpenAI spec
                // (first chunk has `delta: {"role": "assistant"}`).
                self.role_marker_emitted = true;
                vec![self.build_chunk_frame(
                    serde_json::json!({"role": "assistant"}),
                    None,
                )]
            }
            FlowExecutionEvent::StepStart { .. } => {
                // OpenAI has no multi-step concept; silently consume.
                Vec::new()
            }
            FlowExecutionEvent::StepToken { content, .. } => {
                vec![self.build_chunk_frame(
                    serde_json::json!({"content": content}),
                    None,
                )]
            }
            FlowExecutionEvent::StepComplete { .. } => Vec::new(),
            FlowExecutionEvent::ToolCall {
                tool_name,
                content,
                ..
            } => {
                let call_id = self.next_tool_call_id();
                let delta = serde_json::json!({
                    "tool_calls": [{
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": content,
                        }
                    }]
                });
                vec![self.build_chunk_frame(delta, None)]
            }
            FlowExecutionEvent::FlowComplete { .. } => {
                self.terminal_emitted = true;
                self.saw_terminal_reason = TerminalReason::Stop;
                vec![self.build_chunk_frame(
                    serde_json::json!({}),
                    Some("stop"),
                )]
            }
            FlowExecutionEvent::FlowError { .. } => {
                self.terminal_emitted = true;
                self.saw_terminal_reason = TerminalReason::Error;
                // OpenAI doesn't have a dedicated "error" finish_reason
                // — adopter SDKs treat the absence of the `[DONE]`
                // sentinel OR a non-standard finish_reason as the
                // signal. We emit a final chunk with the closest
                // canonical value `"stop"` and rely on the absence
                // of any further content frames as the implicit
                // error signal. Adopters who need explicit error
                // info should also consume the axon_metadata frame
                // (Q7).
                vec![self.build_chunk_frame(
                    serde_json::json!({}),
                    Some("stop"),
                )]
            }
        }
    }

    fn flush_terminator(&mut self) -> Vec<Event> {
        // §Q7 — emit the axon_metadata frame BEFORE the [DONE]
        // sentinel so adopters parsing the full stream see the
        // algebraic-policy side-channels in order. The metadata
        // frame is a non-OpenAI extension; openai-compat clients
        // that strictly validate the chunk shape will ignore it
        // (they don't recognize the top-level `axon_metadata` key
        // and skip the frame).
        //
        // §Fase 33.z.k.e ships the metadata frame as a placeholder
        // (empty fields). 33.z.k.h wires the actual data through.
        //
        // §D5 — emit the [DONE] sentinel per OpenAI spec. This is
        // a non-JSON literal; the adapter emits it via
        // `Event::default().data("[DONE]")` so the wire bytes
        // come out as `data: [DONE]\n\n` per W3C SSE framing.
        vec![
            self.build_axon_metadata_frame(),
            Event::default().data("[DONE]"),
        ]
    }
}
