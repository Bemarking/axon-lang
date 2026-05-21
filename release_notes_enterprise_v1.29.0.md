# axon-enterprise v1.29.0 — catch-up to axon-lang 1.38.0 (The Declared & Compile-Time-Typed Store Schema)

Minor catch-up. axon-lang dep pin advances `>=1.37.0` → `>=1.38.0`. Inherits axon-lang's **Fase 38** end-to-end.

## What's new (inherited from axon-lang v1.38.0)

An `axonstore`'s columns become a **COMPILE-TIME type** the type-checker proves every `where:`, every `persist`, every `mutate`, every `purge` against — the **fifth pillar** of the cognitive data plane (Epistemic + Audit-chained + Streaming + Capability + **TypedColumn**).

The failure of a column typo, a type mismatch, a NOT-NULL omission, or a deploy-time declared-vs-live drift moves from runtime (pre-37.x) → deploy (37.x D8) → **compile time** (v1.38.0).

| D-letter | Guarantee |
|---|---|
| **D1** | Three closed declaration forms — inline `schema { col: Type }` / manifest `schema: "qualified.name"` / per-tenant `schema: env:VAR`; closed 15-type catalog |
| **D2** | `axon check` proves every `where`/`persist`/`mutate`/`purge` against the declared columns; 6 error codes (T801 unknown column + T802 type mismatch + T803 NOT-NULL omission + T804 field typo + T805 manifest hash drift + T807 deploy declared-vs-live) |
| **D3** | Per-tenant env-var resolution at deploy with `application_name` stamping `axon-store/<store>/<tenant>` (Gap-3 inheritance) |
| **D4** | Canonical `.axon-schema.json` manifest (key-sorted, UTF-8, SHA-256 content-hash, byte-deterministic) |
| **D5** | **ABSOLUTE backwards-compat** — undeclared `schema:` is byte-identical to v1.37.0 |
| **D6** | Honest diagnostics — Levenshtein "Did you mean X?" composite hints + type-compatible alternatives |
| **D7** | Dedicated 5-lane CI workflow `fase_38_typed_store_schema.yml` |
| **D8** | `POST /v1/deploy` extends 37.x D8 with declared-vs-live drift detection (T807); activated via `axon serve --schemas-dir <path>` or `AXON_SCHEMAS_DIR` env var |
| **D9** | Closed 15-type catalog (any addition requires a compiler PR + design note) |
| **D10** | `axon store introspect <store>` CLI exports the live schema as a canonical manifest for off-line CI gating |

## Vertical inheritance — what enterprise tenants get

Enterprise tenants on regulated verticals inherit the typed-column proof transparently (no per-tenant code change required):

### 🏥 Healthcare (HIPAA Safe Harbor + 21 CFR Part 11)

Clinical PHI stores (`patient_records`, `triage_decisions`, `medication_orders`) declared with `schema { patient_id: Uuid, mrn: Text, … }` get compile-time proof of every PHI-touching `where:` and `persist` field. A column typo in an audit-required field is caught **before** the deploy reaches a regulated environment — defending the §164.312(b) audit-control surface.

### ⚖️ Legal privilege (FRE 502 + Upjohn / Hickman)

Privilege stores (`privilege_log`, `discovery_log`, `work_product`) get **T803 NOT-NULL discipline at compile time** — a `persist` that forgets the `attorney_id` or `privilege_basis` NOT-NULL column is now a parse-time error, closing a class of waiver-doctrine-defensibility hole that previously surfaced only at the first runtime `INSERT`.

### 💰 Fintech AML (BSA / OFAC / MiFID II)

AML stores (`aml_events`, `sanctions_screen`, `transaction_ledger`) running per-tenant via `schema: env:TENANT_SCHEMA` get **D3's `application_name` stamping** — every pooled session in `pg_stat_activity` carries the tenant, so DBA forensics on a sanctions-screen anomaly identifies the tenant without a separate audit-trail join.

### 🏛 Government (FedRAMP AU-2 + AC-3)

Government record stores get **T807 declared-vs-live drift detection at deploy** — a missing audit-required column or a wrong type on `audit_event_log` fails the deploy (a SDLC control surface), never at first request.

## Files changed (lean catch-up — same shape as v1.9.0 through v1.28.0)

- `pyproject.toml` — version `1.28.0` → `1.29.0`; dep pin `axon-lang>=1.37.0` → `>=1.38.0`
- `axon_enterprise/__init__.py` — `__version__ = "1.28.0"` → `"1.29.0"`

axon-frontend Rust crate dep advances `0.18.0` → `0.19.0` (the AST + type-checker change introducing `schema:` parsing + the `StoreColumnProof` pass).

**NO enterprise-only code change in this release** — the COLUMN pillar ships as a transitive surface advance via the axon-lang dep pin. Substantive Fase 27.k.1 Python ctypes integration still queued for a future release.

## Cross-links

- 📖 [axon-lang v1.38.0 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.0) — the full 10-D-letter contract + 6 error codes + 5-pillar story
- 📖 [Migration guide v1.37.x → v1.38.0](https://github.com/Bemarking/axon-lang/blob/master/docs/MIGRATION_v1.38.md) — 6 scenario-driven recipes A-F
- 📖 [`ADOPTER_AXONSTORE.md` §17](https://github.com/Bemarking/axon-lang/blob/master/docs/ADOPTER_AXONSTORE.md#17-the-compile-time-typed-store-schema-v1380) — 5 recipes (inline / manifest / per-tenant / introspect-then-commit / wiring `--schemas-dir`)
- 📖 [`ADOPTER_TYPED_STORE.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/ADOPTER_TYPED_STORE.md) — the 5-pillar deep-dive (Epistemic + Audit + Streaming + Capability + **TypedColumn**)
- 📋 [Fase 38 plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38_declared_compile_time_typed_store_schema.md) — the full cycle plan

## Upgrade

Pull the new image from ECR Private:

```sh
docker pull 908489016816.dkr.ecr.us-east-1.amazonaws.com/axon/axon-enterprise:v1.29.0
```

Or update your tag pin:

```yaml
image: 908489016816.dkr.ecr.us-east-1.amazonaws.com/axon/axon-enterprise:v1.29.0
```

Tags are **immutable** — no `latest`, no `X.Y` float. Operators pin exact.

## What does NOT change

- The enterprise OIDC + OAuth + tenant context + RBAC scope check surface from v1.8.0+ is unchanged.
- The diagnostic-policy default-strict + telemetry sink + vertical suggest dictionaries surface from v1.15.0+ is unchanged.
- The Daemon Supervisor + Shield Runtime + Trust Cache + audit-chain surfaces are unchanged.
- All adopter-facing APIs, all enterprise CLI subcommands, all configuration files are byte-identical to v1.28.0.

This is a **lean catch-up release** — same footprint as every minor since v1.9.0.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
