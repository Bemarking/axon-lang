# AXON Migration Guide — v1.29.x → v1.30.0

> **Scope:** the Fase 35 *axonstore as a cognitive data plane* cycle.
> v1.30.0 makes an `axonstore` declared with `backend: postgresql`
> **execute real SQL** against the declared database — and that SQL
> store is enriched in four dimensions (epistemic, audit-chained,
> streaming, capability-typed). Full reference:
> [`ADOPTER_AXONSTORE.md`](./ADOPTER_AXONSTORE.md).
>
> **TL;DR — read this first:** v1.30.0 is **backwards-compatible
> absolute**. A flow that uses only in-memory / undeclared stores
> behaves **byte-identically** to v1.29.x — there is no wire flip, no
> behavior change. The SQL path is entered *only* when a matching
> `axonstore` declares `backend: postgresql`. If you have no
> `postgresql`-backed `axonstore`, **nothing in this guide affects
> you** — upgrade freely.

---

## What changed in v1.30.0

| Surface | v1.29.x | v1.30.0 |
|---|---|---|
| `axonstore { backend: postgresql }` | **Ignored.** Every store op went to an in-process key-value store regardless of the declared `backend`. | **Honored.** `persist`/`retrieve`/`mutate`/`purge` execute parameterized SQL against the declared `connection`, on both execution paths identically. |
| `confidence_floor` field | Inert. | **Pillar I** — enforced at `retrieve` (sub-floor rows filtered) and `persist` (sub-floor write → typed error). |
| `on_breach` field | Inert. | **Pillar II** — every mutation appends to a tamper-evident HMAC-Merkle audit chain; `on_breach ∈ {log, raise, rollback}` fires on a detected tamper. |
| `retrieve` result | (the KV path returned a single value) | **Pillar III** — a lazy, backpressured `Stream<Row>` drained off a database cursor; the result is an **epistemic envelope** JSON. |
| `capability` field | (did not exist) | **Pillar IV** — a new optional `axonstore` field; store access requires a capability the type-checker enforces. |
| `mutate` / `purge` `where:` clause | **Silently dropped** — the parser skipped the `{ where: }` block, so every `mutate`/`purge` ran whole-store. | **Captured** — `mutate S { where: "<expr>" }` runs a filtered `UPDATE`/`DELETE`. |
| `in_memory` stores | key-value path | key-value path — **unchanged, byte-identical**. |

---

## Scenario 1 — your `axonstore { backend: postgresql }` was ignored

If your v1.29.x source declared a postgresql-backed store:

```axon
axonstore tenants {
    backend: postgresql
    connection: "env:DATABASE_URL"
}
```

…the runtime quietly ignored `backend` and used the in-memory KV store.
In **v1.30.0 this declaration now executes real SQL.**

**Action required:**

1. The `tenants` table must **exist** in the database `DATABASE_URL`
   points at, with columns matching what your flows bind. v1.30.0
   operates against existing tables — there is no `CREATE TABLE` (see
   [`ADOPTER_AXONSTORE.md` §12](./ADOPTER_AXONSTORE.md#12-honest-scope-boundaries-v1300)).
2. `DATABASE_URL` (or whatever `connection: "env:VAR"` names) must be
   set. If it is unset, the store op now fails with a clear named
   error — it does **not** silently fall back to the KV store.

If you do **not** want SQL — keep the data in-process — change
`backend` to `in_memory` (or remove the `axonstore` declaration; an
undeclared store is in-memory by default).

---

## Scenario 2 — the SQL `retrieve` result is an epistemic envelope

A `retrieve` from a postgresql-backed store no longer binds a bare
value. It binds an **epistemic envelope** (Pillar I + III):

```json
{
  "taint": "untrusted",
  "confidence_floor": null,
  "trusted_rows": 4,
  "below_floor_filtered": 0,
  "rows": [ { "id": 1, … }, … ],
  "stream": { "policy": "pause_upstream", "total_seen": 4,
              "dropped": 0, "truncated": false, "cancelled": false }
}
```

A retrieved row is a **claim, not a fact** — `taint: "untrusted"`. If a
downstream step consumes the retrieve result, read `rows`. The envelope
is the v1.30.0 contract for an SQL `retrieve`; the in-memory `retrieve`
is unchanged.

---

## Scenario 3 — `mutate` / `purge` now honor `where:`

In v1.29.x the parser **silently dropped** the `{ where: }` block on a
`mutate` / `purge` step — every `mutate`/`purge` ran against the whole
store. v1.30.0 closes that gap:

```axon
mutate accounts { where: "id = 5" }    // v1.29.x: updated EVERY row
                                       // v1.30.0: updates only id = 5
```

**Action required:** audit every `mutate` / `purge` in your source. If
one was written with a `{ where: }` clause expecting a targeted
operation, v1.29.x was operating on the *whole store* — v1.30.0 now
does what the clause says. A `mutate`/`purge` with **no** `{ where: }`
block still operates on every row (intentionally — `WHERE TRUE`).

---

## Scenario 4 — capability-gated stores need `requires:` on the endpoint

If you adopt Pillar IV by declaring `capability:` on a store:

```axon
axonstore tenant_pii {
    backend: postgresql
    connection: "env:DATABASE_URL"
    capability: "pii.read"
}
```

…then every `axonendpoint` whose flow accesses `tenant_pii` **must
grant** `pii.read` in its `requires:` list:

```axon
axonendpoint ReadPii {
    method: GET path: "/pii" execute: FetchPii
    requires: [pii.read]
}
```

The type-checker enforces this — a program where an endpoint reaches a
gated store without granting its capability **does not type-check**.
Run `axon check`; a clean check confirms every gate is satisfied. This
is new surface — it affects you only if you add `capability:` fields.

---

## Scenario 5 — you use only `in_memory` stores

**Nothing changes.** The in-memory key-value path is byte-identical to
v1.29.x. An `axonstore` with `backend: in_memory`, an `axonstore` with
no `backend`, and a store name never declared at all — all three take
the unchanged pre-1.30 path. This is a non-negotiable design property
of the Fase 35 cycle (D3): the SQL path is purely additive.

---

## Backwards compatibility

v1.30.0 is **additive and backwards-compatible absolute**:

- The in-memory key-value store path is byte-identical.
- The SQL path is entered *only* for `backend: postgresql`.
- The two new fields (`capability`) and the now-honored fields
  (`backend`, `confidence_floor`, `on_breach`) change behavior only for
  stores that declare them.
- The one behavior change for existing source — Scenario 3, `mutate` /
  `purge` honoring `where:` — corrects a silent defect; it is called
  out explicitly so you can audit before upgrading.

If you have no `postgresql`-backed `axonstore` and no
`mutate`/`purge` with a `{ where: }` block, v1.30.0 is a transparent
upgrade.

---

*See [`ADOPTER_AXONSTORE.md`](./ADOPTER_AXONSTORE.md) for the complete
cognitive data plane reference — every field, the `where` grammar, the
four pillars, and the honest scope boundaries.*
