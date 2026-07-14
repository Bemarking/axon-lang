//! §Fase 112.a — the **source adapter registry**: what an `observe` actually looks at.
//!
//! # Why this exists
//!
//! ```text
//! observe ProdHealth from Infra {
//!     sources: [ prometheus, cloudwatch ]   // ← what ARE these?
//!     quorum: 2
//!     timeout: 5s
//!     on_partition: fail
//!     certainty_floor: 0.8
//! }
//! ```
//!
//! Nothing in the language said what a `source` name resolves to, and so nothing
//! ever resolved one. §111 (F14) found the whole Cognitive-I/O family unreachable;
//! §112 found that the architecture was complete and only two pieces were missing —
//! a supervisor, and **a `Handler` that actually goes and looks at something.**
//!
//! # The defect this replaces
//!
//! The only `Handler` in the tree was [`crate::handlers::dry_run::DryRunHandler`],
//! and its `observe` ends:
//!
//! ```ignore
//! make_envelope(1.0, &self.name, "observed", None)
//! ```
//!
//! **Certainty `1.0`. Always. Without going anywhere.** A perfect-confidence clean
//! bill of health for a system nobody ever examined — and it was the *only* option
//! available, so a supervisor wired to it would have reported perfect health for
//! everything, forever.
//!
//! That is the §111 defect in its purest form, and it is the thing this module
//! exists to make impossible.
//!
//! # The law
//!
//! **An observation that cannot be taken must REFUSE. It must never return a
//! default envelope.** A source that is not registered is not "probably fine" —
//! it is *unknown*, and the difference between *unknown* and *healthy* is the
//! entire reason `observe` exists. So the registry is **deny-by-default**:
//!
//! - unregistered source ⇒ [`SourceError::Unregistered`] ⇒ the observation refuses;
//! - a probe that fails ⇒ that source does not count toward quorum;
//! - fewer successes than `quorum:` ⇒ a **partition**, honoured per `on_partition:`;
//! - aggregate certainty below `certainty_floor:` ⇒ refused.
//!
//! OSS ships the registry with **zero remote adapters** — enterprise mounts
//! Prometheus / CloudWatch / Datadog behind the same trait, exactly as it does for
//! `tool_registry` and `shield_registry`. The one adapter OSS *does* ship is
//! [`ResourceProbeAdapter`] (below), which probes a source that names a **declared
//! `resource`** — the built-in family ratified in the §112 plan.

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, RwLock};

use crate::ir_nodes::IRResource;

/// What a source reported when it was actually asked.
#[derive(Debug, Clone)]
pub struct SourceReading {
    /// Epistemic certainty `c ∈ [0, 1]` in this reading. This is **not** a health
    /// score — it is how sure the adapter is that what it reports is *true*. An
    /// adapter that reached its target cleanly reports high `c`; one that got a
    /// stale cache or a partial answer reports low `c`.
    pub certainty: f64,
    /// The observed state. Opaque here; the kernels downstream (`immune`'s
    /// KL-divergence sensor, `reconcile`'s Jaccard drift) consume it.
    pub data: serde_json::Map<String, serde_json::Value>,
}

impl SourceReading {
    pub fn new(certainty: f64, data: serde_json::Map<String, serde_json::Value>) -> Self {
        SourceReading {
            certainty: certainty.clamp(0.0, 1.0),
            data,
        }
    }
}

/// Why a source could not be read. **Every variant is a refusal** — none of them
/// degrade into an observation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceError {
    /// The source name resolves to no registered adapter.
    ///
    /// This is the load-bearing refusal. An unregistered source is **unknown**,
    /// not healthy, and an `observe` that silently skipped it would report a
    /// quorum it never actually reached.
    Unregistered { source: String },
    /// The adapter was reached but could not answer within `timeout:`.
    Timeout { source: String, after: String },
    /// The adapter reached its target and the target answered with a failure.
    Unreachable { source: String, detail: String },
}

impl std::fmt::Display for SourceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SourceError::Unregistered { source } => write!(
                f,
                "source '{source}' resolves to no registered adapter — an unregistered source is \
                 UNKNOWN, not healthy. Register an adapter for it, or name a declared `resource`. \
                 (§112.a: an observation that cannot be taken must refuse, never return a default \
                 envelope)"
            ),
            SourceError::Timeout { source, after } => {
                write!(f, "source '{source}' did not answer within {after}")
            }
            SourceError::Unreachable { source, detail } => {
                write!(f, "source '{source}' is unreachable: {detail}")
            }
        }
    }
}

impl std::error::Error for SourceError {}

/// A thing an `observe` can actually look at.
///
/// Implementors go somewhere real. **An adapter must never manufacture a reading**
/// — if it cannot reach its target it returns a [`SourceError`], and the caller
/// counts that source as *not answered* rather than as *answered fine*.
pub trait SourceAdapter: Send + Sync {
    /// The source name this adapter answers to (the identifier in `sources: [ … ]`).
    fn name(&self) -> &str;

    /// Probe the source. `resource` is `Some` when the source names a declared
    /// `resource` (the built-in family); `None` for a purely external source.
    ///
    /// `timeout` is the observe's declared `timeout:`, already parsed.
    fn probe(
        &self,
        resource: Option<&IRResource>,
        timeout: std::time::Duration,
    ) -> Result<SourceReading, SourceError>;
}

// ────────────────────────────────────────────────────────────────────
//  The registry — deny by default
// ────────────────────────────────────────────────────────────────────

static REGISTRY: LazyLock<RwLock<HashMap<String, Arc<dyn SourceAdapter>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

/// Register an adapter under a source name. Enterprise calls this at boot for
/// Prometheus / CloudWatch / Datadog / …; OSS registers nothing by default.
pub fn register_source_adapter(name: impl Into<String>, adapter: Arc<dyn SourceAdapter>) {
    REGISTRY
        .write()
        .expect("source registry RwLock poisoned")
        .insert(name.into(), adapter);
}

/// Resolve a source name. `None` ⇒ **unregistered** ⇒ the caller must REFUSE.
pub fn lookup_source_adapter(name: &str) -> Option<Arc<dyn SourceAdapter>> {
    REGISTRY
        .read()
        .expect("source registry RwLock poisoned")
        .get(name)
        .cloned()
}

/// Test/teardown helper — drop every registration.
pub fn clear_source_adapters() {
    REGISTRY
        .write()
        .expect("source registry RwLock poisoned")
        .clear();
}

// ────────────────────────────────────────────────────────────────────
//  The one adapter OSS ships: probe a declared `resource`
// ────────────────────────────────────────────────────────────────────

/// §112.a — the built-in adapter family (ratified): a `source` that names a
/// **declared `resource`** is probed by reaching that resource's `endpoint`.
///
/// This is the honest OSS default. It uses only what the program already declares
/// — `resource Db { kind: postgres  endpoint: "postgres://host:5432/app" }` — and
/// it goes to the real address. It reports:
///
/// - `certainty: 1.0` when the endpoint accepts a connection (we reached it and it
///   is up — that is a fact we established, not one we assumed);
/// - a [`SourceError::Unreachable`] when it does not.
///
/// It deliberately does **not** claim to understand the protocol behind the
/// endpoint. A TCP reachability check is a *modest* claim, and a modest claim we
/// can actually back is worth infinitely more than a confident one we cannot —
/// which is exactly the trade the `DryRunHandler`'s `c: 1.0` got backwards.
/// Deeper, protocol-aware probes (a real `SELECT 1`, a Prometheus query) are
/// enterprise adapters behind this same trait.
pub struct ResourceProbeAdapter {
    name: String,
}

impl ResourceProbeAdapter {
    pub fn new(name: impl Into<String>) -> Self {
        ResourceProbeAdapter { name: name.into() }
    }

    /// Extract `host:port` from a resource endpoint, using the kind's default port
    /// when the URI omits one. Returns `None` when no address can be determined —
    /// and the caller refuses rather than guessing.
    fn socket_addr(resource: &IRResource) -> Option<String> {
        let ep = resource.endpoint.trim();
        if ep.is_empty() {
            return None;
        }
        // Strip a scheme if present, then any path/query tail.
        let after_scheme = ep.split("://").last()?;
        let authority = after_scheme.split(['/', '?']).next()?;
        // Strip credentials (`user:pass@host:port`).
        let hostport = authority.rsplit('@').next()?;
        if hostport.is_empty() {
            return None;
        }
        if hostport.contains(':') {
            return Some(hostport.to_string());
        }
        let port = match resource.kind.as_str() {
            "postgres" => 5432,
            "redis" => 6379,
            "mysql" => 3306,
            "http" => 80,
            "https" => 443,
            // An unknown kind with no explicit port gives us no address to reach.
            // We refuse rather than invent one.
            _ => return None,
        };
        Some(format!("{hostport}:{port}"))
    }
}

impl SourceAdapter for ResourceProbeAdapter {
    fn name(&self) -> &str {
        &self.name
    }

    fn probe(
        &self,
        resource: Option<&IRResource>,
        timeout: std::time::Duration,
    ) -> Result<SourceReading, SourceError> {
        let resource = resource.ok_or_else(|| SourceError::Unregistered {
            source: self.name.clone(),
        })?;

        let addr = Self::socket_addr(resource).ok_or_else(|| SourceError::Unreachable {
            source: self.name.clone(),
            detail: format!(
                "resource '{}' (kind: {}) has no reachable address in its `endpoint: {:?}` — \
                 refusing rather than guessing one",
                resource.name, resource.kind, resource.endpoint
            ),
        })?;

        let socket: std::net::SocketAddr = addr
            .parse()
            .or_else(|_| {
                use std::net::ToSocketAddrs;
                addr.to_socket_addrs()
                    .map_err(|e| SourceError::Unreachable {
                        source: self.name.clone(),
                        detail: format!("cannot resolve '{addr}': {e}"),
                    })
                    .and_then(|mut it| {
                        it.next().ok_or_else(|| SourceError::Unreachable {
                            source: self.name.clone(),
                            detail: format!("'{addr}' resolved to no address"),
                        })
                    })
            })?;

        match std::net::TcpStream::connect_timeout(&socket, timeout) {
            Ok(_) => {
                let mut data = serde_json::Map::new();
                data.insert("resource".into(), resource.name.clone().into());
                data.insert("kind".into(), resource.kind.clone().into());
                data.insert("address".into(), addr.into());
                data.insert("reachable".into(), true.into());
                // c = 1.0 because we ESTABLISHED reachability — we connected. This
                // is a fact, not an assumption, and that is the whole difference
                // between this adapter and the DryRunHandler it replaces.
                Ok(SourceReading::new(1.0, data))
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => Err(SourceError::Timeout {
                source: self.name.clone(),
                after: format!("{timeout:?}"),
            }),
            Err(e) => Err(SourceError::Unreachable {
                source: self.name.clone(),
                detail: format!("{addr}: {e}"),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn resource(name: &str, kind: &str, endpoint: &str) -> IRResource {
        IRResource {
            node_type: "resource",
            source_line: 0,
            source_column: 0,
            name: name.into(),
            kind: kind.into(),
            endpoint: endpoint.into(),
            capacity: None,
            lifetime: "affine".into(),
            certainty_floor: None,
            shield_ref: String::new(),
        }
    }

    /// **The load-bearing law.** An unregistered source resolves to nothing, and
    /// the caller must refuse. There is no default adapter, and there must never
    /// be one: a source nobody registered is UNKNOWN, and reporting unknown as
    /// healthy is the entire defect §112 exists to end.
    ///
    /// NOTE: the registry is a process-global (same shape as `shield_registry`), so
    /// these tests use names nobody else registers rather than clearing it — a
    /// global `clear()` would race with the parallel tests around them.
    #[test]
    fn the_registry_is_deny_by_default() {
        assert!(
            lookup_source_adapter("prometheus").is_none(),
            "OSS must ship ZERO remote adapters — an unregistered source must resolve to nothing"
        );
        assert!(lookup_source_adapter("cloudwatch").is_none());
        assert!(lookup_source_adapter("datadog").is_none());
    }

    #[test]
    fn a_registered_adapter_resolves() {
        register_source_adapter("reg_probe", Arc::new(ResourceProbeAdapter::new("reg_probe")));
        assert!(lookup_source_adapter("reg_probe").is_some());
    }

    /// The probe reaches a REAL address. This is the test that separates §112.a
    /// from the `DryRunHandler` it replaces: the certainty is `1.0` because we
    /// **connected**, not because we assumed.
    #[test]
    fn a_reachable_resource_is_observed_because_we_actually_connected() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let r = resource("Db", "postgres", &format!("postgres://{addr}/app"));

        let reading = ResourceProbeAdapter::new("db")
            .probe(Some(&r), std::time::Duration::from_secs(2))
            .expect("a listening endpoint must be observable");

        assert_eq!(reading.certainty, 1.0);
        assert_eq!(reading.data["reachable"], true);
        assert_eq!(reading.data["resource"], "Db");
    }

    /// **The refusal that matters.** An unreachable resource is an ERROR, never a
    /// reading. The `DryRunHandler` would have returned `c: 1.0` here — a clean
    /// bill of health for a database that is down.
    #[test]
    fn an_unreachable_resource_refuses_rather_than_reporting_health() {
        // Port 1 on loopback: nothing listens there.
        let r = resource("Db", "postgres", "postgres://127.0.0.1:1/app");
        let err = ResourceProbeAdapter::new("db")
            .probe(Some(&r), std::time::Duration::from_millis(500))
            .expect_err(
                "an unreachable resource must REFUSE — returning an envelope here would be a \
                 clean bill of health for a system that is down",
            );
        assert!(matches!(err, SourceError::Unreachable { .. } | SourceError::Timeout { .. }));
    }

    /// We refuse to invent an address. A resource whose endpoint gives us nowhere
    /// to go is not probed optimistically — it is refused.
    #[test]
    fn an_endpoint_with_no_reachable_address_refuses_rather_than_guessing() {
        let r = resource("Blob", "s3", "s3-bucket-name");
        let err = ResourceProbeAdapter::new("blob")
            .probe(Some(&r), std::time::Duration::from_millis(200))
            .expect_err("no address ⇒ refuse");
        let msg = format!("{err}");
        assert!(msg.contains("refusing rather than guessing"), "got {msg}");
    }

    #[test]
    fn default_ports_come_from_the_declared_kind() {
        let pg = resource("Db", "postgres", "postgres://db.internal/app");
        assert_eq!(
            ResourceProbeAdapter::socket_addr(&pg).as_deref(),
            Some("db.internal:5432")
        );
        let redis = resource("Cache", "redis", "redis://cache.internal");
        assert_eq!(
            ResourceProbeAdapter::socket_addr(&redis).as_deref(),
            Some("cache.internal:6379")
        );
        // Credentials are stripped, an explicit port wins.
        let auth = resource("Db", "postgres", "postgres://user:pw@db.internal:6000/app");
        assert_eq!(
            ResourceProbeAdapter::socket_addr(&auth).as_deref(),
            Some("db.internal:6000")
        );
    }
}
