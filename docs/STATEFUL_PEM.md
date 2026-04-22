# Stateful PEM over WebSocket

§λ-L-E Fase 11.d. Cognitive posture survives a WebSocket drop:
density matrix, belief state, short-term memory all snapshot to an
envelope-encrypted row in Postgres and rehydrate — bit-identical —
when the client reconnects with a valid continuity token.

The primitive the rest of Axon binds against is
`axon.runtime.pem.CognitiveState`; the production persistence
sits in `axon_enterprise.cognitive_states`.

## The reconnect problem

A naive reconnect flow is a data-breach waiting to happen AND a
UX cliff waiting to ship. Three things must hold simultaneously:

1. **Identity proof.** A party reconnecting with a session_id must
   prove they're the original client — a sniffed session_id alone
   must not grant mid-flow takeover.
2. **State fidelity.** The density matrix that shipped to the
   client before the drop must rehydrate bit-for-bit. IEEE-754
   round-trip drift across N snapshots is what we're defending
   against.
3. **Data minimisation.** Cognitive state typically carries PII
   (user messages, inferred preferences). The persistence layer
   must encrypt at rest + evict on schedule + respect GDPR
   Art. 17 erasure.

11.d solves all three.

## Q32.32 fixed-point encoding

Floats inside `density_matrix` become signed 64-bit integers with
32 bits of fractional precision:

```
q = (f * 2^32).round() as i64
f = q / 2^32
```

Representable precision: `2^-32 ≈ 2.3e-10`. Worst-case precision
loss on the first quantisation is less than the float's own
rounding error; subsequent snapshots encode the *same* integer so
downstream hashing, replay and SAR export are all byte-stable.

The test `density_matrix_bit_identical_after_three_reconnects`
asserts this invariant in both Rust and Python suites.

## ContinuityToken — reconnect handshake

On disconnect, the server mints a token:

```
raw = session_id ∥ 0x1E ∥ expiry_ms ∥ 0x1E ∥ HMAC-SHA256(secret, session_id ∥ 0x1E ∥ expiry_ms)
wire = base64url(raw)
```

- `session_id` binds the token to exactly one session.
- `expiry_ms` bounds the attack window (default 15 minutes, match
  the `@reconnect_window` annotation).
- `HMAC-SHA256` prevents forgery; the signer secret is rotated on
  the same cadence as refresh-token signing keys (§10.b).

Verification rejects three classes of attack (tests cover each):

- Forged HMAC → `ForgedOrRotated`
- Expired expiry_ms → `Expired`
- Tampered session_id → `ForgedOrRotated` (HMAC fails because body
  changed)

Constant-time comparison via `hmac::Mac::verify_slice` (Rust) /
`hmac.compare_digest` (Python) — tested in
`hmac_uses_constant_time_compare`.

## PersistenceBackend

```rust
#[async_trait]
pub trait PersistenceBackend: Send + Sync {
    async fn persist(&self, session_id: &str, state: &CognitiveState, ttl: Duration) -> ...;
    async fn restore(&self, session_id: &str) -> ...;
    async fn evict(&self, session_id: &str) -> ...;
    async fn evict_expired(&self, before: DateTime<Utc>) -> ...;
}
```

Shipped impls:

- `InMemoryBackend` — dev + test. Mutex-guarded `HashMap`; same
  TTL semantics as Postgres so tests don't diverge.
- Enterprise `CognitiveStateService` — production. Envelope-
  encrypted rows in `axon_control.cognitive_states`, AES-256-GCM
  with per-row wrapped DEK. AAD binds each ciphertext to
  `(tenant_id, session_id, flow_id, subject_user_id)` so row-
  level tampering fails the AEAD tag before decryption produces
  plaintext.

## Composition with Fase 10 + earlier 11

- **§10.b envelope:** Enterprise backend uses the same
  `EnvelopeEncryption` protocol as TOTP secrets. Rotating the
  envelope key rotates cognitive-state encryption transparently.
- **§10.g audit chain:** Every persist / restore / evict /
  reconnect-denied event lands in the tenant's audit chain as
  `pem:state_persisted`, `pem:state_restored`, `pem:state_evicted`,
  `pem:reconnect_denied`.
- **§10.l residency:** Cognitive-state ORM carries `tenant_id`;
  the DataResidencyMiddleware's region-check hits on every restore
  request, preventing cross-region rehydration when the tenant's
  `data_region` ≠ the server's.
- **§10.l SAR:** `SarExporter._collect_tables` now includes
  `cognitive_states.jsonl` — metadata only, the encrypted payload
  stays redacted because the SAR recipient doesn't hold the
  envelope key.
- **§10.l erasure:** `ErasureService.anonymize` deletes every
  cognitive-state snapshot owned by the subject as part of the
  scrub. KMS-backed envelopes make this a true cryptoshred; local-
  envelope adopters get row-delete semantics.
- **§11.a `Stream<T>` / `Trusted<T>`:** State carries already-
  refined user inputs; the compiler's refinement tracking holds
  across reconnects because `subject_user_id` is preserved and
  downstream effects continue to see `Trusted<T>` for the
  rehydrated payload.
- **§11.b `ZeroCopyBuffer`:** Short-term memory stores symbolic
  references (buffer IDs) not raw bytes, so a 30-minute audio
  conversation doesn't bloat the snapshot into the Postgres
  toast threshold.
- **§11.c `ReplayToken`:** `flow_id` is shared between state
  snapshots and replay tokens. An auditor pulling replay tokens
  for a flow can cross-reference the cognitive-state snapshots
  that surrounded each emission.

## Eviction worker

`CognitiveStateEvictionWorker` is the TTL sweeper — same shape as
`ComplianceWorker` from §10.l. Runs as a Deployment alongside
(or on the same pod as) the compliance worker; sweeps every
`poll_interval_seconds` (default 60s) and deletes rows whose
`expires_at` has lapsed.

```bash
axon-enterprise pem run-evictor
```

Single-process is fine for most tenants; the worker is idempotent
(the DELETE is a no-op on already-deleted rows) so N replicas are
safe.

## Wire format

`CognitiveState.encode()` returns key-sorted JSON with no
whitespace — same canonicaliser as §10.g + §11.c so consumers
that already parse audit events or replay tokens parse cognitive-
state snapshots too. The `density_matrix` cells serialise as raw
integers (not scaled floats); on decode they re-wrap into
`FixedPoint` for precision-safe access.

Wire schema (simplified):

```json
{
  "session_id": "sess-1",
  "tenant_id": "alpha",
  "flow_id": "flow-transcribe",
  "subject_user_id": "usr-42",
  "density_matrix": [[429496729, 858993459, 3006477108]],
  "belief_state": {"confidence": 3135890423},
  "short_term_memory": [
    {
      "key": "last_user_msg",
      "payload": {"text": "continue please"},
      "symbolic_refs": ["audio-buf-17"],
      "stored_at": 1700000000000
    }
  ],
  "created_at": 1700000000000,
  "last_updated_at": 1700000000100
}
```

## What 11.d does NOT include (deferred)

- **Client library for the WebSocket handshake.** Adopters wire
  their own WS transport today. The signer / verifier / backend
  are neutral to the transport.
- **Incremental snapshots.** Every `persist()` call rewrites the
  full state. A future revision ships a delta-compression codec
  for long-running sessions. The Q32.32 encoding makes this
  tractable (integer diffs are small + stable).
- **Cross-region replication.** Snapshots live in their tenant's
  region only. A multi-region PEM story needs CRDT design work —
  11.d explicitly defers it.

## Where to look in the code

- Rust primitives: [`axon-rs/src/pem/`](../axon-rs/src/pem/)
- Python mirror: [`axon/runtime/pem/`](../axon/runtime/pem/)
- Enterprise persistence: `axon_enterprise/cognitive_states/`
- Migration: `axon-enterprise/alembic/versions/012_cognitive_states.py`
- Audit events: `axon_enterprise.audit.events.AuditEventType.PEM_*`
- Rust integration tests: [`axon-rs/tests/fase_11d_stateful_pem.rs`](../axon-rs/tests/fase_11d_stateful_pem.rs)
- Python unit tests: [`tests/test_fase_11d_pem.py`](../tests/test_fase_11d_pem.py)
- Enterprise integration tests: `axon-enterprise/tests/cognitive_states/test_service_integration.py`
