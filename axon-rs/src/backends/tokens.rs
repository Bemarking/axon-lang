//! Unified token-counting surface for native Rust LLM backends — Fase 24.b.
//!
//! Provides a single `count_tokens(model, text) -> usize` entry point that
//! dispatches by model-name prefix to the right per-provider tokenizer:
//!
//!   * `gpt-*`, `o1-*`, `o3-*`, `chatgpt-*`              → `tiktoken-rs` (offline)
//!   * `kimi-*`, `moonshot-*`                            → `tiktoken-rs` (cl100k_base; OpenAI-compat tokenizers)
//!   * `glm-*`                                            → `tiktoken-rs` (cl100k_base; OpenAI-compat tokenizers)
//!   * `claude-*`                                        → 4-chars-per-token offline estimate
//!   * `gemini-*`                                        → 4-chars-per-token offline estimate
//!   * `llama-*`, `mistral-*`, `qwen-*`, `phi-*`         → 4-chars-per-token offline estimate
//!   * `openrouter:<provider>/<model>`                   → strip prefix + recurse
//!   * unknown / unmapped                                → 4-chars-per-token offline estimate
//!
//! The estimate fallback is intentionally conservative — for accurate
//! counts on Claude / Gemini / Ollama models, callers can use the
//! provider's HTTP `count_tokens` endpoint via the per-backend
//! `Backend::count_tokens` override (when a network round-trip is
//! acceptable). For sync callers (the trait method is `fn`, not
//! `async fn`), this module gives a deterministic offline answer.
//!
//! # Design intent (D10)
//!
//! `tokens.rs` is designed to be extractable as a standalone crate
//! (`axon-tokens` 0.x.0) in the future — the public surface
//! (`count_tokens`, `Tokenizer` enum, the model-prefix routing) does
//! not depend on any axon-internal types.

use std::sync::OnceLock;

use tiktoken_rs::CoreBPE;

/// Result kind from `count_tokens` — useful for callers that want to
/// distinguish "exact" tokenizer counts from approximate estimates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CountKind {
    /// Counted by an exact tokenizer (BPE / SentencePiece) for this model
    /// family. Within ~1% of what the provider charges.
    Exact,
    /// Approximated as `text.chars().count() / 4`. Useful for budgeting
    /// and rough cost estimates; not authoritative.
    Estimate,
}

/// Unified token count.
///
/// `count` is the integer token count; `kind` reports whether it came
/// from a real tokenizer or the fallback estimator.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TokenCount {
    pub count: usize,
    pub kind: CountKind,
}

impl TokenCount {
    pub const fn exact(count: usize) -> Self {
        Self { count, kind: CountKind::Exact }
    }
    pub const fn estimate(count: usize) -> Self {
        Self { count, kind: CountKind::Estimate }
    }
}

/// Shared `cl100k_base` BPE handle — the OpenAI-family tokenizer.
/// Construction is non-trivial (loads the BPE table); cache it once
/// per process.
fn cl100k_base() -> Option<&'static CoreBPE> {
    static CACHE: OnceLock<Option<CoreBPE>> = OnceLock::new();
    CACHE.get_or_init(|| tiktoken_rs::cl100k_base().ok()).as_ref()
}

/// Shared `o200k_base` BPE handle — newer OpenAI tokenizer used by gpt-4o,
/// o1, o3 families.
fn o200k_base() -> Option<&'static CoreBPE> {
    static CACHE: OnceLock<Option<CoreBPE>> = OnceLock::new();
    CACHE.get_or_init(|| tiktoken_rs::o200k_base().ok()).as_ref()
}

/// Count tokens in `text` for the supplied `model`.
///
/// `model` is matched by prefix to determine the tokenizer family. See
/// the module-level docs for the dispatch table. Unknown model slugs
/// fall back to a 4-chars-per-token offline estimate.
pub fn count_tokens(model: &str, text: &str) -> TokenCount {
    let model_lc = model.to_lowercase();

    // OpenRouter prefix: strip `openrouter:<provider>/` and recurse on
    // the underlying model slug. E.g. `openrouter:openai/gpt-4o-mini`
    // → `gpt-4o-mini` → o200k_base.
    if let Some(rest) = model_lc.strip_prefix("openrouter:") {
        if let Some((_provider, model_only)) = rest.split_once('/') {
            return count_tokens(model_only, text);
        }
        return count_tokens(rest, text);
    }

    // OpenAI o-family + gpt-4o use the o200k_base tokenizer.
    if model_lc.starts_with("o1") || model_lc.starts_with("o3") || model_lc.starts_with("gpt-4o") {
        if let Some(bpe) = o200k_base() {
            return TokenCount::exact(bpe.encode_with_special_tokens(text).len());
        }
    }

    // OpenAI-family (gpt-3.5, gpt-4, gpt-4-turbo, chatgpt-*) + Kimi +
    // GLM all share the cl100k_base BPE table (or a compatible variant).
    // tiktoken-rs is best-effort exact; if the BPE handle fails to load
    // we degrade gracefully to the estimator.
    if model_lc.starts_with("gpt-")
        || model_lc.starts_with("chatgpt-")
        || model_lc.starts_with("kimi-")
        || model_lc.starts_with("moonshot-")
        || model_lc.starts_with("glm-")
    {
        if let Some(bpe) = cl100k_base() {
            return TokenCount::exact(bpe.encode_with_special_tokens(text).len());
        }
    }

    // Anthropic, Gemini, Ollama, and unknown prefixes use the 4-cpt
    // offline estimate. Per-backend `count_tokens` overrides can call
    // the provider's HTTP `count_tokens` endpoint when an exact answer
    // is required + a network round-trip is acceptable.
    estimate(text)
}

/// Compute the offline 4-chars-per-token estimate. Public so per-backend
/// overrides can invoke it as their fallback path.
pub fn estimate(text: &str) -> TokenCount {
    let chars = text.chars().count();
    // Round up: 5 chars → 2 tokens, not 1. Errs on the side of
    // overestimating budget rather than underestimating.
    let count = chars.div_ceil(4);
    TokenCount::estimate(count)
}

// ────────────────────────────────────────────────────────────────────
//  Tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_text_is_zero_tokens() {
        let r = count_tokens("gpt-4o-mini", "");
        assert_eq!(r.count, 0);
    }

    #[test]
    fn empty_text_estimate_is_zero() {
        let r = estimate("");
        assert_eq!(r.count, 0);
        assert_eq!(r.kind, CountKind::Estimate);
    }

    #[test]
    fn estimate_rounds_up() {
        // 5 chars → ceil(5/4) = 2 tokens.
        assert_eq!(estimate("hello").count, 2);
        // 4 chars → exactly 1 token.
        assert_eq!(estimate("ABCD").count, 1);
        // 8 chars → 2 tokens.
        assert_eq!(estimate("ABCDEFGH").count, 2);
        // 9 chars → ceil(9/4) = 3 tokens.
        assert_eq!(estimate("ABCDEFGHI").count, 3);
    }

    #[test]
    fn anthropic_uses_estimate() {
        let r = count_tokens("claude-sonnet-4-5", "hello world this is a test");
        assert_eq!(r.kind, CountKind::Estimate);
    }

    #[test]
    fn gemini_uses_estimate() {
        let r = count_tokens("gemini-2.5-pro", "hello world this is a test");
        assert_eq!(r.kind, CountKind::Estimate);
    }

    #[test]
    fn unknown_model_uses_estimate() {
        let r = count_tokens("totally-fake-model-7b", "hello world");
        assert_eq!(r.kind, CountKind::Estimate);
    }

    #[test]
    fn ollama_local_models_use_estimate() {
        for model in &["llama-3.1-70b", "mistral-7b", "qwen-2.5-7b", "phi-4"] {
            let r = count_tokens(model, "hello world");
            assert_eq!(
                r.kind, CountKind::Estimate,
                "model {model} unexpected kind {r:?}"
            );
        }
    }

    #[test]
    fn gpt_4o_uses_o200k_exact() {
        let r = count_tokens("gpt-4o-mini", "hello world");
        assert_eq!(r.kind, CountKind::Exact);
        // Exact count for "hello world" via o200k is 2 tokens; sanity-
        // check it's small + nonzero.
        assert!(r.count >= 1);
        assert!(r.count <= 5);
    }

    #[test]
    fn gpt_3_5_turbo_uses_cl100k_exact() {
        let r = count_tokens("gpt-3.5-turbo", "hello world");
        assert_eq!(r.kind, CountKind::Exact);
    }

    #[test]
    fn o1_and_o3_use_o200k_exact() {
        let a = count_tokens("o1-mini", "hello world");
        let b = count_tokens("o3-mini", "hello world");
        assert_eq!(a.kind, CountKind::Exact);
        assert_eq!(b.kind, CountKind::Exact);
        // Same text, same tokenizer → same count.
        assert_eq!(a.count, b.count);
    }

    #[test]
    fn kimi_and_glm_use_cl100k_exact() {
        let a = count_tokens("kimi-k2.6", "hello world");
        let b = count_tokens("glm-4-plus", "hello world");
        assert_eq!(a.kind, CountKind::Exact);
        assert_eq!(b.kind, CountKind::Exact);
    }

    #[test]
    fn moonshot_alias_uses_cl100k_exact() {
        let r = count_tokens("moonshot-v1-8k", "hello world");
        assert_eq!(r.kind, CountKind::Exact);
    }

    #[test]
    fn openrouter_strips_prefix_and_recurses() {
        // openrouter:openai/gpt-4o-mini → gpt-4o-mini → o200k_base
        let r = count_tokens("openrouter:openai/gpt-4o-mini", "hello world");
        assert_eq!(r.kind, CountKind::Exact);
    }

    #[test]
    fn openrouter_to_anthropic_falls_back_to_estimate() {
        let r = count_tokens("openrouter:anthropic/claude-sonnet-4-5", "hello world");
        assert_eq!(r.kind, CountKind::Estimate);
    }

    #[test]
    fn case_insensitive_model_matching() {
        // Adopters sometimes specify mixed case; the dispatch must work.
        let r = count_tokens("GPT-4o-mini", "hello");
        assert_eq!(r.kind, CountKind::Exact);
    }

    #[test]
    fn unicode_text_counts_chars_not_bytes() {
        // 5 multi-byte chars → ceil(5/4) = 2 tokens (estimate path).
        let r = estimate("héllo");
        assert_eq!(r.count, 2);
    }
}
