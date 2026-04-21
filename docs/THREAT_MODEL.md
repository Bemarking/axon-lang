# Threat model — Axon Enterprise v1.1.0

STRIDE-based threat model covering the control plane (Python
`axon_enterprise` package) and the shared boundary with the Rust
data plane (`axon-lang` runtime). Data-plane-internal threats
(flow execution, LLM provider integration) are out of scope; the
`axon-lang` repo owns that surface.

## System boundary

```
┌─────────────────────────────────────────────────────────────────┐
│                         Public Internet                         │
└───────────────┬──────────────────────────┬──────────────────────┘
                │ HTTPS                    │ HTTPS
         ┌──────▼──────┐            ┌──────▼──────┐
         │   Portal    │            │   Admin     │
         │   /api/v1/* │            │   /admin/*  │  ← IP allowlist + mTLS
         └──────┬──────┘            └──────┬──────┘
                │                          │
                └──────────┬───────────────┘
                           ▼
                 ┌─────────────────────┐
                 │  AuthMiddleware     │  JWT verify (RS256 + JWKS)
                 │  Residency MW       │  308 / 421 on region mismatch
                 │  Observability MW   │  metrics + traces
                 └─────────┬───────────┘
                           ▼
                 ┌─────────────────────┐
                 │   Service layer     │  PasswordHasher, AuthService,
                 │  (tenant RLS + RBAC)│  SecretsService, MeteringService,
                 │                     │  AuditService, ComplianceService
                 └─────────┬───────────┘
                           ▼
              ┌────────────────────────┐
              │  Postgres (axon_admin) │  RLS + BEFORE triggers
              │  Redis (rate-limit)    │
              │  AWS KMS (envelope)    │
              │  AWS Secrets Manager   │
              │  S3 (compliance blobs) │
              └────────────────────────┘
```

Trust boundaries: each arrow in the diagram is a boundary where
the receiver MUST re-validate inputs.

## Assumptions (what we DO NOT defend against)

- **Compromised infrastructure account.** If an attacker has AWS
  admin credentials they can exfiltrate KMS keys, Secrets Manager
  values, and S3 buckets. Mitigation is organisational (IAM,
  MFA, CloudTrail) not in this codebase.
- **Compromised operator workstation.** A developer whose laptop
  is compromised while connected to the VPN can impersonate them.
  Mitigation: Yubikey-backed SSO for operators, audit logging,
  session TTL.
- **Zero-day in a pinned dependency.** `pyjwt`, `argon2-cffi`,
  `cryptography`, `starlette` etc. Mitigation: Dependabot +
  weekly `pip-audit` in CI.
- **Physical access to production hosts.** Standard cloud-hosting
  assumption — the cloud provider's own controls cover this.

## STRIDE

### Spoofing

| Threat | Mitigation |
|---|---|
| Attacker forges a JWT claiming a valid user | RS256 signatures via KMS; `alg=none`, `alg=HS*` rejected; tests in `tests/security/test_jwt_forgery_resistance.py` |
| Attacker replays a leaked refresh token | Refresh tokens rotate on every use; presenting a rotated-out token revokes the whole chain (10.b) |
| Attacker replays a stolen SSO assertion | `sso_assertion_seen (tenant_id, assertion_id)` UNIQUE — second presentation raises `sso:assertion_replay` audit event |
| Attacker replays a compromised API key | Raw key only stored as Argon2id hash; `revoked_at` enforced at verify time; prefix `axk_` makes accidental leaks greppable |
| Attacker claims another tenant's `tenant_id` in JWT | `require_permission` resolves RBAC against the principal's `(user_id, tenant_id)` — forged tenants find no role assignments and are denied (test in `tests/security/test_rbac_privilege_escalation.py`) |
| Attacker replays a Stripe webhook from a different account | `Stripe-Signature` HMAC verified against `metering.stripe_webhook_secret`; signature mismatch → 400 + no state change |

### Tampering

| Threat | Mitigation |
|---|---|
| Attacker modifies an audit event to hide activity | Per-tenant hash chain + `BEFORE UPDATE/DELETE/TRUNCATE` triggers raising SQLSTATE 42501; `verify_chain` detects any divergence |
| Attacker mutates a user's roles via direct SQL | Admin-only via `axon_admin` role; normal tenant sessions lack the `bypassrls` attribute. RBAC changes are audited |
| Attacker tampers with a SAR export bundle in transit | SHA-256 recorded in `compliance_requests.artefact_sha256` + the `compliance:export_completed` audit event; auditor recomputes |
| Attacker adds a legal hold release they did not authorise | `compliance:legal_hold_applied/released` audit events; the partial unique index prevents duplicate active holds |

### Repudiation

| Threat | Mitigation |
|---|---|
| Operator denies a destructive action | Every admin action emits an audit event carrying `actor_user_id`, `actor_email`, `ip_address`, `user_agent`, timestamp. Chain verification proves the event was not inserted retroactively |
| Tenant admin denies issuing an API key | `api_key:created` audit event + `tenant_api_keys.created_by` FK to `users.user_id` |
| Compliance request denied by operator claims they never saw it | Ticket row immutable except via `TicketService` transitions; `claimed_by` records which worker processed it; complete/fail always emits an audit event |

### Information disclosure

| Threat | Mitigation |
|---|---|
| Tenant A reads tenant B's data | Two-layer defence: Postgres RLS (tenant GUC) + service-level `WHERE tenant_id = :principal.tenant_id`. Tested in `tests/security/test_cross_tenant_isolation.py` |
| Error messages leak user existence | `AuthService.authenticate` returns `InvalidCredentialsError` for both "unknown email" and "wrong password"; timing is equalised via `burn_equivalent_time` (tested in `test_argon2_timing_parity.py`) |
| 404 vs 403 leaks existence information | Portal handlers return 404 for cross-tenant lookups (not 403) so an attacker learns nothing about beta's tickets by probing alpha |
| Secrets returned in API responses | `SecretValue` type redacts plaintext in `repr()` + structlog; portal API never returns `tenant_secrets.value_ciphertext` — only metadata |
| Logs leak PII | structlog processor strips known PII keys; `burn_equivalent_time` path logs no password |
| JWKS endpoint leaks private key material | JWKS builder serialises only public portions (`n`, `e`, `kid`, `use`); private key never leaves KMS |

### Denial of service

| Threat | Mitigation |
|---|---|
| Flood of login attempts locks out legitimate users | Progressive lockout is per-user and clears on success; login rate-limited per-IP at the ingress |
| Flood of audit writes saturates a tenant's advisory lock | Advisory lock keyed by `hashtext(tenant_id)` — flood on tenant A blocks only A's writers; cross-tenant throughput is unaffected. Verified in `k6_audit_storm.js` at 500 RPS across 1000 tenants |
| Flood of compliance requests exhausts the worker queue | `compliance_requests.status` partial index keeps claim query O(log N); worker sleeps `worker_poll_interval_seconds` on empty queue |
| Extremely large SAR export exhausts memory | Per-subject bundle is bounded (one user's rows); tenant-wide export would need streaming (noted as 10.m deferred) |
| Metering flood exhausts rate limit keys in Redis | Redis TTL on rate-limit keys (60s window); Postgres aggregate is the durable truth so Redis outage degrades to Postgres-hit-count path |
| Malformed JSON crashes handler | Starlette's request.json() raises a typed error caught by the error handler → 400 |

### Elevation of privilege

| Threat | Mitigation |
|---|---|
| Viewer role user gains admin capabilities | `@require_permission` decorator + recursive role CTE; `tests/security/test_rbac_privilege_escalation.py` verifies viewer cannot `user:invite` |
| Impersonation endpoint used to pivot to another tenant | `/admin/tenants/{id}/impersonate` mints a token with `imp.target_user_id` that carries the TARGET tenant id; middleware emits `user:impersonated` audit on every request under that token |
| Worker connects as `axon_admin` and escapes its scope | Worker only calls services; services never offer cross-tenant mutation APIs (explicit `tenant_id` argument per call) |
| Compliance erasure anonymises a legal-hold subject | `assert_no_legal_hold` checked at file-time AND anonymize-time — mid-window holds short-circuit the purge |
| Stripe webhook handler creates privileged state | Webhook routes don't accept an admin token; they only run the handful of `invoice.*` state transitions; unknown types → 204 |

## Known residual risks (accepted)

- **Audit event PII lingers post-erasure.** `actor_email` on historical audit rows
  keeps the original subject email because mutating the row breaks the hash
  chain. Auditors accept this; legal confirmed.
- **Region redirect exposes tenant existence.** A 308 to
  `eu-west-1.auth.example` reveals the tenant lives in eu-west-1. Alternative
  (always-421) is worse UX and provides little additional defence.
- **Local blob store is reachable from the compliance CLI.** `axon-enterprise
  compliance status` prints `file://` URIs in dev. Production uses S3 + presigned
  URLs; the env validator rejects local backend for production.

## Verification

- Unit tests: `pytest tests/`
- Integration tests (Postgres via testcontainers): `pytest -m integration`
- Security suite (this document's mitigations): `pytest tests/security/`
- Load tests: `k6 run tests/load/*.js` — see `tests/load/README.md`
- Threat model owner: security team + bemarking.com engineering lead.
  Reviewed per release tag.
