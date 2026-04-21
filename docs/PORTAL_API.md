# Portal API — Tenant Self-Service Guide

Fase 10.k. The Portal API is the HTTP surface tenant admins and
end-user applications drive day-to-day. It lives under `/api/v1`
and is mounted by the same `build_app()` factory as the Admin API
(`/admin/*`) and the inbound webhook sink (`/webhooks/*`).

Every route is served by the same Starlette app. Authentication
rules differ per prefix:

| Prefix | Auth |
|---|---|
| `/api/v1/auth/login`, `/refresh`, `/invite/accept` | Public |
| `/api/v1/sso/oidc/initiate`, `/oidc/callback`, `/saml/*` | Public (provider-driven) |
| `/api/v1/tenant/*` | Bearer JWT (minted by `/auth/login` or SSO) |
| `/webhooks/stripe` | Public; re-authenticates via `Stripe-Signature` HMAC |

The bearer JWT is verified in-process via the `AuthMiddleware`
(10.j) against the JWKS document at `/.well-known/jwks.json`
published by the 10.e issuer.

## Authentication

### Password login

```bash
curl -X POST https://auth.bemarking.com/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{
           "email": "alice@acme.example",
           "password": "<password>",
           "tenant_id": "acme",
           "totp_code": "123456"
         }'
```

Response:

```json
{
  "access_token": "<RS256 JWT>",
  "refresh_token": "<opaque base64url>",
  "expires_at": "2026-04-21T10:00:00+00:00",
  "user": {"user_id": "<uuid>", "email": "alice@acme.example", "display_name": "Alice"},
  "tenant_id": "acme"
}
```

Failure cases:

- `401 identity.invalid_credentials` — email/password mismatch
- `401 identity.totp_required` / `identity.totp_failed` — TOTP enforced
- `423 identity.account_locked` — progressive lockout tripped (see 10.b)

### Refresh

```bash
POST /api/v1/auth/refresh
{"refresh_token": "<opaque>"}
```

The server rotates the refresh token on every successful call.
Presenting a rotated-out token is treated as replay and revokes
the entire session chain.

### Logout

```bash
POST /api/v1/auth/logout
{"refresh_token": "<opaque>"}
```

Marks the session row as revoked. The access JWT remains valid
until it expires — short access lifetimes (default 10 min) are the
mitigation here.

### Invitation accept

```bash
POST /api/v1/auth/invite/accept
{"token": "<raw token from email link>"}
```

Consumes the one-time magic-link token and returns an access JWT
plus a refresh token for the invited user. See *Inviting users*.

## SSO routes

### OIDC

```bash
POST /api/v1/sso/oidc/initiate        # returns {"authorization_url"}
GET  /api/v1/sso/oidc/callback?tenant_id=&state=&code=
```

Delegates to the `SsoService` from 10.d. PKCE S256 and state
correlation are enforced; discovery + JWKS are cached per-tenant.

### SAML

```bash
GET  /api/v1/sso/saml/{tenant_id}/metadata.xml   # SP metadata for IdP
POST /api/v1/sso/saml/{tenant_id}/acs            # HTTP-POST ACS
```

Assertion replay is prevented by a `UNIQUE (tenant_id, assertion_id)`
row in `axon_control.sso_assertions_seen` — second presentation of
the same assertion is rejected with a `sso.assertion_replay` audit
event.

## Tenant self-service

### Inviting users

```bash
POST /api/v1/tenant/users/invite
Authorization: Bearer <tenant admin JWT>

{"email": "bob@acme.example", "display_name": "Bob", "role_name": "developer"}
```

Response:

```json
{
  "user_id": "<uuid>",
  "email": "bob@acme.example",
  "invitation_token": "<raw token — email to invitee>",
  "invitation_expires_at": "2026-04-24T10:00:00+00:00",
  "assigned_role": "developer"
}
```

Only the SHA-256 hash of the token lands in the DB
(`axon_control.tenant_memberships.invitation_token_hash`). Default
TTL is 72h. On accept the column is cleared, so replay is blocked
by construction.

Other user-management routes:

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/tenant/users/` | List members of the caller's tenant |
| DELETE | `/api/v1/tenant/users/{user_id}` | Flip membership status to `suspended` |
| PATCH  | `/api/v1/tenant/users/{user_id}/roles` | Replace role assignments |

### API keys (M2M)

Raw key format: `axk_<32 hex chars>`. The `axk_` prefix is stable
across all tenants so operators can grep logs + access records for
credential leakage. Storage keeps only the Argon2id hash plus the
first 8 hex chars (used as a narrowing index for the verify-time
lookup); the raw key is returned **exactly once** on creation.

```bash
POST /api/v1/tenant/api-keys/
Authorization: Bearer <tenant admin JWT>

{"name": "production-ingest", "expires_at": "2027-01-01T00:00:00Z"}
```

Response (201):

```json
{
  "api_key_id": "<uuid>",
  "name": "production-ingest",
  "key_prefix": "a1b2c3d4",
  "raw_key": "axk_a1b2c3d4e5f6...",
  "expires_at": "2027-01-01T00:00:00+00:00"
}
```

**Do not store the `raw_key` anywhere else; the API will never
return it again.** Lost keys must be revoked and replaced.

Listing + revoke:

```bash
GET    /api/v1/tenant/api-keys/                  # metadata only, never the raw key
DELETE /api/v1/tenant/api-keys/{api_key_id}      # sets revoked_at
```

Keys can be used in place of a bearer JWT on downstream data-plane
requests. The verification path (`ApiKeyService.verify`) indexes
by the 8-hex prefix then Argon2-verifies exactly one candidate per
request, bounded by `identity.argon2_time_cost`.

### Usage + invoices

```bash
GET /api/v1/tenant/usage/             # current period aggregated totals by metric
GET /api/v1/tenant/usage/invoices     # all invoices ever issued for the tenant
```

Both are read-only. Period aggregation runs through `aggregate_period`
(10.h) and reads `usage_events` under tenant RLS.

### Compliance — GDPR

```bash
POST /api/v1/tenant/compliance/export       # Subject Access Request
POST /api/v1/tenant/compliance/erase        # Right to Erasure
```

Both endpoints currently **queue** the request (202 Accepted + a
`ticket_id`) and emit `compliance:export_requested` /
`compliance:erasure_requested` audit events. Full execution — the
export bundle ZIP, the phased purge across tenant tables — lands
in 10.l alongside the retention + legal-hold tooling.

## Stripe webhook

```
POST /webhooks/stripe
```

Verifies the `Stripe-Signature` header against
`metering.stripe_webhook_secret` using the official stripe-python
SDK. Handled event types:

| `event["type"]` | Effect |
|---|---|
| `invoice.finalized`      | `Invoice.status → finalized` |
| `invoice.paid`           | `Invoice.status → paid`, `paid_at := now()` |
| `invoice.payment_failed` | `Invoice.status → failed` |
| `invoice.voided`         | `Invoice.status → void` |

Every other event returns `204 No Content` so Stripe stops
retrying. Stripe's `event["id"]` is the delivery dedupe key;
because every mapping above is idempotent, we tolerate at-least-
once delivery without a dedupe table. When 10.l introduces
side-effecting handlers (e.g., billing-driven tenant suspension)
the dedupe table lands alongside them.

## Errors

Every failure path goes through the 10.j typed-error mapper. The
wire shape is always:

```json
{
  "error": {
    "code": "identity.invalid_credentials",
    "message": "Invalid email or password."
  }
}
```

`message` is safe to surface in the UI — the mapper strips internal
details unless the error's `reveal_to_client` flag is set. Inspect
`.code` for programmatic handling; the string shape is part of the
public API contract.
