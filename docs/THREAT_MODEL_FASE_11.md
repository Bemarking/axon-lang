# Threat model — Fase 11 (axon-lang + axon-enterprise v1.2.0)

Extends `docs/THREAT_MODEL.md` (Fase 10 baseline) with the new
attack surface introduced by the Neuro-Symbolic Micro-OS
primitives: zero-copy buffers across FFI, WebSocket stateful
cognitive persistence, ReplayToken audit replay, LegalBasis
typed effects, and OTS subprocess pipelines.

**Review cadence:** per release tag. Signed off by the engineering
lead and the external pentester on the v1.2.0 cycle (see
`docs/SECURITY_AUDIT_v1_2_0.md`).

## Scope additions vs Fase 10

| Surface | Introduced in |
|---|---|
| `Stream<T>` backpressure primitive | 11.a |
| `Trusted<T>` / `Untrusted<T>` refinement types + closed trust catalogue | 11.a |
| `ZeroCopyBuffer` + `BufferPool` + PEP 3118 buffer protocol | 11.b |
| `multipart/form-data` + WebSocket binary ingest | 11.b |
| `ReplayToken` canonical hashing + ReplayLog persistence | 11.c |
| `LegalBasis` closed catalogue (GDPR / CCPA / SOX / HIPAA / GLBA / PCI-DSS) | 11.c |
| `CognitiveState` + `ContinuityToken` envelope-encrypted persistence | 11.d |
| OTS pipeline synthesis + ffmpeg subprocess fallback | 11.e |

## STRIDE — Fase 11

### Spoofing

| Threat | Mitigation | Test |
|---|---|---|
| Attacker forges a continuity token to hijack a mid-flow session | HMAC-SHA256 signer key + constant-time compare; typed `Forged` / `Expired` errors | `t_11_04_continuity_token_signed_with_attacker_key_rejected` |
| Attacker replays a sniffed session_id without the continuity handshake | Server mandates valid `ContinuityToken` at reconnect; `session_id` alone reaches no backend | `t_11_04_attacker_key_cannot_mint_valid_handshake` |
| Attacker signs an arbitrary HMAC payload as `Trusted<T>` | Closed catalogue of verifiers — only functions named in `axon.runtime.trust.TRUST_VERIFIERS` (Python) / `trust_verifiers.rs` (Rust) satisfy the refinement | `t_11_06_unknown_trust_proof_rejected` |

### Tampering

| Threat | Mitigation | Test |
|---|---|---|
| Attacker mutates a `ReplayToken` row post-hoc | Enterprise `axon_control.replay_tokens` has `BEFORE UPDATE/DELETE/TRUNCATE` triggers raising SQLSTATE 42501; canonical hash re-verified at record-time; audit-chain anchor in 10.g chain | `test_append_only_trigger_blocks_delete` (axon-enterprise) |
| Attacker tampers with `outputs_hash_hex` on the wire | `ReplayService._verify_inputs_outputs_hashes` re-canonicalises + hashes; mismatch → `ReplayTokenMalformed` | `test_record_rejects_tampered_outputs_hash` (axon-enterprise) |
| Attacker mutates a persisted cognitive-state ciphertext | Envelope AAD binds `(tenant_id, session_id, flow_id, subject_user_id)` — any row-swap fails AEAD verification before plaintext surfaces | `test_ciphertext_bound_to_row_aad` (axon-enterprise) |
| Attacker swaps a μ-law decode result mid-pipeline | Dijkstra + `Pipeline.execute` verify per-step `source_kind == prev_sink_kind`; `KindMismatchError` on drift | `pipeline_detects_kind_mismatch_on_wrong_input` (11.e) |

### Repudiation

| Threat | Mitigation | Test |
|---|---|---|
| Operator claims a sensitive effect never ran | Every effect invocation on a `@sensitive` tool emits a `ReplayToken` — hash-chained to the tenant's audit log via `replay:token_emitted` | Covered by 11.c enterprise suite |
| Tenant claims a cognitive-state snapshot was never persisted | `pem:state_persisted` audit event fires atomically inside the persist transaction with the state row | `test_persist_stores_ciphertext_and_emits_audit` (11.d enterprise) |
| Tenant denies a divergence between recorded + re-executed effect | `ReplayExecutor.replay_token` returns `ReplayMismatch` with expected + actual hashes; `record_divergence` emits `replay:divergence_detected` | `test_replay_executor_detects_provider_drift_as_divergence` (11.f) |

### Information disclosure

| Threat | Mitigation | Test |
|---|---|---|
| SAR export reveals ciphertext of another subject's cognitive state | `SarExporter._collect_tables` scopes by `subject_user_id` AND redacts `state_ciphertext` (no envelope key for the SAR recipient) | 10.l SAR integration test extended by 11.d |
| Cross-tenant buffer bleed via `SymbolicPtr` fan-out | `BufferPool` is global; tenant tag travels through clone / slice / retag — cross-tenant operations fail at the service layer (tenant_id mismatch in enclosing session) | `t_11_05_retag_preserves_tenant_tag_so_cross_tenant_tag_does_not_leak` |
| ffmpeg subprocess leaks ePHI via stdout / stderr | HIPAA + ffmpeg is REJECTED at compile time; ePHI flows never reach a subprocess | `t_11_03_hipaa_plus_ffmpeg_always_rejected` |
| `ReplayToken.inputs` contains PII; SAR export dumps it into the bundle | `SarExporter` filters `compliance_requests` by `subject_email`; `replay_tokens` filter by `subject_user_id` — a cross-subject dump is structurally impossible | 10.l SAR + 11.c token service integration |
| LLM `outputs` leaked in structured audit-chain event | `replay:token_emitted` event includes only the token hash, not the structured outputs | `test_record_persists_and_emits_audit` |

### Denial of service

| Threat | Mitigation | Test |
|---|---|---|
| Attacker saturates `Stream<T>` with high-rate producer | Backpressure policy REQUIRED; `DropOldest` / `DegradeQuality` / `PauseUpstream` / `Fail` chosen explicitly per flow | Covered by 11.a suite; k6 `audio_frame_rtt_ms` p99 < 500ms |
| Attacker exhausts BufferPool with oversize allocations | Slab allocator caps per-class capacity (4 KiB / 64 KiB / 1 MiB / 10 MiB + oversize = direct heap); per-tenant soft-limit counter surfaces operator-visible metric | 11.b `BufferPool` tests |
| Attacker floods the ReplayLog to bloat audit chain | `pg_advisory_xact_lock(hashtext(tenant_id))` serialises per-tenant writers; cross-tenant throughput unaffected | 10.g load + 11.c emission SLO (k6 < 2ms p99) |
| ffmpeg subprocess hangs consuming worker memory | `FfmpegPool` TTL evicts idle pipelines; adopter sets `FfmpegPoolConfig.max_entries`; unresponsive subprocess killed when the TokioCommand handle drops | `pool_registers_without_crashing_when_ffmpeg_missing` + operator runbook |
| Dijkstra path search over a pathological registry graph | Registry is built at startup with bounded edges per kind; runtime cannot install a transformer (see §11.e decision "no hot-load") | 11.e tests |
| CognitiveState rehydration on a 10 MiB payload | State size exposed as `state_size_bytes` metadata column so the eviction worker + admin dashboard can alert; snapshots larger than 64 KiB are surfaced as ops warnings but not blocked | 11.d SLO + operator policy |

### Elevation of privilege

| Threat | Mitigation | Test |
|---|---|---|
| `Untrusted<T>` payload reaches a sensitive consumer without refinement | Compile-time check in `axon-rs::type_checker` enforces reach to a `trust:<proof>` effect before sensitive consumption | 11.a `flow_with_untrusted_parameter_requires_verifier_tool` |
| Flow declares `@sensitive` but omits `LegalBasis` | Same-tool coherence rule in the checker: `sensitive:<c>` without `legal:<b>` fails compilation | 11.c + `t_11_02_sensitive_without_legal_basis_fails_compilation` |
| HIPAA ePHI escapes to a subprocess | Compile-time rejection of `sensitive:* + legal:HIPAA.* + ots:backend:ffmpeg` | `t_11_03_hipaa_plus_ffmpeg_always_rejected` |
| Flow skips `LegalBasis` declaration on one tool while another tool carries it | Same-tool coherence (not cross-tool) — every sensitive tool declares its OWN basis per the GDPR Art 6 "each processing activity has a lawful basis" principle | `t_11_02_legal_basis_in_different_tool_does_not_satisfy_same_tool_rule` |
| Adopter ships a custom verifier with a non-constant-time compare | Trust catalogue is CLOSED — only curated verifiers in `trust_verifiers.rs` satisfy the refinement. Adopters contribute upstream | 11.a catalogue tests |

## AI/ML-specific threats (new surface, not in Fase 10 model)

These 5 threats are unique to the LLM-orchestration nature of
Axon and are expressly covered by Fase 11 controls.

### T-ML-01 Model-swap replay

**Threat.** An adopter silently upgrades their LLM provider
(e.g. `openai/gpt-4o-2024-11-20` → `openai/gpt-4o-2024-12-20`).
Previously-emitted ReplayTokens now diverge on replay, but the
production pipeline's human-visible behaviour unchanged. Auditors
cannot detect the swap.

**Mitigation.** `ReplayToken.model_version` is part of the
canonical hash. A replay against a different `model_version`
produces `ReplayMismatch` with both model strings surfaced in
the divergence report. Operators opt in to a mismatch with an
explicit `@force_replay(new_model)` annotation that emits
`replay:model_mismatch` audit event (ships in a Fase 11.f
follow-up if it becomes necessary; the core invariant is already
in place via `model_version` being hash input).

**Test:** `test_replay_executor_detects_provider_drift_as_divergence`.

### T-ML-02 Prompt injection mid-replay

**Threat.** An attacker who compromised a tool's output payload
between emission and replay can corrupt the replay executor into
invoking a different effect downstream. The adversary need only
control a single field in the JSON outputs.

**Mitigation.** Canonical-JSON hashing covers the ENTIRE output
object; a single-field tamper changes `outputs_hash_hex`. Re-
execution hashes the recomputed output and compares
constant-time against the recorded hash. Mismatch → `ReplayMismatch`.

**Residual risk.** If the attacker controls both the payload AND
the enterprise database AND the audit chain, they can rewrite
the recorded hash. This is out-of-scope per the Fase 10 baseline
("compromised infrastructure account"). Audit chain hash
continuity surfaces the tamper.

**Test:** `t_11_01_canonical_hash_rejects_key_reorder_as_different`
+ `test_t_11_01_canonical_hash_differs_when_content_differs`.

### T-ML-03 Buffer exhaustion via SymbolicPtr refcount leak

**Threat.** An adopter that clones `SymbolicPtr<ZeroCopyBuffer>`
across background tasks without releasing clones holds onto pool
slabs indefinitely. Memory grows unbounded.

**Mitigation.** `weakref.finalize()` on Python; `Arc` strong-count
on Rust — refcount decrements on drop deterministically. Pool
free-list is capped at 64 slabs per class, so excess returns to
the heap (no unbounded pool growth regardless of leak). Per-tenant
`live_bytes` metric surfaces leaks to operators.

**Test:** `test_drop_decrements_refcount` + `BufferPool`
free-list cap test.

### T-ML-04 Continuity-token phishing

**Threat.** An attacker who observes the WebSocket TLS handshake
OR an adopter's misbehaving logging captures a continuity token
at disconnect. Replay reconnects with the stolen token.

**Mitigation.** Token TTL default 15 minutes bounds the window.
HMAC key rotation (on the same cadence as refresh-token signing
keys in 10.b) invalidates every outstanding token. Server MAY
enforce client-IP binding on the token body (optional;
transport-level mTLS already provides this for production
deployments).

**Residual risk.** A legitimate user observing their own TLS
traffic can impersonate themselves on another device during the
TTL window — not a threat, that's the intended UX.

**Test:** `t_11_04_*` family (forged key rejected, expired
rejected, session_id swap rejected).

### T-ML-05 HIPAA boundary breach via subprocess

**Threat.** Adopter misconfigures an ffmpeg-backed OTS pipeline
on a flow that processes ePHI. ePHI crosses to the subprocess;
stdout / stderr / tmp files become disclosure vectors not
covered by the BAA.

**Mitigation.** Compile-time rejection of the combination
`sensitive:* + legal:HIPAA.* + ots:backend:ffmpeg`. Adopter
must either (a) register a native transformer that covers the
required pipeline or (b) use a HIPAA-compliant subprocess
wrapper (explicitly registered as `TransformerBackend::Native`
with in-process crypto + the BAA in scope — future work if
demand justifies the complexity).

**Residual risk.** Non-HIPAA regulated data (GDPR / GLBA / PCI)
CAN use ffmpeg; the adopter's ops team accepts the subprocess
risk at deployment time.

**Test:** `t_11_03_hipaa_plus_ffmpeg_always_rejected` +
`t_11_03_hipaa_plus_native_compiles_cleanly`.

## Known residual risks (accepted)

- **Compromised envelope master key** (10.b) still defeats cognitive-state
  confidentiality. KMS-backed envelopes move the bar; accepted per
  Fase 10 baseline.
- **ffmpeg 0-day in a dependency** reaches subprocess stdout. Mitigation:
  pinned dependency + weekly `pip-audit` / `cargo audit`; `FfmpegPool`
  isolates per-call; GDPR/PCI adopters accept residual risk at deploy.
- **Q32.32 precision loss** (≈ 2.3e-10) on cognitive-state density
  matrix. Acceptable because belief states routinely round to
  thousandths; the test harness documents the bound.
- **Dijkstra worst-case path search** on an adversarially pathological
  registry — prevented by startup-only registration (no runtime
  mutation) and bounded edge count per kind.

## Verification

- Unit + integration: `cargo test --all` + `pytest tests/`
- Security adversarial: `pytest tests/test_fase_11f_cross_phase.py` +
  `cargo test --test fase_11f_security_adversarial`
- Cross-phase integration: `cargo test --test fase_11f_cross_phase_integration`
- Load (SLOs): `k6 run tests/load_fase_11/*.js`
- External pentest: required PRE-GA for v1.2.0 — see
  `docs/SECURITY_AUDIT_v1_2_0.md` sign-off gates.
