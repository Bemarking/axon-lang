# Migration to axon-lang v1.32.0

v1.32.0 closes one gap: the **`mutate` SET block**. It is the exact
symmetric counterpart of the v1.31.0 `persist` field block, and like
that release it is small, additive, and **backward-compatible** — most
programs need no change.

> **TL;DR** — `mutate <store> { where: "…" col: value … }` now writes
> *exactly* the `SET` columns you declare. Before v1.32.0 the block
> captured only `where:` and the runtime built the `UPDATE … SET` from
> every flow binding — which fails against any real table. If you use
> `mutate` against a PostgreSQL `axonstore`, declare the `SET` columns.

---

## What changed

`mutate` joins `persist` (v1.31.0), `retrieve` and `purge` as a store
operation with a fully structured block. The `mutate` block now carries
`where:` (the filter) **plus** one `col: value` entry per column to
update:

```axon
mutate accounts {
    where:   "id = ${account_id}"
    balance: "${new_balance}"
    status:  "active"
}
```

This compiles to `UPDATE accounts SET "balance" = $1, "status" = $2
WHERE id = $3` — exactly the two declared `SET` columns, each value
`${name}`-interpolated against the flow context.

---

## Scenario 1 — `mutate` against a real table now needs SET columns

**Before v1.32.0**, a `mutate <store> { where: … }` block captured only
`where:`; every other key was silently skipped. The runtime built the
`UPDATE … SET` clause from *every* binding in scope — flow parameters,
step results, `let` bindings. Against a real table that is almost
always more columns than the table has, so the `UPDATE` failed:

```
column "tenant_id" of relation "accounts" does not exist
```

**v1.32.0** — declare the `SET` columns inside the block, next to
`where:`. The `UPDATE` is scoped to exactly those columns; every other
binding is ignored:

```axon
flow AdjustBalance(account_id, new_balance, tenant_id) -> Unit {
    mutate accounts {
        where:   "id = ${account_id}"
        balance: "${new_balance}"
        status:  "active"
    }
}
```

`tenant_id` and `account_id` never reach the `SET` clause.

**Action:** add `col: value` entries to every `mutate` that targets a
PostgreSQL table.

---

## Scenario 2 — interpolation is `${name}`, not `{{name}}`

Value expressions in the `SET` columns use axon's standard
interpolation — `${name}` or `$name` — exactly as `persist`'s field
block and `retrieve`'s `where:`:

```axon
mutate accounts {
    where:   "id = ${account_id}"   // ✅ filter
    balance: "${new_balance}"       // ✅ substitutes the binding
    status:  "active"               // ✅ a literal — no `$`
}
```

`{{double-brace}}` is **not** axon interpolation; it is written to the
column literally.

---

## Backward compatibility

- **A `mutate <store> { where: … }` with no `col:` entry is
  unchanged.** It still SETs every user binding — the v1.31.0
  behaviour. This still fails against a real table whose columns do not
  match; declare the `SET` columns for PostgreSQL stores.
- **A `mutate <store>` with no block at all** still operates on the
  whole store (`WHERE TRUE`) — unchanged.
- The **`in_memory`** backend is unaffected by the `SET` block.
- No `axonstore`, `persist`, `retrieve` or `purge` syntax changed.
- IR JSON for a `mutate` step gains a `fields` array (empty when no
  `SET` column is declared).

---

## Scope (unchanged from v1.31.0)

`mutate` writes against an **existing** table — v1.32.0 still ships no
DDL and runs single-statement autocommit. See
[`ADOPTER_AXONSTORE.md` §12](ADOPTER_AXONSTORE.md) for the full
honest-scope boundary.
