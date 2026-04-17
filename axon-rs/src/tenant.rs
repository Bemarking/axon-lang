/// Tenant identity and request extraction for Axon Enterprise multi-tenancy.
///
/// Resolves the active tenant from every inbound HTTP request via:
///   1. `X-Tenant-ID` header  (direct, service-to-service calls)
///   2. `Authorization: Bearer <jwt>` claim `"tenant_id"` (user-facing flows)
///   3. Fallback → `"default"` (single-tenant / open-source installs)
///
/// The resolved `TenantContext` is injected as an Axum request extension so
/// any handler can read it with `Extension<TenantContext>`.
use axum::{
    body::Body,
    extract::Request,
    http::{HeaderMap, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Extension,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;

// ── TenantPlan ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TenantPlan {
    Starter,
    Pro,
    Enterprise,
}

impl TenantPlan {
    pub fn from_str(s: &str) -> Self {
        match s {
            "pro" => Self::Pro,
            "enterprise" => Self::Enterprise,
            _ => Self::Starter,
        }
    }
}

impl std::fmt::Display for TenantPlan {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Starter => write!(f, "starter"),
            Self::Pro => write!(f, "pro"),
            Self::Enterprise => write!(f, "enterprise"),
        }
    }
}

// ── TenantContext ─────────────────────────────────────────────────────────────

/// Resolved tenant identity, available in every request handler as an
/// Axum `Extension<TenantContext>`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TenantContext {
    pub tenant_id: String,
    pub plan: TenantPlan,
}

impl TenantContext {
    pub fn new(tenant_id: impl Into<String>, plan: TenantPlan) -> Self {
        Self { tenant_id: tenant_id.into(), plan }
    }

    /// The default / open-source single-tenant context.
    pub fn default_tenant() -> Self {
        Self { tenant_id: "default".to_string(), plan: TenantPlan::Enterprise }
    }

    pub fn is_default(&self) -> bool {
        self.tenant_id == "default"
    }
}

// ── JWT claim extraction ──────────────────────────────────────────────────────

/// Attempt to extract `tenant_id` from the payload of a JWT without verifying
/// the signature. Signature verification is the responsibility of the auth
/// middleware layer that runs before handlers.
fn tenant_id_from_jwt(token: &str) -> Option<String> {
    let parts: Vec<&str> = token.splitn(3, '.').collect();
    if parts.len() < 2 {
        return None;
    }
    let payload_bytes = URL_SAFE_NO_PAD.decode(parts[1]).ok()?;
    let claims: Value = serde_json::from_slice(&payload_bytes).ok()?;
    claims.get("tenant_id")?.as_str().map(|s| s.to_string())
}

/// Extract tenant_id from `Authorization: Bearer <token>` header.
fn tenant_id_from_bearer(headers: &HeaderMap) -> Option<String> {
    let auth = headers.get("authorization")?.to_str().ok()?;
    let token = auth.strip_prefix("Bearer ")?;
    tenant_id_from_jwt(token)
}

// ── Axum middleware ───────────────────────────────────────────────────────────

/// Axum middleware that resolves the active tenant and injects
/// `TenantContext` into request extensions.
///
/// Resolution order:
///   1. `X-Tenant-ID` header
///   2. `tenant_id` claim in `Authorization: Bearer <jwt>`
///   3. Fallback: `TenantContext::default_tenant()`
pub async fn tenant_extractor_middleware(
    mut req: Request<Body>,
    next: Next,
) -> Response {
    let headers = req.headers().clone();

    let ctx = if let Some(tid) = headers
        .get("x-tenant-id")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
    {
        TenantContext::new(tid, TenantPlan::Enterprise)
    } else if let Some(tid) = tenant_id_from_bearer(&headers) {
        TenantContext::new(tid, TenantPlan::Enterprise)
    } else {
        TenantContext::default_tenant()
    };

    tracing::debug!(
        tenant_id = %ctx.tenant_id,
        plan = %ctx.plan,
        "tenant resolved"
    );

    req.extensions_mut().insert(ctx);
    next.run(req).await
}

// ── Helper for handlers ───────────────────────────────────────────────────────

/// Extract `TenantContext` from request extensions.
/// Returns `(StatusCode::UNAUTHORIZED, ...)` if not present (should not happen
/// when the middleware is correctly wired).
pub fn require_tenant(
    ext: Option<Extension<TenantContext>>,
) -> Result<TenantContext, Response> {
    ext.map(|Extension(ctx)| ctx)
        .ok_or_else(|| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                "TenantContext missing — tenant_extractor_middleware not wired",
            )
                .into_response()
        })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};

    fn make_jwt(payload_json: &str) -> String {
        let header = URL_SAFE_NO_PAD.encode(r#"{"alg":"HS256","typ":"JWT"}"#);
        let payload = URL_SAFE_NO_PAD.encode(payload_json);
        format!("{}.{}.fakesig", header, payload)
    }

    #[test]
    fn test_tenant_plan_from_str() {
        assert_eq!(TenantPlan::from_str("starter"), TenantPlan::Starter);
        assert_eq!(TenantPlan::from_str("pro"), TenantPlan::Pro);
        assert_eq!(TenantPlan::from_str("enterprise"), TenantPlan::Enterprise);
        assert_eq!(TenantPlan::from_str("unknown"), TenantPlan::Starter);
    }

    #[test]
    fn test_tenant_plan_display() {
        assert_eq!(TenantPlan::Starter.to_string(), "starter");
        assert_eq!(TenantPlan::Pro.to_string(), "pro");
        assert_eq!(TenantPlan::Enterprise.to_string(), "enterprise");
    }

    #[test]
    fn test_default_tenant() {
        let ctx = TenantContext::default_tenant();
        assert_eq!(ctx.tenant_id, "default");
        assert!(ctx.is_default());
        assert_eq!(ctx.plan, TenantPlan::Enterprise);
    }

    #[test]
    fn test_tenant_id_from_jwt_valid() {
        let jwt = make_jwt(r#"{"sub":"user123","tenant_id":"acme-corp"}"#);
        assert_eq!(tenant_id_from_jwt(&jwt), Some("acme-corp".to_string()));
    }

    #[test]
    fn test_tenant_id_from_jwt_missing_claim() {
        let jwt = make_jwt(r#"{"sub":"user123"}"#);
        assert_eq!(tenant_id_from_jwt(&jwt), None);
    }

    #[test]
    fn test_tenant_id_from_jwt_malformed() {
        assert_eq!(tenant_id_from_jwt("not.a.jwt.at.all"), None);
        assert_eq!(tenant_id_from_jwt("onlyone"), None);
    }

    #[test]
    fn test_tenant_id_from_bearer_valid() {
        let jwt = make_jwt(r#"{"tenant_id":"kivi-kas"}"#);
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            format!("Bearer {}", jwt).parse().unwrap(),
        );
        assert_eq!(tenant_id_from_bearer(&headers), Some("kivi-kas".to_string()));
    }

    #[test]
    fn test_tenant_id_from_bearer_missing() {
        let headers = HeaderMap::new();
        assert_eq!(tenant_id_from_bearer(&headers), None);
    }

    #[test]
    fn test_tenant_context_new() {
        let ctx = TenantContext::new("acme", TenantPlan::Pro);
        assert_eq!(ctx.tenant_id, "acme");
        assert_eq!(ctx.plan, TenantPlan::Pro);
        assert!(!ctx.is_default());
    }
}
