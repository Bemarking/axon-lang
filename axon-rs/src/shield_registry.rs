//! §Fase 40.b — Shield scanner extension point.
//!
//! # Why this exists
//!
//! Per the OSS / ENTERPRISE / SPLIT charter, OSS axon ships the shield
//! *framework* (the `shield apply` algebraic-effect handler + wire shape)
//! but **no scanners** — the OSS default is an identity passthrough. The
//! vertical scanner *implementations* (HIPAA / legal / AML) are enterprise
//! R&D and live in the BSL `axon-enterprise` workspace.
//!
//! Before Fase 40.b there was no clean way for an external crate to inject
//! a scanner: the apply helper was a hardcoded identity. This module is the
//! **public registration hook** the enterprise vertical crate uses. It is a
//! deliberate language extension point — axon-for-axon: it makes axon a
//! better host language for privileged downstream layers, independent of
//! who registers scanners.
//!
//! # Model
//!
//! A [`ShieldScanner`] is registered under a shield *name* (the same name
//! used in `shield apply <name> to <target>`). At dispatch time the
//! `shield apply` handler looks the name up:
//!
//! - **registered** → run the scanner, which returns a [`ShieldVerdict`]
//!   (`Pass` with possibly-redacted content, or `Reject` with a stable
//!   blame code + adopter-facing reason);
//! - **not registered** → OSS identity passthrough (backwards-compatible;
//!   adopters with no enterprise layer see their data unmodified).
//!
//! # Thread-safety / lifecycle
//!
//! The registry is a process-global behind an `RwLock`. Enterprise
//! registers its scanners once at server boot (mirroring the pre-v2.0.0
//! Python `default_registry`). Registration is `last-wins` per name, so a
//! deployment can override a scanner deterministically.

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, RwLock};

/// Context handed to a [`ShieldScanner`] on each invocation.
///
/// Intentionally minimal in 40.b (the field the scanner always needs); the
/// vertical scanners landing in 40.c extend their behaviour through their
/// own state, not by widening this struct, to keep the trait stable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShieldScanContext {
    /// The shield name as written in `shield apply <name> ...`.
    pub shield_name: String,
}

impl ShieldScanContext {
    /// Construct a context for `shield_name`.
    pub fn new(shield_name: impl Into<String>) -> Self {
        Self {
            shield_name: shield_name.into(),
        }
    }
}

/// A scanner's verdict on a target.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShieldVerdict {
    /// Content is allowed through, possibly transformed/redacted. The
    /// returned `String` is bound as the shield step's output.
    Pass(String),
    /// Content is rejected by policy. `code` is a stable slug for blame
    /// attribution (e.g. `"hipaa.phi_unredacted"`); `reason` is the
    /// adopter-facing message. The dispatcher surfaces this as a
    /// `DispatchError::BackendError { name: "shield:<name>", ... }`.
    Reject {
        /// Stable machine slug for blame attribution / metrics.
        code: String,
        /// Human-readable, adopter-facing rejection reason.
        reason: String,
    },
}

impl ShieldVerdict {
    /// Convenience constructor for a passing verdict.
    pub fn pass(content: impl Into<String>) -> Self {
        Self::Pass(content.into())
    }

    /// Convenience constructor for a rejecting verdict.
    pub fn reject(code: impl Into<String>, reason: impl Into<String>) -> Self {
        Self::Reject {
            code: code.into(),
            reason: reason.into(),
        }
    }

    /// True for [`ShieldVerdict::Pass`].
    pub fn is_pass(&self) -> bool {
        matches!(self, Self::Pass(_))
    }
}

/// Implemented by enterprise vertical scanners (HIPAA / legal / AML).
///
/// OSS ships **no** implementations. A scanner is pure-ish from the
/// dispatcher's perspective: given a target string + context it returns a
/// verdict. Scanners must be `Send + Sync` (the registry is shared across
/// the async runtime's worker threads).
pub trait ShieldScanner: Send + Sync {
    /// Scan `target` and return a [`ShieldVerdict`].
    fn scan(&self, target: &str, ctx: &ShieldScanContext) -> ShieldVerdict;
}

// ────────────────────────────────────────────────────────────────────────
//  Process-global registry
// ────────────────────────────────────────────────────────────────────────

static REGISTRY: LazyLock<RwLock<HashMap<String, Arc<dyn ShieldScanner>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

/// Register `scanner` under `shield_name`. Returns the previously
/// registered scanner for that name, if any (last-wins). Safe to call from
/// any thread; intended to run once per name at startup.
pub fn register_shield_scanner(
    shield_name: impl Into<String>,
    scanner: Arc<dyn ShieldScanner>,
) -> Option<Arc<dyn ShieldScanner>> {
    REGISTRY
        .write()
        .expect("shield registry RwLock poisoned")
        .insert(shield_name.into(), scanner)
}

/// Look up the scanner registered under `shield_name`, if any.
pub fn lookup_shield_scanner(shield_name: &str) -> Option<Arc<dyn ShieldScanner>> {
    REGISTRY
        .read()
        .expect("shield registry RwLock poisoned")
        .get(shield_name)
        .cloned()
}

/// True when at least one scanner is registered. Cheap O(1)-ish guard so
/// the dispatcher can skip the lookup entirely in the common OSS case (no
/// enterprise layer present).
pub fn has_registered_scanners() -> bool {
    !REGISTRY
        .read()
        .expect("shield registry RwLock poisoned")
        .is_empty()
}

/// All registered shield names, sorted (for discovery endpoints + audit
/// diagnostics). Deterministic ordering so wire/log output is stable.
pub fn registered_shield_names() -> Vec<String> {
    let mut names: Vec<String> = REGISTRY
        .read()
        .expect("shield registry RwLock poisoned")
        .keys()
        .cloned()
        .collect();
    names.sort();
    names
}

/// Remove the scanner registered under `shield_name`, returning it if
/// present. Mainly for deployments that hot-swap scanners + for tests.
pub fn unregister_shield_scanner(shield_name: &str) -> Option<Arc<dyn ShieldScanner>> {
    REGISTRY
        .write()
        .expect("shield registry RwLock poisoned")
        .remove(shield_name)
}

/// Clear the entire registry. Test-support + clean-shutdown helper.
#[doc(hidden)]
pub fn clear_shield_registry() {
    REGISTRY
        .write()
        .expect("shield registry RwLock poisoned")
        .clear();
}

#[cfg(test)]
mod tests {
    use super::*;

    // NOTE on test isolation: the registry is a process-global and cargo
    // runs tests in parallel. These tests therefore use UNIQUE shield
    // names (disjoint keys never collide under the RwLock), clean up after
    // themselves with `unregister_shield_scanner`, and never assert on
    // GLOBAL state (emptiness / the full name list) — only on the keys they
    // own. `clear_shield_registry` is deliberately NOT used here (it would
    // nuke a concurrent test's registration).

    struct UppercaseScanner;
    impl ShieldScanner for UppercaseScanner {
        fn scan(&self, target: &str, _ctx: &ShieldScanContext) -> ShieldVerdict {
            ShieldVerdict::pass(target.to_uppercase())
        }
    }

    struct AlwaysReject;
    impl ShieldScanner for AlwaysReject {
        fn scan(&self, _target: &str, ctx: &ShieldScanContext) -> ShieldVerdict {
            ShieldVerdict::reject(
                format!("{}.blocked", ctx.shield_name),
                "policy rejection (test)",
            )
        }
    }

    #[test]
    fn register_lookup_roundtrip() {
        const NAME: &str = "t_reg_roundtrip_upper";
        assert!(lookup_shield_scanner(NAME).is_none());

        let prev = register_shield_scanner(NAME, Arc::new(UppercaseScanner));
        assert!(prev.is_none(), "first registration has no predecessor");
        assert!(has_registered_scanners(), "at least our scanner is present");

        let s = lookup_shield_scanner(NAME).expect("registered");
        let v = s.scan("phi data", &ShieldScanContext::new(NAME));
        assert_eq!(v, ShieldVerdict::Pass("PHI DATA".to_string()));

        unregister_shield_scanner(NAME);
        assert!(lookup_shield_scanner(NAME).is_none());
    }

    #[test]
    fn last_wins_and_unregister() {
        const NAME: &str = "t_reg_last_wins";
        register_shield_scanner(NAME, Arc::new(UppercaseScanner));
        let prev = register_shield_scanner(NAME, Arc::new(AlwaysReject));
        assert!(prev.is_some(), "second registration returns the predecessor");

        let s = lookup_shield_scanner(NAME).unwrap();
        assert!(matches!(
            s.scan("x", &ShieldScanContext::new(NAME)),
            ShieldVerdict::Reject { .. }
        ));

        let removed = unregister_shield_scanner(NAME);
        assert!(removed.is_some());
        assert!(lookup_shield_scanner(NAME).is_none());
    }

    #[test]
    fn registered_names_includes_own_in_sorted_order() {
        // Unique prefix so we can filter out any concurrently-registered
        // scanners and assert only on the keys this test owns.
        let names = ["t_names_zeta", "t_names_alpha", "t_names_mu"];
        for n in names {
            register_shield_scanner(n, Arc::new(UppercaseScanner));
        }
        let mut mine: Vec<String> = registered_shield_names()
            .into_iter()
            .filter(|n| n.starts_with("t_names_"))
            .collect();
        // `registered_shield_names` is documented sorted; filtering
        // preserves order, so `mine` must already be sorted ascending.
        let mut expected = mine.clone();
        expected.sort();
        assert_eq!(mine, expected, "registered names must be returned sorted");
        mine.sort();
        assert_eq!(
            mine,
            vec![
                "t_names_alpha".to_string(),
                "t_names_mu".to_string(),
                "t_names_zeta".to_string()
            ]
        );
        for n in names {
            unregister_shield_scanner(n);
        }
    }

    #[test]
    fn verdict_constructors() {
        assert!(ShieldVerdict::pass("ok").is_pass());
        assert!(!ShieldVerdict::reject("c", "r").is_pass());
    }
}
