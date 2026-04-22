# Security audit — GA readiness checklist (axon-lang + axon-enterprise v1.2.0)

Fase 11.f sign-off gate. Every item below must be green for a
`v1.2.0` release tag to ship on either repo. Attack surface added
by Fase 11 (FFI buffers + ffmpeg subprocess + WebSocket stateful
+ LLM replay + legal-basis typed effects) justifies tighter gates
than v1.1.0 — most notably, **external penetration testing is a
pre-GA requirement** for v1.2.0 (Fase 10 deferred it to v1.1.1;
Fase 11 does NOT).

Pair with [`THREAT_MODEL_FASE_11.md`](./THREAT_MODEL_FASE_11.md)
— this file is the pass/fail gate; the threat model is the why.

## Automated verification (CI must pass)

| Gate | Command | Pass criteria |
|---|---|---|
| Unit + integration (Rust) | `cargo test --all` | 100% pass |
| Unit + integration (Python) | `pytest tests/ -q` | 100% pass of non-skipped |
| Fase 11 adversarial (Rust) | `cargo test --test fase_11f_security_adversarial` | 100% pass |
| Fase 11 cross-phase (Rust) | `cargo test --test fase_11f_cross_phase_integration` | 100% pass |
| Fase 11 cross-phase (Python) | `pytest tests/test_fase_11f_cross_phase.py -q` | 100% pass (14+ tests) |
| Lint + type check | `cargo clippy -- -D warnings && ruff check . && mypy axon/` | No errors |
| Dependency audit | `cargo audit && pip-audit` | Zero known high-severity CVEs |
| Load — WS audio | `k6 run tests/load_fase_11/k6_ws_audio_stream.js` | All thresholds green |
| Load — replay emission | `k6 run tests/load_fase_11/k6_replay_emission.js` | p99 < 2ms |
| Load — OTS synthesis | `k6 run tests/load_fase_11/k6_ots_synthesis.js` | Cold p99 < 10ms, cached p99 < 0.1ms |
| Load — PEM snapshot | `k6 run tests/load_fase_11/k6_pem_snapshot.js` | Persist + restore p99 < 50ms for ≤ 64 KiB |

## Code-level invariants (Fase 11)

### 11.a Temporal Effects + Trust Types

- [x] `Stream<T>` in a flow signature fails to compile without a tool declaring `stream:<policy>` reach.
- [x] `Untrusted<T>` in a flow parameter fails to compile without a tool declaring `trust:<proof>` reach.
- [x] Closed trust catalogue (Hmac / JwtSig / OAuthCodeExchange / Ed25519) — unknown proofs rejected with targeted diagnostics.
- [x] HMAC verification uses `hmac::Mac::verify_slice` (constant-time via `subtle`).
- [x] Ed25519 verification uses `verify_strict` (rejects low-order points).

### 11.b Zero-Copy Buffers

- [x] `ZeroCopyBuffer` clone is O(1); slice shares carrier; retag creates a new view without mutating original.
- [x] Buffer pool free-list capped at 64 slabs per class; oversize allocations bypass the cache.
- [x] Tenant tag propagates through clone / slice / retag / freeze.
- [x] multipart parser rejects oversized headers + parts, nested multipart, missing boundary.
- [x] WebSocket binary accumulator rejects orphan continuation frames + oversized messages.

### 11.c Replay + Legal Basis

- [x] `LegalBasis` catalogue CLOSED (21 variants); unknown slugs rejected.
- [x] Tool with `sensitive:<c>` requires same-tool `legal:<b>` — different-tool declaration does NOT satisfy.
- [x] Canonical-JSON hashing matches between Rust + Python (byte-identical).
- [x] `replay_tokens` table has `BEFORE UPDATE/DELETE/TRUNCATE` triggers (SQLSTATE 42501).
- [x] `ReplayService.record` re-verifies inputs_hash + outputs_hash; tampered tokens fail with `ReplayTokenMalformed`.

### 11.d Stateful PEM

- [x] Q32.32 fixed-point density matrix is bit-identical across N serialise/deserialise cycles.
- [x] `CognitiveState` envelope AAD binds `(tenant_id, session_id, flow_id, subject_user_id)`.
- [x] Cross-row ciphertext swap fails AEAD tag before plaintext surfaces.
- [x] `ContinuityToken` HMAC verify uses constant-time compare; forged / expired / session-tampered tokens rejected.
- [x] Eviction worker DELETE is idempotent + emits `pem:state_evicted` per row.
- [x] `SarExporter` includes cognitive-state metadata (payload redacted).
- [x] `ErasureService.anonymize` deletes cognitive-state rows — cryptoshred when envelope is KMS-backed.

### 11.e OTS

- [x] `OTS_BACKEND_CATALOG` CLOSED (native / ffmpeg); unknown backends rejected.
- [x] `ots:transform:<from>:<to>` requires both from + to non-empty.
- [x] HIPAA + ffmpeg combination rejected at compile time.
- [x] GDPR / CCPA / SOX / GLBA / PCI-DSS + ffmpeg NOT blocked (targeted rule).
- [x] μ-law decoder matches ITU G.711 reference vectors (stored-vs-logical byte convention).
- [x] Pipeline execution detects per-step kind mismatches.
- [x] `ffmpeg` absence non-fatal — flows with native paths succeed.

## Operational controls (runtime-enforced)

- [x] Enterprise envelope rejects `local` backend in production (10.b validator).
- [x] JWT signer rejects `local` in production (10.e validator).
- [x] Compliance blob backend rejects `local` in production (10.l validator).
- [x] Replay-token append-only trigger installed by migration 011 (11.c).
- [x] Cognitive-state rows encrypted at rest (envelope + AAD binding) per migration 012 (11.d).
- [x] Data-residency middleware 308-redirects / 421-rejects mis-routed cognitive-state rehydrations (10.l + 11.d).
- [x] Continuity-token signer key rotation procedure documented + scheduled.

## Non-automatable review (sign off before tagging)

- [ ] **External penetration test** completed within 60 days of tag.
      Report attached to the release ticket. Required for v1.2.0
      (Fase 10 deferred to v1.1.1; Fase 11 does NOT defer because
      of novel attack surface: FFI buffers, ffmpeg subprocess,
      WebSocket stateful, LLM replay).
- [ ] Threat-model doc (`THREAT_MODEL_FASE_11.md`) reviewed + signed
      by the engineering lead + external pentester. Any threat marked
      "accepted" must have a named owner + review date.
- [ ] Envelope signer-key rotation dry-run executed in staging
      within the last 90 days.
- [ ] Continuity-token signer-key rotation runbook written + dry-run
      executed.
- [ ] HIPAA BAA review — verify no path a HIPAA-classified flow
      could take reaches `ots:backend:ffmpeg`. The compile-time
      rule is the primary defence; a manual sweep of the adopter's
      effect declarations on their first HIPAA-audited tenant
      closes the loop.
- [ ] SOC 2 control mapping updated — every Fase 11 audit event
      (`pem:*`, `replay:*`) has a corresponding control statement
      in the Type II report scope.
- [ ] Operator runbook — new procedures: pool saturation alert
      (`axon_buffer_pool_live_bytes` per tenant over soft limit),
      ffmpeg-pool TTL expiry spike (indicates flow churn or
      adversarial traffic), cognitive-state eviction-worker stall,
      ReplayDivergence alarm.
- [ ] Backup + restore test on `axon-enterprise` including
      migration 011 + 012 rows. Restored cluster passes `pytest -m
      integration` on its replay + cognitive-state + OTS suites.
- [ ] Legal review — `LegalBasis` catalogue additions (if any
      since last review) reviewed by compliance counsel.
- [ ] External-registered OTS transformers (adopter-supplied crates)
      audit trail: every crate pinned to a specific version, every
      version diff reviewed.

## SLO thresholds (k6-enforced)

| Surface | p95 | p99 | Error rate |
|---|---|---|---|
| WebSocket audio frame end-to-end (11.a + 11.b + 11.e) | 300ms | 500ms | < 0.5% |
| ReplayToken emission (11.c) | 1ms | 2ms | < 0.1% |
| OTS pipeline synthesis cold (11.e) | 5ms | 10ms | < 0.5% |
| OTS pipeline synthesis cached (11.e) | 0.05ms | 0.1ms | < 0.5% |
| CognitiveState snapshot+restore ≤ 64 KiB (11.d) | 30ms | 50ms | < 0.5% |

These map to the enterprise SLA. Any relaxation requires a
breaking-change release note.

## Known deviations (documented, accepted)

- **Q32.32 fixed-point precision ≈ 2.3e-10** on cognitive-state
  density matrix. Documented in `docs/STATEFUL_PEM.md`;
  belief states round to thousandths so the bound is comfortable.
- **Dijkstra path search** is O(V log V) per call; cached in the
  warm path so p99 < 0.1ms. Cold path capped at 10ms by the
  startup-seeded registry (bounded edge count per kind).
- **ffmpeg subprocess spawn-per-call** today. Pipe-in worker
  upgrade is a post-GA optimisation; the SLO holds without it
  because most flows hit the native path.

## Sign-off

Tagging `v1.2.0` on either repo requires:

1. All automated gates green on `master` (both repos).
2. All operational controls present in the infrastructure repo.
3. External pentest report attached to the release ticket — no
   open critical findings.
4. Non-automatable items acknowledged by engineering lead in
   the release checklist issue.
5. This document amended with any deviation between checklist
   and actual state — no silent skips.

Release command:

```bash
# axon-lang (dual-remote)
cd axon-lang/
git tag -a v1.2.0 -m "axon-lang v1.2.0 — Fase 11 Neuro-Symbolic Micro-OS"
git push origin v1.2.0 && git push enterprise v1.2.0

# axon-enterprise (enterprise-only release workflow)
cd ../axon-enterprise
git tag -a v1.2.0 -m "axon-enterprise v1.2.0 — Fase 11 integration"
git push origin v1.2.0     # triggers release.yml → ECR
```

The release workflow on axon-enterprise builds the Docker image
(bundling axon-lang binary + axon-enterprise Python package),
runs the full suite against a fresh Postgres including migrations
011 + 012, pushes to ECR as `axon/axon-enterprise:1.2.0`, and
creates a GitHub Release with the SOC 2 evidence bundle attached.
