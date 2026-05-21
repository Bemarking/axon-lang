# axon-enterprise v1.29.1 — catch-up to axon-lang 1.38.2 (Pooler-coherent Transactions + Admin Schema Isolation)

Patch catch-up bundling the v1.38.1 + v1.38.2 axon-lang chain that closes all three findings from the kivi adopter's smoke 16 (2026-05-20). axon-lang dep pin advances `>=1.38.0` → `>=1.38.2`.

## What enterprise tenants inherit

### 🛡️ Pooler-coherent Transactions Contract (Fase 38.x.a → axon-lang v1.38.1)

The `axonstore postgresql` data plane is now **structurally safe behind every transaction-mode pooler** — Supabase Supavisor `:6543`, PgBouncer `pool_mode=transaction`, Neon, RDS Proxy. The `prepared statement "sqlx_s_N" already exists` collision class that regressed in v1.37.0 (and that v1.36.4's `statement_cache_capacity(0)` could not fully mitigate) is closed permanently:

- **D1** — every `sqlx::query(...)` carries `.persistent(false)` (unnamed PARSE protocol — collision-free by construction)
- **D2** — `PoolOptions::after_release` hook runs `DEALLOCATE ALL` on every released conn (belt-and-suspenders)
- **D3** — the 5 silent `Err(_)` swallows in store ops emit structured `tracing::warn!` so the primary error surfaces in journald/CloudWatch/Loki

### 🏛️ Admin Schema Isolation Contract (Fase 38.x.b → axon-lang v1.38.2)

axon's admin `tenants` table relocated from default search-path schema (`public`) to dedicated `axon_admin.tenants`. Adopters whose application schema already has its own `public.tenants` no longer see `column "plan" does not exist` and the in-memory fallback degradation.

## Enterprise-side companion work (this release)

### 18-FK relocation
Every enterprise ForeignKey that previously pointed at `public.tenants.tenant_id` now points at `axon_admin.tenants.tenant_id`:

| FK category | Count | ondelete | onupdate |
|---|---|---|---|
| Strict-isolation (audit/billing/compliance/identity) | 9 | RESTRICT | CASCADE |
| Cascade-cleanup (rbac/sso/metering/api_keys) | 6 | CASCADE | CASCADE |
| TenantScopedMixin (sessions/sso_configurations/sso_states) | 3 | RESTRICT | CASCADE |

### New alembic migration `013_relocate_tenants_to_axon_admin.py`
Atomic FK swap wrapped in one alembic transaction. Drops every legacy FK pointing at `public.tenants` and recreates pointing at `axon_admin.tenants` with original CASCADE/RESTRICT semantics preserved. Idempotent (`DROP CONSTRAINT IF EXISTS`). Partial state impossible — any failure rolls every preceding drop back.

### alembic 001 baseline precondition update
The `public.tenants` existence assertion now accepts **EITHER** `public.tenants` (legacy v1.38.1 and earlier) **OR** `axon_admin.tenants` (v1.38.2+). Strictly more lenient — every previously-passing deploy still passes. Fresh installs against v1.38.2+ axon-lang also pass via the new branch.

## Vertical inheritance

Enterprise tenants on regulated verticals inherit the contract transparently — no per-tenant code change required:

- 🏥 **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** clinical PHI stores: the audit-chain HMAC across mutations now survives every pooled session without prepared-statement collision dropouts; structured warn diagnostics replace cascade-error masking.
- ⚖️ **FRE 502 + Upjohn / Hickman + ABA Rule 1.6** legal privilege stores: streaming audit forensics no longer mask root causes behind `25P02 in_failed_sql_transaction` cascades; the waiver-doctrine-defensibility surface remains observable.
- 💰 **BSA / OFAC / MiFID II** AML fintech stores: million-row scans through transaction-mode poolers run uninterrupted; the streaming cursor path no longer encounters prepared-statement collisions mid-drain.
- 🏛 **FedRAMP AU-2 + AC-3** government record stores: SDLC-control diagnostic signal restored — operators see primary errors at deploy time instead of secondary cascades.

## Migration steps

For existing v1.29.0 deployments:

1. **Upgrade axon-lang to >=1.38.2** (PyPI + crates.io live).
2. **Run axon-rs M1 migration** — creates `axon_admin.tenants`; idempotently copies rows from legacy `public.tenants` if axon-owned (detection via the unique-to-axon `plan` + `status` column markers).
3. **Pull the v1.29.1 image**:
   ```sh
   docker pull 908489016816.dkr.ecr.us-east-1.amazonaws.com/axon/axon-enterprise:v1.29.1
   ```
4. **Run alembic to revision 013** — atomic FK swap. Rolls back cleanly if any RESTRICT-protected orphan row would break the relocation.
5. **Legacy `public.tenants` is left intact** — adopters may keep it for their own RLS / app FKs / readers; axon never writes to it again.

For fresh installs:

- v1.29.1 + axon-lang v1.38.2+ from scratch: alembic 001 baseline runs the more lenient precondition; alembic 013 is effectively a no-op (FKs already point at axon_admin via the updated source code).

## Files changed

- 18 ForeignKey refs across 10 enterprise modules (`public.tenants` → `axon_admin.tenants`)
- 1 new alembic migration: `013_relocate_tenants_to_axon_admin.py`
- 1 precondition update: alembic `001_baseline_foundation.py` (more lenient OR check)
- 4 doc updates + 4 test updates
- `pyproject.toml`: version `1.29.0` → `1.29.1`; dep pin `axon-lang>=1.38.0` → `>=1.38.2`
- `axon_enterprise/__init__.py`: `__version__` → `1.29.1`

axon-frontend Rust crate dep stays `0.19.0` transitively (no AST change in v1.38.1 or v1.38.2).

## Cross-links

- 📋 [Fase 38.x.a plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38x_pooler_transactions.md) — Pooler-coherent Transactions Contract
- 📋 [Fase 38.x.b plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38xb_admin_schema_isolation.md) — Admin Schema Isolation Contract
- 📖 [axon-lang v1.38.1 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.1)
- 📖 [axon-lang v1.38.2 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.2)
- 📖 [v1.29.0 GitHub Release](https://github.com/Bemarking/axon-enterprise/releases/tag/v1.29.0) — Fase 38 catch-up parent

## Acknowledgements

Closed same day as the kivi adopter's smoke 16 report (2026-05-20). Three findings, two axon-lang patches (v1.38.1 + v1.38.2), one enterprise catch-up. The multitenant cognitive data plane is whole again.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
