---
name: dataspace_basic
title: "A `dataspace` as a logical reference target"
summary: "`dataspace` declares a logical grouping for cross-store consistency proofs. Today the body is open; the declaration itself is the citable reference name that `axonstore` declarations under this dataspace point to."
topic: data
primitives:
  - dataspace
  - axonstore
---

// `dataspace` is the logical grouping primitive — per-domain
// (`ClinicalData`, `BillingData`), per-region (`USData`, `EUData`),
// or per-tenant. Future Fase increments will land typed fields
// (retention, cross-store policies); today the dataspace is a
// reference target: axonstore declarations cite it.

dataspace ClinicalData {
}

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
