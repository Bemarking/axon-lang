//! [`PersistenceBackend`] — async trait for cognitive-state persistence.
//!
//! Shipped impls:
//! - [`InMemoryBackend`]: dev + test, single-process, no TTL eviction
//!   (tests snapshot + restore within a unit test's lifetime).
//!
//! Production impl lives in `axon_enterprise::cognitive_states` —
//! Postgres + envelope-encrypted rows, worker-driven eviction that
//! cryptoshreds envelope keys on expiry.

use std::collections::HashMap;
use std::sync::Mutex;

use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};

use crate::pem::state::CognitiveState;

/// Errors every backend speaks.
#[derive(Debug)]
pub enum PersistenceError {
    NotFound {
        session_id: String,
    },
    Expired {
        session_id: String,
        expired_at: DateTime<Utc>,
    },
    Backend(String),
}

impl std::fmt::Display for PersistenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound { session_id } => {
                write!(f, "cognitive state not found: {session_id:?}")
            }
            Self::Expired {
                session_id,
                expired_at,
            } => write!(
                f,
                "cognitive state for {session_id:?} expired at {expired_at}"
            ),
            Self::Backend(m) => write!(f, "backend: {m}"),
        }
    }
}

impl std::error::Error for PersistenceError {}

/// Minimal interface every backend implements. Adopters who need
/// richer querying (list by tenant, filter by subject) extend in
/// their own trait — this core surface is the contract Axon
/// itself depends on.
#[async_trait]
pub trait PersistenceBackend: Send + Sync {
    /// Persist the state under `session_id`. `ttl` is advisory; the
    /// backend is free to honour it via a scheduled eviction job
    /// (the Postgres impl) or a best-effort timer (in-memory).
    async fn persist(
        &self,
        session_id: &str,
        state: &CognitiveState,
        ttl: ChronoDuration,
    ) -> Result<(), PersistenceError>;

    /// Fetch a previously persisted state. Returns
    /// [`PersistenceError::NotFound`] when no record exists and
    /// [`PersistenceError::Expired`] when one exists but its TTL
    /// lapsed.
    async fn restore(
        &self,
        session_id: &str,
    ) -> Result<CognitiveState, PersistenceError>;

    /// Irreversibly delete the state. Idempotent — no-op when the
    /// session has no stored state.
    async fn evict(
        &self,
        session_id: &str,
    ) -> Result<(), PersistenceError>;

    /// Evict every state whose TTL lapsed at or before `before`.
    /// Returns the count of rows removed for observability. Called
    /// periodically by the eviction worker in production; in-memory
    /// impl sweeps on-demand.
    async fn evict_expired(
        &self,
        before: DateTime<Utc>,
    ) -> Result<u64, PersistenceError>;
}

// ── InMemoryBackend ─────────────────────────────────────────────────

struct InMemoryEntry {
    state: CognitiveState,
    expires_at: DateTime<Utc>,
}

/// Single-process, Mutex-guarded. Rejects stale fetches so the
/// same semantics as the Postgres impl hold in tests.
#[derive(Debug, Default)]
pub struct InMemoryBackend {
    inner: Mutex<HashMap<String, StoredEntry>>,
}

// Private struct so callers don't reach past the trait.
struct StoredEntry {
    state_bytes: Vec<u8>,
    expires_at: DateTime<Utc>,
}

impl std::fmt::Debug for StoredEntry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StoredEntry")
            .field("state_bytes_len", &self.state_bytes.len())
            .field("expires_at", &self.expires_at)
            .finish()
    }
}

impl InMemoryBackend {
    pub fn new() -> Self {
        Default::default()
    }

    pub fn len(&self) -> usize {
        self.inner.lock().expect("poisoned").len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[async_trait]
impl PersistenceBackend for InMemoryBackend {
    async fn persist(
        &self,
        session_id: &str,
        state: &CognitiveState,
        ttl: ChronoDuration,
    ) -> Result<(), PersistenceError> {
        let expires_at = Utc::now() + ttl;
        let bytes = state.encode();
        let mut guard = self.inner.lock().expect("poisoned");
        guard.insert(
            session_id.to_string(),
            StoredEntry {
                state_bytes: bytes,
                expires_at,
            },
        );
        Ok(())
    }

    async fn restore(
        &self,
        session_id: &str,
    ) -> Result<CognitiveState, PersistenceError> {
        let guard = self.inner.lock().expect("poisoned");
        let entry = guard
            .get(session_id)
            .ok_or(PersistenceError::NotFound {
                session_id: session_id.to_string(),
            })?;
        if entry.expires_at <= Utc::now() {
            return Err(PersistenceError::Expired {
                session_id: session_id.to_string(),
                expired_at: entry.expires_at,
            });
        }
        CognitiveState::decode(&entry.state_bytes).map_err(|e| {
            PersistenceError::Backend(format!(
                "decode failed for {session_id:?}: {e}"
            ))
        })
    }

    async fn evict(
        &self,
        session_id: &str,
    ) -> Result<(), PersistenceError> {
        let mut guard = self.inner.lock().expect("poisoned");
        guard.remove(session_id);
        Ok(())
    }

    async fn evict_expired(
        &self,
        before: DateTime<Utc>,
    ) -> Result<u64, PersistenceError> {
        let mut guard = self.inner.lock().expect("poisoned");
        let expired: Vec<String> = guard
            .iter()
            .filter(|(_, e)| e.expires_at <= before)
            .map(|(k, _)| k.clone())
            .collect();
        let count = expired.len() as u64;
        for k in expired {
            guard.remove(&k);
        }
        Ok(count)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pem::state::{CognitiveState, FixedPoint};
    use chrono::Duration;

    fn make_state() -> CognitiveState {
        let mut s = CognitiveState::new("sess-1", "alpha", "flow-1");
        s.density_matrix = vec![FixedPoint::vec_from_f64(&[0.1, 0.9])];
        s
    }

    #[tokio::test]
    async fn persist_then_restore_roundtrip() {
        let b = InMemoryBackend::new();
        let state = make_state();
        b.persist(&state.session_id, &state, Duration::minutes(15))
            .await
            .unwrap();
        let restored = b.restore(&state.session_id).await.unwrap();
        assert_eq!(restored, state);
    }

    #[tokio::test]
    async fn restore_unknown_session_returns_not_found() {
        let b = InMemoryBackend::new();
        let err = b.restore("missing").await.unwrap_err();
        matches!(err, PersistenceError::NotFound { .. });
    }

    #[tokio::test]
    async fn restore_expired_session_returns_expired() {
        let b = InMemoryBackend::new();
        let state = make_state();
        // Persist with negative TTL so the entry is already stale.
        b.persist(&state.session_id, &state, Duration::seconds(-1))
            .await
            .unwrap();
        let err = b.restore(&state.session_id).await.unwrap_err();
        matches!(err, PersistenceError::Expired { .. });
    }

    #[tokio::test]
    async fn evict_is_idempotent() {
        let b = InMemoryBackend::new();
        b.evict("nothing-here").await.unwrap();

        let state = make_state();
        b.persist(&state.session_id, &state, Duration::minutes(5))
            .await
            .unwrap();
        b.evict(&state.session_id).await.unwrap();
        b.evict(&state.session_id).await.unwrap();
        let err = b.restore(&state.session_id).await.unwrap_err();
        matches!(err, PersistenceError::NotFound { .. });
    }

    #[tokio::test]
    async fn evict_expired_removes_only_stale_rows() {
        let b = InMemoryBackend::new();
        let mut stale = make_state();
        stale.session_id = "stale".into();
        let mut fresh = make_state();
        fresh.session_id = "fresh".into();

        b.persist(&stale.session_id, &stale, Duration::seconds(-10))
            .await
            .unwrap();
        b.persist(&fresh.session_id, &fresh, Duration::minutes(15))
            .await
            .unwrap();

        let removed = b.evict_expired(Utc::now()).await.unwrap();
        assert_eq!(removed, 1);

        // Fresh still there, stale gone.
        b.restore(&fresh.session_id).await.unwrap();
        let err = b.restore(&stale.session_id).await.unwrap_err();
        matches!(err, PersistenceError::NotFound { .. });
    }

    #[tokio::test]
    async fn len_tracks_live_entries() {
        let b = InMemoryBackend::new();
        assert!(b.is_empty());
        let s = make_state();
        b.persist(&s.session_id, &s, Duration::minutes(5)).await.unwrap();
        assert_eq!(b.len(), 1);
        b.evict(&s.session_id).await.unwrap();
        assert_eq!(b.len(), 0);
    }
}
