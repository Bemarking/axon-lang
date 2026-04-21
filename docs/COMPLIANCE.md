# Compliance Tooling — Operator Guide

Fase 10.l. Closes the GDPR / CCPA / SOC 2 gap that the 10.k portal
stubs left open: SAR export execution, Right to Erasure, data
residency, legal holds, and SOC 2 evidence bundle generation.

## Moving parts

| Component | Purpose |
|---|---|
| `ComplianceService` | High-level façade for portal + CLI |
| `TicketService` | Queue ops: issue, claim (SKIP LOCKED), complete, fail, reschedule |
| `SarExporter` | Art. 15 Subject Access Request — tar.gz with one JSONL per source table |
| `ErasureService` | Art. 17 Right to Erasure — two-stage soft-delete + anonymize |
| `LegalHoldService` | Blocks erasure during litigation |
| `EvidenceBundleService` | SOC 2 per-period bundle (audit + RBAC + SSO + holds + requests) |
| `DataResidencyMiddleware` | 308-redirects / 421-rejects mis-routed requests |
| `ComplianceWorker` | Long-running poller that drains the queue |
| `BlobStore` protocol | Where artefacts land (`LocalBlobStore` / `S3BlobStore`) |

## Persistence (`010_compliance.py`)

- `axon_control.compliance_requests` — unified queue for SAR + erasure tickets.
  Partial index on `(status, scheduled_for)` keeps worker claims fast.
- `axon_control.legal_holds` — at most one ACTIVE hold per
  `(tenant_id, subject_email)` enforced by a partial unique index.
- `public.tenants.data_region` — region slug consumed by the
  residency middleware; default `us-east-1`.

## Subject Access Request (GDPR Art. 15)

```
POST /api/v1/tenant/compliance/export
{ "subject_email": "subject@example.com" }
→ 202  { "ticket_id": "<uuid>", "status": "queued", "sla_days": 30 }
```

The worker picks up the ticket, streams the subject's rows from
every table listed in `SarExporter._collect_tables` into a tar.gz
(members: `manifest.json`, `README.md`, and one `<table>.jsonl`
per source), uploads via `BlobStore.put`, then marks the ticket
`completed`.

Excluded tables are enumerated in `manifest.excluded` with a
reason — auditors can confirm nothing was silently dropped.

Polling:

```
GET /api/v1/tenant/compliance/{ticket_id}
→ 200  { "status": "completed", "download_url": "https://...", ... }
```

`download_url` is a pre-signed URL (S3) or a `file://` URI (local
store). TTL is `compliance.blob_signed_url_ttl_seconds` (default 1h).

## Right to Erasure (GDPR Art. 17)

```
POST /api/v1/tenant/compliance/erase
{ "subject_email": "...", "reason": "user request" }
→ 202  { "ticket_id": "...", "soft_delete_window_days": 7, "sla_days": 30 }
→ 409  { "error": { "code": "compliance.legal_hold_active" } }   # if an active hold exists
```

**Stage 1 — soft delete (immediate).** On worker pickup the
service revokes every session + API key owned by the subject and
flips `tenant_memberships.status = 'erased_pending'`. The ticket
is parked in `awaiting_purge` with
`scheduled_for = now + erasure_soft_delete_days` (default 7).

**Stage 2 — anonymize (after the reversion window).** The worker's
`promote_due_purges` ticker flips `awaiting_purge → queued` when
the window elapses; the next claim runs `ErasureService.anonymize`:

- `users.email` → `erased-<sha16>@axon.internal`
- `users.display_name` → `[erased]`
- `users.password_hash` → `NULL`
- `sessions` rows → deleted
- `tenant_api_keys` rows → deleted
- `tenant_memberships.status` → `'erased'`

A purge report (JSON with row counts + SHA-256 of the original
email) is uploaded to the blob store and recorded in
`audit_events` as `compliance:erasure_completed`.

`audit_events` rows are NOT mutated — doing so would break the
hash chain. The audit trail shows what happened (with original
email in `actor_email`) while the live tables carry only the
anonymized identifier. Auditors accept this split because
anonymization intent is captured.

## Legal holds

```bash
axon-enterprise compliance legal-hold apply subject@example.com \
    --tenant alpha --matter "FTC investigation #2026-04"

axon-enterprise compliance legal-hold release <HOLD_ID> --reason "matter closed"
```

`ErasureService.assert_no_legal_hold` is consulted at file-time
(immediate 409 for the caller) and again at anonymize-time (a
hold applied mid-window short-circuits the purge).

## Data residency

Every tenant declares `data_region`. Requests arriving at a server
whose `compliance.server_region` ≠ tenant region are rejected or
redirected by `DataResidencyMiddleware`:

- `compliance.residency_redirect_base="https://{region}.auth.example"`
  → 308 redirect to `https://eu-west-1.auth.example/<path>`
- Redirect base unset → 421 Misdirected Request

Every mis-routed request is recorded as
`compliance:residency_violation` in the audit chain so operators
can see where traffic is hitting the wrong region.

## SOC 2 evidence bundle

```bash
axon-enterprise compliance evidence-bundle \
    --tenant alpha --from 2026-01-01 --to 2026-03-31
```

Produces a tar.gz with:

- `manifest.json` — period metadata + audit-chain verification
  report (`ok`, `checked`, `broken_at` if corrupted)
- `audit_events.jsonl` — every event in the period, including
  `event_hash_hex` + `prev_hash_hex` for independent chain verification
- `rbac_snapshot.json` — roles, user_roles, role_permissions
- `sso_configurations.json` — public portions of SSO configs
- `legal_holds.jsonl` — holds active at any point in the period
- `compliance_requests.jsonl` — SAR + erasure requests filed + outcomes

An audit event `compliance:evidence_bundle_generated` records the
bundle URI + SHA-256 so the bundle's provenance is itself auditable.

## Worker

```bash
axon-enterprise compliance run-worker
```

Runs two loops:

- `run_forever` — claims the next queued ticket via
  `FOR UPDATE SKIP LOCKED`, dispatches on `kind`, fails the ticket
  (typed audit event) on any exception so the queue keeps moving.
- `promote_due_purges` — on each poll interval, flips
  `awaiting_purge → queued` for tickets whose reversion window has
  elapsed.

Safe to run N replicas. The partial index
`ix_compliance_requests_status_scheduled_for` keeps the claim
query O(log active-queue) even with millions of historical rows.

## Settings

```ini
AXON_COMPLIANCE_BLOB_BACKEND=s3
AXON_COMPLIANCE_BLOB_S3_BUCKET=axon-compliance-artefacts
AXON_COMPLIANCE_BLOB_S3_PREFIX=compliance
AXON_COMPLIANCE_BLOB_SIGNED_URL_TTL_SECONDS=3600

AXON_COMPLIANCE_SERVER_REGION=us-east-1
AXON_COMPLIANCE_RESIDENCY_REDIRECT_BASE=https://{region}.auth.example

AXON_COMPLIANCE_ERASURE_SOFT_DELETE_DAYS=7
AXON_COMPLIANCE_ERASURE_ANONYMIZE_SLA_DAYS=30

AXON_COMPLIANCE_WORKER_POLL_INTERVAL_SECONDS=5
AXON_COMPLIANCE_WORKER_MAX_CONCURRENT_JOBS=1
AXON_COMPLIANCE_WORKER_JOB_TIMEOUT_SECONDS=3600
```

Production validator rejects `blob_backend=local` — the local
store is for dev / on-prem appliances only.
