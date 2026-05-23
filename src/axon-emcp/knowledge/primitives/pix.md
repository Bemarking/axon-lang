---
name: pix
summary: Provenance Index — an append-only, hash-linked chain of every state transition with tamper-evident verification.
category: data_plane
top_level: true
since: Fase 19
grammar: |
  pix <Name> {
      source: "<uri>"               # required — content source the PIX indexes
      depth: <integer>              # optional — chain depth to retain (default unbounded)
      branching: <integer>          # optional — branching factor (Merkle-style)
      model: <ident>                # optional — hashing model slug (e.g. sha256 | blake3)
  }
---

# `pix`

`pix` (Provenance Index) declares **an append-only, hash-linked
chain** that records every state transition a bound surface
produces. Every mutation to an audited primitive — an
`axonstore` write, a `flow` emission, an `agent` action — can
be linked into a PIX chain whose head hash is **tamper-evident
by construction**: any post-hoc modification to a historical
row breaks the chain head, surfaced by `axon-emcp.audit verify`.

This is the foundation of AXON's audit-chain integrity story
(§Fase 19 Production Hardening, §27.k FIPS-friendly hashing).
Without PIX, the audit chain is append-only-by-convention;
with PIX, it's append-only-by-cryptographic-construction.

## Surface

`pix` is a **top-level declaration**. It is *not* nested
inside an axonstore or flow.

```axon
pix LedgerAudit {
    source:    "axonstore://GeneralLedger"
    depth:     unbounded
    branching: 2
    model:     sha256
}
```

## Fields

### `source:` (required)

A **string literal** containing the URI of the content surface
the PIX indexes. Common URI schemes:

| Scheme | Target |
|---|---|
| `axonstore://<Name>` | Every mutation to the named store. |
| `flow://<Name>` | Every emission of the named flow. |
| `agent://<Name>` | Every action of the named agent. |
| `manifest://<Name>` | Every configuration change to the manifest. |
| `dataspace://<Name>` | Every cross-store operation in the dataspace. |

The runtime resolves the URI at deploy time and binds the PIX
chain to the named surface.

### `depth:` (optional)

A **non-negative integer literal** OR the identifier
`unbounded`. The chain depth to retain (older rows beyond this
are not pruned — they're moved to cold-storage archives that
keep the chain integrity).

| Value | Retention semantic |
|---|---|
| `<integer>` | Hot window of the last N rows; older rows archived. |
| `unbounded` | All rows stay hot (default for regulated systems). |

### `branching:` (optional)

A **non-negative integer literal**. Branching factor for the
Merkle-style tree the PIX may organise rows under. `branching:
2` (binary) is the Merkle-tree default; `branching: 0`
(default) means a flat linear chain.

### `model:` (optional)

A **single identifier** naming the hashing model. Common
values: `sha256` (default), `blake3`, `sha3`. The runtime
picks a FIPS 140-3 validated implementation when available
(see §Fase 27.k).

## Runtime behaviour

`pix` lowers to a `PixDefinition` IR node. At deploy time, the
runtime resolves the `source:` URI and attaches the PIX
recorder to the named surface. Every state transition emits a
new chain row carrying:

```
{
    seq:      <monotonic counter>,
    prev_hash: <hash of previous row>,
    payload_hash: <hash of this row's content>,
    timestamp: <UTC ISO 8601>,
    actor:    <OIDC-verified subject>,
    operation: <verb-tagged>,
}
```

The **chain head** is the hash of the most recent row;
verifying integrity at any point means recomputing the head by
walking the chain. The `axon-emcp.audit verify` CLI does this
verification on demand.

For Fase 21+ enterprise deployments, the chain head is also
signed with a deployment-managed key — providing
**non-repudiation** in addition to tamper-evidence.

## What this primitive is NOT

- **Not a store.** PIX records *the history of transitions* to
  another surface. The source content lives in the bound
  `axonstore` / `flow` / `agent`.
- **Not optional for regulated deployments.** Production
  HIPAA / GDPR / SOX / PCI deployments declare at least one
  PIX over the regulated axonstore. The runtime emits
  `axon-W013` for compliance-tagged stores without a bound
  PIX.
- **Not a backup.** PIX records every transition; restoring
  to a point-in-time requires replaying the chain. For
  efficient restore, run periodic full-backup snapshots
  alongside the PIX chain.
- **Not generic logging.** Standard `tracing` events go to
  stderr / the observability layer. PIX is the
  cryptographically-linked persistence chain — different
  surface, different guarantees.

## See also

- `axon://primitives/axonstore` — the most common PIX source.
- `axon://primitives/dataspace` — usually one PIX per
  dataspace.
- `axon://primitives/observe` — observe + PIX is the
  read-side / write-side audit pair.
- `axon://compliance/sox` — example of SOX §404 attestation
  via PIX chain head.
- [`docs/papers/paper_audit_chain.md`](https://github.com/Bemarking/axon-lang)
  — the formal integrity story (when shipped).
