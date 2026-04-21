# SSO — Operator Guide

Production-grade OIDC + SAML 2.0 federation introduced in Fase 10.d
(v1.1.0). Replaces the v1.0.0 scaffolding (every method a `TODO`)
with signature-verifying, replay-defended, tenant-scoped flows.

## Architecture at a glance

```
   Browser ──► /sso/{tenant}/oidc/initiate
                    │ builds state + nonce + PKCE, persists SsoState row
                    ▼
               (302) to IdP authorization endpoint
                    │
                    │  user authenticates at IdP
                    ▼
   Browser ──► /sso/{tenant}/oidc/callback?state=&code=
                    │ consume state (single-use, replay-defended)
                    │ POST token endpoint with PKCE verifier
                    │ verify ID token sig against JWKS (cached)
                    │ validate iss + aud + exp + nbf + iat + nonce
                    │ map claims → MappedIdentity
                    │ upsert User + TenantMembership (rate-limited)
                    │ apply role_map (IdP groups → Axon roles)
                    │ mint Session via SessionService
                    ▼
                SsoLoginResult
```

Same shape for SAML: `POST /sso/{tenant}/saml/acs` replaces the
callback, `RelayState` carries our `state`, `SAMLResponse` replaces
`code`, and `python3-saml` handles the XML signature dance.

## Data model

| Table | Purpose | RLS |
|---|---|---|
| `sso_configurations` | Tenant-scoped IdP config, envelope-encrypted payload, `attribute_map`, `role_map`, `default_role_id`, `auto_provision`, `enabled` flag | `tenant_isolation + admin_bypass` |
| `sso_states` | Short-lived `(state, nonce, code_verifier, return_url)` per login attempt — consumed on first success, replay-rejected on second | `tenant_isolation + admin_bypass` |
| `sso_assertion_seen` | SAML assertion ID cache (48h window) for replay defence | `tenant_isolation + admin_bypass` |

The `config_encrypted` column is envelope-encrypted with AAD
`{tenant_id, provider_type, purpose="sso_config"}` so a ciphertext
cannot be smuggled between tenants or between OIDC and SAML slots.
Local backend (Fernet+HKDF) is accepted for dev; production **must**
use KMS (enforced by the settings validator from 10.b).

## OIDC — hardening checklist

- **Discovery** fetches `/.well-known/openid-configuration` with a
  1h TTL cache; concurrent lookups for the same issuer are
  de-duplicated behind an `asyncio.Lock`.
- **PKCE S256 is mandatory** — `plain` is a downgrade attack we do
  not support. The challenge sent to the IdP is SHA-256 of the raw
  verifier; verifier is posted to the token endpoint so only the
  originating client can complete the flow.
- **State** (32-byte URL-safe random) guards against CSRF and
  response stealing. Single-use via `SsoStateService.consume()`.
- **Nonce** (32-byte URL-safe random) is bound into the
  authorization URL and re-validated against the ID token's `nonce`
  claim — prevents replay of a stolen ID token across sessions.
- **JWKS** cached with 10min TTL. On `kid` miss we force-refresh
  once (standard rotation window). Supported key types: RSA
  (RS256/384/512), EC (ES256/384/512). `alg=none` is explicitly
  rejected.
- **ID token validation** uses `PyJWT` for signature +
  claim-level checks: `iss` matches configured issuer, `aud`
  contains the client_id, `exp`/`nbf`/`iat` within ±60s skew,
  `nonce` matches the stored value, `email_verified = true` (else
  `OidcEmailNotVerified`).
- **Token endpoint** POSTed with `client_id` + `code_verifier`.
  `client_secret` only included when the tenant configured a
  confidential client.

## SAML — hardening checklist

- **SP metadata** generated from `SpMetadataInput` (pure Python, no
  xmlsec dependency) at `/sso/{tenant}/saml/metadata.xml`.
- **AuthnRequest signed** with the tenant's SP private key when
  configured.
- **Response validation** delegated to `python3-saml` (OneLogin) —
  audited upstream library. It enforces:
  - XML signature on the `Response` and/or `Assertion`
  - `Destination` matches the SP ACS URL
  - `InResponseTo` matches an outstanding request
  - `Audience` restriction
  - `NotBefore` / `NotOnOrAfter` window
- **Assertion replay defence** — every processed assertion ID is
  inserted into `sso_assertion_seen`; the UNIQUE constraint converts
  a replay into `SamlAssertionReplay`. A cleanup job
  (`purge_assertion_seen`) removes rows older than 48h.
- **RelayState** carries our own `SsoState.state` so the response is
  tied to a specific outstanding request. Single-use.

## OIDC payload (envelope-encrypted at rest)

```json
{
  "issuer": "https://accounts.google.com",
  "client_id": "123456.apps.googleusercontent.com",
  "client_secret": "GOCSPX-...",
  "scopes": ["openid", "email", "profile"],
  "redirect_uri": "https://auth.bemarking.com/sso/acme/oidc/callback"
}
```

## SAML payload

```json
{
  "idp_entity_id": "https://idp.example.com",
  "idp_sso_url": "https://idp.example.com/sso",
  "idp_slo_url": "https://idp.example.com/slo",
  "idp_x509_cert": "-----BEGIN CERTIFICATE-----...",
  "sp_entity_id": "https://auth.bemarking.com/sso/acme/saml/metadata",
  "sp_acs_url":   "https://auth.bemarking.com/sso/acme/saml/acs",
  "sp_private_key": "-----BEGIN PRIVATE KEY-----...",
  "sp_x509_cert":   "-----BEGIN CERTIFICATE-----..."
}
```

Upsert both via `SsoConfigurationService.upsert()` — the service
validates required fields, rejects unknown providers, and transparently
envelope-encrypts the payload before persistence.

## Auto-provisioning

When `auto_provision = true` and the IdP-provided email has no
matching user, the service creates one with `email_verified = true`
(copied from the IdP) and a fresh `TenantMembership`. `default_role_id`
is assigned atomically.

**Rate limit**: 30 new users per minute per `(tenant, provider)` by
default (`sso.auto_provision_rate_limit_per_minute`). Exceeded
attempts raise `SsoRateLimited` — the request is rejected without
touching the DB, so a token-forgery flood cannot explode the users
table.

## Role mapping

`role_map` is a dict `{idp_group: axon_role_name}` stored alongside
the configuration. On login the service:

1. Extracts `groups` from the ID token claim (OIDC) or attribute
   statement (SAML) using the configured attribute key.
2. Translates each group through `role_map`.
3. Assigns every mapped role that exists in the tenant.

Unmapped groups are silently ignored — no implicit role creation.
The service never **revokes** roles on SSO login (admins can grant
additional roles out-of-band and those survive). A future
`role_sync_mode = strict` flag enables the revoke path when
compliance mandates it.

## Error codes (reveal-to-client matrix)

| Code | Reveal | Notes |
|---|---|---|
| `sso.not_configured` | ✅ | Harmless — tenant hasn't enabled SSO |
| `sso.provider_disabled` | ✅ | Config exists but `enabled=false` |
| `sso.state_invalid` | ❌ | Generic "session expired" to client |
| `sso.state_replayed` | ❌ | Silent — looks like `state_invalid` |
| `sso.state_expired` | ✅ | Safe — just re-initiate |
| `sso.oidc.id_token_invalid` | ❌ | Signature / claims failed — generic 401 |
| `sso.oidc.nonce_mismatch` | ❌ | Possible replay — generic 401 |
| `sso.oidc.pkce_mismatch` | ❌ | Misbehaving client — generic 401 |
| `sso.oidc.email_not_verified` | ✅ | Tells user to verify with IdP first |
| `sso.saml.response_invalid` | ❌ | Signature / window / audience failed |
| `sso.saml.assertion_replay` | ❌ | Silent |
| `sso.rate_limited` | ✅ | Client sees 429 with Retry-After |

## Service API

```python
from axon_enterprise.db.session import admin_session
from axon_enterprise.sso import SsoService, SsoProviderType

svc = SsoService.build()

# First-time config (envelope-encrypted automatically)
async with admin_session() as db:
    await svc.config_store.upsert(
        db,
        tenant_id="acme",
        provider_type=SsoProviderType.OIDC,
        payload=oidc_payload,
        attribute_map={"email": "email", "display_name": "name"},
        role_map={"engineers": "developer", "ops": "admin"},
        auto_provision=True,
        default_role_id=viewer_role_id,
    )

# Initiate (handler 302s to the returned URL)
async with admin_session() as db:
    url = await svc.initiate_oidc(db, tenant_id="acme", return_url="/app")

# Complete (handler reads state + code from the callback URL)
async with admin_session() as db:
    result = await svc.complete_oidc(
        db,
        tenant_id="acme",
        state=state,
        code=code,
        user_agent=request.headers["user-agent"],
        ip_address=request.client.host,
    )
    # result.session.raw_refresh_token returned to client ONCE.
```

## What comes next

Fase 10.e wires the JWT Issuer (signed with KMS-backed RS256) so
the Rust runtime can verify access tokens against a published JWKS
instead of the current unverified extraction. Fase 10.g emits
`auth.sso_login`, `auth.sso_provisioned`, and `sso.config_changed`
audit events into the hash-chained audit log. Fase 10.k exposes the
tenant-owner API for managing SsoConfiguration through a portal.
