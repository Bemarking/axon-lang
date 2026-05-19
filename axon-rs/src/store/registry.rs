//! §Fase 35.d (v1.30.0) — `StoreRegistry`, the closed-catalog
//! SQL-vs-KV dispatch chokepoint of the `axonstore` cognitive data
//! plane.
//!
//! The registry is the **single point** at which a store-op's
//! `store_name` is resolved to a backend. Both execution paths — the
//! sync runner (35.e) and the streaming dispatcher (35.f) — route
//! through it, so there is exactly one SQL-vs-KV decision site and no
//! path divergence (the SSE-gap lesson).
//!
//! # D2 — store resolution is a total function over a closed catalog
//!
//! [`StoreRegistry::build`] is the catalog gate: every `IRAxonStore`'s
//! `backend` must classify into the closed set `{in_memory,
//! postgresql}` ([`classify_backend`]). An unknown backend (`sqlite`,
//! `mysql`, a typo) fails the build with a named [`RegistryError`] —
//! pure, no I/O, fail-fast at deploy. After build, [`resolve`] is
//! total: every `store_name` yields a [`StoreHandle`] or a typed
//! [`StoreError`] — never a panic.
//!
//! [`resolve`]: StoreRegistry::resolve
//!
//! # D3 — zero regression on the key-value path (absolute)
//!
//! `in_memory` is the **implicit default**: a store that is undeclared,
//! declared with an empty `backend`, or declared `in_memory` resolves
//! to [`StoreHandle::InMemory`] — the byte-identical pre-35 key-value
//! path. The SQL path is entered *iff* a matching `IRAxonStore` has
//! `backend == "postgresql"`.
//!
//! Crucially: a declared `postgresql` store whose connection cannot be
//! resolved (a missing `env:` variable, a malformed DSN) yields a typed
//! error — **never** a silent fallback to the key-value store. Silently
//! degrading a misconfigured SQL store to KV would lose writes and
//! serve stale reads; the registry refuses to do it.
//!
//! # Lazy, per-DSN pool cache (D7)
//!
//! The registry build is pure (catalog validation only). A
//! `PostgresStoreBackend` — and therefore its pool and its `env:`
//! resolution — is created on the **first** `resolve` of a given
//! postgresql store, then cached **by resolved DSN**: stores that share
//! a DSN share one pool. A store that is never used never resolves its
//! connection — so a broken `postgresql` store cannot break an
//! unrelated `in_memory` flow (D3).

use std::collections::HashMap;
use std::fmt;
use std::sync::Mutex;

use crate::ir_nodes::IRAxonStore;
use crate::store::postgres_backend::{
    resolve_dsn, PostgresStoreBackend, StoreError,
};

// ════════════════════════════════════════════════════════════════════
//  Closed backend catalog (D2)
// ════════════════════════════════════════════════════════════════════

/// The closed catalog of `axonstore` backends honored by the v1.30.0
/// runtime. Growth (e.g. `sqlite`) is a deliberate language decision —
/// a new variant here plus a backend implementation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StoreBackendKind {
    /// The in-process key-value path — the pre-35 behavior, and the
    /// implicit default for an undeclared or empty-`backend` store.
    InMemory,
    /// A `sqlx::PgPool`-backed SQL store (35.c `PostgresStoreBackend`).
    Postgresql,
}

impl StoreBackendKind {
    /// The canonical `backend:` spelling.
    pub fn as_str(self) -> &'static str {
        match self {
            StoreBackendKind::InMemory => "in_memory",
            StoreBackendKind::Postgresql => "postgresql",
        }
    }
}

impl fmt::Display for StoreBackendKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Classify an `IRAxonStore.backend` string into the closed catalog.
///
/// The match is trimmed + case-insensitive. An empty string is the
/// implicit `in_memory` default. `None` means the value is outside the
/// closed catalog — the caller turns that into a build error.
pub fn classify_backend(backend: &str) -> Option<StoreBackendKind> {
    match backend.trim().to_ascii_lowercase().as_str() {
        "" | "in_memory" => Some(StoreBackendKind::InMemory),
        "postgresql" => Some(StoreBackendKind::Postgresql),
        _ => None,
    }
}

// ════════════════════════════════════════════════════════════════════
//  Build-phase error catalog
// ════════════════════════════════════════════════════════════════════

/// A failure building a [`StoreRegistry`] from `IRProgram`'s
/// `axonstore_specs`. These are deploy-time errors — pure, no I/O.
#[derive(Debug, Clone, PartialEq)]
pub enum RegistryError {
    /// An `axonstore` declares a `backend` outside the closed catalog.
    UnknownBackend { store: String, backend: String },
    /// Two `axonstore` declarations share a name.
    DuplicateStore { store: String },
}

impl fmt::Display for RegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RegistryError::UnknownBackend { store, backend } => write!(
                f,
                "axonstore `{store}` declares unknown backend `{backend}` \
                 — the v1.30.0 closed catalog is {{in_memory, postgresql}} \
                 (sqlite is a documented future fase)"
            ),
            RegistryError::DuplicateStore { store } => write!(
                f,
                "axonstore `{store}` is declared more than once — store \
                 names must be unique"
            ),
        }
    }
}

impl std::error::Error for RegistryError {}

// ════════════════════════════════════════════════════════════════════
//  Store handle — the resolved dispatch target
// ════════════════════════════════════════════════════════════════════

/// The resolved backend for a store operation. The runner (35.e) and
/// the dispatcher (35.f) match on this to route to SQL or to the
/// key-value path.
#[derive(Debug, Clone)]
pub enum StoreHandle {
    /// The in-process key-value path (D3 — byte-identical to pre-35).
    InMemory,
    /// A Postgres-backed store, with its (shared, cached) backend.
    Postgres(PostgresStoreBackend),
}

impl StoreHandle {
    /// `true` iff this resolves to the key-value path.
    pub fn is_in_memory(&self) -> bool {
        matches!(self, StoreHandle::InMemory)
    }

    /// `true` iff this resolves to the SQL path.
    pub fn is_postgres(&self) -> bool {
        matches!(self, StoreHandle::Postgres(_))
    }
}

// ════════════════════════════════════════════════════════════════════
//  Registered store entry
// ════════════════════════════════════════════════════════════════════

/// One validated `axonstore` declaration held by the registry.
#[derive(Debug, Clone)]
struct RegisteredStore {
    spec: IRAxonStore,
    kind: StoreBackendKind,
}

// ════════════════════════════════════════════════════════════════════
//  StoreRegistry
// ════════════════════════════════════════════════════════════════════

/// The closed-catalog store resolver. Built once from a program's
/// `axonstore` declarations; shared (behind an `Arc`) across concurrent
/// dispatch. `Send + Sync`.
pub struct StoreRegistry {
    /// `store_name` → its validated declaration.
    stores: HashMap<String, RegisteredStore>,
    /// resolved DSN → connected backend. Lazy: an entry appears on the
    /// first `resolve` of a postgresql store with that DSN. Stores that
    /// share a DSN share one pool.
    pool_cache: Mutex<HashMap<String, PostgresStoreBackend>>,
}

impl fmt::Debug for StoreRegistry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // List names + kinds only — never dump raw `connection` strings
        // (a literal DSN can carry a password).
        let mut kinds: Vec<(&str, StoreBackendKind)> = self
            .stores
            .iter()
            .map(|(name, r)| (name.as_str(), r.kind))
            .collect();
        kinds.sort_by(|a, b| a.0.cmp(b.0));
        f.debug_struct("StoreRegistry")
            .field("stores", &kinds)
            .field("cached_pools", &self.cached_pool_count())
            .finish()
    }
}

impl StoreRegistry {
    /// Build a registry from a program's `axonstore` declarations.
    ///
    /// D2 catalog gate — pure, no I/O. Fails fast if any declaration
    /// names an unknown backend or if two declarations collide on name.
    /// Connection validity is **not** checked here — that is resolved
    /// lazily, per store, so a broken `postgresql` store cannot fail
    /// the build for an unrelated `in_memory` flow (D3).
    pub fn build(specs: &[IRAxonStore]) -> Result<StoreRegistry, RegistryError> {
        let mut stores: HashMap<String, RegisteredStore> =
            HashMap::with_capacity(specs.len());

        for spec in specs {
            let kind = classify_backend(&spec.backend).ok_or_else(|| {
                RegistryError::UnknownBackend {
                    store: spec.name.clone(),
                    backend: spec.backend.clone(),
                }
            })?;
            if stores.contains_key(&spec.name) {
                return Err(RegistryError::DuplicateStore {
                    store: spec.name.clone(),
                });
            }
            stores.insert(
                spec.name.clone(),
                RegisteredStore { spec: spec.clone(), kind },
            );
        }

        Ok(StoreRegistry {
            stores,
            pool_cache: Mutex::new(HashMap::new()),
        })
    }

    /// An empty registry — a program that declares no `axonstore`. Every
    /// `resolve` then yields [`StoreHandle::InMemory`] (D3).
    pub fn empty() -> StoreRegistry {
        StoreRegistry {
            stores: HashMap::new(),
            pool_cache: Mutex::new(HashMap::new()),
        }
    }

    /// Resolve a store name to its dispatch target.
    ///
    /// - An undeclared store, or one declared `in_memory` / empty →
    ///   [`StoreHandle::InMemory`] (the implicit default, D3).
    /// - A `postgresql` store → [`StoreHandle::Postgres`], its backend
    ///   lazily connected and cached by resolved DSN.
    /// - A `postgresql` store whose connection cannot be resolved → a
    ///   typed [`StoreError`]. **Never** a silent KV fallback.
    ///
    /// Total: every input yields `Ok(handle)` or `Err(StoreError)`.
    /// Must be called within a Tokio runtime context when it may
    /// connect a postgresql backend (the lazy pool, per 35.c).
    pub fn resolve(&self, store_name: &str) -> Result<StoreHandle, StoreError> {
        let registered = match self.stores.get(store_name) {
            // Undeclared → implicit in_memory default (D3 — pre-35
            // behavior: a store needs no declaration to be key-value).
            None => return Ok(StoreHandle::InMemory),
            Some(r) => r,
        };

        match registered.kind {
            StoreBackendKind::InMemory => Ok(StoreHandle::InMemory),
            StoreBackendKind::Postgresql => {
                // Resolve the DSN first — this is the cache key, and
                // the point at which a missing `env:` var surfaces as
                // a typed error rather than a silent KV fallback.
                let dsn = resolve_dsn(&registered.spec.connection)?;

                let mut cache = self.lock_cache();
                if let Some(backend) = cache.get(&dsn) {
                    return Ok(StoreHandle::Postgres(backend.clone()));
                }
                let backend = PostgresStoreBackend::connect_named(
                    &registered.spec.connection,
                    store_name,
                )?;
                cache.insert(dsn, backend.clone());
                Ok(StoreHandle::Postgres(backend))
            }
        }
    }

    /// The declaration backing a store name, if any. The pillars
    /// consult it — 35.g for `confidence_floor`, 35.h for `on_breach`.
    pub fn spec(&self, store_name: &str) -> Option<&IRAxonStore> {
        self.stores.get(store_name).map(|r| &r.spec)
    }

    /// The backend kind a store name resolves to, if declared.
    pub fn backend_kind(&self, store_name: &str) -> Option<StoreBackendKind> {
        self.stores.get(store_name).map(|r| r.kind)
    }

    /// The number of declared stores.
    pub fn len(&self) -> usize {
        self.stores.len()
    }

    /// `true` iff no `axonstore` is declared.
    pub fn is_empty(&self) -> bool {
        self.stores.is_empty()
    }

    /// The number of distinct connection pools currently cached — one
    /// per resolved DSN actually used. Useful for a health surface.
    pub fn cached_pool_count(&self) -> usize {
        self.lock_cache().len()
    }

    /// Lock the pool cache, recovering the guard if a prior holder
    /// panicked (the critical section only does infallible map ops, so
    /// poisoning is effectively impossible — but recovery keeps the
    /// registry panic-free regardless).
    fn lock_cache(
        &self,
    ) -> std::sync::MutexGuard<'_, HashMap<String, PostgresStoreBackend>> {
        self.pool_cache
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

// ════════════════════════════════════════════════════════════════════
//  Unit tests
// ════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    /// Build an `IRAxonStore` test fixture.
    fn spec(name: &str, backend: &str, connection: &str) -> IRAxonStore {
        IRAxonStore {
            node_type: "axonstore",
            source_line: 0,
            source_column: 0,
            name: name.to_string(),
            backend: backend.to_string(),
            connection: connection.to_string(),
            confidence_floor: None,
            isolation: String::new(),
            on_breach: String::new(),
            capability: String::new(),
        }
    }

    // ── classify_backend ─────────────────────────────────────────────

    #[test]
    fn classify_postgresql() {
        assert_eq!(
            classify_backend("postgresql"),
            Some(StoreBackendKind::Postgresql)
        );
    }

    #[test]
    fn classify_in_memory_and_empty_default() {
        assert_eq!(
            classify_backend("in_memory"),
            Some(StoreBackendKind::InMemory)
        );
        assert_eq!(classify_backend(""), Some(StoreBackendKind::InMemory));
    }

    #[test]
    fn classify_is_trimmed_and_case_insensitive() {
        assert_eq!(
            classify_backend("  PostgreSQL  "),
            Some(StoreBackendKind::Postgresql)
        );
        assert_eq!(
            classify_backend("IN_MEMORY"),
            Some(StoreBackendKind::InMemory)
        );
    }

    #[test]
    fn classify_unknown_backends_are_none() {
        // `sqlite` / `mysql` are syntactically valid in the frontend
        // but outside the v1.30.0 runtime catalog.
        for backend in ["sqlite", "mysql", "postgres", "mongodb", "redis"] {
            assert_eq!(classify_backend(backend), None, "backend {backend}");
        }
    }

    // ── build — D2 catalog gate ──────────────────────────────────────

    #[test]
    fn build_accepts_valid_specs() {
        let specs = [
            spec("cache", "in_memory", ""),
            spec("tenants", "postgresql", "env:DATABASE_URL"),
            spec("scratch", "", ""),
        ];
        let registry = StoreRegistry::build(&specs).unwrap();
        assert_eq!(registry.len(), 3);
        assert!(!registry.is_empty());
    }

    #[test]
    fn build_rejects_unknown_backend() {
        let specs = [spec("legacy", "sqlite", "file:./db.sqlite")];
        match StoreRegistry::build(&specs) {
            Err(RegistryError::UnknownBackend { store, backend }) => {
                assert_eq!(store, "legacy");
                assert_eq!(backend, "sqlite");
            }
            other => panic!("expected UnknownBackend, got {other:?}"),
        }
    }

    #[test]
    fn build_rejects_duplicate_store_name() {
        let specs = [
            spec("tenants", "in_memory", ""),
            spec("tenants", "postgresql", "env:DB"),
        ];
        match StoreRegistry::build(&specs) {
            Err(RegistryError::DuplicateStore { store }) => {
                assert_eq!(store, "tenants");
            }
            other => panic!("expected DuplicateStore, got {other:?}"),
        }
    }

    #[test]
    fn build_empty_specs_yields_empty_registry() {
        let registry = StoreRegistry::build(&[]).unwrap();
        assert!(registry.is_empty());
        assert_eq!(registry.len(), 0);
    }

    #[test]
    fn empty_constructor_is_empty() {
        assert!(StoreRegistry::empty().is_empty());
    }

    // ── resolve — D3 key-value path ──────────────────────────────────

    #[test]
    fn resolve_undeclared_store_is_in_memory() {
        // The load-bearing D3 test: a store that was never declared
        // resolves to the byte-identical pre-35 key-value path.
        let registry = StoreRegistry::empty();
        let handle = registry.resolve("never_declared").unwrap();
        assert!(handle.is_in_memory());
    }

    #[test]
    fn resolve_declared_in_memory_store() {
        let registry =
            StoreRegistry::build(&[spec("cache", "in_memory", "")]).unwrap();
        assert!(registry.resolve("cache").unwrap().is_in_memory());
    }

    #[test]
    fn resolve_empty_backend_store_is_in_memory() {
        let registry = StoreRegistry::build(&[spec("s", "", "")]).unwrap();
        assert!(registry.resolve("s").unwrap().is_in_memory());
    }

    #[test]
    fn resolve_empty_store_name_is_in_memory() {
        assert!(StoreRegistry::empty().resolve("").unwrap().is_in_memory());
    }

    // ── resolve — D2: never a silent KV fallback ─────────────────────

    #[test]
    fn resolve_postgres_with_missing_env_var_errors_not_kv_fallback() {
        // A declared postgresql store whose `env:` var is unset MUST
        // surface a typed error — never degrade silently to KV.
        let registry = StoreRegistry::build(&[spec(
            "tenants",
            "postgresql",
            "env:AXON_NONEXISTENT_VAR_FASE35D",
        )])
        .unwrap();
        match registry.resolve("tenants") {
            Err(StoreError::MissingEnvVar { var }) => {
                assert_eq!(var, "AXON_NONEXISTENT_VAR_FASE35D");
            }
            other => panic!("expected MissingEnvVar, got {other:?}"),
        }
    }

    #[test]
    fn resolve_postgres_with_empty_connection_errors() {
        let registry =
            StoreRegistry::build(&[spec("t", "postgresql", "")]).unwrap();
        assert!(matches!(
            registry.resolve("t"),
            Err(StoreError::EmptyConnection)
        ));
    }

    // ── resolve — postgres path + per-DSN pool cache ─────────────────

    #[tokio::test]
    async fn resolve_postgres_store_yields_a_postgres_handle() {
        let registry = StoreRegistry::build(&[spec(
            "tenants",
            "postgresql",
            "postgresql://u:p@localhost:5432/axon",
        )])
        .unwrap();
        assert!(registry.resolve("tenants").unwrap().is_postgres());
    }

    #[tokio::test]
    async fn resolving_one_store_twice_reuses_one_pool() {
        let registry = StoreRegistry::build(&[spec(
            "tenants",
            "postgresql",
            "postgresql://u:p@localhost:5432/axon",
        )])
        .unwrap();
        assert_eq!(registry.cached_pool_count(), 0);
        registry.resolve("tenants").unwrap();
        registry.resolve("tenants").unwrap();
        assert_eq!(
            registry.cached_pool_count(),
            1,
            "the second resolve must hit the cache, not reconnect"
        );
    }

    #[tokio::test]
    async fn two_stores_sharing_a_dsn_share_one_pool() {
        let dsn = "postgresql://u:p@localhost:5432/shared";
        let registry = StoreRegistry::build(&[
            spec("alpha", "postgresql", dsn),
            spec("beta", "postgresql", dsn),
        ])
        .unwrap();
        registry.resolve("alpha").unwrap();
        registry.resolve("beta").unwrap();
        assert_eq!(
            registry.cached_pool_count(),
            1,
            "stores on the same DSN must share one pool"
        );
    }

    #[tokio::test]
    async fn two_stores_with_distinct_dsns_get_distinct_pools() {
        let registry = StoreRegistry::build(&[
            spec("alpha", "postgresql", "postgresql://u:p@localhost/db_a"),
            spec("beta", "postgresql", "postgresql://u:p@localhost/db_b"),
        ])
        .unwrap();
        registry.resolve("alpha").unwrap();
        registry.resolve("beta").unwrap();
        assert_eq!(registry.cached_pool_count(), 2);
    }

    #[tokio::test]
    async fn malformed_dsn_errors_and_is_not_cached() {
        let registry = StoreRegistry::build(&[spec(
            "broken",
            "postgresql",
            "this is not a dsn",
        )])
        .unwrap();
        assert!(matches!(
            registry.resolve("broken"),
            Err(StoreError::PoolInit { .. })
        ));
        assert_eq!(
            registry.cached_pool_count(),
            0,
            "a failed connect must not populate the cache"
        );
    }

    // ── accessors ────────────────────────────────────────────────────

    #[test]
    fn spec_accessor_returns_the_declaration() {
        let registry = StoreRegistry::build(&[spec(
            "tenants",
            "postgresql",
            "env:DB",
        )])
        .unwrap();
        let s = registry.spec("tenants").unwrap();
        assert_eq!(s.name, "tenants");
        assert_eq!(s.backend, "postgresql");
        assert!(registry.spec("absent").is_none());
    }

    #[test]
    fn backend_kind_accessor() {
        let registry = StoreRegistry::build(&[
            spec("kv", "in_memory", ""),
            spec("pg", "postgresql", "env:DB"),
        ])
        .unwrap();
        assert_eq!(
            registry.backend_kind("kv"),
            Some(StoreBackendKind::InMemory)
        );
        assert_eq!(
            registry.backend_kind("pg"),
            Some(StoreBackendKind::Postgresql)
        );
        assert_eq!(registry.backend_kind("absent"), None);
    }

    // ── StoreHandle + display + Debug safety ─────────────────────────

    #[test]
    fn store_handle_predicates() {
        assert!(StoreHandle::InMemory.is_in_memory());
        assert!(!StoreHandle::InMemory.is_postgres());
    }

    #[test]
    fn backend_kind_display() {
        assert_eq!(StoreBackendKind::InMemory.to_string(), "in_memory");
        assert_eq!(StoreBackendKind::Postgresql.to_string(), "postgresql");
    }

    #[test]
    fn registry_debug_does_not_leak_connection_strings() {
        // A literal DSN with a password must not appear in Debug.
        let registry = StoreRegistry::build(&[spec(
            "tenants",
            "postgresql",
            "postgresql://user:fakecred0@localhost/db",
        )])
        .unwrap();
        let debug = format!("{registry:?}");
        assert!(!debug.contains("fakecred0"), "Debug must not leak the DSN");
        assert!(debug.contains("tenants"));
        // The kind surfaces via the `StoreBackendKind` enum's derived
        // Debug (`Postgresql`) — case-insensitive check.
        assert!(debug.to_lowercase().contains("postgresql"));
    }

    #[test]
    fn registry_errors_have_non_empty_display() {
        let errors = [
            RegistryError::UnknownBackend {
                store: "s".into(),
                backend: "mysql".into(),
            },
            RegistryError::DuplicateStore { store: "s".into() },
        ];
        for e in errors {
            assert!(!e.to_string().is_empty());
        }
    }
}
