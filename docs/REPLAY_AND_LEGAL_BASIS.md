# Deterministic Replay + Legal-Basis Typed Effects

§λ-L-E Fase 11.c. The differentiator for regulated verticals
(banking, fintech, legaltech, medicaltech). Two primitives land
together because they answer the same regulatory question from
two sides:

- **LegalBasis<>**  — "under which law did this system process
  this data?" — enforced at *compile time* by the checker.
- **ReplayToken**  — "can you reproduce bit-for-bit what the system
  did, right now, from its own records?" — enforced at *runtime* +
  hash-anchored to the 10.g audit chain.

Together they close the auditor's loop: every sensitive effect is
tied to a declared legal basis AND to a re-executable receipt that
proves the system behaved as recorded.

## LegalBasis — the closed catalogue

Unlike the open `BufferKind` registry in 11.b, the `LegalBasis`
catalogue is **closed**: each slug maps to a real article/section
of a real regulation, and adding one requires a compiler patch
+ legal review.

| Slug | Regulation | Scope |
|---|---|---|
| `GDPR.Art6.Consent` | GDPR | Consent to processing personal data |
| `GDPR.Art6.Contract` | GDPR | Performance of a contract |
| `GDPR.Art6.LegalObligation` | GDPR | Compliance with legal obligation |
| `GDPR.Art6.VitalInterests` | GDPR | Vital interests of subject |
| `GDPR.Art6.PublicTask` | GDPR | Task in the public interest |
| `GDPR.Art6.LegitimateInterests` | GDPR | Legitimate interests (balance test) |
| `GDPR.Art9.ExplicitConsent` | GDPR | Explicit consent for special-category data |
| `GDPR.Art9.Employment` | GDPR | Employment / social security |
| `GDPR.Art9.VitalInterests` | GDPR | Vital interests (Art. 9 scope) |
| `GDPR.Art9.NotForProfit` | GDPR | Not-for-profit bodies |
| `GDPR.Art9.PublicData` | GDPR | Manifestly made public |
| `GDPR.Art9.LegalClaims` | GDPR | Establishment / defence of legal claims |
| `GDPR.Art9.SubstantialPublicInterest` | GDPR | Substantial public interest |
| `GDPR.Art9.HealthcareProvision` | GDPR | Preventive / occupational medicine |
| `GDPR.Art9.PublicHealth` | GDPR | Public-health reasons |
| `GDPR.Art9.ArchivingResearch` | GDPR | Archiving / scientific research |
| `CCPA.1798_100` | CCPA | Right-to-know acknowledgement |
| `SOX.404` | SOX | Internal-controls attestation |
| `HIPAA.164_502` | HIPAA | Permitted uses + disclosures of PHI |
| `GLBA.501b` | GLBA | Safeguards rule (non-public personal info) |
| `PCI_DSS.v4_Req3` | PCI-DSS | Stored cardholder data protection |

## Source syntax

Two effect slugs are added to the catalogue in 11.c:

- `sensitive:<category>` — this tool touches regulated data. The
  category is an **open taxonomy** (adopter-defined) because data
  categories vary wildly by vertical.
- `legal:<basis>` — this tool's processing is authorised under the
  named basis. The basis MUST be in the closed catalogue above.

```axon
tool process_patient_note {
  provider: local
  timeout: 30s
  effects: <sensitive:phi, legal:HIPAA.164_502>
}

tool authorize_wire_transfer {
  provider: local
  timeout: 10s
  effects: <sensitive:financial_txn, legal:SOX.404>
}

tool export_eu_user_data {
  provider: local
  timeout: 30s
  effects: <sensitive:eu_personal_data, legal:GDPR.Art6.Consent>
}
```

## Compile-time contract

The checker enforces:

1. Every tool declaring `sensitive:<category>` MUST also declare
   `legal:<basis>` from the closed catalogue. **Same tool.** Not
   "somewhere in the flow"; compliance authors wanted each
   processing boundary to carry its own declared basis.
2. `legal:<basis>` with an unknown slug → error listing the full
   catalogue.
3. `sensitive` without a category qualifier → error.
4. `legal` without a basis qualifier → error.

Error messages the checker emits:

```
error: Tool 'process_patient_note' declares sensitive effect(s)
       [phi] but carries no 'legal:<basis>' effect. Regulated
       processing requires an explicit legal basis: GDPR.Art6.Consent,
       GDPR.Art6.Contract, ...
```

```
error: Unknown legal basis 'hipaa.164_502' in tool 'x'. Valid:
       GDPR.Art6.Consent, ..., HIPAA.164_502, ...
```

## ReplayToken — the receipt

Every effect invocation the runtime performs produces a
`ReplayToken` with:

- `effect_name` — `call_tool:send_slack`, `llm_infer:claude-opus-4-7`,
  `db_read:customers`.
- `inputs` / `outputs` — the structured data (retained for replay),
  plus their canonical SHA-256 hashes for tamper detection.
- `model_version` — stable slug for deterministic effects
  (`axon.builtin.db_read.v1`); provider model id for LLM effects.
- `sampling` — `temperature`, `top_p`, `top_k`, `seed`, `max_tokens`,
  plus provider-specific `extras`.
- `timestamp`, `nonce` (128-bit random).
- `token_hash_hex` — SHA-256 over the canonical RS-separated
  encoding of the above. Matches Rust + Python byte-for-byte.

Canonical-JSON hashing uses the same algorithm as the 10.g audit
chain: key-sorted, no whitespace, ASCII-safe escapes, Record
Separator `\x1e` between logical fields. A ReplayToken's hash
anchors directly into the audit chain as a `replay:token_emitted`
event.

## Enterprise persistence

`axon_enterprise.replay`:

- `ReplayTokenRecord` ORM → `axon_control.replay_tokens` table
  (tenant-scoped + RLS + `BEFORE UPDATE/DELETE/TRUNCATE` triggers
  with SQLSTATE 42501 — same append-only posture as `audit_events`).
- `ReplayService.record` persists a token AND emits the anchoring
  `replay:token_emitted` audit event — the two writes happen in
  the same transaction.
- `ReplayService.record_divergence` is called by the executor when
  a replay fails; emits `replay:divergence_detected` with `status`
  = `failure` so divergences surface in operator dashboards.
- `Alembic 011_replay_tokens.py` creates the table + triggers +
  RLS policies, foreign-keys `audit_event_id` back to
  `axon_control.audit_events` so the replay graph is itself
  queryable through the audit writer.

## Re-execution protocol

`ReplayExecutor` orchestrates the protocol without owning any
dispatch logic — adopters plug in an `EffectInvoker` (their own
HTTP client, LangChain adapter, etc.):

```python
from axon.runtime.replay import (
    ReplayExecutor, InMemoryReplayLog, EffectInvoker,
)

class MyInvoker(EffectInvoker):
    def invoke(self, effect_name, inputs, model_version, sampling):
        # Adopter dispatch — must be deterministic for deterministic
        # effects, honour sampling.seed for LLM calls.
        return self.dispatcher.call(effect_name, inputs, ...)

executor = ReplayExecutor(log=my_replay_log, invoker=MyInvoker())
outcome = executor.replay_token(token_hash_hex)
# outcome is ReplayMatch or ReplayMismatch(divergence)
```

Outcome semantics:

- `ReplayMatch` — recomputed outputs hash exactly to the recorded
  `outputs_hash_hex`. The effect reproduces deterministically under
  the recorded model + sampling.
- `ReplayMismatch(divergence)` — recomputed hash differs. The
  `divergence` field carries `expected_outputs_hash_hex`,
  `actual_outputs_hash_hex`, and the structured `actual_outputs`
  so an operator sees exactly what differs without re-running.

## Non-replayable effects

Providers that don't support seeded sampling cannot participate in
deterministic replay. The convention: tool descriptors mark such
effects `@non_replayable` and the checker (follow-up to 11.c)
rejects their use inside a `@sensitive` context. For 11.c they are
legal to invoke outside regulated scopes; 11.c.1 extends the
checker to enforce the incompatibility at compile time.

## Model-version changes

A `ReplayToken` records the exact model version at call time. If
an adopter upgrades their LLM provider mid-stream, replays against
the old token will diverge — that's by design, not a bug. To
intentionally replay against a new model the adopter calls the
invoker with a deliberate override and emits a new token.

## Why this is the regulated-vertical unlock

The SOX § 404 question is always "show me that your controls
worked on this date for this transaction". The HIPAA § 164.502
question is always "show me that PHI disclosures had a lawful
basis". The GDPR Art. 6 question is always "show me which basis
you relied on".

With 11.c, each of those questions has a machine-checkable
answer. The regulator:

1. Picks a tenant + a date range.
2. Pulls every `ReplayToken` from `axon_control.replay_tokens`
   filtered by `legal_basis` + `recorded_at`.
3. Re-runs every token via `ReplayExecutor`.
4. Receives a list of `ReplayMatch` / `ReplayMismatch` outcomes —
   with the exact decision graph hash-anchored to the tenant's
   audit chain.

No prose. Receipts.

## Where to look in the code

- Rust closed catalogue: [`axon-rs/src/legal_basis.rs`](../axon-rs/src/legal_basis.rs)
- Rust ReplayToken + log + executor: [`axon-rs/src/replay_token/`](../axon-rs/src/replay_token/)
- Rust checker extension (sensitive + legal qualifier + tool coherence): [`axon-rs/src/type_checker.rs`](../axon-rs/src/type_checker.rs)
- Python catalogue mirror: [`axon/compiler/legal_basis.py`](../axon/compiler/legal_basis.py)
- Python checker mirror: [`axon/compiler/legal_basis_check.py`](../axon/compiler/legal_basis_check.py)
- Python runtime mirror: [`axon/runtime/replay/`](../axon/runtime/replay/)
- Enterprise persistence: `axon_enterprise/replay/` + Alembic `011_replay_tokens.py`
- Rust integration tests: [`axon-rs/tests/fase_11c_replay_and_legal_basis.rs`](../axon-rs/tests/fase_11c_replay_and_legal_basis.rs)
- Python unit tests: [`tests/test_fase_11c_replay.py`](../tests/test_fase_11c_replay.py), [`tests/test_fase_11c_legal_basis_check.py`](../tests/test_fase_11c_legal_basis_check.py)
- Enterprise integration tests: `axon-enterprise/tests/replay/test_service_integration.py`
