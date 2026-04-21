# Security audit — GA readiness checklist (v1.1.0)

Fase 10.m sign-off gate. Every item below must be green for a
release tag to ship. The checklist covers code invariants verified
by automated tests, operational controls enforced at runtime, and
the non-automatable items reviewed by the engineering lead.

Pair with [`THREAT_MODEL.md`](./THREAT_MODEL.md) — this file is the
pass/fail gate; the threat model is the why.

## Automated verification (CI must pass)

| Gate | Command | Pass criteria |
|---|---|---|
| Unit + integration tests | `pytest -q` | 100% of non-skipped tests pass |
| Security tests | `pytest tests/security/ -q` | 100% pass (cross-tenant, RLS, RBAC, JWT, audit, timing) |
| Hypothesis invariants | `pytest tests/security/test_audit_chain_invariants.py` | 10+ examples pass for each `@given`; no falsifying counter-examples |
| Lint + type check | `ruff check . && mypy axon_enterprise/` | No errors |
| `pip-audit` | `pip-audit` | Zero known high-severity CVEs in pinned deps |
| Schemathesis fuzzing | `schemathesis run openapi.yaml --checks all` | No 5xx responses, no schema violations, no negative-test false-positives |
| Load — Portal API | `k6 run tests/load/k6_portal_api.js` | All thresholds green (see `tests/load/README.md`) |
| Load — Admin API | `k6 run tests/load/k6_admin_api.js` | All thresholds green |
| Load — Audit storm | `k6 run tests/load/k6_audit_storm.js` | p99 < 100ms at 500 RPS, error rate < 0.1% |

## Code-level invariants

- [x] Every tenant-scoped table has `tenant_isolation` + `admin_bypass`
      RLS policies (via `full_policy_set_sql` in each migration).
- [x] Every service query that touches a tenant-scoped table carries an
      explicit `WHERE tenant_id = ...` — verified by
      `test_manual_guc_flip_does_not_reveal_cross_tenant_rows`.
- [x] `audit_events` is append-only at the DB level via
      `BEFORE UPDATE/DELETE/TRUNCATE` triggers with SQLSTATE 42501.
- [x] `PasswordHasher.verify` and `.burn_equivalent_time` are within
      1.5× of each other on shared CI runners.
- [x] JWT verification rejects: missing bearer, `alg=none`, HMAC algs,
      unknown `kid`, wrong `iss`/`aud`, expired tokens.
- [x] RBAC `@require_permission` resolves against the principal's
      `(user_id, tenant_id)` — forged tenants are denied.
- [x] SAR bundles include `manifest.audit_chain` with head sequence +
      event hash so the bundle is independently verifiable.
- [x] Erasure soft-delete + anonymize are both gated by
      `assert_no_legal_hold`.

## Operational controls (runtime-enforced)

- [x] Production settings validator rejects:
      `envelope.backend=local`, `jwt.signer_backend=local`,
      `secrets.backend=memory`, `compliance.blob_backend=local`,
      `db.ssl_mode ∈ {disable, allow, prefer}`, `db.echo_sql=true`.
- [x] JWT signing key lives in AWS KMS — `kms:Sign` API only, private
      key never materialises in process memory.
- [x] TOTP secrets stored under envelope encryption (KMS backend in
      production).
- [x] Admin API (`/admin/*`) is protected by ingress IP allowlist +
      mTLS (infrastructure layer — see `infrastructure/terraform/`).
- [x] Stripe webhook (`/webhooks/stripe`) verifies `Stripe-Signature`
      against `metering.stripe_webhook_secret`.
- [x] Data residency middleware enforces tenant region on every
      authenticated request; violation emits audit.
- [x] Audit hash chain verified on evidence bundle generation; broken
      chain halts bundle creation with an explicit `broken_at` report.

## Non-automatable review (sign off before tagging)

- [ ] **Secrets rotation runbook** exists and has been dry-run executed
      in staging within the last 90 days.
- [ ] **Key rotation runbook** for the JWT signing key — operator can
      promote a new KMS key while keeping the old one in the JWKS
      document for the configured grace period.
- [ ] **Incident response runbook** covers: compromised operator
      credentials, tenant RLS bypass report, SAR export blob leak, audit
      chain divergence pager, legal hold service outage.
- [ ] **Penetration test** by an external firm scheduled within 180 days
      of GA (acceptable to tag GA without it; not acceptable to renew
      enterprise contracts without it).
- [ ] **Third-party dependency review** — every package in
      `pyproject.toml` has an active maintainer OR a documented mirror
      + fork contingency.
- [ ] **Backup + restore test** — Postgres point-in-time-recovery
      exercised end-to-end within the last quarter; restored cluster
      passes `pytest -m integration` against it.
- [ ] **GDPR + CCPA legal review** — compliance team has signed off on
      `SarExporter` table list + erasure anonymisation semantics.
- [ ] **SOC 2 control mapping** — every control in the Type II report
      has a corresponding audit event type emitted by the system.

## SLO thresholds (k6-enforced)

| Surface | p95 | p99 | Error rate |
|---|---|---|---|
| Portal API read (GET) | 300ms | 500ms | < 0.5% |
| Portal API mutate (POST/DELETE) | 500ms | 1s | < 1% |
| Admin API mutate | 500ms | 1s | < 1% |
| Audit write | 50ms | 100ms | < 0.1% |
| Compliance worker job (SAR, per subject) | — | 60s | < 1% |
| SSO callback | 800ms | 2s | < 1% |

These map directly to the enterprise SLA surfaced to tenants. Any
relaxation requires a breaking-change release note.

## Known deviations (documented, accepted)

- **Audit event PII lingers post-erasure** — historical `actor_email`
  on audit rows keeps the original subject email because mutating
  breaks the hash chain. Accepted: compliance + legal reviewed.
- **Region redirect leaks tenant region** — 308 to
  `eu-west-1.auth.example` identifies the tenant as EU-hosted.
  Accepted: alternative (always-421) is worse UX and provides
  marginal additional defence.
- **Local blob store reachable via CLI in dev** — production
  settings validator rejects it; no effect on live deployments.

## Sign-off

Tagging `v1.1.0` requires:

1. All automated gates green on the `master` branch.
2. All operational controls present in the infrastructure repo.
3. Non-automatable items acknowledged by the engineering lead in
   the release checklist issue.
4. This document amended with any deviation between checklist and
   actual state — no silent skips.

Tag command:

```bash
cd axon-enterprise/
git tag -a v1.1.0 -m "Axon Enterprise v1.1.0 — Fase 10 complete"
git push origin v1.1.0         # triggers release.yml → ECR
```

The release workflow builds the image, runs the full suite against
a fresh Postgres, pushes to ECR as `axon/axon-enterprise:1.1.0`,
and creates a GitHub Release with the evidence bundle attached.
