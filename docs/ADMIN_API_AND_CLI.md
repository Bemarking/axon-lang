# Admin API + CLI — Operator Guide

Fase 10.j. Exposes every service built in 10.a–10.i through an
HTTP layer (Starlette, pure ASGI — no FastAPI) and a Typer CLI.
All business logic stays in the service layer; the HTTP +
CLI entry points are thin adapters.

## HTTP app

```python
from axon_enterprise.http import build_app

app = build_app()   # ready for `uvicorn axon_enterprise.http:app`
```

The factory wires:

- `ObservabilityMiddleware` (outermost — always records metrics)
- `AuthMiddleware` (inner — verifies JWT, sets `PrincipalContext`
  ContextVar, enforces tenant binding)
- Route tree:
  - `/.well-known/jwks.json` — public; published by 10.e issuer
  - `/healthz` + `/readyz` — public; liveness + readiness probes
  - `/metrics` — public; Prometheus scrape target
  - `/admin/*` — admin API; JWT required + control-plane tenant
- Error handlers mapping every typed `IdentityError` subclass to
  the correct HTTP status with the reveal-to-client contract applied

Middleware order matters — `AuthMiddleware` runs **inside**
`ObservabilityMiddleware` so failed auth requests still emit
metrics + logs.

## Admin API routes

All under `/admin`. Every handler verifies the caller is a member
of the control-plane admin tenant (`default` by default) with an
`owner` role — the coarse gate before RBAC fine-grained checks.

### Tenants

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/tenants/` | Create tenant + seed RBAC roles + subscription |
| GET  | `/admin/tenants/` | Paginated list with optional `?status=` filter |
| GET  | `/admin/tenants/{tenant_id}` | Fetch a single tenant |
| POST | `/admin/tenants/{tenant_id}/suspend` | Flip status to `suspended` |
| POST | `/admin/tenants/{tenant_id}/resume` | Flip back to `active` |

```bash
curl -X POST http://auth.bemarking.com/admin/tenants/ \
     -H "Authorization: Bearer ${OPERATOR_JWT}" \
     -H "Content-Type: application/json" \
     -d '{
           "slug": "acme",
           "name": "Acme Corp",
           "plan_id": "enterprise",
           "owner_user_id": "<uuid>"
         }'
```

Response:

```json
{
  "tenant_id": "acme",
  "name": "Acme Corp",
  "plan_id": "enterprise",
  "status": "active",
  "roles": {
    "owner": "<uuid>",
    "admin": "<uuid>",
    "developer": "<uuid>",
    "viewer": "<uuid>"
  }
}
```

### Users

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/users/` | Register a user via `AuthService.register` |
| GET  | `/admin/users/` | Paginated list |
| DELETE | `/admin/users/{user_id}` | Flip status to `suspended` |

### JWT signing keys

| Method | Path | Purpose |
|---|---|---|
| GET  | `/admin/keys/` | List active + grace keys |
| POST | `/admin/keys/kms` | Register a KMS key (demotes current active to grace) |
| POST | `/admin/keys/rotate` | Create a new active key (KMS ARN or local generation) |
| POST | `/admin/keys/retire-grace` | Retire grace keys past their `grace_until` |

### Audit

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/audit/{tenant_id}/verify` | Walk the hash chain; returns `AuditChainReport` |
| GET  | `/admin/audit/{tenant_id}/events` | Cross-tenant event export |

## Pagination

Two shapes:

- **Offset** (`?limit=&offset=`) for small admin tables: tenants,
  users, roles. Total count included so the UI can render page
  numbers.
- **Cursor** (`?cursor=<base64>`) for high-volume tables:
  `usage_events`, `audit_events`. Stable across inserts because
  the cursor encodes `(last_created_at, last_id)` and the query
  filters `WHERE (created_at, id) < (cursor.ts, cursor.id)`.

`limit` is capped at `max_limit` per endpoint (default 500; audit
listing bumps it to 1000).

## Error shape

Every response is JSON. The typed-error mapper emits:

```json
{
  "error": {
    "code": "rbac.permission_denied",
    "message": "permission denied: secret:write"
  }
}
```

Status codes:

| Status | When |
|---|---|
| 400 | Password policy, invalid permission string, malformed input |
| 401 | Authentication required / session expired / TOTP failed |
| 402 | QuotaExceeded — hard_cap tenant exceeded its allowance |
| 403 | PermissionDenied / AccountLockedError / SsoProviderDisabled |
| 404 | SecretNotFound / RoleNotFound / SsoConfigurationNotFound |
| 409 | EmailAlreadyRegistered / RoleCycleError |
| 410 | SsoStateExpired |
| 413 | SecretValueTooLarge |
| 422 | SsoStateInvalid |
| 429 | RateLimited — includes `Retry-After` header |
| 500 | Unexpected error — body collapsed to opaque `"internal"` |

`reveal_to_client=False` errors (InvalidCredentials, TotpVerification,
…) collapse to the generic family message (`"Authentication
required"`) so observers can't enumerate which step failed.

## CLI — `axon-enterprise`

Typer-based. Installed via ``pyproject.toml``'s ``project.scripts``:

```
[project.scripts]
axon-enterprise = "axon_enterprise.cli:entrypoint"
```

All commands share the same Postgres + services the HTTP layer uses
— no second code path for ops.

### `axon-enterprise tenant ...`

```bash
axon-enterprise tenant create --slug acme --name "Acme" --plan pro \
                              --owner-user-id <uuid>
axon-enterprise tenant list --status active --limit 20
axon-enterprise tenant suspend acme --reason "payment overdue"
axon-enterprise tenant resume acme
```

### `axon-enterprise user ...`

```bash
# Password from stdin — never on argv
echo "correct-horse-battery-staple-9" | \
  axon-enterprise user create --email alice@acme.com \
                              --display-name "Alice" \
                              --password-stdin

axon-enterprise user list --status active
axon-enterprise user deactivate <user_uuid>
```

The CLI refuses any invocation that would pass the password via
argv — argv is visible in `ps(1)` output on shared hosts.

### `axon-enterprise keys ...`

```bash
axon-enterprise keys list
axon-enterprise keys register-kms --kms-arn arn:aws:kms:...
axon-enterprise keys rotate --kms-arn arn:aws:kms:...
axon-enterprise keys retire-grace         # daily cron
axon-enterprise keys jwks                 # dump current JWKS doc
```

### `axon-enterprise audit ...`

```bash
axon-enterprise audit verify                     # all tenants
axon-enterprise audit verify --tenant-id acme
axon-enterprise audit verify --exit-zero         # cron-friendly toggle
```

Exits non-zero when any tenant's chain is broken — pipe into
CloudWatch / Prometheus Pushgateway for alerting.

### `axon-enterprise migrate ...`

Thin wrapper over Alembic; reads `AXON_DB_URL` like everything else.

```bash
axon-enterprise migrate current
axon-enterprise migrate upgrade head
axon-enterprise migrate downgrade -1
axon-enterprise migrate history
axon-enterprise migrate stamp head   # bootstrap against existing DB
```

## Deployment pattern

```
┌──────────────────────┐
│  OTel Collector      │
│  (sidecar)           │◀─────── metrics + traces ──── Axon Enterprise
└──────────────────────┘                                 process
                                                         │
┌──────────────────────┐                                 │
│  nginx / envoy       │─── JWT validated & forwarded ───┤
│  (IP allowlist for   │                                 │
│   /admin/*)          │                                 │
└──────────────────────┘                                 │
         ▲                                               │
         │ HTTPS                                         │
┌──────────────────────┐                          ┌──────▼──────┐
│   Operator / portal  │                          │  Postgres   │
└──────────────────────┘                          │  (shared    │
                                                  │   with Rust)│
                                                  └─────────────┘
```

`/admin/*` is gated at the ingress layer by an IP allowlist — the
operator team's network only. `/api/v1/*` (Fase 10.k) is public
behind JWT. Both live on the same process because they share state;
splitting them would introduce a second deploy artefact for no
architectural benefit.

## What comes next

- 10.k (Tenant Self-Service Portal API) — `/api/v1/*` routes for
  tenant admins: user invites, SSO config, API keys, usage dashboard,
  invoice PDFs, Stripe webhook handler
- 10.l (Compliance) — `/admin/compliance/evidence-bundle` that
  assembles ESK + audit + metering into a SOC 2 evidence ZIP
