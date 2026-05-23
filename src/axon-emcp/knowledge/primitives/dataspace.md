---
name: dataspace
summary: A named, isolated data namespace — multi-tenant by construction, with cross-tenant proof obligations.
category: data_plane
top_level: true
since: Fase 36
grammar: |
  dataspace <Name> {
      # Body is intentionally open at the parser level — the §40
      # tenant model + cross-tenant proof obligations are enforced
      # in downstream §36.x.b column-proof checks, not in parse.
  }
---

# `dataspace`

`dataspace` declares **a named, isolated data namespace** that
holds a related set of `axonstore`s. Where `axonstore` declares
*one* typed store, `dataspace` declares *the namespace* every
store within it shares — multi-tenant by construction, with
cross-tenant proof obligations enforced by the §40 column-proof
discipline.

The dataspace is **the unit of tenancy** in the data plane: a
write to an axonstore at dataspace D under tenant T cannot be
read by tenant T' even at the SQL level (the column-proof
mandates `tenant_id` filtering on every query against
HIPAA/GDPR/PCI-tagged stores).

## Surface

`dataspace` is a **top-level declaration**. It is *not* nested
inside an axonstore or manifest.

```axon
dataspace ClinicalData {
    # The dataspace body is open at the parser level. Future
    # Fase increments will land typed fields here (retention,
    # cross-store query policies, etc.). For now the dataspace
    # is a reference target: axonstore declarations under this
    # dataspace cite it for cross-store consistency proofs.
}
```

## Anatomy

### Header — `dataspace <Name>`

A **PascalCase identifier** unique within the module. Common
patterns: per-domain (`ClinicalData`, `BillingData`,
`AuditData`), per-region (`USData`, `EUData`,
`APACData`), or per-tenant-class (`SharedTenants`,
`DedicatedTenants`).

### Body — `{ ... }`

The body is **currently open at the parser level**: the parser
accepts any content + skips it structurally. This is
intentional — the §40 + §36.x.b cross-store proof discipline
sits above the parser, and future Fase increments will land
typed fields (e.g. `retention: 7y`, `region: "us-east-1"`,
`cross_query_policy: deny_join`).

## Runtime behaviour

`dataspace` lowers to a `DataspaceDefinition` IR node. At
deploy time, the runtime registers the namespace; every
axonstore that references the dataspace is mounted within it.

**The cross-tenant proof obligation:** any compliance-tagged
axonstore (HIPAA, GDPR, PCI_DSS, SOX) inside a dataspace MUST
carry a `tenant_id` column. The §36.x.b column proof at parse
time enforces this; runtime reads/writes that don't filter on
tenant_id are rejected (cross-tenant data movement is a
shield breach, not a runtime fault).

Audit rows: every cross-dataspace operation emits
`dataspace:<source>:<dest>:transfer` with full lineage so
data movement between namespaces is reviewable.

## What this primitive is NOT

- **Not an axonstore.** An axonstore is one *typed store*; a
  dataspace is the *namespace* multiple stores share.
- **Not a database.** Multiple dataspaces can live on the same
  physical backend — the namespace is logical, not
  storage-bound. The §36 isolation discipline does the work.
- **Not a `manifest`.** A manifest deploys infrastructure
  (resources + fabric); a dataspace declares the data-plane
  namespace those stores live in.
- **Not optional for multi-tenant deployments.** Production
  multi-tenant AXON programs declare a dataspace per tenancy
  policy; without one, the §40 column proof falls back to
  permissive mode (audit row `axon-W012` warns).

## See also

- `axon://primitives/axonstore` — typed stores within a
  dataspace.
- `axon://primitives/manifest` — infrastructure deployment
  layer (orthogonal to dataspaces).
- `axon://primitives/pix` — provenance chain (often one per
  dataspace).
- `axon://compliance/gdpr` — region-locked dataspace pattern.
- `axon://logic/flow_composition` — when to declare multiple
  dataspaces vs. one.
