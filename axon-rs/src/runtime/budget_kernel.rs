//! §Fase 72.b — the RateLease budget kernel.
//!
//! The runtime for `budget { rate/max … on Tool(X) }` (§72.a). A [`RateLease`] is
//! the **refilling generalization** of the [`lease_kernel`](crate::runtime::lease_kernel)'s
//! τ-decay affine `LeaseToken`: where a `LeaseToken` is single-use and DECAYS to
//! nothing, a `RateLease` is N-use and REFILLS — but the linearity invariant is
//! the same, *a consumed token is gone until it is refilled*. This is what makes
//! "no more than N external effects per period" a real linear contract rather
//! than an advisory counter (the §72 doctrine `effects_are_linear`).
//!
//! Two quota kinds, both PURE functions of `(lease state, now)`:
//!
//!   * `rate:` → a **token bucket** of capacity `limit`, refilling continuously
//!     at `limit / period` tokens per second (so it permits a burst up to
//!     `limit`, then a steady rate). The §72.a default daemon starts full.
//!   * `max:`  → a **fixed tumbling window**: at most `limit` consumptions per
//!     `period`; the window rolls (counter resets) once `period` has elapsed
//!     since it opened. No intra-window refill — a hard cap.
//!
//! Refill/roll is LAZY: every `try_acquire` brings the lease current from the
//! elapsed wall-clock, so the decision never depends on a background tick's
//! granularity. [`RateLeaseKernel::tick`] is housekeeping (keeps `available`
//! queries fresh + reaps), the refilling analogue of the lease kernel's `sweep`
//! / the reconcile loop's periodic pass.

#![allow(dead_code)]

use std::collections::HashMap;

use chrono::{DateTime, Duration, Utc};

use crate::ir_nodes::IRBudgetQuota;

// ═══════════════════════════════════════════════════════════════════
//  PERIOD — the closed catalog (mirrors axon-T832)
// ═══════════════════════════════════════════════════════════════════

/// A budget quota's renewal/window period. Closed catalog — the type checker
/// (`axon-T832`) already rejected anything else at compile time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BudgetPeriod {
    Second,
    Minute,
    Hour,
    Day,
}

impl BudgetPeriod {
    /// Parse the closed catalog spelling. `None` for an unknown period (the
    /// type-checker guarantees this does not happen for compiled programs).
    pub fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "second" => BudgetPeriod::Second,
            "minute" => BudgetPeriod::Minute,
            "hour" => BudgetPeriod::Hour,
            "day" => BudgetPeriod::Day,
            _ => return None,
        })
    }

    /// The period length in seconds.
    pub fn as_secs(self) -> f64 {
        match self {
            BudgetPeriod::Second => 1.0,
            BudgetPeriod::Minute => 60.0,
            BudgetPeriod::Hour => 3600.0,
            BudgetPeriod::Day => 86400.0,
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
//  ACQUIRE OUTCOME
// ═══════════════════════════════════════════════════════════════════

/// The result of attempting to consume one token from a [`RateLease`]. A pure
/// function of the lease's state + `now`.
#[derive(Debug, Clone, PartialEq)]
pub enum AcquireOutcome {
    /// A token was consumed — the budgeted effect MAY proceed.
    Granted,
    /// The quota is exhausted. `retry_at` is the earliest instant a token will
    /// be available again (the input to `on_exhausted: defer`'s reschedule).
    Denied { retry_at: DateTime<Utc> },
}

impl AcquireOutcome {
    pub fn is_granted(&self) -> bool {
        matches!(self, AcquireOutcome::Granted)
    }
}

// ═══════════════════════════════════════════════════════════════════
//  RATE LEASE
// ═══════════════════════════════════════════════════════════════════

#[derive(Debug, Clone)]
enum RateState {
    /// `rate:` — a refilling token bucket. `tokens` is fractional (continuous
    /// refill); `last_refill` is the watermark elapsed-time is measured from.
    Bucket { tokens: f64, last_refill: DateTime<Utc> },
    /// `max:` — a fixed tumbling window. `consumed` resets when the window rolls.
    Window { window_start: DateTime<Utc>, consumed: i64 },
}

/// One quota's live state: a refilling bucket (`rate:`) or a fixed window
/// (`max:`). Construct via [`RateLease::rate`] / [`RateLease::max`] /
/// [`RateLease::from_quota`]. Consume via [`RateLease::try_acquire`].
#[derive(Debug, Clone)]
pub struct RateLease {
    /// The declared tool this quota governs (`on Tool(effect)`).
    pub effect: String,
    /// The token allowance per period (> 0).
    pub limit: i64,
    /// The renewal/window period.
    pub period: BudgetPeriod,
    state: RateState,
}

impl RateLease {
    /// A `rate:` quota — a token bucket starting FULL (`limit` tokens), refilling
    /// `limit` tokens per `period`.
    pub fn rate(effect: impl Into<String>, limit: i64, period: BudgetPeriod, now: DateTime<Utc>) -> Self {
        RateLease {
            effect: effect.into(),
            limit,
            period,
            state: RateState::Bucket { tokens: limit.max(0) as f64, last_refill: now },
        }
    }

    /// A `max:` quota — a fixed window of `period`, starting empty (0 consumed).
    pub fn max(effect: impl Into<String>, limit: i64, period: BudgetPeriod, now: DateTime<Utc>) -> Self {
        RateLease {
            effect: effect.into(),
            limit,
            period,
            state: RateState::Window { window_start: now, consumed: 0 },
        }
    }

    /// Build a lease from a compiled [`IRBudgetQuota`]. `None` if the period is
    /// not in the closed catalog (the type checker prevents this for compiled
    /// programs; the caller fail-closes defensively).
    pub fn from_quota(q: &IRBudgetQuota, now: DateTime<Utc>) -> Option<Self> {
        let period = BudgetPeriod::parse(&q.period)?;
        Some(match q.kind.as_str() {
            "max" => RateLease::max(q.effect.clone(), q.limit, period, now),
            // "rate" (and defensively any other kind) → a refilling bucket.
            _ => RateLease::rate(q.effect.clone(), q.limit, period, now),
        })
    }

    /// The refill-per-second rate for a bucket (`limit / period_secs`).
    fn refill_per_sec(&self) -> f64 {
        self.limit.max(0) as f64 / self.period.as_secs()
    }

    /// Bring the lease current as of `now` (refill the bucket / roll the window).
    /// Idempotent at a fixed `now`; pure given the prior state.
    pub fn refill(&mut self, now: DateTime<Utc>) {
        let rate = self.refill_per_sec();
        let capacity = self.limit.max(0) as f64;
        let period_secs = self.period.as_secs();
        match &mut self.state {
            RateState::Bucket { tokens, last_refill } => {
                let elapsed = (now - *last_refill).num_milliseconds() as f64 / 1000.0;
                if elapsed > 0.0 {
                    *tokens = (*tokens + elapsed * rate).min(capacity);
                    *last_refill = now;
                }
            }
            RateState::Window { window_start, consumed } => {
                let elapsed = (now - *window_start).num_milliseconds() as f64 / 1000.0;
                if elapsed >= period_secs {
                    *window_start = now;
                    *consumed = 0;
                }
            }
        }
    }

    /// Attempt to consume one token as of `now`. Refills/rolls first, then either
    /// consumes (→ [`AcquireOutcome::Granted`]) or denies with the next-available
    /// instant. PURE: same `(state, now)` ⇒ same outcome + same post-state.
    pub fn try_acquire(&mut self, now: DateTime<Utc>) -> AcquireOutcome {
        self.refill(now);
        let rate = self.refill_per_sec();
        let period_secs = self.period.as_secs();
        match &mut self.state {
            RateState::Bucket { tokens, .. } => {
                if *tokens >= 1.0 {
                    *tokens -= 1.0;
                    AcquireOutcome::Granted
                } else {
                    // Time until the bucket accrues the missing fraction of a token.
                    let deficit = 1.0 - *tokens;
                    let wait_secs = if rate > 0.0 { deficit / rate } else { f64::INFINITY };
                    let retry_at = now + secs_to_duration(wait_secs);
                    AcquireOutcome::Denied { retry_at }
                }
            }
            RateState::Window { window_start, consumed } => {
                if *consumed < self.limit {
                    *consumed += 1;
                    AcquireOutcome::Granted
                } else {
                    let retry_at = *window_start + secs_to_duration(period_secs);
                    AcquireOutcome::Denied { retry_at }
                }
            }
        }
    }

    /// The number of tokens currently available (after refilling to `now`).
    /// Whole tokens for a window; fractional for a bucket.
    pub fn available(&self, now: DateTime<Utc>) -> f64 {
        let mut probe = self.clone();
        probe.refill(now);
        match probe.state {
            RateState::Bucket { tokens, .. } => tokens,
            RateState::Window { consumed, .. } => (self.limit - consumed).max(0) as f64,
        }
    }
}

/// Convert fractional seconds to a chrono [`Duration`] (millisecond precision;
/// non-finite / negative values clamp to zero).
fn secs_to_duration(secs: f64) -> Duration {
    if !secs.is_finite() || secs <= 0.0 {
        return Duration::zero();
    }
    // Cap at ~100 days to avoid i64-millis overflow on an infinite-ish wait.
    let capped = secs.min(8_640_000.0);
    Duration::milliseconds((capped * 1000.0) as i64)
}

// ═══════════════════════════════════════════════════════════════════
//  RATE LEASE KERNEL — the in-process registry (OSS single-replica)
// ═══════════════════════════════════════════════════════════════════

/// An in-process registry of [`RateLease`]s, keyed by an opaque subject string
/// (the §72.c dispatch gate composes the key from the budget's scope + the
/// effect + the quota kind, e.g. `"daemon:Outbound:Tool(TelnyxCall):rate"`). This
/// is the OSS single-replica reference; the §72.e enterprise layer binds the
/// per-tenant Redis `RateLimiter` for multi-replica enforcement.
#[derive(Default)]
pub struct RateLeaseKernel {
    leases: HashMap<String, RateLease>,
}

impl RateLeaseKernel {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register (or replace) the lease for `key`.
    pub fn register(&mut self, key: impl Into<String>, lease: RateLease) {
        self.leases.insert(key.into(), lease);
    }

    /// Whether a lease is registered for `key`.
    pub fn contains(&self, key: &str) -> bool {
        self.leases.contains_key(key)
    }

    /// Attempt to consume one token from the lease at `key`. A `key` with no
    /// registered lease is **unbudgeted** ⇒ always [`AcquireOutcome::Granted`]
    /// (an effect with no declared quota is not rate-limited).
    pub fn try_acquire(&mut self, key: &str, now: DateTime<Utc>) -> AcquireOutcome {
        match self.leases.get_mut(key) {
            Some(lease) => lease.try_acquire(now),
            None => AcquireOutcome::Granted,
        }
    }

    /// Tokens currently available at `key` (`None` if unregistered).
    pub fn available(&self, key: &str, now: DateTime<Utc>) -> Option<f64> {
        self.leases.get(key).map(|l| l.available(now))
    }

    /// Housekeeping pass — refill/roll every registered lease to `now` so
    /// `available` snapshots are fresh. The refilling analogue of the lease
    /// kernel's `sweep`. Acquisition does not depend on this (refill is lazy).
    pub fn tick(&mut self, now: DateTime<Utc>) {
        for lease in self.leases.values_mut() {
            lease.refill(now);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t0() -> DateTime<Utc> {
        "2026-06-29T00:00:00Z".parse().unwrap()
    }

    // ── BudgetPeriod ─────────────────────────────────────────────────────

    #[test]
    fn period_parses_and_maps_to_seconds() {
        assert_eq!(BudgetPeriod::parse("hour"), Some(BudgetPeriod::Hour));
        assert_eq!(BudgetPeriod::parse("fortnight"), None);
        assert_eq!(BudgetPeriod::Second.as_secs(), 1.0);
        assert_eq!(BudgetPeriod::Minute.as_secs(), 60.0);
        assert_eq!(BudgetPeriod::Hour.as_secs(), 3600.0);
        assert_eq!(BudgetPeriod::Day.as_secs(), 86400.0);
    }

    // ── rate: token bucket ───────────────────────────────────────────────

    #[test]
    fn bucket_starts_full_and_grants_up_to_capacity() {
        let now = t0();
        let mut l = RateLease::rate("Telnyx", 3, BudgetPeriod::Hour, now);
        // A burst of 3 succeeds (starts full)...
        assert!(l.try_acquire(now).is_granted());
        assert!(l.try_acquire(now).is_granted());
        assert!(l.try_acquire(now).is_granted());
        // ...the 4th is denied at the same instant (bucket empty).
        match l.try_acquire(now) {
            AcquireOutcome::Denied { retry_at } => {
                // 3/hour ⇒ one token every 1200s; deficit is a full token.
                assert_eq!(retry_at, now + Duration::seconds(1200));
            }
            other => panic!("expected Denied, got {other:?}"),
        }
    }

    #[test]
    fn bucket_refills_over_time() {
        let now = t0();
        let mut l = RateLease::rate("Telnyx", 2, BudgetPeriod::Hour, now);
        // Drain both tokens.
        assert!(l.try_acquire(now).is_granted());
        assert!(l.try_acquire(now).is_granted());
        assert!(!l.try_acquire(now).is_granted());
        // 2/hour ⇒ 1 token per 1800s. After 1800s, exactly one token is back.
        let later = now + Duration::seconds(1800);
        assert!(l.try_acquire(later).is_granted());
        assert!(!l.try_acquire(later).is_granted());
    }

    #[test]
    fn bucket_refill_is_capped_at_capacity() {
        let now = t0();
        let mut l = RateLease::rate("Telnyx", 5, BudgetPeriod::Minute, now);
        // Drain one, then wait a full day — refill must NOT exceed capacity.
        assert!(l.try_acquire(now).is_granted());
        let way_later = now + Duration::days(1);
        // Only `limit` (5) grants available, not days' worth.
        for _ in 0..5 {
            assert!(l.try_acquire(way_later).is_granted());
        }
        assert!(!l.try_acquire(way_later).is_granted(), "capped at capacity");
    }

    // ── max: fixed window ────────────────────────────────────────────────

    #[test]
    fn window_caps_at_limit_then_rolls() {
        let now = t0();
        let mut l = RateLease::max("Telnyx", 50, BudgetPeriod::Day, now);
        // 50 calls in the window succeed.
        for _ in 0..50 {
            assert!(l.try_acquire(now).is_granted());
        }
        // The 51st is denied; retry at the window roll (24h later).
        match l.try_acquire(now) {
            AcquireOutcome::Denied { retry_at } => {
                assert_eq!(retry_at, now + Duration::seconds(86400));
            }
            other => panic!("expected Denied, got {other:?}"),
        }
        // Just before the roll → still denied.
        assert!(!l.try_acquire(now + Duration::seconds(86399)).is_granted());
        // After the roll → the window resets, calls succeed again.
        let next_day = now + Duration::seconds(86400);
        assert!(l.try_acquire(next_day).is_granted());
        assert_eq!(l.available(next_day), 49.0);
    }

    #[test]
    fn window_has_no_intra_window_refill() {
        let now = t0();
        let mut l = RateLease::max("Telnyx", 2, BudgetPeriod::Hour, now);
        assert!(l.try_acquire(now).is_granted());
        assert!(l.try_acquire(now).is_granted());
        // Halfway through the window, still capped (no continuous refill).
        assert!(!l.try_acquire(now + Duration::seconds(1800)).is_granted());
    }

    // ── from_quota + available ───────────────────────────────────────────

    #[test]
    fn from_quota_builds_the_right_kind() {
        let now = t0();
        let rate_q = IRBudgetQuota {
            kind: "rate".into(),
            limit: 8,
            period: "hour".into(),
            effect: "Telnyx".into(),
        };
        let max_q = IRBudgetQuota {
            kind: "max".into(),
            limit: 50,
            period: "day".into(),
            effect: "Telnyx".into(),
        };
        let rate = RateLease::from_quota(&rate_q, now).unwrap();
        assert_eq!(rate.available(now), 8.0, "a rate bucket starts full");
        let maxl = RateLease::from_quota(&max_q, now).unwrap();
        assert_eq!(maxl.available(now), 50.0, "a max window starts with the full allowance");
        // An invalid period fails closed to None.
        let bad = IRBudgetQuota { period: "fortnight".into(), ..rate_q };
        assert!(RateLease::from_quota(&bad, now).is_none());
    }

    // ── kernel ───────────────────────────────────────────────────────────

    #[test]
    fn kernel_unregistered_key_is_unbudgeted() {
        let mut k = RateLeaseKernel::new();
        // No lease for the key ⇒ an effect with no quota is never limited.
        assert!(k.try_acquire("daemon:X:Tool(Y):rate", t0()).is_granted());
        assert_eq!(k.available("daemon:X:Tool(Y):rate", t0()), None);
    }

    #[test]
    fn kernel_enforces_a_registered_lease() {
        let now = t0();
        let mut k = RateLeaseKernel::new();
        k.register("d:Out:Tool(Telnyx):rate", RateLease::rate("Telnyx", 1, BudgetPeriod::Hour, now));
        assert!(k.try_acquire("d:Out:Tool(Telnyx):rate", now).is_granted());
        assert!(!k.try_acquire("d:Out:Tool(Telnyx):rate", now).is_granted());
        // After a full hour, the single token is back.
        let later = now + Duration::seconds(3600);
        assert!(k.try_acquire("d:Out:Tool(Telnyx):rate", later).is_granted());
    }

    #[test]
    fn kernel_tick_refreshes_available_without_consuming() {
        let now = t0();
        let mut k = RateLeaseKernel::new();
        k.register("k", RateLease::rate("E", 4, BudgetPeriod::Minute, now));
        // Drain to empty.
        for _ in 0..4 {
            assert!(k.try_acquire("k", now).is_granted());
        }
        assert_eq!(k.available("k", now), Some(0.0));
        // 30s = half a minute ⇒ 4/min * 30s = 2 tokens refilled by tick.
        let later = now + Duration::seconds(30);
        k.tick(later);
        assert_eq!(k.available("k", later), Some(2.0));
    }
}
