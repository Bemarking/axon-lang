# Tenant Secrets — Operator Guide

Per-tenant secret storage introduced in Fase 10.f (v1.1.0).
Replaces the scaffolding from v1.0.0 (the `config:secret_access`
audit event enum that was never emitted by anything) with a
production-grade service: values in AWS Secrets Manager, metadata
in Postgres, plaintext never logged.

## Architecture

```
REST layer (Fase 10.j)           SecretsService              AWS Secrets Manager
  POST /secrets                ─► put_secret      ────►      create / put_secret_value
  GET  /secrets                ─► list_secrets  (metadata only, no AWS call)
  GET  /secrets/{k}            ─► reveal_secret ─►           get_secret_value
  DELETE /secrets/{k}          ─► schedule_del  ─►           delete_secret (recovery)
  POST /secrets/{k}/rotate     ─► rotate_secret ─►           put_secret_value (new ver)

Postgres                         Rust runtime reads via TenantSecretsClient
  tenant_secrets (metadata)      at: axon/tenants/<tid>/<key> — paths match.
```

Values live in AWS SM under `{path_prefix}/{tenant_id}/{key}`
(default: `axon/tenants/<tenant>/<key>`). This convention is
deliberately identical to `axon-rs/src/tenant_secrets.rs` (§M3) so
the Rust runtime reads the same secrets without any translation
layer.

## Data model

`axon_control.tenant_secrets` — metadata only. Composite PK
`(tenant_id, key)`. Values NEVER live here.

| Column | Meaning |
|---|---|
| `tenant_id` | FK to `public.tenants`, part of PK |
| `key` | Canonical name (lowercased, matches `^[a-z0-9][a-z0-9_-]*$`) |
| `backend` | `aws_sm` or `memory` |
| `storage_path` | Full backend path (e.g. `axon/tenants/acme/openai_api_key`) |
| `storage_arn` | ARN returned by AWS SM (null for in-memory backend) |
| `current_version` | Opaque version id of the `AWSCURRENT` secret |
| `description` | Operator note; shown in the portal UI (Fase 10.k) |
| `status` | `active` / `deleted_pending` / `deleted` |
| `deleted_pending_until` | Mirrors AWS SM recovery window |
| `created_by` / `last_rotated_by` | Audit trail — FK to `axon_control.users` |
| `last_accessed_at` / `accessed_count` | Usage telemetry (updated on every successful read) |

RLS: `tenant_isolation + admin_bypass`. Tenant A cannot read tenant
B's metadata even with a forged SELECT.

## Value redaction

Every plaintext value flowing through Python is wrapped in
`SecretValue`. The wrapper:

- returns `<SecretValue len=N fingerprint='xxxxyyyy'>` in `repr`,
  `str`, and unformatted f-strings
- raises `ValueError` when an f-string uses a format spec — so
  `f"{secret:>20}"` fails at the boundary instead of leaking
- substitutes `[REDACTED]` when pickled or deep-copied
- equality is constant-time (`hmac.compare_digest`)
- `fingerprint` = SHA-256[:8] — audit events carry this so
  operators can correlate value changes across time without the
  plaintext ever appearing in a log

Callers unwrap exactly where the boundary demands plaintext — HTTP
responses, backend SDK calls, and nowhere else.

## Key naming policy

- Allowed characters: lowercase alphanumeric plus `_` and `-`
- Length: 3..128 chars
- Reserved prefixes: `axon_`, `system_`, `internal_` (operators
  cannot create secrets under these)
- Normalisation: `" OpenAI_Api_Key "` is accepted and canonicalised
  to `openai_api_key` before hitting the backend

## Backends

### AWS Secrets Manager (`backend=aws_sm`) — production

- `create_secret` on first write; `put_secret_value` on subsequent
  writes (AWS SM auto-demotes the previous version to
  `AWSPREVIOUS`)
- `get_secret_value` on reads
- `delete_secret` with `RecoveryWindowInDays` (default 30, min 7,
  max 30). Schedules deletion — the value is recoverable within
  the window.
- `describe_secret` for existence probes
- IAM required on the service account:
  - `secretsmanager:CreateSecret`
  - `secretsmanager:GetSecretValue`
  - `secretsmanager:PutSecretValue`
  - `secretsmanager:DeleteSecret`
  - `secretsmanager:UpdateSecret`
  - `secretsmanager:DescribeSecret`
  - Resource ARN scoped to `{region}:*:secret:axon/tenants/*`

### In-memory (`backend=memory`) — dev / tests

Single-process dict. The production settings validator rejects
`memory` so forgetting to switch backends is caught at startup.

## Audit

Every mutation + every read (when `audit_on_read=true`, default)
emits an event through `SecretsAuditEmitter`. For 10.f the default
emitter writes structured logs; Fase 10.g swaps in the
hash-chained writer without code changes. Event types:

| Event | When |
|---|---|
| `secret:create` | First `put_secret` for a key |
| `secret:update` | Subsequent `put_secret` (new version, same key) |
| `secret:read` | Every `reveal_secret` (when `audit_on_read=true`) |
| `secret:rotate` | `rotate_secret` call |
| `secret:delete_scheduled` | `schedule_deletion` call |

Event payload always includes the tenant_id, user_id, key, and
fingerprint — never the plaintext.

## Required environment

Production:

```
AXON_SECRETS_BACKEND=aws_sm
AXON_SECRETS_AWS_REGION=us-east-1
AXON_SECRETS_PATH_PREFIX=axon/tenants   # matches axon-rs (do not change)
AXON_SECRETS_DELETION_RECOVERY_WINDOW_DAYS=30
AXON_SECRETS_AUDIT_ON_READ=true
```

Dev / tests:

```
AXON_SECRETS_BACKEND=memory
```

## Service API

```python
from axon_enterprise.db.session import tenant_session
from axon_enterprise.secrets import SecretsService, SecretValue

svc = SecretsService.default()

async with tenant_session(ctx) as db:
    await svc.put_secret(
        db,
        tenant_id=ctx.tenant_id,
        key="openai_api_key",
        value=SecretValue(request_body["value"]),
        user_id=principal.user_id,
        description="OpenAI key for the prod flow",
    )

    revealed = await svc.reveal_secret(
        db, tenant_id=ctx.tenant_id, key="openai_api_key"
    )
    plaintext = revealed.value.reveal()   # explicit unwrap at the boundary

    items = await svc.list_secrets(db, tenant_id=ctx.tenant_id)
    # items[i].description + metadata — values are never included
```

## What comes next

- Fase 10.g (Audit) replaces `LoggingAuditEmitter` with the
  hash-chained audit writer; every `secret:*` event becomes part of
  the tamper-evident log.
- Fase 10.j (Admin API) wires the REST surface (`POST /api/v1/tenants/
  {id}/secrets`, `GET .../secrets/{key}`, etc.) and enforces the
  `secret:*` permissions from 10.c.
- Fase 10.l (Compliance) adds a reconciliation job that detects
  orphan AWS SM entries (values without metadata) and merges them
  back into the catalogue.
