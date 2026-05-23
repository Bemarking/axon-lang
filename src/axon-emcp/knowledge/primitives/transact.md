---
name: transact
summary: A flow-body block that wraps multiple data-plane mutations in a single transactional unit with rollback semantics.
category: data_plane
top_level: false
since: Fase 36
grammar: |
  # Flow-body form (canonical):
  transact { ... }                        # body parsed structurally; runtime treats as atomic unit

  # Top-level form (permissive, via generic-declaration):
  transact <Name> [(<args>)] [{ ... }]    # accepted by the parser; rare in practice
---

# `transact`

`transact` declares **an atomic transactional unit** wrapping
multiple data-plane mutations. Where a single `persist` /
`mutate` / `purge` operation is auto-committed against the
target `axonstore`, a `transact` block bundles a sequence of
such operations under **all-or-nothing semantics** — either
every mutation commits or all roll back.

This is AXON's surface for **multi-record consistency
guarantees**: clinical-record updates spanning multiple
tables, financial postings that touch ledger + audit + cache,
multi-step state migrations that must not partially apply.

## Surface

`transact` is **nested by convention** (the canonical
production usage) — a flow-body block. The parser ALSO
accepts a permissive top-level form via the generic-
declaration path, but adopter usage is overwhelmingly the
flow-body block.

### Flow-body block (canonical)

```axon
flow PostJournalEntry(entry: JournalEntry) -> PostReceipt {
    step Validate {
        given: entry
        ask: "Validate the entry's accounting balance."
        output: ValidatedEntry
    }

    transact {
        # Body is parsed structurally; the runtime treats this as
        # an atomic unit. Inside the block, persist/mutate/purge
        # operations against axonstores execute under one
        # transaction; a failure rolls all back.
    }

    step Acknowledge {
        given: Validate.output
        ask: "Render the post receipt."
        output: PostReceipt
    }
}
```

### Top-level (permissive)

```axon
# Permissive top-level form via generic-declaration parsing.
# Rare in practice; the block-step inside a flow body is the
# canonical surface.
transact ExportPipeline {
    # ...
}
```

## Anatomy

### Block — `transact { ... }`

The body is **currently parsed structurally** (via
`parse_block_step("transact")`) — the lexer's brace pair
encloses the block, and the parser skips contents while
recording the block's source position. The runtime treats the
block as one transactional boundary; inside, every store
mutation participates in the same backend transaction.

**Future Fase increments will land typed isolation semantics**
(e.g. `isolation:` field, `on_conflict:` policy) analogous to
`axonstore.isolation:`. Until then, the block inherits the
declared isolation of the target store(s).

## Runtime behaviour

`transact` (the flow-body block) lowers to a `TransactBlock`
IR node carrying the block's source location. At execution:

1. The runtime opens a backend transaction (per the bound
   store's `isolation:` declaration).
2. Every `persist` / `mutate` / `purge` operation inside the
   block runs under that transaction.
3. If every operation succeeds → commit. Audit row
   `transact:<source_loc>:committed` carries `(operation_count,
   duration, isolation_level)`.
4. If ANY operation fails → roll back. Audit row
   `transact:<source_loc>:rolled_back` carries the failing
   operation's diagnostic.

Cross-store transactions: when the block touches multiple
axonstores, the runtime uses the strongest declared
isolation level among them. Cross-backend transactions
(Postgres + MySQL) are NOT supported — the §40 deploy gate
rejects them with a structured error.

## What this primitive is NOT

- **Not a `forge`.** Forge is a CONSTRUCTOR session
  (assembling typed values from sub-step outputs); transact
  is an ATOMIC MUTATION boundary against the data plane.
  Different intent.
- **Not a `lease`.** Lease is time-bounded resource
  acquisition; transact is all-or-nothing-commit semantics
  over multiple mutations. The two compose: a flow can
  acquire a lease + run a transact inside it.
- **Not a generic block statement.** The runtime gives
  transactional meaning to the block; without bound store
  mutations inside, the block is a no-op (still emits an
  audit row but no commits occur).
- **Not cross-backend atomic.** A `transact` touching both
  a Postgres `axonstore` and a MySQL `axonstore` is
  rejected at deploy time — distributed transactions are
  out of scope.

## See also

- `axon://primitives/axonstore` — the target of mutations
  inside transact.
- `axon://primitives/forge` — constructor-session
  counterpart (different intent).
- `axon://primitives/flow` — the parent of every flow-body
  transact block.
- `axon://compliance/sox` — §404 SoX requires atomic
  posting; transact is the canonical surface.
