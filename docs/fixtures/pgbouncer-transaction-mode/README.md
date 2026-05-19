# Local transaction-mode pooler fixture (Fase 37.x.i)

A minimal `docker compose` stack that brings up Postgres 16 with
PgBouncer in front of it in `pool_mode=transaction` on port `6432` — the
same shape adopters meet in production behind Supabase Supavisor (`:6543`),
PgBouncer transaction mode, Neon, RDS Proxy, etc.

This is the adopter-side counterpart of the CI lane
`pgbouncer-transaction-mode` in [`.github/workflows/fase_35_axonstore.yml`](../../../.github/workflows/fase_35_axonstore.yml).
The lane runs every PR + master push; this fixture lets you reproduce
its execution context locally.

## Why a local fixture exists at all

Fase 37.x's honest-scope note: findings A+B (the introspection /
operation session split) manifest **only** behind a transaction-mode
pooler. A direct connection to Postgres is always coherent and cannot
reproduce the bug. Owning the reproduction is the whole point of this
sub-fase.

If you're an adopter who hit the `operator does not exist: uuid = text`
chain in the field, this stack is the fastest local repro. If you're an
axon contributor working on the store substrate, this is the harness to
verify a change before opening a PR.

## Bring it up

```sh
cd docs/fixtures/pgbouncer-transaction-mode
docker compose up -d
```

Wait for the healthcheck to pass (a few seconds):

```sh
docker compose ps
```

Confirm the end-to-end path is live (Postgres → PgBouncer → your client):

```sh
PGPASSWORD=axon psql -h localhost -p 6432 -U axon -d axon_store_test -tAc 'select 1'
# 1
```

## Run the axon-rs 37.x test surface against it

```sh
export AXON_TEST_DATABASE_URL="postgresql://axon:axon@localhost:6432/axon_store_test"

# The faithful smoke-15 reproduction (37.x.i):
cargo test -p axon-lang --test fase37x_i_pgbouncer_integration -- --nocapture

# The broad D5 zero-regression guard (35.l + 37.x.a) routed through the pooler:
cargo test -p axon-lang --test fase35_l_postgres_integration -- --nocapture
cargo test -p axon-lang --test fase37x_a_pooler_coherent_diagnostic -- --nocapture

# The pure-total property/fuzz surfaces (no DB, but harmless to run in any env):
cargo test -p axon-lang --test fase37x_i_property_fuzz -- --nocapture
```

A direct-to-Postgres point of comparison (port `5432` instead of
`6432`) is sometimes useful when investigating a defect: a test that
passes direct-but-fails-pooled is exactly the 37.x kind of bug.

```sh
# Direct-to-Postgres — bypasses the pooler.
export AXON_TEST_DATABASE_URL="postgresql://axon:axon@localhost:5432/axon_store_test"
```

## Tear it down

```sh
docker compose down -v
```

(`-v` drops the implicit volume so the next `up -d` starts from a
clean Postgres.)

## A note on `default_pool_size`

The stack ships with `DEFAULT_POOL_SIZE: "5"` — much smaller than the
~13 parallel integration tests, so cross-session multiplexing is
**forced**. Two successive operations on the same client connection
will land on different physical Postgres backends. If you raise this
above the parallel test count, multiplexing becomes accidental, and a
regression that only shows under multiplexing may slip the harness.
The CI lane uses the same value for the same reason.

## What this fixture is NOT

- It is **not** a production deployment template. Postgres has no
  persistent volume, the password is hard-coded, and the network is
  open on `localhost`. It exists for tests and local repro only.
- It is **not** a substitute for the CI lane. The lane is the
  permanent regression guard — every PR runs the full integration
  surface through PgBouncer transaction mode automatically.
