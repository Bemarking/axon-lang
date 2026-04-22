//! [`ReplayExecutor`] — re-run an effect from a token and detect
//! divergence.
//!
//! The executor is intentionally mechanism-free: it doesn't know how
//! to invoke any specific effect (that's adopter territory). It
//! orchestrates the **protocol**:
//!
//! 1. Fetch the token from a [`ReplayLog`].
//! 2. Hand the token's `inputs` + `sampling` + `model_version` to an
//!    [`EffectInvoker`] the adopter supplied.
//! 3. Canonical-hash the returned outputs.
//! 4. Compare the recomputed hash to `token.outputs_hash_hex`.
//! 5. Report either [`ReplayOutcome::Match`] or
//!    [`ReplayOutcome::Diverged`].
//!
//! Adopters plug in whichever effect dispatcher they use — there's
//! no assumption about provider, transport, or async runtime beyond
//! `async_trait`.

use async_trait::async_trait;
use serde_json::Value;

use crate::replay_token::log::{ReplayLog, ReplayLogError};
use crate::replay_token::token::{canonical_hash, ReplayToken, SamplingParams};

// ── Adopter-supplied effect invoker ──────────────────────────────────

/// What the adopter plugs in. Given the replay inputs +
/// model/sampling context, produce the effect's output value.
///
/// Implementations should be deterministic for deterministic effects
/// (DB reads against a snapshot, pure transformations) and honour
/// `sampling.seed` for LLM inference. Non-seedable providers return
/// an [`EffectInvokerError::NonReplayable`] so the executor's
/// divergence report pinpoints the cause.
#[async_trait]
pub trait EffectInvoker: Send + Sync {
    async fn invoke(
        &self,
        effect_name: &str,
        inputs: &Value,
        model_version: &str,
        sampling: &SamplingParams,
    ) -> Result<Value, EffectInvokerError>;
}

#[derive(Debug)]
pub enum EffectInvokerError {
    NonReplayable(String),
    Runtime(String),
}

impl std::fmt::Display for EffectInvokerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NonReplayable(m) => write!(f, "non-replayable: {m}"),
            Self::Runtime(m) => write!(f, "invoker runtime: {m}"),
        }
    }
}

impl std::error::Error for EffectInvokerError {}

// ── Outcome ──────────────────────────────────────────────────────────

/// What a single-token replay produced.
#[derive(Debug, Clone, PartialEq)]
pub enum ReplayOutcome {
    /// The recomputed outputs hashed identically to the token's
    /// recorded hash — the effect is deterministically reproducible
    /// under the conditions the token recorded.
    Match {
        token_hash_hex: String,
    },
    /// The outputs diverged. `divergence` carries the full report so
    /// an operator can pinpoint what differs without re-running.
    Diverged {
        token_hash_hex: String,
        divergence: ReplayDivergence,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct ReplayDivergence {
    pub expected_outputs_hash_hex: String,
    pub actual_outputs_hash_hex: String,
    pub actual_outputs: Value,
}

// ── Executor errors ──────────────────────────────────────────────────

#[derive(Debug)]
pub enum ReplayExecutorError {
    Log(ReplayLogError),
    Invoker(EffectInvokerError),
}

impl std::fmt::Display for ReplayExecutorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Log(e) => write!(f, "replay log: {e}"),
            Self::Invoker(e) => write!(f, "effect invoker: {e}"),
        }
    }
}

impl std::error::Error for ReplayExecutorError {}

impl From<ReplayLogError> for ReplayExecutorError {
    fn from(e: ReplayLogError) -> Self {
        Self::Log(e)
    }
}

impl From<EffectInvokerError> for ReplayExecutorError {
    fn from(e: EffectInvokerError) -> Self {
        Self::Invoker(e)
    }
}

// ── Executor ─────────────────────────────────────────────────────────

pub struct ReplayExecutor<L: ReplayLog, I: EffectInvoker> {
    pub log: L,
    pub invoker: I,
}

impl<L: ReplayLog, I: EffectInvoker> ReplayExecutor<L, I> {
    pub fn new(log: L, invoker: I) -> Self {
        ReplayExecutor { log, invoker }
    }

    /// Replay a single token; return the outcome.
    pub async fn replay_token(
        &self,
        token_hash_hex: &str,
    ) -> Result<ReplayOutcome, ReplayExecutorError> {
        let token = self.log.get(token_hash_hex).await?;
        Ok(self.verify_token(&token).await?)
    }

    /// Replay every token for a flow, short-circuiting at the first
    /// divergence. Adopters that prefer to collect every divergence
    /// can call [`Self::verify_token`] in a custom loop.
    pub async fn replay_flow(
        &self,
        flow_id: &str,
    ) -> Result<Vec<ReplayOutcome>, ReplayExecutorError> {
        let tokens = self.log.tokens_for_flow(flow_id).await?;
        let mut outcomes = Vec::with_capacity(tokens.len());
        for t in tokens {
            let outcome = self.verify_token(&t).await?;
            let diverged = matches!(outcome, ReplayOutcome::Diverged { .. });
            outcomes.push(outcome);
            if diverged {
                break;
            }
        }
        Ok(outcomes)
    }

    /// Low-level — given a concrete token, re-invoke + compare.
    pub async fn verify_token(
        &self,
        token: &ReplayToken,
    ) -> Result<ReplayOutcome, EffectInvokerError> {
        let actual = self
            .invoker
            .invoke(
                &token.effect_name,
                &token.inputs,
                &token.model_version,
                &token.sampling,
            )
            .await?;
        let actual_hash = canonical_hash(&actual);
        let actual_hash_hex = hex(&actual_hash);
        if actual_hash_hex == token.outputs_hash_hex {
            Ok(ReplayOutcome::Match {
                token_hash_hex: token.token_hash_hex.clone(),
            })
        } else {
            Ok(ReplayOutcome::Diverged {
                token_hash_hex: token.token_hash_hex.clone(),
                divergence: ReplayDivergence {
                    expected_outputs_hash_hex: token.outputs_hash_hex.clone(),
                    actual_outputs_hash_hex: actual_hash_hex,
                    actual_outputs: actual,
                },
            })
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::replay_token::log::InMemoryReplayLog;
    use crate::replay_token::token::{ReplayTokenBuilder, SamplingParams};
    use chrono::{TimeZone, Utc};
    use serde_json::json;

    struct FixedInvoker {
        returns: Value,
    }

    #[async_trait]
    impl EffectInvoker for FixedInvoker {
        async fn invoke(
            &self,
            _effect_name: &str,
            _inputs: &Value,
            _model_version: &str,
            _sampling: &SamplingParams,
        ) -> Result<Value, EffectInvokerError> {
            Ok(self.returns.clone())
        }
    }

    fn mk_token(effect: &str, outputs: Value) -> ReplayToken {
        ReplayTokenBuilder::new()
            .effect_name(effect)
            .inputs(json!({"flow_id": "f1"}))
            .outputs(outputs)
            .model_version("axon.builtin.test.v1")
            .sampling(SamplingParams::default())
            .timestamp(
                Utc.with_ymd_and_hms(2026, 4, 22, 12, 0, 0).unwrap(),
            )
            .nonce([0u8; 16])
            .mint()
    }

    #[tokio::test]
    async fn match_when_outputs_are_bit_identical() {
        let log = InMemoryReplayLog::new();
        let t = mk_token("call_tool:x", json!({"a": 1, "b": 2}));
        log.append(t.clone()).await.unwrap();

        let invoker = FixedInvoker {
            returns: json!({"b": 2, "a": 1}), // keys reordered — canonical hash is key-order-independent
        };
        let executor = ReplayExecutor::new(log, invoker);
        let outcome = executor.replay_token(&t.token_hash_hex).await.unwrap();
        matches!(outcome, ReplayOutcome::Match { .. });
    }

    #[tokio::test]
    async fn diverge_when_outputs_differ() {
        let log = InMemoryReplayLog::new();
        let t = mk_token("call_tool:x", json!({"a": 1}));
        log.append(t.clone()).await.unwrap();

        let invoker = FixedInvoker {
            returns: json!({"a": 999}),
        };
        let executor = ReplayExecutor::new(log, invoker);
        let outcome = executor.replay_token(&t.token_hash_hex).await.unwrap();
        match outcome {
            ReplayOutcome::Diverged { divergence, .. } => {
                assert_eq!(
                    divergence.expected_outputs_hash_hex,
                    t.outputs_hash_hex
                );
                assert_ne!(
                    divergence.actual_outputs_hash_hex,
                    t.outputs_hash_hex
                );
                assert_eq!(divergence.actual_outputs, json!({"a": 999}));
            }
            other => panic!("expected Diverged, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn replay_flow_short_circuits_at_first_divergence() {
        let log = InMemoryReplayLog::new();
        let t1 = mk_token("step1", json!({"x": 1}));
        let t2 = mk_token("step2", json!({"x": 2}));
        let t3 = mk_token("step3", json!({"x": 3}));
        log.append(t1.clone()).await.unwrap();
        // We'll force a divergence on step2 by making the invoker
        // always return {x:1}.
        log.append(t2.clone()).await.unwrap();
        log.append(t3.clone()).await.unwrap();

        let invoker = FixedInvoker {
            returns: json!({"x": 1}),
        };
        let executor = ReplayExecutor::new(log, invoker);
        let outcomes = executor.replay_flow("f1").await.unwrap();
        // step1 matches, step2 diverges, step3 was never attempted.
        assert_eq!(outcomes.len(), 2);
        matches!(outcomes[0], ReplayOutcome::Match { .. });
        matches!(outcomes[1], ReplayOutcome::Diverged { .. });
    }
}
