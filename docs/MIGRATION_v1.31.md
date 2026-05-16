# Migration to axon-lang v1.31.0

v1.31.0 closes one adopter-reported gap: the **`persist` field block**.
It is a small, additive, **backward-compatible** release — most programs
need no change. This guide covers the one case that does.

> **TL;DR** — `persist <store> { col: value … }` now writes *exactly*
> the columns you declare. Before v1.31.0 the block was parsed but
> silently dropped, and `persist` wrote every flow binding as the row —
> which fails against any real table. If you use `persist` against a
> PostgreSQL `axonstore`, add a field block.

---

## What changed

`persist` is the third store operation to gain a structured block —
joining `retrieve { where:, as: }` and (v1.30.0) `mutate` / `purge
{ where: }`. A `persist` step may now declare the columns it writes:

```axon
persist into chat_history {
    session_id: "${session_id}"
    sender:     "user"
    content:    "${message}"
    tenant_id:  "${tenant_id}"
}
```

This compiles to `INSERT INTO chat_history (session_id, sender,
content, tenant_id) VALUES ($1, $2, $3, $4)` — exactly the four
declared columns, every value interpolated against the flow context.

---

## Scenario 1 — `persist` against a real table now needs a field block

**Before v1.31.0**, a `persist <store>` block was silently discarded
and the runtime built the row from *every* binding in scope — flow
parameters, step results, `retrieve` aliases, `let` bindings. Against a
real table that is almost always more columns than the table has, so
the `INSERT` failed:

```
column "channel_kind" of relation "chat_history" does not exist
```

**v1.31.0** — declare a field block. The `INSERT` is scoped to exactly
those columns; every other binding is ignored:

```axon
flow ChatFlow(message, session_id, tenant_id, channel_kind) -> Unit {
    step GenerateResponse { ask: "reply to ${message}" }
    persist into chat_history {
        session_id: "${session_id}"
        sender:     "user"
        content:    "${message}"
        tenant_id:  "${tenant_id}"
    }
}
```

`channel_kind` and the `GenerateResponse` step result never reach the
`INSERT`.

**Action:** add a `{ col: value }` block to every `persist` that
targets a PostgreSQL table.

---

## Scenario 2 — interpolation is `${name}`, not `{{name}}`

Value expressions inside the field block use axon's standard
interpolation — `${name}` or `$name` — the same syntax `retrieve`'s
`where:` and every prompt body use:

```axon
persist into chat_history {
    content:   "${message}"     // ✅ substitutes the binding `message`
    sender:    "user"           // ✅ a literal — no `$`
}
```

`{{double-brace}}` is **not** axon interpolation; it is written to the
column literally. If you came from a templating language expecting
`{{ }}`, switch to `${ }`.

---

## Scenario 3 — the optional `into` connector

`persist into <store> { … }` and `persist <store> { … }` are
equivalent — `into` reads as documentation and is skipped. Before
v1.31.0, `persist into chat_history` captured `into` *as the store
name* (a lateral bug). Both forms now resolve the store name
correctly.

---

## Backward compatibility

- **A bare `persist <store>` with no block is unchanged.** It still
  writes every user binding as the row — the v1.30.0 behaviour. This
  remains useful for an `in_memory` store (which snapshots flow state)
  but will still fail against a real table whose columns do not match;
  prefer a field block for PostgreSQL stores.
- The **`in_memory`** backend is unaffected by the field block — it has
  no columns; it snapshots flow state as key-value entries.
- No `axonstore`, `retrieve`, `mutate` or `purge` syntax changed.
- IR JSON for a `persist` step gains a `fields` array (empty when no
  block is written).

---

## Scope (unchanged from v1.30.0)

`persist` writes against an **existing** table — v1.31.0 still ships no
DDL (`CREATE TABLE` / schema synthesis) and runs single-statement
autocommit. See [`ADOPTER_AXONSTORE.md` §12](ADOPTER_AXONSTORE.md) for
the full honest-scope boundary.
