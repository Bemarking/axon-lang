---
name: deliver
summary: "Governed CRM Delivery — the egress-dual of acquisition. A declarative, compile-time-validated write of assertions into a system of record (a CRM): idempotent operations (`upsert_contact`/`create_deal`/`add_note`), per-tenant credentials via §94 custody, `web` effect. The provenance-stripping barrier (T920) refuses a `provenance: cleared` delivery of an unshielded flow value — a vendor guess must arrive in the CRM labeled as a guess, not laundered into a fact."
category: operators
top_level: true
since: Fase 105 (v2.60.0)
grammar: |
  deliver <Name> {
      target:     crm                     # required — the system-of-record class (T921)
      provenance: attached | cleared      # optional — how field origin crosses (default attached, T922)
      secret:     <credential_key>        # required — per-tenant key, §94 custody (T923)
      effects:    <web, sensitive:<cat>, legal:<basis>>   # must include web (T924)

      # ── operations (closed catalog per target) ──
      upsert_contact {                    # idempotent by natural key
          key:       <value>              # required — idempotency key (T926)
          email:     <value>
          firstname: <value>
          company:   <value>
      }
      create_deal { key: <value>  name: <value>  amount: <value> }
      add_note    { key: <value>  body: <value> }
  }
---

# `deliver`

`deliver` declares **a write of assertions into a system of record**
(a CRM) as a declarative, compile-time-validated structure. It is the
**dual of `scrape` (§98)**: where a scraped value ENTERS the program
born adversarial and Untrusted, a delivered value LEAVES the epistemic
lattice into a machine system that downstream humans — a sales rep, an
account manager, an auditor — will read *as fact*
(`delivery_is_assertion_egress`).

A contact row *in a CRM reads as verified* — the system of record itself
confers an authority the value never earned. A §104-enriched email is a
vendor's probabilistic guess (born `speculate`/`believe`, never `know`);
landing it in HubSpot as a bare string **launders the guess into a
fact**. The **provenance-stripping barrier** makes that impossible by
construction: a flow value delivered with `provenance: cleared` and no
epistemic vouch is `axon-T920`. It is the exact egress-form of §99's
assertion-laundering barrier (`document`, T916).

## Surface

`deliver` is a **top-level declaration**. `target:` selects a
system-of-record *class*, not a vendor — the concrete CRM (HubSpot,
Salesforce, Pipedrive, …) is the enterprise transducer's per-tenant
configuration, so the language binds no vendor (D105.1).

```axon
deliver push_lead {
    target:     crm
    provenance: attached
    secret:     crm_api_key
    effects:    <web>

    upsert_contact {
        key:       resolved_email        # idempotency key — a retry never double-creates
        email:     resolved_email
        firstname: resolved_name
        company:   company_name
    }
}
```

> With `provenance: attached` (the default) each field lands in the CRM
> alongside its `axon_provenance` block — the epistemic level,
> confidence, source vendor, and acquisition time — so a `speculate`
> email arrives *labeled as a guess*. The barrier is **labeling, not
> prohibition**: the lead pipeline delivers guesses honestly instead of
> being blocked. Only *silent stripping* is forbidden.

## The barrier (`axon-T920`)

`provenance: cleared` delivers bare values (no provenance block). That
is an assertion that the values are verified facts, and it is legal
**only** when the author vouches by wrapping the delivery in
`epistemic { mode: believe }` / `{ mode: know }` — which itself is only
sound after a `shield` (scanning `hallucination`/`pii_leak`) and an
`anchor` (a `confidence_floor`) cleared the value upstream. A
`provenance: cleared` delivery that binds any flow value with no such
vouch is `axon-T920`.

```axon
# T920: launders a flow value into the CRM as a bare fact.
deliver bad { target: crm  secret: k  effects: <web>
    upsert_contact { key: guessed_email  email: guessed_email }   # provenance: cleared, unvouched
}

# OK: the author vouches the values are ≥ believe.
epistemic { mode: believe }
deliver good { target: crm  secret: k  effects: <web>
    upsert_contact { key: verified_email  email: verified_email }
}
```

## Fields

### `target:` (required)

`crm` — a closed catalog (`axon-T921`). Additive: future
system-of-record classes (marketing automation, helpdesk) land here.

### `provenance:` (optional)

`attached` (default) | `cleared` (`axon-T922`). `attached` carries each
field's epistemic origin into the CRM record; `cleared` strips it and is
gated by `axon-T920`.

### `secret:` (required)

The per-tenant credential key (`axon-T923`). Resolved via §94 secret
custody at dispatch — the value crosses only at the transducer boundary,
never into cognition (`rotation_without_revelation`). For an OAuth CRM,
token refresh is a §94 `rotate` (CAS), not a bespoke flow.

### `effects:` (required to include `web`)

A CRM write crosses the network trust boundary, so the row must include
`web` (`axon-T924`). `sensitive:<category>` / `legal:<basis>` are
**propagated** from the delivered data — delivering PII into a system of
record is *further processing* (D105.6); a `sensitive:*` delivery with no
`legal:<basis>` is `axon-T924`.

### operations (closed catalog, `axon-T925`)

- **`upsert_contact`** — idempotent create-or-update of a person by
  natural key (email/domain).
- **`create_deal`** — an opportunity/deal object.
- **`add_note`** — a timeline note against an existing record.

Every operation requires a **`key:`** — the idempotency key
(`axon-T926`) so an at-least-once retry (Brief #63 hard-deadline
timeouts included) never double-creates a record (D105.5). A miss or a
vendor failure degrades to a typed error + an audit row, never a
fabricated receipt.

## What this primitive is NOT

- **Not a general HTTP client.** `deliver` writes canonical, typed CRM
  operations, not arbitrary requests. Arbitrary egress is a `tool` over
  `provider: http` — without the T920 barrier or the idempotency law.
- **Not a bidirectional sync.** `deliver` is egress only; reading a CRM
  back into the program is future scope (and would be born Untrusted,
  the §98 problem).
- **Not a connector catalog.** The language binds no vendor; the
  enterprise transducer maps the canonical operations onto the tenant's
  configured CRM. axon competes on the governed boundary, not on
  connector breadth.
- **Not a lawful basis.** Governance (per-tenant enable default OFF, SoD
  `crm:deliver`, the audit trail) demonstrates diligence; it does not
  create a GDPR lawful basis for the PII being delivered (D105.6).
