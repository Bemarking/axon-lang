---
name: dataspace_basic
title: "A `dataspace` — the deterministic data plane's declared store"
summary: "`dataspace` declares an analytical data container: the store the data-plane verbs (`ingest` / `focus` / `aggregate` / `associate` / `explore`) operate on. §108 is landing the engine in stages: today the declaration is name-only (the body's typed `column` schema arrives with §108.b), and the verbs are FAIL-CLOSED — a flow that reaches them without the columnar engine refuses (`MissingDependency: dataspace_engine`) instead of asking an LLM to narrate data it never loaded. A dataspace is analytical (append-only batches, relational queries); the transactional store is `axonstore` — one primitive, one algebra."
topic: data
primitives:
  - dataspace
  - axonstore
---

// `dataspace` is the ANALYTICAL data container — the deterministic data
// plane's store (§108). It is the dual of `axonstore`:
//
//   axonstore  = transactional (OLTP): rows, isolation levels, breach policy.
//   dataspace  = analytical   (OLAP): append-only columnar batches, queried
//                with relational algebra (σ/π/γ/⋈), never mutated row-by-row.
//
// §108 lands the engine in stages. TODAY the declaration is name-only —
// the typed `column` schema (§108.b), governed `ingest` (§108.c) and the
// lazy relational verbs (§108.d) are arriving. Until they do, the
// data-plane verbs fail CLOSED: a flow that reaches `ingest` / `focus` /
// `aggregate` / `associate` / `explore` without the columnar engine is
// REFUSED (`MissingDependency: dataspace_engine`) — axon does not ask a
// language model to pretend it loaded your data.

dataspace ClinicalMetrics {
}

// The transactional side of the same domain, for contrast: `axonstore`
// is where individual records are written with isolation + breach
// policy. Analytical questions ("average per region", "how many per
// diagnosis") belong to the dataspace, not to row storage.

axonstore PatientLedger {
    backend:     postgresql
    connection:  "postgres://clinical.internal/patient_ledger"
    isolation:   serializable
    on_breach:   raise
    capability:  "clinical.write"
    schema {
        patient_id:  Text primary_key
        diagnosis:   Text not_null
        recorded_at: Timestamp not_null
    }
}
