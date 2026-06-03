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

// ────────────────────────────────────────────────────────────────────────
//  §Fase 53.e — NO PHANTOM GUARDRAILS (founder refinement C)
// ────────────────────────────────────────────────────────────────────────

/// Every `(shield_name, category)` where a shield declares an
/// EXTENSION-introduced scan category (one declared via an
/// `extension { category: scan }` block) but has **no registered
/// scanner** — i.e. a guardrail the operator believes is active that is
/// actually a silent no-op.
///
/// Canonical scan categories are intentionally NOT gated: they carry a
/// documented framework meaning, and the OSS identity passthrough (no
/// scanner) is the backwards-compatible default. Only adopter-introduced
/// extension categories — which have NO default semantics — require an
/// explicit scanner; serving one unscanned is a false sense of security.
pub fn unscanned_extension_scan_categories(
    ir: &crate::ir_nodes::IRProgram,
) -> Vec<(String, String)> {
    let mut ext_cats: std::collections::HashSet<&str> = std::collections::HashSet::new();
    for ext in &ir.extensions {
        if ext.category == "scan" {
            for m in &ext.members {
                ext_cats.insert(m.name.as_str());
            }
        }
    }
    if ext_cats.is_empty() {
        return Vec::new();
    }
    let mut violations = Vec::new();
    for shield in &ir.shields {
        // A registered scanner owns the shield: it is responsible for the
        // declared categories. Only a shield with NO scanner can leave an
        // extension category as a ghost guardrail.
        if lookup_shield_scanner(&shield.name).is_some() {
            continue;
        }
        for cat in &shield.scan {
            if ext_cats.contains(cat.as_str()) {
                violations.push((shield.name.clone(), cat.clone()));
            }
        }
    }
    violations
}

/// §Fase 53.e — the boot gate. `Ok(())` when every extension scan
/// category used by a shield has a registered scanner; `Err(blame)` (a
/// Server-Blame message) otherwise. The boot sequence MUST treat `Err`
/// as FATAL — refuse to serve rather than present a ghost guardrail
/// (founder refinement C: no silent no-op, fail loud).
pub fn check_extension_scan_coverage(ir: &crate::ir_nodes::IRProgram) -> Result<(), String> {
    let violations = unscanned_extension_scan_categories(ir);
    if violations.is_empty() {
        return Ok(());
    }
    let detail = violations
        .iter()
        .map(|(s, c)| format!("shield '{s}' → scan category '{c}'"))
        .collect::<Vec<_>>()
        .join("; ");
    Err(format!(
        "§Fase 53.e refusing to boot — extension scan categor(ies) declared but \
         UNSCANNED (no scanner registered): {detail}. An `extension` scan category \
         has no default meaning; serving it as a silent no-op would be a phantom \
         guardrail. Register a scanner for the shield(s) or remove the category."
    ))
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

    // ── §Fase 53.e — phantom-guardrail boot gate ───────────────────

    fn ir_from(src: &str) -> crate::ir_nodes::IRProgram {
        let tokens = crate::lexer::Lexer::new(src, "<test>")
            .tokenize()
            .expect("lex");
        let program = crate::parser::Parser::new(tokens).parse().expect("parse");
        crate::ir_generator::IRGenerator::new().generate(&program)
    }

    struct PassScanner;
    impl ShieldScanner for PassScanner {
        fn scan(&self, target: &str, _ctx: &ShieldScanContext) -> ShieldVerdict {
            ShieldVerdict::pass(target.to_string())
        }
    }

    /// A shield using ONLY canonical scan categories (no scanner) is NOT
    /// a violation — the canonical passthrough is the documented default.
    #[test]
    fn canonical_category_without_scanner_is_not_a_violation() {
        let ir = ir_from(
            "shield T53e_canon { scan: [code_injection] strategy: pattern on_breach: halt }",
        );
        assert!(unscanned_extension_scan_categories(&ir).is_empty());
        assert!(check_extension_scan_coverage(&ir).is_ok());
    }

    /// A shield using an EXTENSION scan category with NO registered
    /// scanner is a phantom guardrail → reported + boot refused.
    #[test]
    fn extension_category_without_scanner_is_a_violation() {
        let ir = ir_from(
            "extension t53e_x { category: scan members: [ \"dunning_pressure\" ] }\n\
             shield T53e_ghost { scan: [dunning_pressure] strategy: pattern on_breach: halt }",
        );
        let v = unscanned_extension_scan_categories(&ir);
        assert_eq!(
            v,
            vec![("T53e_ghost".to_string(), "dunning_pressure".to_string())]
        );
        let err = check_extension_scan_coverage(&ir).expect_err("must refuse boot");
        assert!(err.contains("phantom guardrail"), "got: {err}");
        assert!(err.contains("dunning_pressure"), "got: {err}");
    }

    /// Same source, but a scanner registered under the shield name → the
    /// extension category is covered → no violation.
    #[test]
    fn extension_category_with_scanner_is_ok() {
        const SHIELD: &str = "T53e_covered";
        let _prev = register_shield_scanner(SHIELD, Arc::new(PassScanner));
        let ir = ir_from(&format!(
            "extension t53e_y {{ category: scan members: [ \"dunning_pressure\" ] }}\n\
             shield {SHIELD} {{ scan: [dunning_pressure] strategy: pattern on_breach: halt }}"
        ));
        let ok = check_extension_scan_coverage(&ir);
        // Clean up BEFORE asserting so a failure doesn't leak the scanner.
        unregister_shield_scanner(SHIELD);
        assert!(ok.is_ok(), "a registered scanner must cover the category: {ok:?}");
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
