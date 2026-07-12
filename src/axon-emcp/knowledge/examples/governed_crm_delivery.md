---
name: governed_crm_delivery
title: Governed CRM delivery — acquire → enrich → deliver, provenance intact
summary: "`deliver` (§105): the egress-dual of acquisition. A partial lead is enriched (§104 — the resolved email is born `speculate`/`believe`, Untrusted, NEVER `know`) and then DELIVERED to the CRM. With `provenance: attached` (the default) each delivered field lands beside its epistemic origin, so a vendor guess arrives LABELED a guess — never laundered into a bare fact (`delivery_is_assertion_egress`, the egress form of the §99 `document` T916 barrier). The credential rides §94 custody (`secret:`), never entering cognition; every operation carries an idempotency `key:` so an at-least-once retry never double-creates. Delivering bare values (`provenance: cleared`) would be a compile-time refusal (axon-T920) unless wrapped in `epistemic { believe }` after a shield + anchor."
topic: data
primitives:
  - deliver
  - tool
  - flow
---

// The lead-gen vertical's last hop: acquire (§102) → enrich (§104) →
// DELIVER (§105). This example shows the deliver primitive — the governed
// egress of assertions into a system of record.

// §104 — a governed enrichment tool. The resolved contact is born INFERRED
// (a vendor's probabilistic guess): its fields carry a confidence + an
// epistemic level bounded at `believe` (never `know`), and the value is
// Untrusted until a shield clears it. Enrichment resolves the missing
// email/phone from a partial (name + company).
tool Enrich {
    provider: scrape_enrich
    parameters: { name: String, company: String }
    output_type: Json
    effects: <network, web>
}

// §105 — the governed CRM delivery. This is the point where a value LEAVES
// the epistemic lattice into a machine others treat as fact.
//   - target: crm         — the system-of-record class (a vendor is the
//                           enterprise transducer's per-tenant config; the
//                           language binds no vendor).
//   - provenance: attached — the DEFAULT: every field lands with its origin
//                           (level + confidence + source), so a `speculate`
//                           email arrives LABELED a guess. `cleared` (bare
//                           values) is a compile-time refusal (axon-T920)
//                           unless the flow vouched via `epistemic { believe }`.
//   - secret: crm_api_key — the per-tenant credential resolved via §94
//                           custody at dispatch; the flow never touches it.
//   - effects: <web>      — a CRM write crosses the network trust boundary.
// Every operation carries an idempotency `key:` (a natural key like the
// email) so an at-least-once retry NEVER double-creates a record.
deliver PushLead {
    target:     crm
    provenance: attached
    secret:     crm_api_key
    effects:    <web>

    upsert_contact {
        key:       lead_email
        email:     lead_email
        firstname: lead_name
        company:   lead_company
    }
}

// The flow that feeds the delivery. It enriches the partial lead; the
// deliver's `ref` fields (lead_email / lead_name / lead_company) resolve
// against the flow's bindings by name at dispatch. The enriched value is
// Untrusted — a real pipeline routes it through a `shield` + an `anchor`
// (confidence_floor) before booking it; here we keep the example focused on
// the deliver surface.
flow CaptureLead(name: String, company: String) -> Json {
    use Enrich(name = name, company = company)
    return Enrich.output
}
