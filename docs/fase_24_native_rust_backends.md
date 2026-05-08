---
title: "Plan vivo: Fase 24 — Native Rust Backends (full migration de los 7 providers)"
status: DRAFTED 2026-05-08 — sub-fases 24.a–24.k pendientes; target axon-lang v1.18.0 cross-stack
owner: AXON Language Team
created: 2026-05-08
updated: 2026-05-08
target: axon-lang v1.18.0 (PyPI + crates.io)
depends_on: Fase 22 SHIPPED (Python backend coverage v1.16.0 + typed errors v1.16.1 + locked-model dispatch v1.16.2); Fase 23 SHIPPED (algebraic effects v1.17.0); existing axon-rs/src/backend.rs blocking impl + axon-rs/src/resilient_backend.rs + axon-rs/src/circuit_breaker.rs + axon-rs/src/retry_policy.rs
---

## ▶ Status snapshot (2026-05-08 — DRAFTED)

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 24.a Engineering spec | ✅ DONE 2026-05-08 | doc-only | — | Este doc + memory entries + decisiones D1–D10 ratificadas (D1/D6/D7/D8 founder explícito; D2/D3/D4/D5/D9/D10 implícito operacionales) |
| 24.b Shared infra — Backend trait + registry + error + retry + observability + locked_model + tokens | ✅ DONE 2026-05-08 | ~1900 effective | Rust | `axon-rs/src/backends/{mod,error,retry,observability,locked_model,tokens}.rs` + 3 deps añadidas (`regex`, `futures`, `tiktoken-rs`). Backend trait async via `async_trait` + Registry tipado + ChatRequest/ChatResponse/Usage/FinishReason/ChatChunk/Capability/Role/Message/ToolSpec types + per-provider FinishReason mapping (anthropic/openai/gemini case-folded). 77/77 tests verdes (target era ~30); 1169/1169 lib totales en axon-rs (0 regressions). Trait object-safe (D1) — Registry usa `Box<dyn Backend>`. error.rs: 5 typed variants (RateLimit/Auth/ContextLength/SafetyBreach/ModelNotFound) + Generic + `categorise_http()` mirror del Python `_categorise_http_error`. locked_model.rs: port literal del v1.16.2 registry (kimi-k2.x/o1/o3 regex patterns + apply_sampling_params). retry.rs: BackendRetryPolicy con DEFAULT_MAX_RETRIES=3, DEFAULT_MAX_BACKOFF=30s + parse_retry_after honoring integer-seconds form. observability.rs: tracing span helpers (call_span/stream_span + on_request_built/http_send/http_recv/retry_scheduled/parsed_response/complete/error). tokens.rs: count_tokens dispatch by prefix (gpt-4o/o1/o3 → o200k_base; gpt-/chatgpt-/kimi-/moonshot-/glm- → cl100k_base; claude-/gemini-/llama-/mistral- → 4-cpt estimate; openrouter:provider/model strip+recurse). |
| 24.c Anthropic backend (Claude Messages API) | ✅ DONE 2026-05-08 | ~1100 effective | Rust | `axon-rs/src/backends/anthropic.rs`. `AnthropicBackend` struct + builder API (`from_env`/`with_api_key`/`with_base_url`/`with_default_model`/`with_retry_policy`) + `Backend` trait impl async (complete + stream stub + count_tokens + supports). HTTP transport `call_with_retry` mirror del Python `_call_with_retry`: build_headers (x-api-key + anthropic-version 2023-06-01 + content-type) + retry on 429/408/5xx con BackendRetryPolicy + parse_retry_after honoring + categorise_http on fail-fast statuses + observability spans estructurados (request_built/http_send/http_recv/retry_scheduled/parsed_response/complete/error). Request body builder lifts system role messages al top-level `system` field (Anthropic-specific) + serialises ToolSpec → `{name, description, input_schema}` (Anthropic envelope) + Tool role messages → `tool_result` content blocks (Anthropic encoding). Response parser concatena multiple text blocks + extrae usage con cache_read_tokens / cache_creation_tokens (Anthropic prompt caching) + lifts safety-breach finish_reason a typed `BackendError::SafetyBreach`. Streaming surface explícita con `BackendError::Generic` "not yet implemented" (24.c.2 sub-followup) — born mature: no panic / no unimplemented!(). 34/34 tests verdes (target era ~25); 1203/1203 lib totales (0 regressions). |
| 24.d OpenAI-compat shared base + OpenAI backend | ✅ DONE 2026-05-08 | ~1700 effective | Rust | `axon-rs/src/backends/{transport,openai_compat,openai}.rs`. Refactored `transport::call_with_retry` extracted to its own module (single source of truth — anthropic.rs ahora delega aquí, dedup -150 LOC). `openai_compat.rs`: `OpenAICompatConfig` con 5 presets factory (openai/kimi/glm/ollama/openrouter) + `OpenAICompatibleBackend` struct con builder API + `Backend` trait async impl + body builder OpenAI-shape (system stays in messages array vs Anthropic top-level lift; OpenAI tool envelope `{type: "function", function: {name, description, parameters}}`; Tool role → `{role: "tool", content, tool_call_id}`; `apply_sampling_params` dispatch via `locked_model::` para strip de fields que kimi-k2.x/o1/o3 rejectan; max_tokens default 4096; `completion_tokens_details.reasoning_tokens` extraction para o1/o3); response parser `choices[0].message.content` + safety-breach lifting cuando `finish_reason=content_filter`. `openai.rs`: thin factory + capability override (Vision = true sólo para gpt-4o family; LockedParams via shared base). 51 nuevos tests verdes en openai_compat + openai (target era ~25); 162/162 tests `backends::*` totales; 1254/1254 lib totales (0 regressions). Streaming explícito con BackendError::Generic "not yet implemented" (24.d.2 followup) — born mature. |
| 24.e Gemini backend (generateContent) | ✅ DONE 2026-05-08 | ~1000 effective | Rust | `axon-rs/src/backends/gemini.rs`. `GeminiBackend` struct + builder API + `Backend` trait async impl. Wire shape distinta de Anthropic + OpenAI: API key en URL `?key=<KEY>` (NOT header) — security: `transport.rs` ahora acepta `display_url: Option<&str>` para redactar la key en tracing spans (`?key=REDACTED`); body builder con `systemInstruction.parts[].text` (top-level lift como Anthropic, pero parts envelope), `contents` array (NOT messages), roles `user`/`model`/`function` (assistant→model, tool→function); `generationConfig` con `topP` (camelCase), `maxOutputTokens` (NOT max_tokens); `tools: [{functionDeclarations: [...]}]` envelope (NOT OpenAI flat); Tool role → `functionResponse {name, response}` part (parses JSON content cuando es válido, wraps en `{content: <text>}` cuando no). Response parser `candidates[0].content.parts[*].text` (concat) + `usageMetadata.{promptTokenCount, candidatesTokenCount, totalTokenCount}` (NOT `usage` object) + `candidates[0].finishReason` UPPERCASE (STOP/MAX_TOKENS/SAFETY — case-folded por `FinishReason::from_provider`); `modelVersion` field preference for resolved model. Capabilities: SafetySettings=true (Gemini-only), Vision=true para 1.5/2.0/2.5 families, StructuredOutput=true, PromptCaching/LockedParams=false. 35 nuevos tests verdes (target era ~25); 197/197 backends:: totales; 1289/1289 lib totales (0 regressions). Streaming explícito con BackendError::Generic "not yet implemented" (24.e.2 followup) — born mature. |
| 24.f Kimi backend (Moonshot, K2.6 locked params) | ✅ DONE 2026-05-08 | ~330 effective | Rust | `axon-rs/src/backends/kimi.rs`. Thin factory + capability override sobre `OpenAICompatibleBackend` (preset `OpenAICompatConfig::kimi()`: base URL `https://api.moonshot.ai`, default model `moonshot-v1-8k`, env `KIMI_API_KEY`). Vision = false explicit (mainstream Kimi families son text-only — K2.x reasoning + moonshot-v1-* chat); LockedParams + Streaming + ToolUse + StructuredOutput delegate al base. **K2.x dispatch verificado**: tests confirm que `kimi-k2.6` y `kimi-k2.8` strip `temperature`/`top_p` en body; `moonshot-v1-*` chat models keep them. Esto cierra el incident Kivi v1.16.2 permanentemente en el Rust path. 19 nuevos tests verdes (target era ~20); 1308/1308 lib totales (0 regressions). |
| 24.g GLM backend (Zhipu, web_search opt-in) | ✅ DONE 2026-05-08 | ~310 effective | Rust | `axon-rs/src/backends/glm.rs`. Thin factory + capability override sobre `OpenAICompatibleBackend` (preset `OpenAICompatConfig::glm()`: base URL `https://open.bigmodel.cn/api/paas`, default model `glm-4-plus`, env `GLM_API_KEY`). Vision = true para `glm-4v*` family (multimodal), false para chat-only models (glm-4-plus, glm-4-air, glm-4-flash, glm-3-turbo). LockedParams = false (GLM no tiene locked-param families); sampling params pass through unchanged en todos los modelos GLM (verificado por test parametrized). Streaming/ToolUse/StructuredOutput delegate al base. `web_search` retrieval opt-in y `tools[].retrieval` envelope deferred a 24.g.2 followup si demand surfaces. 18 nuevos tests verdes (target era ~20); 1326/1326 lib totales (0 regressions). |
| 24.h Ollama backend (local) | ✅ DONE 2026-05-08 | ~400 effective | Rust | `axon-rs/src/backends/ollama.rs`. Thin factory + capability override sobre `OpenAICompatibleBackend` (preset `OpenAICompatConfig::ollama()`: base URL `http://localhost:11434`, default model `llama3.1:8b`, NO env var requerido). `from_env()` honors `OLLAMA_HOST` (base URL override estándar de Ollama) + `OLLAMA_API_KEY` (opcional, para proxies fronting el daemon); `local()` factory para el caso más común (no key, no host override). Vision = true para 6 multimodal families documentadas (case-insensitive substring match: llava, bakllava, llama3.2-vision/llama-3.2-vision, qwen2-vl, qwen2.5-vl, minicpm-v); Vision = false para text-only (llama3.1, mistral, qwen2.5, phi-4, deepseek-r1, gemma3). LockedParams = false. **Critical assertion**: complete() sin API key NO retorna Auth error (Ollama es local, sin auth) — verificado por test que confirma transport-layer Generic en lugar de Auth. ndjson streaming deferred a 24.h.2 followup (Ollama's native streaming surface es ndjson, no SSE — needs dedicated parser). 22 nuevos tests verdes (target era ~15, el extra cubre 6 multimodal families + 6 text-only models + case insensitivity + helper unit tests); 1348/1348 lib totales (0 regressions). |
| 24.i OpenRouter backend (multi-provider gateway) | ✅ DONE 2026-05-08 | ~520 effective | Rust | `axon-rs/src/backends/openrouter.rs` + extension a `locked_model.rs` (slug normalisation). Thin factory + slug-aware capability override sobre `OpenAICompatibleBackend` (preset `OpenAICompatConfig::openrouter()`: base URL `https://openrouter.ai/api`, default model `openai/gpt-4o-mini`, env `OPENROUTER_API_KEY`). **`locked_model.rs` extended**: nueva función privada `normalise(model)` strip-ea `provider/` prefix antes del pattern match — backward-compatible widening que permite `openai/o1-mini`/`moonshot/kimi-k2.6` matchear las regex existentes (`^o1`, `^kimi-k2\.`). 3 tests adicionales en locked_model verifican (a) slug form matchea correctamente, (b) NO causa spurious matches para chat slugs, (c) idempotencia para direct names. **Slug-aware Vision dispatch** — match per provider segment del slug: `openai/gpt-4o*`→true, `anthropic/claude-*`→true, `google/gemini-{1.5,2.0,2.5}*`→true, `meta-llama/llama-3.2-vision*` o `*llava*`→true, `qwen/*vl*`→true, `mistralai/pixtral*`→true, `microsoft/phi-{3.5,4}-vision`→true, `zhipu/glm-4v*`→true; otros→false. Provider list cubre 8 providers. **count_tokens slug-aware**: strip-ea `provider/` antes de delegar a `tokens::count_tokens` — `openai/gpt-4o-mini` obtiene exact `o200k_base` count en lugar del 4-cpt fallback. 34 nuevos tests en openrouter + 3 en locked_model = 37; 1385/1385 lib totales (0 regressions). |
| 24.j Cross-backend test pack + Python↔Rust drift gate (mono-file retirement deferred a 24.j.2) | ✅ DONE 2026-05-08 | ~580 effective | Rust + Python | **3 entregables**: (1) `Registry::production()` populado: ahora construye los 7 backends from_env() en lugar del stub vacío de 24.b. (2) `axon-rs/tests/fase24_backends_cross.rs` cross-backend integration (~20 LOC tests effective): construction sin panic en los 7, registry populates 7, default models pinned, capability matrix uniforme (Streaming/ToolUse universals; PromptCaching=Anthropic-only; SafetySettings=Gemini-only; StructuredOutput=6/7; LockedParams uniform via slug normalisation incluyendo OpenRouter), count_tokens reachable en los 7. (3) `tests/test_fase24_backend_parity.py` Python↔Rust drift gate (~25 LOC tests effective): provider count + name set match (canonical 7), per-provider env var pinning verified (excepto Ollama local), `_LOCKED_PARAMETER_MODELS` regex patterns + locked sets idénticos cross-stack (kimi-k2 = 6 params; o1 = o3 = 6 params), Rust module structure sanity (mod.rs pub uses todos, cada provider module impl Backend trait + surfaces canonical short name, locked_model.normalise existe, transport.display_url existe). 21+23 = 44 nuevos tests verdes; 1385/1385 lib Rust + 23 drift Python = 1429 totales (0 regressions). **Mono-file retirement DEFERRED a 24.j.2 followup**: el legacy `axon-rs/src/backend.rs` (1392 LOC blocking) tiene 4 caller files (axon_server.rs / runner.rs / tenant_secrets.rs / integration.rs) que requieren refactor a async — scope > 24.j budget. Documentado en plan vivo + memory; el retirement no bloquea v1.18.0 ship porque legacy + new infra cohabitan limpiamente (D6 dual presence). |
| 24.k Coordinated cross-stack release v1.18.0 | ⏳ NEXT | release | — | bump-my-version 1.17.0 → 1.18.0 (Python axon-lang + Rust axon-lang) + axon-frontend bump si aplica + commit + tag + push + cargo publish + PyPI publish + GitHub Release + drift gate verde |

**Acceptance metrics target:**

- **≥185 nuevos tests** distribuidos: ~30 infra + 25×3 (anthropic/openai/gemini) + 20×2 (kimi/glm) + 15×2 (ollama/openrouter) + 30 cross-backend = 195 ≈ 185+.
- **7/7 providers como módulos Rust async tipados**: anthropic, openai, gemini, kimi, glm, ollama, openrouter. Cada uno implementa el `Backend` trait + cada uno tiene su archivo dedicado + cada uno usa `reqwest` async + `tokio` (no más `reqwest::blocking`).
- **Feature parity con Python v1.16.2**: typed transport errors (RateLimitError, AuthError, ContextLengthError, SafetyBreachError, ModelNotFoundError) + retry policy (Retry-After + exponential backoff) + ModelResponse extended (model_name, provider_name, finish_reason, retry_count) + tracer observability + locked-model dispatch (kimi-k2.x, o1, o3 regex registry).
- **`tokens.rs` unificado**: una sola surface `count_tokens(model: &str, text: &str) -> usize` con dispatch por provider (tiktoken-rs base + per-provider overrides + HTTP fallback for Gemini).
- **Cross-stack drift gate**: `tests/test_fase24_backend_parity.py` verifica que cada backend del Python `BACKEND_REGISTRY` tiene contraparte Rust con el mismo nombre + arity + ambos soportan los mismos modelos (whitelist).
- **Mono-file retirement**: `axon-rs/src/backend.rs` deja de existir post-24.j; toda invocación va vía `axon-rs/src/backends/`.
- **Born mature**: cero `TODO` / `unimplemented!()` / `panic!("not yet")` en el código merged. Si una feature del Python no llega a 24.x, se documenta explícitamente en este plan vivo + se difiere a Fase 24.h-followup, no se mergea a medio camino.

## How to apply (post-SHIPPED)

Cuando el usuario, un adopter, o un colaborador menciona LLM backends, "providers nativos", "cuántos providers soporta axon", o "cómo se implementa anthropic/openai/etc en Rust" — la respuesta post-v1.18.0 es: cada provider vive en `axon-rs/src/backends/<provider>.rs` con un Backend trait async + observability tracing + locked-model dispatch + retry. La interface Python sigue idéntica para adopters (D8); el cambio es interno (refactor + Rust runtime). El paper-pure type-safe estado del arte queda como sub-product: cada error es un Result<T, BackendError>, no una exception untyped.

---

# FASE 24 — NATIVE RUST BACKENDS

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** axon-rs gana 7 backends LLM como módulos Rust tipados independientes (anthropic, openai, gemini, kimi, glm, ollama, openrouter), full async via reqwest+tokio, con feature parity completa con la implementación Python v1.16.2 (typed transport errors + retry policy + locked-model dispatch + observability tracing). Mono-file `axon-rs/src/backend.rs` se retira.
- **Why:** alinea con D6 (Rust runtime) y founder vision long-term Rust+C; el ROI principal es type-safety + observability automática vía `tracing` crate + tokio concurrency más limpia que asyncio Python; Kivi (único adopter) está pre-launch sin usuarios reales así que la ventana de cambio cross-stack está abierta.
- **OSS / ENTERPRISE / SPLIT split:** **100% OSS.** Backends son fundacionales del runtime, no feature enterprise.
- **Robustness target:** cada backend pasa una smoke test contra el provider real (creds-gated `pytest.skip`); cada error de transport es typed (RateLimitError / AuthError / ContextLengthError / SafetyBreachError / ModelNotFoundError); el retry policy honra Retry-After + exponential backoff; el locked-model dispatch (de v1.16.2) está portado y enforza la omisión correcta de sampling params para kimi-k2.x / o1 / o3 families; tracing spans cubren cada call (start, request, response, retry, finish, error).

---

## 2. Audit findings — qué tenemos y qué falta

### 2.1 Python side (post-Fase 22, v1.16.2 SHIPPED)

| Componente | LOC | Status |
|---|---|---|
| `axon/backends/_openai_compatible.py` | 472 | ✅ shared base, locked-model dispatch, sampling param omission |
| `axon/backends/anthropic_backend.py` | 613 | ✅ full impl (Claude Messages API + system + prompt caching) |
| `axon/backends/gemini_backend.py` | 619 | ✅ full impl (generateContent + safetySettings) |
| `axon/backends/openai_backend.py` | 39 | ✅ thin subclass de `_openai_compat` |
| `axon/backends/kimi_backend.py` | 37 | ✅ thin subclass de `_openai_compat` |
| `axon/backends/glm_backend.py` | 41 | ✅ thin subclass de `_openai_compat` |
| `axon/backends/ollama_backend.py` | 46 | ✅ thin subclass de `_openai_compat` |
| `axon/backends/openrouter_backend.py` | 47 | ✅ thin subclass de `_openai_compat` |

### 2.2 Rust side (current state, pre-Fase-24)

| Componente | LOC | Status |
|---|---|---|
| `axon-rs/src/backend.rs` | 1392 | ⚠️ **mono-file**, blocking reqwest, 7 providers en 3 API families, sin typed errors enriched, sin locked-model dispatch, sin tracing spans |
| `axon-rs/src/backend_error.rs` | 153 | ⚠️ error enum básico, falta el dual con `runtime_errors.py` v1.16.1 (RateLimitError, AuthError, ContextLengthError, SafetyBreachError, ModelNotFoundError nombrados) |
| `axon-rs/src/resilient_backend.rs` | 441 | ✅ wrapper con circuit breaker + retry + fallback chain |
| `axon-rs/src/circuit_breaker.rs` | 309 | ✅ CB pattern por (tenant_id, provider) |
| `axon-rs/src/retry_policy.rs` | 180 | ✅ exponential backoff with jitter |
| `axon-rs/src/backends/` | 0 | ❌ no existe; target del refactor |
| `axon-rs/src/backends/tokens.rs` | 0 | ❌ no existe en ningún lado (Python tampoco tiene módulo unificado de tokenizers) |

### 2.3 Brecha = Fase 24

1. **Refactor estructural**: mono-file → per-provider files con `Backend` trait común.
2. **Async migration**: `reqwest::blocking` → `reqwest` async + tokio (consistente con resto de axon-rs).
3. **Feature port v1.16.1/v1.16.2**: typed errors named + locked-model dispatch + sampling param omission + ModelResponse fields enriched + tracer observability spans.
4. **Tokens unification**: nuevo `tokens.rs` con dispatch por provider — primer módulo de su tipo cross-stack.
5. **Drift gate**: Python BACKEND_REGISTRY ≡ Rust registry keys (parity verificable).
6. **Retirement del mono-file**: post-migración el `backend.rs` viejo se elimina.

---

## 3. Architecture — el diseño operacional

### 3.1 Module layout

```
axon-rs/src/backends/
├── mod.rs                 # Backend trait + Registry + ChatRequest/ChatResponse types
├── error.rs               # BackendError enum with named variants (RateLimit, Auth, ContextLength, Safety, ModelNotFound, Generic)
├── retry.rs               # RetryPolicy + retry-after parsing + exponential backoff
├── observability.rs       # tracing span helpers per call (start/request/response/retry/finish/error)
├── locked_model.rs        # _LOCKED_PARAMETER_MODELS registry + apply_sampling_params
├── tokens.rs              # count_tokens dispatch per provider
├── _openai_compat.rs      # OpenAICompatibleBackend shared base
├── anthropic.rs           # Claude Messages API
├── openai.rs              # GPT chat/completions (subclass de _openai_compat with o1/o3 locked params)
├── gemini.rs              # Google generateContent
├── kimi.rs                # Moonshot (subclass de _openai_compat, kimi-k2.x locked)
├── glm.rs                 # Zhipu (subclass de _openai_compat)
├── ollama.rs              # Local LLM (subclass de _openai_compat with custom base_url + ndjson stream)
└── openrouter.rs          # Multi-provider gateway (subclass de _openai_compat, pass-through model names)
```

### 3.2 Backend trait

```rust
#[async_trait::async_trait]
pub trait Backend: Send + Sync {
    /// Provider name ("anthropic", "openai", "gemini", "kimi", "glm", "ollama", "openrouter").
    fn name(&self) -> &str;

    /// Default model for this provider (used when ChatRequest.model is empty).
    fn default_model(&self) -> &str;

    /// Synchronous-result chat completion. Streams are exposed via `stream()`.
    async fn complete(&self, request: ChatRequest) -> Result<ChatResponse, BackendError>;

    /// Streaming chat completion. Returns a stream of `ChatChunk`s.
    async fn stream(
        &self,
        request: ChatRequest,
    ) -> Result<Pin<Box<dyn Stream<Item = Result<ChatChunk, BackendError>> + Send>>, BackendError>;

    /// Token count for a piece of text against a specific model on this provider.
    fn count_tokens(&self, model: &str, text: &str) -> usize;

    /// Capability discovery — does this backend support feature X for the given model?
    fn supports(&self, capability: Capability, model: &str) -> bool;
}

pub enum Capability {
    Streaming,
    ToolUse,
    Vision,
    PromptCaching,    // Anthropic
    SafetySettings,   // Gemini
    StructuredOutput, // OpenAI
    LockedParams,     // Kimi K2.x, o1, o3
}
```

### 3.3 Request/Response types

```rust
pub struct ChatRequest {
    pub model: String,                       // empty => use default_model()
    pub messages: Vec<Message>,
    pub system: Option<String>,
    pub max_tokens: Option<u32>,
    pub temperature: Option<f64>,
    pub top_p: Option<f64>,
    pub tools: Vec<ToolSpec>,
    pub stream: bool,
    pub trace_id: Option<String>,
}

pub struct ChatResponse {
    pub content: String,
    pub model_name: String,           // resolved model (e.g., "claude-sonnet-4-20250514")
    pub provider_name: String,        // "anthropic", "openai", etc.
    pub finish_reason: FinishReason,  // Stop / Length / ToolUse / SafetyBreach / Other
    pub usage: Usage,
    pub retry_count: u32,
    pub trace_id: String,
}

pub enum FinishReason {
    Stop,
    Length,
    ToolUse,
    SafetyBreach,
    Other(String),
}

pub struct Usage {
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub total_tokens: u32,
    pub cache_read_tokens: u32,    // Anthropic prompt caching
    pub cache_creation_tokens: u32,
}
```

### 3.4 Observability — tracing spans per call

Cada `complete` / `stream` invocation crea un span estructurado:

```
backend.complete(provider="anthropic", model="claude-sonnet-4-20250514", trace_id="...")
  ├─ event: request_built (max_tokens, temperature, n_messages, n_tools)
  ├─ event: http_send (url, body_size_bytes)
  ├─ event: http_recv (status_code, body_size_bytes, duration_ms)
  ├─ event: retry_scheduled (attempt, after_ms, reason="429"|"503")  [if retry]
  ├─ event: parsed_response (input_tokens, output_tokens, finish_reason)
  └─ event: complete (total_duration_ms, retry_count, success=true)
```

Spans se emiten via la `tracing` crate (ya dep de axon-rs). Los adopters pueden subscribir a estos spans con `tracing-subscriber` o exportarlos a OpenTelemetry / Jaeger.

---

## 4. Sub-fases & schedule

| Sub-phase | Description | Stack | Depends on | Deliverable |
|---|---|---|---|---|
| 24.a | Engineering spec (este doc + memory) | — | Fase 23 SHIPPED | spec ratificada |
| 24.b | Shared infra (`mod.rs` + `error.rs` + `retry.rs` + `observability.rs` + `locked_model.rs` + `tokens.rs`) + Backend trait | Rust | 24.a | `axon-rs/src/backends/` skeleton + 30 tests |
| 24.c | `anthropic.rs` (Claude Messages API) | Rust | 24.b | Anthropic backend full async + 25 tests |
| 24.d | `_openai_compat.rs` shared base + `openai.rs` (con o1/o3 locked) | Rust | 24.b | Compat base + OpenAI backend + 25 tests |
| 24.e | `gemini.rs` (generateContent) | Rust | 24.b | Gemini backend + 25 tests |
| 24.f | `kimi.rs` (Moonshot, K2.6 locked params) | Rust | 24.d | Kimi subclass + 20 tests |
| 24.g | `glm.rs` (Zhipu) | Rust | 24.d | GLM subclass + 20 tests |
| 24.h | `ollama.rs` (local, ndjson streaming) | Rust | 24.d | Ollama subclass + 15 tests |
| 24.i | `openrouter.rs` (multi-provider gateway) | Rust | 24.d | OpenRouter subclass + 15 tests |
| 24.j | Cross-backend test pack + drift gate (Python↔Rust parity) + retire `backend.rs` mono-file | Rust + Python | 24.c–24.i all done | 30 cross-backend tests + drift gate green + mono-file deleted |
| 24.k | Coordinated cross-stack release v1.18.0 | release | 24.j | bump 1.17.0 → 1.18.0 + tag + push + cargo publish + PyPI publish |

**Classification**: 100% OSS.

**Parallelisability**: 24.b es prerequisito hard. 24.c puede ir en paralelo con 24.d (independientes). 24.f/g/h/i todas dependen de 24.d (`_openai_compat`) pero entre sí son independientes — pueden ir en paralelo si hay tiempo. 24.e (Gemini) es independiente del compat base.

**Cadencia calendario sugerida** (3-5 días focused):

```
Día 1: 24.a (1 hora) + 24.b (4-5 horas) + 24.c arranca (2-3 horas)
Día 2: 24.c termina + 24.d (compat base + OpenAI, 6-8 horas)
Día 3: 24.e Gemini + 24.f Kimi + 24.g GLM (paralelos donde aplique)
Día 4: 24.h Ollama + 24.i OpenRouter + 24.j cross-backend + drift gate
Día 5: 24.k release v1.18.0
```

---

## 5. Decisions (D1–D10)

**D1 — async_trait vs native async-fn-in-trait** ✅ **RATIFIED 2026-05-08 by founder**

Rust 1.75+ soporta async fn nativos en traits, pero pierden object-safety (no se pueden usar `dyn Trait`). Para el `Registry: HashMap<String, Box<dyn Backend>>` necesitamos object-safety. **Decision: usar `async_trait`** (already a dep de axon-rs). Trade-off: una box-allocation por call (negligible vs latencia de LLM ~1-30s).

**D2 — Streaming abstraction**

Un `Stream<Item = Result<ChatChunk, BackendError>>` por call; cada provider implementa internamente: SSE para anthropic/openai/kimi/glm/openrouter, ndjson para ollama, custom para gemini. Surface adopter: idéntica.

**D3 — Token counting dispatch**

`tokens.rs` exporta un `count_tokens(model: &str, text: &str) -> usize` con dispatch por prefix:
- `claude-*` → claude-tokenizer-rs (offline)
- `gpt-*` / `o1-*` / `o3-*` → tiktoken-rs (offline)
- `gemini-*` → HTTP `count_tokens` API (online, async)
- `kimi-*` / `moonshot-*` → tiktoken-rs (compatible)
- `glm-*` → tiktoken-rs (compatible)
- `llama-*` / `mistral-*` (Ollama) → server-side tokenize endpoint
- `openrouter:*` → strip prefix + recurse

**Trade-off**: Gemini necesita HTTP call (no hay tokenizer offline disponible). Para evitar bloquear `count_tokens()` (sync function), Gemini hace estimate offline (~4 chars per token) + un async warmup que actualiza un cache; el primer call usa el estimate, los siguientes usan el valor exacto.

**D4 — Locked-model dispatch port**

El registry `_LOCKED_PARAMETER_MODELS` de Python (kimi-k2.x, o1, o3 regex patterns → frozenset de locked params) se porta literalmente a `locked_model.rs` con `static LOCKED_PARAMS: Lazy<HashMap<&str, HashSet<&str>>>` + `is_locked(model: &str, param: &str) -> bool`. La función `apply_sampling_params` filtra el body antes de send según el modelo.

**Drift gate**: un test en `tests/test_fase24_locked_model_parity.py` verifica que el registry Rust ≡ Python.

**D5 — Tracing span structure**

Spans estructurados con campos tipados (no f-strings) — `tracing::span!(Level::INFO, "backend.complete", provider, model, trace_id, ...)`. Cada event dentro del span usa `tracing::event!` con campos. Esto permite extracción JSON sin parsing.

**D6 — Backward compat con `axon-rs/src/backend.rs` durante transición** ✅ **RATIFIED 2026-05-08 by founder**

24.j retira el mono-file. Pero durante 24.b–24.i hay dual presence. Los call sites existentes en axon-rs (varios — `runner.rs`, `axon_server.rs`, etc) siguen llamando al `backend::call(...)` viejo. Estrategia: **el mono-file se mantiene unchanged hasta 24.j**, momento en el cual se sustituye con un thin re-export shim que delega al nuevo `backends::Registry` + se borra eventualmente. Esto evita tocar 200+ call sites en cada sub-fase.

**D7 — Python side untouched** ✅ **RATIFIED 2026-05-08 by founder**

Fase 24 NO toca el código Python en `axon/backends/`. La Python implementation sigue siendo la production runtime para flows axon ejecutados desde el Python runtime. Los Rust backends son consumidos por:
- el algebraic effects runtime (Fase 23.f) cuando ejecuta perform sites de tipo "LLM call"
- el axon-rs CLI directo (`axon run` / `axon repl` / `axon chat` cuando arranquen)
- futuros runtime paths (Fase 25+ — Rust general flow executor)

Esto preserva D8 backward compat para adopters: el `.axon` source no cambia, el comportamiento del Python runtime no cambia.

**D8 — Drift gate Python ↔ Rust** ✅ **RATIFIED 2026-05-08 by founder**

Test en `tests/test_fase24_backend_parity.py` itera el `axon.backends.BACKEND_REGISTRY` y verifica:
- cada nombre tiene contraparte Rust en el axon-rs registry (parsing de `backends/mod.rs`)
- cada modelo soportado en Python aparece como soportado en Rust
- los `locked_models` regex patterns son idénticos

Falla CI si alguien añade un backend en un solo lado.

**D9 — Streaming chunk shape canonical**

```rust
pub struct ChatChunk {
    pub delta: String,           // incremental text
    pub finish_reason: Option<FinishReason>,
    pub usage: Option<Usage>,    // populated only on the last chunk
}
```

Adopters que consumen un stream lo iteran asincrónicamente; el último chunk lleva `finish_reason` + `usage`.

**D10 — `tokens.rs` first-class as standalone library**

`tokens.rs` se diseña para ser publicable como crate independiente (`axon-tokens` 0.x.0) en el futuro — adopters no-axon que necesiten count_tokens dispatch unificado se beneficiarían. Para 24.b vive dentro de `axon-rs/src/backends/` pero con interfaces estables (no usa tipos privados de axon-rs).

---

## 6. Tests target — ≥185 nuevos

| Suite | Path | Tests | Coverage |
|---|---|---|---|
| Shared infra | `axon-rs/src/backends/{mod,error,retry,observability,locked_model,tokens}.rs::tests` | ~30 | Backend trait object-safety, error variants, retry policy backoff, locked-model dispatch, tokens dispatch per prefix |
| Anthropic | `axon-rs/tests/backends/anthropic_test.rs` | ~25 | Messages API + system + prompt caching + headers + retry on 429 + safety breach finish reason + smoke test (creds-gated) |
| OpenAI | `axon-rs/tests/backends/openai_test.rs` | ~25 | chat/completions + tools + o1/o3 locked params + streaming SSE + smoke test |
| Gemini | `axon-rs/tests/backends/gemini_test.rs` | ~25 | generateContent + safetySettings + URL-key auth + count_tokens HTTP + smoke test |
| Kimi | `axon-rs/tests/backends/kimi_test.rs` | ~20 | _openai_compat subclass + K2.6 locked param verification (Moonshot docs spec) + smoke test |
| GLM | `axon-rs/tests/backends/glm_test.rs` | ~20 | _openai_compat subclass + web_search opt-in + smoke test |
| Ollama | `axon-rs/tests/backends/ollama_test.rs` | ~15 | _openai_compat subclass + ndjson streaming + custom base_url + local-only smoke (ollama serve) |
| OpenRouter | `axon-rs/tests/backends/openrouter_test.rs` | ~15 | _openai_compat subclass + model name pass-through + smoke test |
| Cross-backend | `axon-rs/tests/backends/cross_test.rs` + `tests/test_fase24_backend_parity.py` | ~30 | Registry symmetry + drift gate + usage field shape + finish_reason mapping per provider |

**Total**: ~205 nuevos. Smoke tests gated `#[ignore]` + `cargo test -- --ignored` for live integration; CI runs only the offline suite.

---

## 7. Out of scope (Fase 25+)

- Flow executor en Rust (consumidor full de los Backend trait — actualmente solo el algebraic effects runtime los consume).
- Token cost ledger persistido en axonstore (parte de Fase 22.i deferred).
- Streaming-to-WebSocket bridge para axon-server (consumirá el `Stream<ChatChunk>` shipped aquí).
- Provider-specific advanced features que no están en Python actualmente (function calling structured outputs avanzados, vision multi-modal, batch APIs, fine-tune endpoints).

---

## 8. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Gemini count_tokens HTTP latency en sync path | Medium | Adopter UX hiccup | Estimate offline + async warmup cache (D3) |
| Provider quirks no anticipados (header diffs, body schema drift) | High | Per-provider tests rojos | Smoke tests creds-gated por provider; capturan early |
| `async_trait` perf overhead (heap allocation per call) | Low | Negligible | LLM calls son 1-30s; box-alloc es <1µs |
| Rust → Python drift en BACKEND_REGISTRY | Medium | CI rojo | Drift gate test en 24.j |
| Mono-file `backend.rs` retirement breaks 200+ call sites | High | Compile failure | D6 — diferir retirement a 24.j; introducir thin shim primero |
| Ollama ndjson streaming distinto a SSE | Low | Custom code | Streaming abstraction (D2) absorbe el diff per-provider |

---

## 9. Cómo fue motivada

El usuario pidió 2026-05-08 migrar los 7 backends LLM completamente a Rust: "quiero migrar completamente los backends a Rust 100%, Implementar src/backends/anthropic.rs, src/backends/openai.rs, src/kimi.rs, src/glm.rs, así todos los 7 backends nativos usando reqwest y tokio". Justificación founder: alinea con D6 + long-term Rust+C destiny + Kivi (único adopter) está pre-launch así que la ventana cross-stack está abierta. La fase también captura la oportunidad de portar las features v1.16.1/v1.16.2 (typed errors named + locked-model dispatch) que actualmente solo viven en Python.

---

## 10. Next operational step

Ratificación del founder sobre las decisiones D1–D10 (especialmente D1 async_trait, D6 mono-file dual presence, D7 Python untouched, D8 drift gate). Cuando estén ratificadas → arrancar 24.b (shared infra). Estimado calendario total: 3-5 días focused desde 24.b hasta v1.18.0 publicado.
