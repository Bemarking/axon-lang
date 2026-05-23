---
name: resource
summary: Declares an external compute/storage resource (database, S3, ML endpoint) consumable by a flow.
category: cognitive_io
top_level: true
since: Fase 6
grammar: |
  resource <Name> {
      kind: <ident>                              # required — backend kind slug
      endpoint: "<addr>"                          # optional — connection URI
      capacity: <integer>                         # optional — pool/concurrency cap
      lifetime: <linear|affine|persistent>        # optional — handle lifecycle
      certainty_floor: <0.0..1.0>                 # optional — observation gate
      shield: <ShieldRef>                         # optional — defence layer
  }
---

# `resource`

`resource` declares **an external compute or storage resource** the
cognitive layer can consume — a database, an S3 bucket, an ML
inference endpoint, a network egress. A flow references resources
through the `manifest` declaration; `lease` acquires them with
typed lifecycle semantics; `observe` watches their health.

This is the foundation of AXON's **cognitive I/O surface**:
external state is named, typed, and lifecycled at the language
level, not delegated to runtime config files.

## Surface

`resource` is a **top-level declaration**. It is *not* nested
inside a manifest or fabric.

```axon
resource EHRDatabase {
    kind:            postgres
    endpoint:        "ehr.clinical.internal:5432"
    capacity:        300
    lifetime:        linear
    certainty_floor: 0.95
    shield:          PHIShield
}
```

## Fields

### `kind:` (required)

A **single identifier** naming the backend kind. The catalogue is
open at the parser level — the runtime decides what's actually
mountable. Common slugs: `postgres`, `mysql`, `s3`, `redis`,
`dynamodb`, `compute`, `kafka`, `grpc`.

### `endpoint:` (optional)

A **string literal** containing the resource address. The format
is kind-specific — `host:port` for databases, `s3://bucket/prefix`
for object stores, `https://service.tld/path` for HTTP endpoints.

### `capacity:` (optional)

A **non-negative integer literal**. Concurrency cap or pool size
— the maximum number of in-flight handles the runtime will grant
simultaneously.

### `lifetime:` (optional)

A **single identifier** from the closed lifecycle catalogue,
mirroring linear-logic semantics:

| Value | Semantic |
|---|---|
| `linear` | Handle must be used exactly once. Move-on-pass. |
| `affine` | Handle may be used at most once. Drop-allowed. **Default.** |
| `persistent` | Handle may be shared + reused. |

The type checker rejects unknown values. Parser-enforced closed
set.

### `certainty_floor:` (optional)

A **numeric literal in `[0.0, 1.0]`**. Minimum observational
certainty the runtime requires before treating reads from this
resource as authoritative. Below the floor, reads emit
`axon-W010` and the calling step can decide to retry.

### `shield:` (optional)

A **single identifier** referencing a declared `shield`. Every
read/write through the resource passes through the shield's scan
list before commitment. The most common production discipline:
HIPAA-tagged resources always carry a PHI-redaction shield.

## Runtime behaviour

`resource` lowers to a `ResourceDefinition` IR node. At deploy
time, the runtime resolves the `kind:` slug against its mount
registry and acquires a connection pool sized to `capacity:`.
Every handle granted to a flow carries the declared `lifetime:`
discipline — the linearity analyser (Fase 6 §λ-L-E) rejects
flows that violate the handle's usage contract at parse time.

Every read/write emits an audit row tagged
`resource:<name>:<op>` carrying `(actor, certainty, latency,
shield_outcome)`.

## What this primitive is NOT

- **Not a connection string.** A resource declaration is a
  *typed handle to external state*. The endpoint is one of its
  fields, not the whole declaration.
- **Not an `axonstore`.** `axonstore` is the typed,
  audit-chained data plane with explicit columns + isolation;
  `resource` is the lower-level handle to ANY external
  service. The two layer: an `axonstore` can sit on top of a
  `resource`.
- **Not automatically mounted.** A declared resource that no
  `manifest` references is rejected by the §40 deployment
  gate. Resources must be wired into a manifest to be
  acquirable.

## See also

- `axon://primitives/manifest` — bundles resources into a
  deployable unit.
- `axon://primitives/fabric` — the cloud substrate that hosts
  resources.
- `axon://primitives/lease` — typed acquisition + expiry.
- `axon://primitives/observe` — health monitoring per resource.
- `axon://primitives/shield` — mandatory defence wrapper.
