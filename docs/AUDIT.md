# Audit — Operator Guide

Tamper-evident, append-only audit log introduced in Fase 10.g
(v1.1.0). Replaces the in-memory ``AuditLogger`` scaffolding from
v1.0.0 with durable, hash-chained persistence and Postgres triggers
that refuse any UPDATE or DELETE at the storage layer.

## Design anchors

1. **Append-only at the DB level.** Three triggers on
   ``axon_control.audit_events`` raise ``SQLSTATE 42501`` on UPDATE,
   DELETE, and TRUNCATE. Retention is achieved by migration, never
   by row modification.
2. **Per-tenant hash chain.** Every event embeds
   ``prev_hash = SHA-256(previous event's event_hash)`` and its own
   ``event_hash``. First-event ``prev_hash`` is the deterministic
   genesis ``SHA-256(b"AXON_AUDIT_GENESIS:" || tenant_id)`` — no
   magic bootstrap value, any operator who knows the tenant_id can
   verify the root.
3. **Canonical JSON.** The same serialiser used by axon-lang's ESK
   ``provenance`` module — sorted keys, compact separators,
   ``ensure_ascii=True``, UUIDs as strings, datetimes as ISO 8601 UTC,
   bytes as urlsafe-base64 without padding. Byte-identical hash
   input whether Python or Rust computes it.
4. **ESK stitch.** An optional ``esk_stitch`` column holds the
   hash of an ESK ``provenance_chain`` entry. Auditors can cross-
   reference runtime provenance against the audit log without
   either side being authoritative.

## Schema

```
axon_control.audit_events
    event_id         UUID PK
    tenant_id        TEXT FK → axon_admin.tenants
    sequence_number  BIGINT  (monotonic per tenant, starts at 1)
    event_type       TEXT    (AuditEventType enum — see below)
    actor_user_id    UUID?
    actor_email      TEXT?
    resource_type    TEXT
    resource_id      TEXT?
    action           TEXT
    status           TEXT    ('success' | 'failure' | 'denied')
    ip_address       TEXT?   (plain text — NOT INET, to avoid
                              Postgres normalising the representation
                              and breaking hash recomputation)
    user_agent       TEXT?
    details          JSONB   (arbitrary event-specific payload)
    prev_hash        BYTEA   (32 bytes — SHA-256 of predecessor)
    event_hash       BYTEA   (32 bytes — SHA-256 over canonical input)
    esk_stitch       BYTEA?  (optional ESK provenance hash)
    created_at       TIMESTAMPTZ
    UNIQUE (tenant_id, sequence_number)
```

RLS: ``tenant_isolation + admin_bypass``. Tenant-scoped sessions see
only their events; the Admin API (10.j) connects as ``axon_admin``
for cross-tenant compliance exports.

## Hash chain construction

```
prev_hash(1)    = SHA-256(b"AXON_AUDIT_GENESIS:" || tenant_id_utf8)
event_hash(n)   = SHA-256(
                    prev_hash(n)
                    || 0x1e || tenant_id_utf8
                    || 0x1e || sequence_number_be64
                    || 0x1e || event_type_utf8
                    || 0x1e || canonical_json(payload)
                  )
prev_hash(n+1)  = event_hash(n)
```

The field separator (0x1e, ASCII Record Separator) prevents
ambiguity between two fields whose concatenation could match a
different legitimate combination.

## Concurrency

Writers on the same tenant serialise via
``pg_advisory_xact_lock(hashtext(tenant_id))``. Locks auto-release
at transaction end. Cross-tenant writers never contend because each
tenant hashes to a distinct advisory key space.

If two writers race past the advisory lock (misconfigured hash
function, buggy driver), the ``UNIQUE (tenant_id, sequence_number)``
constraint rejects the second write. ``AuditService.record`` surfaces
this as ``AuditSequenceConflict`` — pager-worthy but safely recoverable.

## Verification

```python
from axon_enterprise.audit import AuditService

svc = AuditService()
async with admin_session() as db:
    report = await svc.verify_chain(db, tenant_id="acme")
    if not report.ok:
        print(f"CHAIN BROKEN at seq={report.broken_at}: {report.reason}")
    else:
        print(f"chain intact — {report.checked} events verified")
```

The verifier never raises on divergence — it returns an
``AuditChainReport`` so operators can pipe results into dashboards.
``require_chain_healthy()`` is a thin wrapper that raises
``AuditChainBroken`` when the chain is not intact, for scripts that
prefer exception-based flow.

A daily cron job runs
``axon-enterprise audit verify --every-tenant`` (wired in 10.j) and
pages on any divergence.

## Event catalogue

``AuditEventType`` is a closed enum. Adding a new event requires a
migration that extends the accompanying Postgres check (if any) and
a code change that emits it. Every enum value uses the
``resource:action`` naming convention.

Categories:

| Category | Examples |
|---|---|
| ``auth`` | ``auth:login_success``, ``auth:login_failed``, ``auth:totp_verified`` |
| ``sso`` | ``sso:config_created``, ``sso:login_success``, ``sso:assertion_replay`` |
| ``jwt`` | ``jwt:key_registered``, ``jwt:key_rotated``, ``jwt:token_revoked`` |
| ``rbac`` | ``rbac:role_created``, ``rbac:permission_granted``, ``rbac:permission_denied`` |
| ``tenant`` | ``tenant:created``, ``tenant:suspended``, ``tenant:plan_changed`` |
| ``user`` | ``user:created``, ``user:invited``, ``user:impersonated`` |
| ``secret`` | ``secret:created``, ``secret:read``, ``secret:rotated`` |
| ``flow`` | ``flow:created``, ``flow:executed``, ``flow:deployed`` |
| ``config`` | ``config:changed`` |
| ``compliance`` | ``compliance:export_requested``, ``compliance:erasure_completed`` |

## Wiring services into the audit log

Each upstream service uses a narrow Protocol-based emitter:

```python
# 10.f — SecretsService already accepts any SecretsAuditEmitter
from axon_enterprise.audit import AuditService, SecretsAuditAdapter

audit = AuditService()
svc = SecretsService(
    backend=AwsSmBackend.from_settings(),
    policy=SecretsPolicy.default(),
    audit=SecretsAuditAdapter(service=audit, db=db),
    settings=get_settings().secrets,
)
```

The adapters translate service-specific ``emit()`` signatures into
``AuditWriteRequest`` + ``AuditService.record``. When a caller
forgets to pass an adapter, the default ``LoggingAuditEmitter``
keeps structured logs (lower SLO, no hash chain) — services never
hard-depend on the audit log being wired.

## Export for compliance

```python
events = await svc.list_events(
    db,
    tenant_id="acme",
    event_types=[AuditEventType.SECRET_READ, AuditEventType.RBAC_PERMISSION_DENIED],
    since=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
# Serialise to JSONL / ZIP as needed — hash values become base64 at
# the export layer so SIEMs can consume without binary headaches.
```

10.l (Compliance Tooling) adds a one-shot bundle generator that
includes the full chain, a verifier-run snapshot, and the
EvidencePackage format already produced by ESK.

## What comes next

- 10.h (Metering): ``audit:metering_event`` emission when quotas trip
- 10.i (Observability): Prometheus counters for audit write rate +
  chain verification latency per tenant
- 10.j (Admin API): HTTP endpoints + the CLI verifier
- 10.l (Compliance): GDPR export + right-to-erasure integration
  (audit events of an erased user become anonymised but stay in the
  chain — hash must continue to verify)
