# Load tests — Fase 10.m

Scripts run via [k6](https://k6.io/docs/getting-started/installation/).
Each script declares `options.thresholds` mapping to the GA SLOs
enumerated in `docs/SECURITY_AUDIT.md`; k6 exits non-zero when any
threshold breaches, so these double as CI gates.

## Running

```bash
# Portal API happy path (login + api-key CRUD + usage dashboard)
k6 run tests/load/k6_portal_api.js \
    --env BASE_URL=https://alpha.auth.example \
    --env EMAIL=load@acme.example \
    --env PASSWORD=... \
    --env TENANT=alpha

# Admin API flood (tenant CRUD + key rotation under operator JWT)
k6 run tests/load/k6_admin_api.js \
    --env BASE_URL=https://auth.example \
    --env ADMIN_JWT=eyJhbGciOi...

# Audit write storm (1k concurrent tenants, append-heavy)
k6 run tests/load/k6_audit_storm.js
```

## SLO thresholds (enforced by each script)

| Surface | p95 | p99 | Error rate | Notes |
|---|---|---|---|---|
| Portal API read (GET) | 300ms | 500ms | < 0.5% | Ingress + DB read path |
| Portal API mutate (POST/DELETE) | 500ms | 1s | < 1% | Includes Argon2 / envelope crypto |
| Admin API mutate | 500ms | 1s | < 1% | Same as tenant admin |
| Audit write | 50ms | 100ms | < 0.1% | advisory-lock per-tenant matters |
| SSO callback | 800ms | 2s | < 1% | Includes IdP JWKS round-trip |

## What these scripts DON'T cover

- Tenant **data plane** (axon-rs runtime) — separate load harness in
  the `axon-lang` repo (`benchmarks/`).
- Long-running compliance jobs — measured by the worker's own
  `compliance_worker_job_duration_seconds` histogram, not k6.
