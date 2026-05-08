//! Native Rust LLM backends — Fase 24.
//!
//! Per-provider async backends consumed by the algebraic-effects
//! runtime (Fase 23.f) and, in upcoming Fase 25+, the general flow
//! executor. Each provider lives in its own submodule:
//!
//!   * [`anthropic`]   — Claude Messages API (Fase 24.c)
//!   * [`openai`]      — GPT chat/completions (Fase 24.d)
//!   * [`gemini`]      — Google generateContent (Fase 24.e)
//!   * [`kimi`]        — Moonshot K2.x (Fase 24.f, locked params)
//!   * [`glm`]         — Zhipu GLM-4.x (Fase 24.g)
//!   * [`ollama`]      — local LLMs via REST (Fase 24.h)
//!   * [`openrouter`]  — multi-provider gateway (Fase 24.i)
//!
//! Shared infrastructure ships in 24.b alongside the trait + Registry:
//!
//!   * [`error`]            — typed transport errors named per failure mode
//!   * [`retry`]            — retry policy + `Retry-After` parsing
//!   * [`observability`]    — tracing span helpers per call lifecycle
//!   * [`locked_model`]     — locked-parameter dispatch (Kimi K2.x / o1 / o3)
//!   * [`tokens`]           — unified `count_tokens` dispatch by model prefix
//!
//! Adopter usage (post-24.k):
//!
//! ```ignore
//! use axon::backends::{Registry, ChatRequest, Message, Role};
//!
//! let registry = Registry::production();
//! let backend = registry.get("anthropic").expect("anthropic registered");
//!
//! let req = ChatRequest {
//!     model: "claude-sonnet-4-5".into(),
//!     messages: vec![Message::user("Hello!")],
//!     ..Default::default()
//! };
//! let response = backend.complete(req).await?;
//! println!("{}", response.content);
//! ```
//!
//! # Architecture decisions (see docs/fase_24_native_rust_backends.md)
//!
//! * **D1** — `async_trait` over native async-fn-in-trait so `dyn Backend`
//!   stays object-safe (Registry uses `HashMap<String, Box<dyn Backend>>`).
//! * **D6** — the legacy [`crate::backend`] module stays in place during
//!   24.b–24.i to avoid touching 200+ call sites; in 24.j it becomes a
//!   thin re-export shim that delegates here.
//! * **D7** — Python `axon/backends/*.py` is untouched; flows running on
//!   the Python runtime keep using it.

#![allow(dead_code)]

use std::collections::HashMap;
use std::pin::Pin;

use async_trait::async_trait;
use futures::Stream;

pub mod anthropic;
pub mod error;
pub mod gemini;
pub mod glm;
pub mod kimi;
pub mod locked_model;
pub mod observability;
pub mod ollama;
pub mod openai;
pub mod openai_compat;
pub mod openrouter;
pub mod retry;
pub mod tokens;
pub(crate) mod transport;

pub use anthropic::AnthropicBackend;
pub use error::{categorise_http, BackendError};
pub use gemini::GeminiBackend;
pub use glm::GLMBackend;
pub use kimi::KimiBackend;
pub use ollama::OllamaBackend;
pub use openai::OpenAIBackend;
pub use openai_compat::{OpenAICompatConfig, OpenAICompatibleBackend};
pub use openrouter::OpenRouterBackend;

// ────────────────────────────────────────────────────────────────────
//  Request / Response types — the wire shape every backend speaks
// ────────────────────────────────────────────────────────────────────

/// Role of a message in a chat conversation.
///
/// Mirrors the OpenAI ChatML enumeration with one provider-neutral
/// addition (`Tool`) used for tool-call result messages. Per-provider
/// adapters translate this enum to the wire encoding that provider
/// expects (e.g. Anthropic's `system` becomes a top-level field, not a
/// message; Gemini uses `user`/`model`/`function`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    System,
    User,
    Assistant,
    Tool,
}

impl Role {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::System => "system",
            Self::User => "user",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
        }
    }
}

/// One chat message in a conversation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Message {
    pub role: Role,
    pub content: String,
    /// Optional tool-call identifier when role == Tool. Per-provider
    /// adapters thread this back to the correct tool call ID.
    pub tool_call_id: Option<String>,
}

impl Message {
    pub fn user(content: impl Into<String>) -> Self {
        Self { role: Role::User, content: content.into(), tool_call_id: None }
    }
    pub fn assistant(content: impl Into<String>) -> Self {
        Self { role: Role::Assistant, content: content.into(), tool_call_id: None }
    }
    pub fn system(content: impl Into<String>) -> Self {
        Self { role: Role::System, content: content.into(), tool_call_id: None }
    }
}

/// A tool the model may invoke during the response.
///
/// `parameters_json` is the JSON Schema describing the parameter shape;
/// each provider serialises it with its own envelope.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolSpec {
    pub name: String,
    pub description: String,
    pub parameters_json: String,
}

/// Provider-feature discovery enum — used by [`Backend::supports`] so
/// adopters can ask "does this backend support X for this model?"
/// without parsing model strings themselves.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Capability {
    Streaming,
    ToolUse,
    Vision,
    /// Anthropic prompt caching (cache_control breakpoints).
    PromptCaching,
    /// Gemini safetySettings on the request body.
    SafetySettings,
    /// OpenAI structured outputs (response_format=json_schema).
    StructuredOutput,
    /// Provider hard-codes sampling parameters (Kimi K2.x, o1, o3).
    LockedParams,
}

/// One canonical chat request — provider-neutral. Per-provider adapters
/// translate to the wire JSON the provider expects.
#[derive(Debug, Clone, Default)]
pub struct ChatRequest {
    /// Empty string → backend uses its `default_model()`.
    pub model: String,
    pub messages: Vec<Message>,
    /// System prompt — Anthropic puts it in a top-level field; OpenAI &
    /// compats prepend a system message to the messages array.
    pub system: Option<String>,
    pub max_tokens: Option<u32>,
    /// Temperature; ignored when the resolved model is locked-params.
    pub temperature: Option<f64>,
    pub top_p: Option<f64>,
    pub tools: Vec<ToolSpec>,
    /// `false` → call `complete()`. `true` → call `stream()` and consume
    /// the chunk stream incrementally.
    pub stream: bool,
    /// Trace ID propagated from the calling flow step. Surfaces in
    /// tracing spans so log lines correlate.
    pub trace_id: Option<String>,
}

/// How the model decided to stop generating.
///
/// Maps the provider-specific finish-reason strings to a closed enum
/// callers can `match` on. Unmapped values land in `Other(s)` so the
/// raw string is still recoverable for diagnostics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FinishReason {
    /// Natural end of generation (Anthropic `end_turn`, OpenAI `stop`,
    /// Gemini `STOP`).
    Stop,
    /// Hit `max_tokens` budget (Anthropic `max_tokens`, OpenAI `length`,
    /// Gemini `MAX_TOKENS`).
    Length,
    /// Model invoked a tool (Anthropic `tool_use`, OpenAI `tool_calls`).
    ToolUse,
    /// Provider's content filter blocked output (OpenAI `content_filter`,
    /// Gemini `SAFETY`, Anthropic empty + `end_turn`).
    SafetyBreach,
    /// Anything else; carries the raw provider string.
    Other(String),
}

impl FinishReason {
    /// Map a raw provider string into the enum.
    pub fn from_provider(provider: &str, raw: &str) -> Self {
        let lc = raw.to_ascii_lowercase();
        match (provider, lc.as_str()) {
            ("anthropic", "end_turn") => Self::Stop,
            ("anthropic", "max_tokens") => Self::Length,
            ("anthropic", "tool_use") => Self::ToolUse,
            ("anthropic", "stop_sequence") => Self::Stop,
            (_, "stop") => Self::Stop,
            (_, "length") => Self::Length,
            (_, "tool_calls") | (_, "function_call") => Self::ToolUse,
            (_, "content_filter") => Self::SafetyBreach,
            // Gemini uses upper-case slugs.
            (_, "max_tokens") => Self::Length,
            (_, "safety") => Self::SafetyBreach,
            (_, "") => Self::Other(String::new()),
            _ => Self::Other(raw.to_string()),
        }
    }

    /// True iff this finish reason is the provider's safety classifier
    /// blocking output. Used by `BackendError::SafetyBreach` lifting.
    pub fn is_safety_breach(&self) -> bool {
        matches!(self, Self::SafetyBreach)
    }
}

/// Token-usage breakdown returned by the provider. Field naming is
/// canonical (input/output/total); per-provider deltas (cache reads on
/// Anthropic, reasoning tokens on o1/o3) live in dedicated fields so
/// aggregating dashboards across providers stay coherent.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Usage {
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub total_tokens: u32,
    /// Anthropic prompt-cache hit (`cache_read_input_tokens`).
    pub cache_read_tokens: u32,
    /// Anthropic prompt-cache write (`cache_creation_input_tokens`).
    pub cache_creation_tokens: u32,
    /// OpenAI o1/o3 reasoning-token allocation (`reasoning_tokens`).
    pub reasoning_tokens: u32,
}

/// A complete chat response from a non-streaming `complete()` call.
#[derive(Debug, Clone)]
pub struct ChatResponse {
    pub content: String,
    /// Resolved model slug — what the provider actually returned the
    /// response from (may differ from request when an alias was sent).
    pub model_name: String,
    /// Provider name (`"anthropic"`, `"openai"`, etc.).
    pub provider_name: String,
    pub finish_reason: FinishReason,
    pub usage: Usage,
    /// Number of retries that fired before this success. 0 on a clean
    /// first-attempt response.
    pub retry_count: u32,
    /// Trace ID echoed back from the request (or auto-generated if the
    /// request omitted one).
    pub trace_id: String,
}

/// One delta in a streaming response.
///
/// `delta` is the incremental text fragment for this chunk. `finish_reason`
/// + `usage` are populated only on the final chunk so consumers can
/// compute totals without keeping a running tally.
#[derive(Debug, Clone, Default)]
pub struct ChatChunk {
    pub delta: String,
    pub finish_reason: Option<FinishReason>,
    pub usage: Option<Usage>,
}

/// Pinned, boxed stream alias — the concrete return type of
/// [`Backend::stream`]. Adopters consume via `futures::StreamExt`.
pub type ChatStream =
    Pin<Box<dyn Stream<Item = Result<ChatChunk, BackendError>> + Send>>;

// ────────────────────────────────────────────────────────────────────
//  Backend trait — the per-provider contract
// ────────────────────────────────────────────────────────────────────

/// One LLM provider's native Rust client.
///
/// Implementors live in `axon-rs/src/backends/<provider>.rs` and are
/// registered into [`Registry`] at process startup. The trait is
/// object-safe (D1 — uses `async_trait`) so registries can hold
/// `Box<dyn Backend>` for runtime dispatch by name.
#[async_trait]
pub trait Backend: Send + Sync {
    /// Short provider name used as the registry key.
    /// E.g. `"anthropic"`, `"openai"`, `"kimi"`.
    fn name(&self) -> &str;

    /// Default model used when [`ChatRequest::model`] is empty.
    fn default_model(&self) -> &str;

    /// Synchronous-result chat completion (non-streaming).
    async fn complete(&self, request: ChatRequest) -> Result<ChatResponse, BackendError>;

    /// Streaming chat completion. Adopter consumes the returned stream;
    /// per-chunk text arrives in `ChatChunk::delta`, finish reason +
    /// usage in the final chunk.
    async fn stream(&self, request: ChatRequest) -> Result<ChatStream, BackendError>;

    /// Best-effort token count for `text` against a specific model on
    /// this provider. Default impl delegates to the unified
    /// [`tokens::count_tokens`] dispatch; per-provider overrides may
    /// consult the provider's HTTP `count_tokens` endpoint when an
    /// exact answer is required + a network round-trip is acceptable.
    fn count_tokens(&self, model: &str, text: &str) -> usize {
        tokens::count_tokens(model, text).count
    }

    /// Capability discovery — does this backend support `capability`
    /// for the given model? Default returns `false` for everything;
    /// per-provider impls override.
    #[allow(unused_variables)]
    fn supports(&self, capability: Capability, model: &str) -> bool {
        false
    }
}

// ────────────────────────────────────────────────────────────────────
//  Registry — string-keyed dispatch by provider name
// ────────────────────────────────────────────────────────────────────

/// Process-wide registry of registered backends.
///
/// Backends are registered by their canonical short name (the same
/// string the Python `BACKEND_REGISTRY` uses — verified by the
/// Fase 24.j drift gate). Lookup is `O(1)` HashMap.
pub struct Registry {
    backends: HashMap<String, Box<dyn Backend>>,
}

impl Registry {
    /// Empty registry — useful for tests that want to register only
    /// stub backends.
    pub fn empty() -> Self {
        Self { backends: HashMap::new() }
    }

    /// Production registry — populated with all 7 native backends.
    ///
    /// Every backend is constructed via its `from_env()` factory — i.e.
    /// API keys are read at registry-construction time from the
    /// per-provider env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
    /// `GEMINI_API_KEY`, `KIMI_API_KEY`, `GLM_API_KEY`, `OPENROUTER_API_KEY`,
    /// plus `OLLAMA_HOST` / `OLLAMA_API_KEY` for the local daemon).
    /// Backends whose env var is missing still construct successfully;
    /// the auth check fires on the first `complete()` call instead.
    ///
    /// The registry's `provider_names()` returns the sorted list of all
    /// 7 keys: `["anthropic", "gemini", "glm", "kimi", "ollama",
    /// "openai", "openrouter"]`. The Fase 24.j drift gate
    /// (`tests/test_fase24_backend_parity.py`) asserts this set
    /// matches Python's `BACKEND_REGISTRY` keys exactly.
    pub fn production() -> Self {
        let mut registry = Self::empty();
        registry.register(Box::new(anthropic::AnthropicBackend::from_env()));
        registry.register(Box::new(gemini::GeminiBackend::from_env()));
        registry.register(Box::new(glm::GLMBackend::from_env()));
        registry.register(Box::new(kimi::KimiBackend::from_env()));
        registry.register(Box::new(ollama::OllamaBackend::from_env()));
        registry.register(Box::new(openai::OpenAIBackend::from_env()));
        registry.register(Box::new(openrouter::OpenRouterBackend::from_env()));
        registry
    }

    /// Register `backend` under the key `backend.name()`. Replaces any
    /// existing entry with the same name (last-write-wins).
    pub fn register(&mut self, backend: Box<dyn Backend>) {
        self.backends.insert(backend.name().to_string(), backend);
    }

    /// Look up a backend by name. Returns `None` if not registered.
    pub fn get(&self, name: &str) -> Option<&dyn Backend> {
        self.backends.get(name).map(|b| b.as_ref())
    }

    /// All registered provider names, sorted alphabetically. Used by
    /// the cross-stack drift gate (Fase 24.j) to verify the Rust set
    /// equals the Python `BACKEND_REGISTRY` set.
    pub fn provider_names(&self) -> Vec<String> {
        let mut names: Vec<String> = self.backends.keys().cloned().collect();
        names.sort();
        names
    }

    pub fn len(&self) -> usize {
        self.backends.len()
    }

    pub fn is_empty(&self) -> bool {
        self.backends.is_empty()
    }
}

impl Default for Registry {
    fn default() -> Self {
        Self::production()
    }
}

// ────────────────────────────────────────────────────────────────────
//  Tests — trait + types + Registry
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use futures::StreamExt;

    /// Test-only stub that lets us exercise the Registry + trait without
    /// hitting a real provider.
    struct StubBackend {
        name: String,
    }

    #[async_trait]
    impl Backend for StubBackend {
        fn name(&self) -> &str {
            &self.name
        }
        fn default_model(&self) -> &str {
            "stub-model"
        }
        async fn complete(
            &self,
            _request: ChatRequest,
        ) -> Result<ChatResponse, BackendError> {
            Ok(ChatResponse {
                content: "stubbed".into(),
                model_name: "stub-model".into(),
                provider_name: self.name.clone(),
                finish_reason: FinishReason::Stop,
                usage: Usage::default(),
                retry_count: 0,
                trace_id: "stub".into(),
            })
        }
        async fn stream(
            &self,
            _request: ChatRequest,
        ) -> Result<ChatStream, BackendError> {
            let chunks = vec![
                Ok(ChatChunk { delta: "hi ".into(), ..Default::default() }),
                Ok(ChatChunk {
                    delta: "world".into(),
                    finish_reason: Some(FinishReason::Stop),
                    usage: Some(Usage { input_tokens: 1, output_tokens: 2, total_tokens: 3, ..Default::default() }),
                }),
            ];
            Ok(Box::pin(futures::stream::iter(chunks)))
        }
        fn supports(&self, capability: Capability, _model: &str) -> bool {
            matches!(capability, Capability::Streaming)
        }
    }

    fn stub(name: &str) -> Box<dyn Backend> {
        Box::new(StubBackend { name: name.to_string() })
    }

    #[test]
    fn role_round_trips_via_as_str() {
        for r in [Role::System, Role::User, Role::Assistant, Role::Tool] {
            assert!(!r.as_str().is_empty());
        }
        assert_eq!(Role::User.as_str(), "user");
    }

    #[test]
    fn message_helpers_set_role() {
        assert_eq!(Message::user("a").role, Role::User);
        assert_eq!(Message::assistant("b").role, Role::Assistant);
        assert_eq!(Message::system("c").role, Role::System);
    }

    #[test]
    fn chat_request_default_is_empty() {
        let r = ChatRequest::default();
        assert!(r.model.is_empty());
        assert!(r.messages.is_empty());
        assert!(r.tools.is_empty());
        assert!(!r.stream);
    }

    #[test]
    fn finish_reason_anthropic_mapping() {
        assert_eq!(FinishReason::from_provider("anthropic", "end_turn"), FinishReason::Stop);
        assert_eq!(FinishReason::from_provider("anthropic", "max_tokens"), FinishReason::Length);
        assert_eq!(FinishReason::from_provider("anthropic", "tool_use"), FinishReason::ToolUse);
        assert_eq!(FinishReason::from_provider("anthropic", "stop_sequence"), FinishReason::Stop);
    }

    #[test]
    fn finish_reason_openai_mapping() {
        assert_eq!(FinishReason::from_provider("openai", "stop"), FinishReason::Stop);
        assert_eq!(FinishReason::from_provider("openai", "length"), FinishReason::Length);
        assert_eq!(FinishReason::from_provider("openai", "tool_calls"), FinishReason::ToolUse);
        assert_eq!(FinishReason::from_provider("openai", "content_filter"), FinishReason::SafetyBreach);
    }

    #[test]
    fn finish_reason_gemini_mapping_uppercase() {
        // Gemini emits SAFETY / MAX_TOKENS / STOP — case-folded.
        assert_eq!(FinishReason::from_provider("gemini", "STOP"), FinishReason::Stop);
        assert_eq!(FinishReason::from_provider("gemini", "MAX_TOKENS"), FinishReason::Length);
        assert_eq!(FinishReason::from_provider("gemini", "SAFETY"), FinishReason::SafetyBreach);
    }

    #[test]
    fn finish_reason_unknown_preserves_raw() {
        let r = FinishReason::from_provider("openai", "weird_signal");
        assert_eq!(r, FinishReason::Other("weird_signal".into()));
    }

    #[test]
    fn finish_reason_safety_breach_predicate() {
        assert!(FinishReason::SafetyBreach.is_safety_breach());
        assert!(!FinishReason::Stop.is_safety_breach());
        assert!(!FinishReason::Other("anything".into()).is_safety_breach());
    }

    #[test]
    fn registry_empty_then_register() {
        let mut r = Registry::empty();
        assert_eq!(r.len(), 0);
        r.register(stub("anthropic"));
        assert_eq!(r.len(), 1);
        assert!(r.get("anthropic").is_some());
        assert!(r.get("openai").is_none());
    }

    #[test]
    fn registry_provider_names_sorted() {
        let mut r = Registry::empty();
        r.register(stub("openai"));
        r.register(stub("anthropic"));
        r.register(stub("gemini"));
        assert_eq!(
            r.provider_names(),
            vec!["anthropic".to_string(), "gemini".to_string(), "openai".to_string()]
        );
    }

    #[test]
    fn registry_replace_on_duplicate_register() {
        let mut r = Registry::empty();
        r.register(stub("anthropic"));
        r.register(stub("anthropic"));
        assert_eq!(r.len(), 1); // last-write-wins
    }

    #[tokio::test]
    async fn stub_complete_returns_response() {
        let b = StubBackend { name: "stub".into() };
        let resp = b.complete(ChatRequest::default()).await.unwrap();
        assert_eq!(resp.content, "stubbed");
        assert_eq!(resp.provider_name, "stub");
        assert_eq!(resp.finish_reason, FinishReason::Stop);
    }

    #[tokio::test]
    async fn stub_stream_yields_chunks() {
        let b = StubBackend { name: "stub".into() };
        let stream = b.stream(ChatRequest::default()).await.unwrap();
        let chunks: Vec<_> = stream.collect().await;
        assert_eq!(chunks.len(), 2);
        let first = chunks[0].as_ref().unwrap();
        assert_eq!(first.delta, "hi ");
        assert!(first.finish_reason.is_none());
        let last = chunks[1].as_ref().unwrap();
        assert_eq!(last.delta, "world");
        assert!(matches!(last.finish_reason, Some(FinishReason::Stop)));
        let usage = last.usage.as_ref().unwrap();
        assert_eq!(usage.total_tokens, 3);
    }

    #[tokio::test]
    async fn registry_dispatches_to_correct_backend() {
        let mut r = Registry::empty();
        r.register(stub("anthropic"));
        r.register(stub("openai"));
        let b = r.get("openai").expect("openai registered");
        let resp = b.complete(ChatRequest::default()).await.unwrap();
        assert_eq!(resp.provider_name, "openai");
    }

    #[test]
    fn supports_capability_default_false() {
        struct DefaultBackend;
        #[async_trait]
        impl Backend for DefaultBackend {
            fn name(&self) -> &str {
                "default"
            }
            fn default_model(&self) -> &str {
                ""
            }
            async fn complete(
                &self,
                _r: ChatRequest,
            ) -> Result<ChatResponse, BackendError> {
                unreachable!()
            }
            async fn stream(
                &self,
                _r: ChatRequest,
            ) -> Result<ChatStream, BackendError> {
                unreachable!()
            }
        }
        let b = DefaultBackend;
        assert!(!b.supports(Capability::Streaming, "anything"));
        assert!(!b.supports(Capability::ToolUse, "anything"));
    }

    #[test]
    fn count_tokens_default_uses_unified_dispatch() {
        let b = StubBackend { name: "stub".into() };
        // The stub doesn't override count_tokens, so the trait default
        // delegates to tokens::count_tokens — same model dispatch as
        // the standalone function.
        let n = b.count_tokens("gpt-4o-mini", "hello world");
        assert!(n > 0);
    }
}
