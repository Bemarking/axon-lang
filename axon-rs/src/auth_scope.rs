//! §Fase 32.g — Auth scope (capability subset matching) for first-class
//! axonendpoint routes.
//!
//! D8 ratificada 2026-05-11. When an axonendpoint declares
//! `requires: [admin, legal.read, …]`, the runtime verifies the request
//! bearer's capabilities contain every declared capability (AND
//! semantics). Missing capability → 403 Forbidden with a structured
//! error so the client KNOWS which capability is needed.
//!
//! ## Closed slug grammar (mirror of `axon_frontend::parser::is_valid_capability_slug`)
//!
//! `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`
//!
//! - Each segment starts with a lowercase letter.
//! - Each segment contains lowercase letters, digits, or underscores.
//! - Segments separated by single dots.
//!
//! Closed grammar refuses interpretation drift — adopters can't
//! accidentally introduce slug shapes that fail to match in production
//! (e.g. `Admin`, `legal-read`).
//!
//! ## OSS vs enterprise capability surface
//!
//! - **OSS (this module)**: capabilities are read from the JWT bearer's
//!   `capabilities` claim. No signature verification at this layer
//!   (signature is verified by `tenant_extractor_middleware` upstream
//!   when JWKS is configured). The unverified-decode path matches the
//!   existing `tenant_id_from_bearer_unverified` precedent for single-
//!   tenant / dev installs.
//! - **Enterprise** (Fase 21 integration surface): capabilities are
//!   registered + version-introspected via `/.well-known/axon-
//!   capabilities`; auditors verify the runtime's capability set matches
//!   the deployed source. Layered on top of this OSS primitive.
//!
//! ## Pillar trace per D12
//!
//! - **PHILOSOPHY** — the access contract IS the source declaration:
//!   auditors read source + KNOW which endpoints require which
//!   capabilities. No middleware side-channel.
//! - **LOGIC** — `declared_requires ⊆ token_capabilities` is the
//!   precise subset predicate; total boolean over the two sets.
//! - **MATHEMATICS** — capability matching is set-theoretic: subset
//!   check is associative, idempotent, and decidable.
//! - **COMPUTING** — D9 backwards-compat absolute: empty `requires`
//!   list short-circuits to pass-through; no behavior change for
//!   v1.20.x–v1.22.x adopters.

use std::collections::BTreeSet;

use axum::http::HeaderMap;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde_json::Value;

/// Result of an auth-scope check. Total enum — every input maps to
/// exactly one variant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthVerdict {
    /// No `requires:` declared, OR bearer holds every required slug.
    Allow,
    /// Bearer is missing one or more declared capabilities. The
    /// payload surfaces BOTH lists so the adopter client can correct
    /// the request without server-log diving (precise, auditable).
    Deny {
        missing: Vec<String>,
        required: Vec<String>,
        have: Vec<String>,
    },
}

/// Re-export the parser-layer slug validator so runtime callers
/// (config loaders, dynamic ingestion paths, fuzz harnesses) hit the
/// same predicate the parser enforces. Single source of truth across
/// compile time + runtime + tests.
pub fn is_valid_capability_slug(slug: &str) -> bool {
    crate::parser::is_valid_capability_slug(slug)
}

/// Extract the bearer's capability slugs from `Authorization: Bearer
/// <jwt>`. Returns an empty vec when there's no bearer, the token
/// isn't a structurally-valid JWT, or the payload doesn't carry a
/// `capabilities` claim.
///
/// Signature verification is performed UPSTREAM by
/// `tenant_extractor_middleware` when `AXON_JWT_JWKS_URL` is set.
/// In OSS / single-tenant installs without JWKS, this decode is
/// unverified — matching the existing precedent in
/// `axon::tenant::tenant_id_from_bearer_unverified`. Adopters in
/// production who need verified extraction layer enterprise auth
/// middleware on top.
///
/// The `capabilities` claim MUST be a JSON array of strings. Other
/// shapes (object, scalar) are treated as "no capabilities" — be
/// strict in what we accept (D8 + LOGIC pillar).
pub fn extract_capabilities_from_bearer(headers: &HeaderMap) -> Vec<String> {
    let auth = match headers.get("authorization").and_then(|v| v.to_str().ok()) {
        Some(a) => a,
        None => return Vec::new(),
    };
    let token = match auth.strip_prefix("Bearer ") {
        Some(t) => t,
        None => return Vec::new(),
    };
    let parts: Vec<&str> = token.splitn(3, '.').collect();
    if parts.len() < 2 {
        return Vec::new();
    }
    let payload_bytes = match URL_SAFE_NO_PAD.decode(parts[1]) {
        Ok(b) => b,
        Err(_) => return Vec::new(),
    };
    let claims: Value = match serde_json::from_slice(&payload_bytes) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };
    let arr = match claims.get("capabilities").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return Vec::new(),
    };
    arr.iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect()
}

/// Subset check: are all `declared` capabilities present in `have`?
///
/// Total predicate. Empty `declared` returns `Allow` unconditionally
/// (D9 backwards-compat). Returns `Deny` with `missing` = `declared \
/// have`, preserving declaration order for client-side diagnostic
/// continuity.
pub fn check_capabilities(declared: &[String], have: &[String]) -> AuthVerdict {
    if declared.is_empty() {
        return AuthVerdict::Allow;
    }
    let have_set: BTreeSet<&str> = have.iter().map(|s| s.as_str()).collect();
    let missing: Vec<String> = declared
        .iter()
        .filter(|d| !have_set.contains(d.as_str()))
        .cloned()
        .collect();
    if missing.is_empty() {
        AuthVerdict::Allow
    } else {
        AuthVerdict::Deny {
            missing,
            required: declared.to_vec(),
            have: have.to_vec(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    fn jwt_with_caps(caps: &[&str]) -> String {
        let header = URL_SAFE_NO_PAD.encode(b"{\"alg\":\"none\",\"typ\":\"JWT\"}");
        let payload_json = serde_json::json!({"capabilities": caps});
        let payload =
            URL_SAFE_NO_PAD.encode(serde_json::to_vec(&payload_json).unwrap());
        format!("{header}.{payload}.")
    }

    fn headers_with_auth(token: &str) -> HeaderMap {
        let mut h = HeaderMap::new();
        let value = format!("Bearer {token}");
        h.insert("authorization", HeaderValue::from_str(&value).unwrap());
        h
    }

    #[test]
    fn no_bearer_returns_empty_capabilities() {
        let h = HeaderMap::new();
        assert!(extract_capabilities_from_bearer(&h).is_empty());
    }

    #[test]
    fn malformed_token_returns_empty_capabilities() {
        let h = headers_with_auth("not-a-jwt");
        assert!(extract_capabilities_from_bearer(&h).is_empty());
    }

    #[test]
    fn token_without_capabilities_claim_returns_empty() {
        let header = URL_SAFE_NO_PAD.encode(b"{\"alg\":\"none\"}");
        let payload = URL_SAFE_NO_PAD.encode(b"{\"sub\":\"alice\"}");
        let token = format!("{header}.{payload}.");
        let h = headers_with_auth(&token);
        assert!(extract_capabilities_from_bearer(&h).is_empty());
    }

    #[test]
    fn extracts_array_of_capabilities() {
        let h = headers_with_auth(&jwt_with_caps(&["admin", "legal.read"]));
        let caps = extract_capabilities_from_bearer(&h);
        assert_eq!(caps, vec!["admin".to_string(), "legal.read".to_string()]);
    }

    #[test]
    fn check_allows_empty_required() {
        // D9 backwards-compat path.
        let v = check_capabilities(&[], &[]);
        assert_eq!(v, AuthVerdict::Allow);
        let v = check_capabilities(&[], &["admin".to_string()]);
        assert_eq!(v, AuthVerdict::Allow);
    }

    #[test]
    fn check_allows_exact_match() {
        let v = check_capabilities(
            &["admin".to_string()],
            &["admin".to_string()],
        );
        assert_eq!(v, AuthVerdict::Allow);
    }

    #[test]
    fn check_allows_superset() {
        let v = check_capabilities(
            &["admin".to_string()],
            &["admin".to_string(), "other".to_string()],
        );
        assert_eq!(v, AuthVerdict::Allow);
    }

    #[test]
    fn check_denies_missing() {
        let v = check_capabilities(
            &["admin".to_string(), "legal.read".to_string()],
            &["admin".to_string()],
        );
        match v {
            AuthVerdict::Deny { missing, required, have } => {
                assert_eq!(missing, vec!["legal.read".to_string()]);
                assert_eq!(required.len(), 2);
                assert_eq!(have.len(), 1);
            }
            _ => panic!("expected Deny"),
        }
    }

    #[test]
    fn check_denies_empty_have() {
        let v = check_capabilities(
            &["admin".to_string()],
            &[],
        );
        match v {
            AuthVerdict::Deny { missing, .. } => {
                assert_eq!(missing, vec!["admin".to_string()]);
            }
            _ => panic!("expected Deny"),
        }
    }

    #[test]
    fn check_preserves_declaration_order_in_missing() {
        // Diagnostic continuity — adopter sees missing in source-
        // declaration order, not hash-table order.
        let v = check_capabilities(
            &[
                "a".to_string(),
                "b".to_string(),
                "c".to_string(),
                "d".to_string(),
            ],
            &["b".to_string()],
        );
        match v {
            AuthVerdict::Deny { missing, .. } => {
                assert_eq!(missing, vec!["a", "c", "d"]);
            }
            _ => panic!("expected Deny"),
        }
    }

    #[test]
    fn capabilities_claim_with_non_string_values_drops_them() {
        // Defensive: a malformed token containing mixed types in the
        // capabilities array drops the non-strings (extract_*) which
        // preserves the strict type contract — capabilities are
        // strings, period.
        let header = URL_SAFE_NO_PAD.encode(b"{\"alg\":\"none\"}");
        let payload = URL_SAFE_NO_PAD.encode(
            b"{\"capabilities\":[\"admin\",42,null,\"legal.read\"]}",
        );
        let token = format!("{header}.{payload}.");
        let h = headers_with_auth(&token);
        let caps = extract_capabilities_from_bearer(&h);
        assert_eq!(caps, vec!["admin".to_string(), "legal.read".to_string()]);
    }

    #[test]
    fn slug_validator_round_trip_with_parser() {
        // Anchor: the runtime + parser share ONE predicate. Confirm
        // a sample of accepted + rejected slugs.
        assert!(is_valid_capability_slug("admin"));
        assert!(is_valid_capability_slug("legal.read"));
        assert!(!is_valid_capability_slug("Admin"));
        assert!(!is_valid_capability_slug("bank-officer"));
        assert!(!is_valid_capability_slug(""));
    }
}
