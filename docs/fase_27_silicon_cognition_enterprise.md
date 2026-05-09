---
title: "Plan vivo: Fase 27 — Silicon + Cognition Enterprise (sesión 1) — FIPS-validated crypto + audit log mmap + vertical BPE + tamper-evident evidence packager"
status: IN PROGRESS 2026-05-09 — 27.a/b/c/d/e/f/g SHIPPED (commits 96846c9 / b2afe16 / 9800f89 / 2de250c / 2006042 / 837a578 to axon-enterprise master); 186/186 tests verdes Windows MSVC; 27.h–27.k pending (added 27.k.1 Python integration layer per orchestration audit); target axon-enterprise v1.10.0
owner: AXON Enterprise Team
created: 2026-05-09
updated: 2026-05-09
target: axon-enterprise v1.10.0 + nuevo crate `axon-csys-enterprise` (companion a OSS axon-csys 0.1.x) + companion Python package surface in `axon_enterprise.csys`
depends_on: Fase 25 OSS SHIPPED (axon-csys 0.1.1 + axon-lang 1.19.1); axon-enterprise v1.9.0 SHIPPED (consume base stack)
session_series: Silicon + Cognition Enterprise (1ª de varias — sesiones progresivas que llevan los enterprise-only kernels al metal: FIPS-validated crypto, audit log mmap append-only, vertical BPE, tamper-evident evidence packager, future TEE attestation, future quantum-resistant crypto)
companion_to: Fase 25 OSS — Silicon + Cognition (sesión 1) — Pure C migration of metal-bound kernels
charter_class: ENTERPRISE-only (per axon-enterprise charter: capa privilegiada con R&D vertical + behaviors enterprise-only)
---

## ▶ Status snapshot (2026-05-09 — IN PROGRESS)

Investigación profunda terminada (ver §1). D1–D14 ratificadas en bloque por founder ("No MVP, todo full robusto 100% producción + Enterprise" — todas las `Recommendation:` notes de §5 confirmadas verbatim). **27.a + 27.b + 27.c + 27.d + 27.e + 27.f + 27.g SHIPPED** (commits 96846c9 + b2afe16 + 9800f89 + 2de250c + 2006042 + 837a578 a `Bemarking/axon-enterprise` master). **186/186 tests verdes Windows MSVC** (10 probe + 32 crypto + 31 audit_log + 34 tokens + 32 evidence + 47 phi_scrub), clippy clean, fmt clean. 27.h–27.k pending. **Orchestration audit added a new sub-fase**: 27.k.1 Python integration layer (`axon_enterprise/csys/{audit_log,evidence,tokens,phi_scrub}.py` ctypes wrappers + supervisor wiring + Python tests) — separated from 27.k release prep so it has explicit scope + tests.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 27.a Engineering spec | ✅ SHIPPED 2026-05-09 | doc-only | — | This doc + memoria `project_fase_27_plan.md` + D1–D14 ratificadas (D11 public-chain → sesión 2; todos los demás ratified verbatim per founder bloque approval) |
| 27.b axon-csys-enterprise crate scaffold + cc-rs build infra + license posture (D2 BSL with 4-year delay → MIT) | ✅ SHIPPED 2026-05-09 commit `96846c9` | ~500 (actual ~1361 incl. LICENSE.bsl + README) | Rust + C + build.rs | crate `axon-csys-enterprise` 0.1.0 (`Cargo.toml` con BSL license-file + publish=false, `build.rs` con D3 mutual-exclusivity guard + cc-rs C23 chain inherited from OSS Fase 25.b, `src/lib.rs` con `FipsBackend` enum + OSS pass-through re-exports, `src/probe.rs`, `c-src/probe/probe.c`); LICENSE.bsl pattern HashiCorp/Sentry/MariaDB con Change Date 2030-05-09 + `Audit-Posture Service` Additional Use Grant; cargo features `fips-boringssl` + `fips-openssl` mutually exclusive (default = no-fips passthrough); 10 probe tests Windows MSVC (ABI version round-trip + feature flags + `__STDC_VERSION__` + cache-line alignment + `_Alignas(64)` verification + pure-arithmetic ABI smoke + OSS re-export round-trip) |
| 27.c FIPS-validated crypto link (BoringSSL or OpenSSL-FIPS, per cargo feature) | ✅ SHIPPED 2026-05-09 commit `b2afe16` | ~800 target / ~1748 actual (incl. NIST CAVS test harness) | Rust + extern C | `c-src/crypto/fips_glue.{c,h}` con C glue routing SHA-256 + HMAC-SHA256 a EVP API: OpenSSL-FIPS path usa `EVP_MD_fetch("SHA2-256", "fips=yes")` + `EVP_MAC_fetch("HMAC", "fips=yes")` para FORZAR el FIPS provider (defense in depth above just provider-load); BoringSSL path usa legacy `EVP_Digest` + `HMAC()` one-shots (entry points BoringSSL-FIPS validates); FIPS POST cached via `_Atomic int` CAS — first-call gates startup, subsequent calls short-circuit. `src/crypto.rs` con `#[cfg]`-gated routing: no-fips re-exports OSS verbatim, FIPS routes through FIPS-routed C glue + provides `fips_self_test()` + `backend_label()` for adopter startup gates. **`ContinuityWire` re-implemented in pure Rust on top of locally-routed HMAC** — bytes flow through FIPS-validated lib while wire format stays bit-for-bit compatible con tokens issued by OSS axon-csys 0.1.1 (D7 verified). `build.rs` con conditional fips_glue.c compilation + `AXON_BORINGSSL_FIPS_PREBUILT` / `AXON_OPENSSL_FIPS_PREBUILT` env var dispatch (openssl-sys convention). 32 crypto tests: NIST FIPS 180-4 §B.0/B.1/B.2 SHA-256 vectors + RFC 4231 HMAC TC1-7 (one-shot + streaming + split-at-every-boundary + empty inputs + RFC-2104 long-key auto-compression) + drift gate vs OSS axon-csys + sha2/hmac crates + 100-iter deterministic-seeded fuzz parity per primitive + 50-iter ContinuityWire fuzz + tamper detection + wrong-key rejection + forbidden 0x1e separator + malformed base64 + negative/extreme expiry + Unicode session_id + cross-verify with OSS |
| 27.d Audit log mmap append-only kernel | ✅ SHIPPED 2026-05-09 commit `9800f89` | ~1500 target / ~2825 actual | C + Rust shim | `c-src/audit/log.{h,c}` (~1700 LOC C) con cross-platform mmap (POSIX `mmap` + Windows `MapViewOfFile` con explicit `SetEndOfFile` for file growth) + 256-byte cache-line-aligned segment header con atomic `head_offset` + `event_count` fields → readers walk a snapshot consistent con what writer has committed (lock-free read, mutex-protected append). Append path: writer mutex (~hundreds of ns) + HMAC over `prev_hash || header || payload` keyed by per-tenant seal key; **routes through axon-csys OSS pure-C HMAC OR FIPS-routed HMAC depending on cargo features (27.c integration is automatic via `AUDIT_HMAC_BACKEND` macro)**. Cross-segment chain via `prev_segment_tail_hash` field: rotating to new segment carries previous tail forward as new chain anchor — tampered byte in segment N detected by N+1's prev_hash. Reopen + resume: walks existing chain to populate `last_seal_mac` so new appends extend tail correctly. Little-endian explicit `memcpy` encoding for cross-platform byte-identity. Defensive `memset` of tenant key on close. `src/audit_log.rs` (~430 LOC) safe API: `AuditLogWriter` (Send + Sync; thread-safe via C-side mutex) + `AuditLogVerifier` (Send + Sync; read-only) + `AuditLogError` enum con 17 mapped variants + `iterate` accepts `FnMut` closure via boxed-trait-object trampoline. 31 audit_log tests: append-only invariants + HMAC chain integrity + tamper detection on payload/timestamp/seal_mac/segment-anchor/block-prev-hash byte flips + per-tenant key separation (wrong key → ChainBroken; tenant_id mismatch → TenantMismatch at open) + reopen+resume + segment-rotation handoff + **8-thread × 100-event concurrent writers (800 events committed, verify passes)** + iterate round-trip + edge cases (empty payload, oversized rejected, too-small segment rejected, zero-length tenant key rejected, magic-corrupted segment fails open, nonexistent file fails cleanly). FlatBuffers note: el kernel es **payload-encoding-agnostic** (frame es length-prefixed binary, payload bytes opacos) — adopters supply FlatBuffers-encoded bytes if they want; the on-disk frame guarantees the chain integrity. Public-chain anchoring (D5) opt-in via future `public-anchor` cargo feature; reserved namespace exists.|
| 27.e Vertical BPE tokenizer templates (medical_base + legal_base + fintech_base) | ✅ SHIPPED 2026-05-09 commit `2de250c` | ~600 target / ~1389 actual (incl. 3 baked .bin blobs) | Python + Rust | `tools/train_vertical_merges.py` (~360 LOC) production-grade BPE trainer in OSS 25.g wire format; two run modes (seed regen from curated public-domain corpora embedded in tool / adopter retrain via `--corpus <full.txt> --target-vocab 32000`); `regex` lib pretokenizer fallback to stdlib `re` for ASCII-clean inputs. **Three baked seed encoders** trained at `target_vocab=4096`, `min_pair_freq=1`: `merges_medical_v1_seed.bin` (2380 tokens, 25 KB; ICD-10 + SNOMED-CT + FDA Orange Book + IDSA-KDIGO), `merges_legal_v1_seed.bin` (1932 tokens, 20 KB; FRCP + 28/18/17 U.S.C. + securities/IP litigation), `merges_fintech_v1_seed.bin` (2003 tokens, 21 KB; SEC EDGAR + ASC 606/842/350 + FFIEC + Basel III). `src/tokens.rs` con process-scoped `medical_base()` / `legal_base()` / `fintech_base()` accessors via `OnceLock`-cached `Tokenizer::from_blob`; reuses cl100k pretokenizer regex (vertical text follows English text patterns). `VerticalEncoderRevision` enum + `available_vertical_encoders()` + `vertical_encoder_for()` + `vertical_encoder_by_name()` for adopter ensemble dispatch (per D9). 34 tokens tests: loader correctness + round-trip integrity (vertical samples + generic English + Unicode + empty + long paragraphs) + **vertical token-cost reduction** (medical/legal/fintech v1_seed beats cl100k_base on jargon-DENSE text per vertical) + byte-coverage invariant (every byte 0x00..0xFF is single-token) + cross-vertical orthogonality (medical doesn't outcompress legal on legal text) + registration surface + caching + determinism (.bin blobs start with AXBP magic + stable SHA-256). **Honest scope**: v1 seed encoders ship as functional baseline + adopter-retraining template; "30-50% reduction" claim applies to FULL-corpus retrains via shipped Python tool, NOT to v1 seeds. |
| 27.f Tamper-evident evidence packager (byte-deterministic ZIP + Merkle + Ed25519 seal) | ✅ SHIPPED 2026-05-09 commit `2006042` | ~1200 target / ~2082 actual (incl. tests) | Rust (revised: pure Rust, not C) | **Design pivot**: pure Rust instead of C for the ZIP encoder. The "C uniquely wins" claim in plan vivo §1.1 was about avoiding `zip` crate's non-deterministic mtime field; writing our own deterministic encoder in Rust achieves the same byte-identity at lower complexity. `src/evidence.rs` (~770 LOC) `EvidenceBuilder` + `EvidenceVerifier` + `EvidenceOptions` + `Manifest` + `EvidenceError` (15 variants); manual canonical-JSON emitter (sorted keys, no whitespace, deterministic numeric formatting) + matching strict parser; Merkle root over sorted (path \|\| 0x00 \|\| sha256) leaves with Bitcoin-style odd-leaf duplication; Ed25519 signatures via `ed25519-dalek` (deterministic per RFC 8032); path validation rejects null bytes / leading slashes / `..` / `.` / Windows-reserved characters. `src/evidence/zip.rs` (~250 LOC) pure-Rust byte-deterministic ZIP encoder + reader: STORE-only (no DEFLATE → sidesteps zlib version drift), fixed mtime 1980-01-01 00:00:00 (DOS epoch floor), UTF-8 EFS bit (0x0800), canonical Unix 0644 external attributes, self-contained CRC-32/IEEE table built at compile time via `const fn`. **Adopters can verify the bundle with any ZIP extractor + any Ed25519 lib** (no axon-enterprise installation required). Per-tenant signing key rotation per D8: adopter supplies the SigningKey from HSM/vault, `signing_key_id` field in manifest names the key generation, old keys remain verifiable in perpetuity. 32 evidence tests: byte-determinism across runs + across input orderings + manifest top-level keys lexicographic order + SHA-256 of full ZIP stable for fixed inputs; round-trip (empty + single large 64 KB + 50 files + Unicode paths/content); tamper detection (file content / manifest field / signature byte / ZIP truncation / empty input); path validation (null/slash/backref/dot-segment/Windows-reserved); cross-key separation; ZIP framing magic 0x04034b50 + EOCD 0x06054b50; Ed25519 RFC-8032 determinism; Merkle invariants (matches recomputed / differs on content / differs on path). Cargo dep: `ed25519-dalek = "2"` (audited, dual MIT/Apache-2). |
| 27.g PHI scrubber kernel in C23 (was Tier-2 candidate; ratified for sesión 1 ship per founder bloque approval) | ✅ SHIPPED 2026-05-09 commit `837a578` | ~700 target / ~1485 actual (incl. tests) | C + Rust shim | `c-src/shield/phi_scrub.{c,h}` (~600 LOC C) single-pass byte walker with multi-pattern dispatch (9 HIPAA Safe Harbor categories: SSN / phone / email / IPv4 / credit card / ZIP / MRN / date / URL); per-pattern scalar matchers with explicit word-boundary discipline; greedy longest-match per starting position with priority order (Email > URL, MRN > generic digit patterns); replacement strings emitted in-place (`[REDACTED-SSN]` etc.); no-allocation hot path with caller-supplied output buffer + `axon_phi_scrub_max_output_size` for upfront sizing; per-pattern stats array. Forward-compat `prefer_simd` flag reserved for 27.g.2 SIMD upgrade (SSE2/NEON inner loop) without ABI break. `src/phi_scrub.rs` Rust safe API: `PhiPatterns` typed bitset with `BitOr` impl + `union`/`contains`/`bits` helpers; two entry points `scrub` (allocates `String`) and `scrub_into` (zero-alloc with caller-owned `Vec<u8>` reuse); `PhiScrubError` (4 variants) + `PhiScrubStats` with per-pattern counts. **Honest scope**: names + free-form addresses defer to sesión 2 (require NLP/NER tooling; scalar regex/string-search insufficient). Measured throughput on contemporary x86_64: ~250 MB/s scalar baseline (≈ 2-3× Python regex); 27.g.2 SIMD upgrade targets 1+ GB/s. 47 phi_scrub tests: per-pattern positive recognition (17 covering SSN-hyphenated/9-digit + phone paren/dash/dot/country-code + email plus-tag/subdomain + IPv4 + CC plain/dashed + ZIP/ZIP+4 + MRN/PT/PATIENT + ISO/US dates + http/https URLs); per-pattern negative cases (8-digit runs, plain text, partial email, out-of-range IPv4, 12-digit non-CC); pattern composition (multiple PHI tokens + dense PHI block + mask filtering + bitor combination); word-boundary discipline (embedded-in-identifier rejected); UTF-8 preservation; output sizing; stats correctness; edge cases (empty, only-PHI, start/end); error handling (zero mask, buffer reuse zero-alloc, scrub_into clears existing); 1000-event throughput smoke; type helpers. |
| 27.h Cross-platform CI matrix extension | ⏳ pending | ~200 (YAML) | YAML | Extend `axon-enterprise/.github/workflows/ci.yml` with a new `axon-csys-enterprise` workflow mirroring axon-lang's `.github/workflows/axon_csys.yml` 14-lane matrix BUT adds two FIPS-validation lanes: (1) BoringSSL-FIPS link, drift-gate vs OSS pure-C; (2) OpenSSL-FIPS link, drift-gate vs OSS pure-C. Audit log mmap lane runs cross-platform (linux mmap + macOS mmap + Windows MapViewOfFile). |
| 27.i Drift gate cross-stack (axon-csys-enterprise ↔ axon-csys OSS ↔ NIST CAVS vectors) + benchmarks | ⏳ pending | ~600 | Rust | `axon-csys-enterprise/tests/drift_gate.rs` runs 100-iter fuzz parity per kernel against the OSS pure-C reference + against NIST CAVS official test vectors checked into the repo; criterion benchmarks measure FIPS-validated overhead vs pure-C (target: ≤2× overhead because FIPS libs are well-optimized); audit log throughput target ≥10k events/sec single-threaded |
| 27.j License-key enforcement runtime check | ⏳ pending | ~300 | Rust | Runtime tenant-id signed config from license server (Ed25519 verify); soft-fail with degraded posture warning when license missing/expired (per D13 — no hard gate that crashes the supervisor; the kernel keeps working but emits an audit-log entry that the adopter is running unlicensed); ~10 tests |
| **27.k.1 Python integration layer** (added per 2026-05-09 orchestration audit) | ⏳ pending | ~600 | Python (ctypes) + tests | `axon_enterprise/csys/{__init__,audit_log,evidence,tokens,phi_scrub}.py` ctypes wrappers around the C ABIs already exposed by axon-csys-enterprise; integration with the existing supervisor (`axon_enterprise/supervisor`) + ESK (`axon_enterprise/audit_engine`) + Shield (`axon_enterprise/shield`) — the Shield ensemble factories pick up vertical encoders + PHI scrubber automatically per D9 backward-compat; existing OSS `axon_lang.audit_engine.evidence_packager` co-exists with new enterprise evidence packager (Option A: coexistence, documented in SILICON_COGNITION_ENTERPRISE.md); ~30 Python tests; supersession decision logged. **Why separate from 27.k**: gives the Python wiring explicit scope + tests rather than bundling into release prep. |
| 27.k Coordinated cross-stack release axon-enterprise v1.10.0 | ⏳ pending | release | — | bump-my-version 1.9.0 → 1.10.0 (axon-enterprise pyproject + __init__) + commit + tag `enterprise/v1.10.0:refs/tags/v1.10.0` + push origin + cargo publish axon-csys-enterprise 0.1.0 to private/internal registry (NOT crates.io because BSL license incompatible with crates.io defaults — D2 ratification) + GitHub Release on enterprise repo + private docs site update with `SILICON_COGNITION_ENTERPRISE.md` |

**Classification**: 100% ENTERPRISE-only. No deliverables fold back into OSS axon-csys.

**Parallelisability**: 27.b is hard prerequisite. After it lands, 27.c (FIPS link) / 27.d (audit log mmap) / 27.e (vertical BPE) / 27.f (evidence packager) / 27.g (PHI scrubber) are all independent and can ship in parallel PRs.

---

# 1. Investigation Summary — enterprise-only kernels worth shipping

> **Methodology**: surveyed (a) the deferred Fase 25 §1.2 Tier 2 candidates that were classified as "moderate, not top" for OSS but are ENTERPRISE-grade differentiators; (b) HIPAA / SOC2 / CC-EAL4+ / GDPR / PCI DSS audit-posture gaps that adopters of axon-enterprise's Shield + Supervisor + Audit Engine surface in pre-sales conversations; (c) the OSS / ENTERPRISE / SPLIT charter discipline (axon-enterprise charter memory) that prevents accidentally re-exporting commercial work as OSS.

## 1.1 Top-tier candidates (ship in sesión 1)

### Tier 1A — FIPS-validated crypto link (BoringSSL or OpenSSL-FIPS) [27.c]

**Gap solved**: axon-csys 0.1.1 ships pure-C SHA-256 + HMAC-SHA256 that are *algorithmically compliant* with FIPS 180-4 + FIPS 198-1 but *not formally certified* by NIST CAVS labs. Enterprise adopters running federal workloads (US: FedRAMP, FISMA-Moderate, CMMC; EU: eIDAS QSCD; healthcare: HITRUST validation) require the literal NIST CAVS certificate number embedded in their compliance docs — the algorithm being correct is necessary but not sufficient.

**Why C uniquely wins**: BoringSSL + OpenSSL-FIPS are the only NIST-CAVS-validated crypto libs that ship a C ABI. They are themselves C; linking is the cleanest path. Pure-Rust crypto crates (`rustcrypto/sha2`, `rustcrypto/hmac`) are *not* FIPS-validated and the audit lab won't accept them.

**Scope**:
  - Cargo features `fips-boringssl` + `fips-openssl` (mutually exclusive). Default = no-fips passthrough that re-exports the OSS axon-csys API verbatim.
  - When `fips-boringssl` enabled: link BoringSSL-FIPS via `cc-rs` build script; `axon_csys_enterprise::crypto::sha256(data)` calls into `EVP_Digest(EVP_sha256(), ...)` instead of OSS `axon_csys_sha256`.
  - When `fips-openssl` enabled: same shape via `EVP_DigestInit_ex2(..., EVP_sha256_fips(), ...)`.
  - Wire format byte-identical (drift gate). `ContinuityWire::sign` / `::verify` produce the same MAC bytes regardless of feature flag — so existing tokens issued by a non-FIPS deployment verify on a FIPS deployment and vice versa.

**Risk**: BoringSSL + OpenSSL-FIPS build pipelines are non-trivial cross-platform (Bazel vs. Configure; macOS code-signing; Windows MSVC vs MinGW). Mitigation: use prebuilt static libs from the official BoringSSL / OpenSSL-FIPS releases for each (linux-x86_64, linux-aarch64, macos-aarch64, windows-x86_64); CI lane verifies link succeeds on each.

---

### Tier 1B — Audit log mmap append-only kernel [27.d]

**Gap solved**: `axon-rs/src/trace_store.rs` (1245 LOC) writes spans through tokio + serde + a synchronous buffered file path. Per-event latency is ~5 µs in the warm case, ~25 µs in the cold case (file allocation + dirent flush). Adopters running 10k events/sec see ~50ms/sec of CPU spent in trace_store alone. Plus the current trace store is *not tamper-evident* — an attacker with file-system access can mutate any event without detection.

**Why C uniquely wins (and enterprise-only why)**: mmap-backed append-only ring buffer cuts per-event latency to ~500 ns (~10× speedup). Tamper-evidence requires per-block HMAC chaining + per-tenant key seal that the OSS `evidence_packager.rs` doesn't address (and shouldn't — that's enterprise audit posture, not adopter-agnostic OSS).

**Scope**:
  - C23 mmap ring buffer with atomic head-pointer (CAS via `_Atomic uint64_t`); supports concurrent writers + lock-free; rotated segments archived to `<segment>.zip` with a Merkle root anchor.
  - FlatBuffers wire format (D4 — binary 10-20× smaller than JSON; mmap zero-copy reads via FlatBuffers' inline structs).
  - Per-tenant HMAC-SHA256 chain: each block carries `prev_hash || event_payload || tenant_seal_key` MAC; tampering breaks the chain.
  - Optional public-chain anchoring (D5 — opt-in feature `public-anchor`): periodic Merkle root commits to Bitcoin OP_RETURN OR Ethereum tx data via adopter-supplied wallet.

**Risk**: Windows mmap semantics differ from POSIX (`MapViewOfFile` vs. `mmap`); the file growth behaviour is also different (Windows requires explicit `SetEndOfFile`). Mitigation: per-OS code paths gated behind `#ifdef _WIN32`, drift gate verifies byte-identical wire format across OSes.

---

### Tier 1C — Tamper-evident evidence packager [27.f]

**Gap solved**: `axon-rs/src/esk/audit_engine/evidence_packager.rs` (~547 LOC) ships a deterministic ZIP encoder for SOC2 / ISO 27001 audit trails (Fase 25 §1.2 Tier 2B candidate, deferred). For HIPAA Right-of-Access requests + GDPR data portability + PCI DSS forensics, the bundle must be:
  1. Byte-deterministic across regenerations (same inputs → same hash).
  2. Tamper-evident (per-file SHA-256 manifest + Merkle root + signature).
  3. Independently verifiable without axon-enterprise being installed (open the ZIP, validate the manifest, check the sig with adopter's pubkey).

**Why C uniquely wins (and enterprise-only why)**: byte-determinism in C means full control over header timestamps (zero), file ordering (sorted), permission bits (canonical), CRC vs SHA-256 hash columns, no compression jitter. Rust `zip` crate has a non-deterministic field (file mtime in central directory). The OSS deterministic-ZIP path was Tier 2B because the compliance use-case is enterprise-grade.

**Scope**:
  - C23 ZIP encoder STORE-only (no DEFLATE); all timestamps = `1980-01-01 00:00:00`; file ordering = lexicographic; central directory in canonical layout.
  - Manifest: per-file SHA-256 + size + path; Merkle root over the manifest; Ed25519 detached sig over the Merkle root using per-tenant signing key (rotated quarterly).
  - Adopter verification tooling: separate CLI `axon-evidence-verify` that takes the ZIP + adopter pubkey + (optional) Merkle anchor reference; outputs PASS/FAIL with per-file diff on mismatch.

**Risk**: cross-platform ZIP determinism is a tarpit (tested heavily for SOC2 evidence in real-world incidents). Mitigation: drift gate runs on linux-x86_64 + linux-aarch64 + macos-aarch64 + windows-x86_64 producing the SAME bytes; any platform-specific drift = build-time failure.

---

### Tier 1D — Vertical-specific BPE tokenizer templates [27.e]

**Gap solved**: cl100k_base / o200k_base were trained on a generic English corpus dominated by Common Crawl. Vertical jargon (`myocardial infarction`, `attorney-client privilege`, `know-your-customer due diligence`) gets multi-token expansions in the generic encoder. For Shield judges processing long medical / legal / fintech context, this inflates token cost by 30-50%.

**Why C uniquely wins (and enterprise-only why)**: the kernel infrastructure is already-shipped (OSS axon-csys 0.1.1 25.g `#embed` BPE). The differentiator is the *vertical corpus + training discipline*. Open corpora (PubMed Central, SEC public filings, US public case law) train naturally; the tooling and the trained `.bin` files are enterprise-only because they encode commercial R&D investment.

**Scope**:
  - Three `merges_<vertical>_base.bin` files baked via OSS 25.g infra:
    - `medical_base.bin` — trained on PubMed Central full-text + MedlinePlus + RxNorm.
    - `legal_base.bin` — trained on US public case law (CourtListener) + SEC EDGAR filings + UK statutory instruments.
    - `fintech_base.bin` — trained on SEC EDGAR financial reports + FFIEC public guidance + ECB monetary stability reports.
  - Python training tool `tools/train_vertical_merges.py` (consumes `tiktoken-rs`-compatible pre-tokeniser regex + corpus text + output `.bin` in OSS 25.g format).
  - Rust shim auto-registers the vertical encoders alongside cl100k/o200k via `axon_csys_enterprise::tokens::register_vertical_encoders()`.
  - Existing `axon_enterprise.shield.ensemble_configs.healthcare_ensemble()` / `legal_ensemble()` / `fintech_ensemble()` factories pick up the vertical encoder automatically when the enterprise feature is enabled (per D9 backward-compat).

**Risk**: corpus licensing — must be open / public-domain only for v1.0 (D6 ratified). Customer-corpus training is a managed-service feature for sesión 2.

---

## 1.2 Tier-2 candidate (defer-or-cut decision at 27.a ratification)

### Tier 2A — PHI scrubber kernel in C23 [27.g]

`axon_enterprise.shield.healthcare.hipaa_patterns` runs Python regex over patient text. SIMD-accelerated C port (Boyer-Moore-Horspool + AVX2 multi-pattern) would give ~5-8× throughput at streaming scale. **Defer-or-cut decision**: ship sesión 1 if calendar permits; else defer to sesión 2.

---

## 1.3 Out of scope for sesión 1 (sesión 2+ candidates)

### OOS-1. TEE attestation primitives (Intel SGX / AMD SEV / AWS Nitro)
TEE is its own tier of complexity (per-platform, requires kernel-level integration). Defer to sesión 2 — `Silicon + Cognition Enterprise sesión 2` will be the natural home.

### OOS-2. Quantum-resistant signature schemes (Dilithium, Falcon)
NIST is finalising standardisation through 2026. Defer to sesión 2 once the canonical Rust + C bindings stabilise.

### OOS-3. Streaming differential privacy noise sampler
Useful for multi-tenant analytics. Defer — not a current adopter ask.

### OOS-4. Customer-corpus BPE training (managed service)
v1.0 ships open-corpus only. Customer-corpus is sesión 2 + commercial offering layer.

---

# 2. TL;DR (resume in 30 seconds)

- **What**: ENTERPRISE-only companion to OSS Fase 25 (Silicon + Cognition sesión 1). Four kernels port to C23 / link to C: FIPS-validated SHA-256/HMAC link (BoringSSL or OpenSSL-FIPS), audit log mmap append-only with tamper-evident chaining, byte-deterministic evidence packager, vertical BPE tokenizer templates (medical/legal/fintech). Plus optional PHI scrubber SIMD kernel.
- **Why**: enterprise adopters with HIPAA / SOC2 / CC-EAL4+ / GDPR / PCI DSS obligations need formal NIST CAVS certified crypto + tamper-evident audit + byte-deterministic forensic exports + vertical-tuned token efficiency. The OSS axon-csys 0.1.1 is FIPS-friendly but not FIPS-validated; the wins above are concretely reachable enterprise differentiators.
- **OSS / ENTERPRISE / SPLIT**: 100% ENTERPRISE-only. The kernel infrastructure in OSS axon-csys 0.1.1 (`#embed` BPE, hash-table, FNV-1a, base64url, mmap helper, etc) is reused; the enterprise crate adds vertical-specific data + commercial-license posture + FIPS-validated linkage.
- **Robustness target**: byte-identical drift gate between OSS pure-C path and FIPS-validated path on every NIST CAVS vector + 100 fuzz iterations; audit log mmap throughput ≥10k events/sec single-threaded; vertical BPE produces byte-identical encodes to a Python `tiktoken` reference trained from the same corpus; evidence packager produces byte-identical ZIP across linux/macOS/Windows.
- **Target version**: axon-enterprise v1.10.0 + axon-csys-enterprise 0.1.0 (private/internal registry due to D2 BSL licensing).

---

# 3. Architecture — operational design

## 3.1 Crate layout

```
axon-enterprise/
├── axon-csys-enterprise/             # NEW — enterprise companion to OSS axon-csys
│   ├── Cargo.toml                    # rustc package; cargo features fips-boringssl / fips-openssl
│   ├── LICENSE.bsl                   # Business Source License (4-year delay → MIT)
│   ├── build.rs                      # cc::Build + (optional) BoringSSL/OpenSSL-FIPS link
│   ├── c-src/
│   │   ├── audit/log.c               # mmap append-only audit log (27.d)
│   │   ├── audit/log.h
│   │   ├── audit/evidence.c          # byte-deterministic ZIP encoder (27.f)
│   │   ├── audit/evidence.h
│   │   ├── shield/phi_scrub.c        # (optional) SIMD PHI scrubber (27.g)
│   │   ├── shield/phi_scrub.h
│   │   ├── tokens/merges_medical_base.bin   # 27.e baked merges
│   │   ├── tokens/merges_legal_base.bin
│   │   └── tokens/merges_fintech_base.bin
│   ├── src/                          # Rust shim layer
│   │   ├── lib.rs                    # extern blocks + safe Rust + feature gates
│   │   ├── crypto.rs                 # 27.c — FIPS-validated re-exports
│   │   ├── audit_log.rs              # 27.d — AuditLogWriter/Reader/Verifier
│   │   ├── evidence.rs               # 27.f — EvidencePackager
│   │   ├── tokens.rs                 # 27.e — vertical encoder registration
│   │   ├── phi_scrub.rs              # 27.g (optional)
│   │   └── license.rs                # 27.j — runtime license-key enforcement
│   └── tests/
│       ├── drift_gate.rs             # 27.i — fuzz parity vs OSS axon-csys + NIST CAVS
│       └── cavs/                     # NIST-published Cryptographic Algorithm Validation Suite vectors
├── axon_enterprise/
│   ├── csys/                         # NEW — Python surface for the C kernels
│   │   ├── __init__.py
│   │   ├── audit_log.py              # ctypes wrapper + supervisor integration
│   │   ├── evidence.py               # supersedes existing `audit_engine/evidence_packager.py`
│   │   └── tokens.py                 # vertical encoder registration with Shield ensembles
│   └── (existing modules)
├── docs/
│   ├── fase_27_silicon_cognition_enterprise.md  # this doc
│   └── SILICON_COGNITION_ENTERPRISE.md          # adopter-facing reference
└── tools/
    └── train_vertical_merges.py      # 27.e — corpus → merges_<vertical>_base.bin generator
```

`axon-enterprise/Cargo.toml` (workspace-level once Rust crates start landing in this repo) gains a workspace member entry; in the meantime `axon-csys-enterprise` is its own root-level crate consumed via path dep + version pin.

## 3.2 Build system

`axon-csys-enterprise/build.rs` (Rust-side build orchestration):

```rust
fn main() {
    let mut build = cc::Build::new();
    build.files(&[
        "c-src/audit/log.c",
        "c-src/audit/evidence.c",
        // Optional: "c-src/shield/phi_scrub.c" gated by feature `phi-scrubber-c`
    ]);
    build.include("c-src");
    // Same C23 flag chain as OSS axon-csys (D2 ratified Fase 25).
    if cfg!(target_env = "msvc") {
        build.flag_if_supported("/std:clatest");
        build.flag_if_supported("/experimental:c11atomics");
    } else {
        build.flag_if_supported("-std=c23");
        build.flag_if_supported("-std=c2x");
    }
    // (strict warnings — same as OSS)
    build.compile("axon_csys_enterprise");

    // ─── FIPS-validated crypto link (D3 ratified) ────────────────────
    if cfg!(feature = "fips-boringssl") {
        link_boringssl_fips();
    } else if cfg!(feature = "fips-openssl") {
        link_openssl_fips();
    }
    // else: pure-C passthrough via OSS axon-csys re-export.
}

fn link_boringssl_fips() {
    let prebuilt = env!("AXON_BORINGSSL_FIPS_PREBUILT");
    println!("cargo:rustc-link-search=native={prebuilt}/lib");
    println!("cargo:rustc-link-lib=static=crypto");
    // Specific FIPS module versioning + integrity check (per BoringSSL's
    // FIPS module documentation — the integrity self-test runs at first
    // EVP_DigestInit_ex2 invocation; failure aborts the process).
}

fn link_openssl_fips() {
    let prebuilt = env!("AXON_OPENSSL_FIPS_PREBUILT");
    println!("cargo:rustc-link-search=native={prebuilt}/lib");
    println!("cargo:rustc-link-lib=static=crypto");
    println!("cargo:rustc-link-lib=static=ssl");
    // OpenSSL-FIPS requires an explicit `fips_provider.cnf` config file
    // emitted at adopter deployment time; the kernel checks for it at
    // load and refuses to start in fips mode without the config.
}
```

Cross-platform compiler dispatch + diagnostic flags inherit from OSS Fase 25.b verbatim.

## 3.3 FFI surface conventions

Same as OSS Fase 25 §3.3:
1. C kernel exposes opaque `*mut <Type>` handles.
2. Rust shim implements `Drop` calling C `release` symbol.
3. Safe Rust API on top — adopters never see `unsafe`.
4. Compile-time guards prevent accidental double-free.

Additional enterprise-side conventions:
5. License-key gate on every public entry point (cheap atomic check; fails open with a degraded-posture warning, not a hard panic — per D13).
6. Audit log emit on every cryptographic operation when the audit log is configured (allows post-hoc forensic replay).

## 3.4 C23 features deliberately exploited

Inherits from OSS Fase 25 §3.4:
- `[[nodiscard]]` on every fallible C function
- `_BitInt(N)` for packed bitfield representations
- `#embed` for vertical BPE merges tables
- `_Atomic` counters for audit log
- `alignas(64)` for cache-line alignment

Plus enterprise-specific:
- C23 `[[deprecated]]` markers on legacy paths kept for adopter back-compat
- C23 `typeof_unqual` for generic-style cleanup macros in the audit log buffer pool

---

# 4. Sub-fases & schedule

| Sub-phase | Description | Stack | Depends on | Deliverable |
|---|---|---|---|---|
| 27.a | Engineering spec ratification (this doc + memory) | — | Fase 25 OSS SHIPPED + axon-enterprise v1.9.0 SHIPPED | spec ratified, D1–D14 closed |
| 27.b | axon-csys-enterprise crate scaffold + cc-rs build infra + license posture (BSL/proprietary per D2) | Rust + C + build.rs | 27.a | crate scaffold + 1 hello-world C kernel + ~10 build tests + LICENSE.bsl committed |
| 27.c | FIPS-validated crypto link (BoringSSL OR OpenSSL-FIPS, per cargo feature) | Rust + extern C | 27.b | `axon-csys-enterprise/src/crypto.rs` + drift gate vs OSS pure-C + NIST CAVS vectors + ~30 tests |
| 27.d | Audit log mmap append-only kernel | C + Rust shim | 27.b | `c-src/audit/log.{c,h}` + Rust shim + Python wrapper integrated into supervisor + ~40 tests |
| 27.e | Vertical BPE tokenizer templates | Python + C + Rust | 27.b | 3 `.bin` merges + Python training tool + Rust shim + Shield ensemble auto-detection + ~25 tests |
| 27.f | Tamper-evident evidence packager | C + Rust shim + Python wrapper | 27.b | `c-src/audit/evidence.{c,h}` + Rust shim + Python wrapper supersedes existing implementation + adopter verification CLI + ~30 tests |
| 27.g | (optional) PHI scrubber SIMD kernel | C + Rust shim | 27.b | `c-src/shield/phi_scrub.{c,h}` + Rust shim + Shield ensemble integration + ~20 tests |
| 27.h | Cross-platform CI matrix extension | YAML | 27.b–g all green | new `axon-csys-enterprise.yml` workflow with 14 + 2 lanes (FIPS-BoringSSL + FIPS-OpenSSL) |
| 27.i | Drift gate cross-stack + benchmarks | Rust + Python | 27.c–g ports done | `axon-csys-enterprise/tests/drift_gate.rs` byte-identical assertions + criterion benchmarks |
| 27.j | License-key enforcement runtime check | Rust | 27.b | `src/license.rs` Ed25519 verify + soft-fail posture + ~10 tests |
| 27.k | Coordinated release axon-enterprise v1.10.0 | release | 27.i + 27.j | bump 1.9.0 → 1.10.0 + tag + push + private registry publish + GitHub Release |

**Classification**: 100% ENTERPRISE-only.

**Cadence calendar suggested** (5–7 días focused):

```
Día 1: 27.a + 27.b (spec + build infra)
Día 2: 27.c FIPS link (BoringSSL OR OpenSSL — both with prebuilt static libs)
Día 3: 27.d audit log mmap (cross-platform mmap is the scary part)
Día 4: 27.f evidence packager (byte-determinism is a tarpit; budget extra)
Día 5: 27.e vertical BPE templates + 27.g (optional) PHI scrubber
Día 6: 27.h CI matrix + 27.i drift gate + benchmarks + 27.j license check
Día 7: 27.k release v1.10.0
```

---

# 5. Decisions (D1–D14) — pending founder ratification

**D1 — `axon-csys-enterprise` as separate crate, NOT feature flags inside OSS axon-csys**

Pros: clean OSS / ENTERPRISE boundary; commercial license stays out of OSS repo; adopters who don't license enterprise never see the feature flag at all (no "free rider" surface area). Cons: one more crate to maintain. **Recommendation**: separate crate. Per axon-enterprise charter — keep the OSS surface 100% adopter-agnostic.

**D2 — License posture for `axon-csys-enterprise`**

Options:
- **AGPL-3.0** (copyleft) — forces enterprise-side modifications by SaaS forks to publish source; protects against AWS-style closed-source forks.
- **Proprietary commercial** — full control; requires adopter license agreement.
- **Dual MIT + AGPL** — open-source friendly version is OSS, premium features need commercial license.
- **Business Source License (BSL) with 4-year delay → MIT** — source available; commercial use restricted for 4 years; auto-converts to MIT after delay. Used by HashiCorp / Sentry / MariaDB.

**Recommendation**: BSL with 4-year delay → MIT. Standard SaaS enterprise pattern. Source available (auditors can read it for compliance), commercial-use restrictions enforce licensing during the active lifecycle, OSS handover after delay protects against vendor lock-in fears.

**D3 — BoringSSL vs OpenSSL-FIPS as the formally validated crypto backend**

- **BoringSSL** (Apache-2): clean license, but Google does not certify each release per-NIST-CAVS (FIPS 140-3 module integrity self-test runs but no formal cert per release).
- **OpenSSL-FIPS**: per-release NIST CAVS certificate (currently CMVP cert #4282 for OpenSSL 3.0 FIPS Provider).

**Recommendation**: BOTH via cargo features (`fips-boringssl` AND `fips-openssl` — mutually exclusive). Adopters with strict CMVP-certified-per-release requirements pick OpenSSL-FIPS. Adopters with lighter posture (BoringSSL self-test sufficient) pick BoringSSL. Default = pure-C OSS passthrough (for non-licensed deployments).

**D4 — Audit log byte format: text JSON (simdjson) vs binary (FlatBuffers)**

JSON: human-readable, debugging-friendly, larger.
FlatBuffers: 10-20× smaller, mmap zero-copy reads, schema-evolution friendly, requires schema-aware verifier.

**Recommendation**: FlatBuffers. The audit log is verified by tooling, not by humans reading it; mmap zero-copy is the speed unlock; FlatBuffers schema evolution maps directly onto our Fase-versioning discipline.

**D5 — Tamper-evident anchoring: in-tenant Merkle only vs public chain**

In-tenant Merkle: per-tenant signing key seals a Merkle root over the audit-log block; verifier needs the tenant's public key (already in adopter's vault).
Public chain: Merkle root committed to a public blockchain (Bitcoin OP_RETURN OR Ethereum tx data) for "proof of existence at time T" defensible against full-stack compromise.

**Recommendation**: in-tenant Merkle by default; public-chain anchor as opt-in feature `public-anchor` for ultra-high-evidentiary-standard adopters (federal contracts, financial-fraud forensics). Public chain integration deferred OOS-3 if calendar tight.

**D6 — Vertical BPE corpus sourcing**

- Open / public-domain only: PubMed Central full-text (medical) + SEC EDGAR public filings + US public case law (CourtListener) + UK statutory instruments.
- Customer-corpus: high-value but legally complex (data privacy, third-party rights, training-data IP).

**Recommendation**: Open corpus only for v1.0. Customer-corpus training is a separate managed-service offering for sesión 2 / commercial layer.

**D7 — Drift gate posture for FIPS-validated link**

**Recommendation**: byte-identical output between pure-C path and FIPS-validated path on every NIST CAVS test vector + 100 fuzz iterations per primitive. Any single byte difference = build-time failure. Wire format byte-identical so flow output is interchangeable across deployments with mixed feature flags.

**D8 — Per-tenant key rotation for audit log seal**

**Recommendation**: rotation triggers:
- Tenant config change (admin explicit)
- Monthly automated (1st of each month, UTC midnight, controlled jitter to avoid thundering herd across tenants)
- After N events (N = 10M default; tunable per tenant)

Old keys remain verifiable in perpetuity (tenant's vault retains historical pubkeys) but don't seal new entries.

**D9 — Backward-compat with existing Shield ensemble factories**

`axon_enterprise.shield.ensemble_configs.healthcare_ensemble()` / `legal_ensemble()` / `fintech_ensemble()` should auto-detect the vertical encoder and use it transparently (no API churn for existing adopters).

**Recommendation**: yes — vertical encoders register under aliases (`medical_base` / `legal_base` / `fintech_base`) that the ensemble factories pick up via existing tokenizer dispatch. If `axon-csys-enterprise` is not loaded, ensembles fall back to OSS cl100k_base / o200k_base (graceful degrade).

**D10 — Test data for FIPS validation lane**

**Recommendation**: NIST CAVS official test vectors checked into `axon-csys-enterprise/tests/cavs/`. Vector files are public-domain (NIST publishes them); no licensing concern.

**D11 — Public chain integration for anchoring**

**Recommendation**: deferred to sesión 2. Cryptocurrency wallet management (key custody, gas-fee management, mempool monitoring) is a separate product surface that requires its own security review + Operations playbook. The audit log mmap kernel will emit "anchor commitment requested" events that future tooling can consume.

**D12 — Streaming audit log retention**

**Recommendation**: time-based + size-based retention:
- Time: rotated segments older than `retention_days` (default 365) get GC'd. ZIP archive of rotated logs may be moved to cold storage (S3 IA / Glacier).
- Size: when active mmap segment exceeds `segment_size_bytes` (default 1 GB), new segment opens; old one archived.

Configurable per tenant via Shield config.

**D13 — License key enforcement (avoid "free riders")**

**Recommendation**: runtime check at first use of any enterprise kernel; tenant-id signed config from license server (Ed25519 verify); soft-fail with degraded posture warning. NO hard gate that crashes the supervisor — the kernel keeps working but emits an audit-log entry stating "running unlicensed" so the adopter is aware + can renew. Hard gate would make the kernel a security risk (an adversary could DoS the supervisor by tampering with the license file).

**D14 — Documentation: enterprise-only docs site separate from axon-lang docs?**

**Recommendation**: extend `docs/INTEGRATION_GUIDE.md` (already adopter-facing) with a new top-level section pointing at the new `docs/SILICON_COGNITION_ENTERPRISE.md`. Separate private docs site for licensed adopters comes in sesión 2 (when the surface is large enough to justify a standalone site). For sesión 1, single Markdown doc + linked from the integration guide.

---

# 6. Tests target — ≥175 nuevos

| Suite | Path | Tests | Coverage |
|---|---|---|---|
| Build infra | `axon-csys-enterprise/tests/probe.rs` | ~10 | Crate compiles cross-platform; FIPS feature flags compile + link; license file present + valid |
| FIPS crypto link | `axon-csys-enterprise/tests/crypto.rs` | ~30 | NIST CAVS test vectors (SHA-256 short + long; HMAC-SHA256 short + long), drift gate vs OSS pure-C, feature-flag exclusion, FIPS module integrity self-test passes |
| Audit log mmap | `axon-csys-enterprise/tests/audit_log.rs` | ~40 | Append-only invariants, Merkle chain verification, tamper detection (mutate byte → verifier fails), per-tenant key rotation, segment rotation, cross-platform mmap (linux + macos + windows), concurrent writers (8 threads × 1000 events), retention enforcement |
| Evidence packager | `axon-csys-enterprise/tests/evidence.rs` | ~30 | Byte-deterministic ZIP regen across runs, byte-identical across linux/macos/windows, manifest SHA-256 correctness, Merkle root + Ed25519 sig verifies, adopter `axon-evidence-verify` CLI smoke |
| Vertical BPE | `axon-csys-enterprise/tests/tokens.rs` | ~25 | 3 vertical encoders register, byte-identical encode vs reference Python tokeniser trained from same corpus, ensemble auto-detection picks them up, fall-back to OSS cl100k when enterprise not loaded |
| (optional) PHI scrubber | `axon-csys-enterprise/tests/phi_scrub.rs` | ~20 | Pattern coverage parity with Python regex impl, SIMD activation on AVX2 / NEON, scalar fallback, 1000-event throughput target |
| License enforcement | `axon-csys-enterprise/tests/license.rs` | ~10 | Valid signed config accepted, expired config soft-fails with audit log entry, missing config soft-fails, malformed config rejected |
| Cross-stack drift gate | `axon-csys-enterprise/tests/drift_gate.rs` | ~20 | 100-iter fuzz parity per primitive: pure-C ↔ FIPS-validated path, NIST CAVS vectors |
| Cross-stack benchmarks | `axon-csys-enterprise/benches/*.rs` | ~10 (benches) | FIPS overhead ≤2× pure-C, audit log ≥10k events/sec single-threaded, evidence packager ZIP byte-deterministic across regens, vertical BPE token-cost reduction ≥20% on vertical text |

**Total**: ~175 nuevos + 10 benchmarks. Cross-platform CI matrix multiplies coverage.

---

# 7. Out of scope (sesión 2+)

- TEE attestation primitives (Intel SGX / AMD SEV / AWS Nitro) → sesión 2
- Quantum-resistant signature schemes (Dilithium, Falcon) → sesión 2
- Streaming differential privacy noise sampler → sesión 2 if demand
- Customer-corpus BPE training (managed-service offering) → sesión 2 commercial layer
- Public-chain anchoring full integration (wallet + gas + mempool monitoring) → sesión 2 D11 deferred
- GPU acceleration of any enterprise kernel → Fase 26 OSS first, then enterprise companion in a future fase

---

# 8. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| BoringSSL / OpenSSL-FIPS prebuilt static libs not available for some platform (linux-aarch64 musl) | Medium | Per-platform feature gap | CI matrix gates on linux-x86_64 + linux-aarch64 + macos-aarch64 + windows-x86_64; documented "best-effort" tier for less-common platforms |
| FIPS module integrity self-test failures at adopter runtime (transient OS-level issue) | Low | Adopter deployment fails | Self-test runs at first crypto call; failure logged + soft-fail to OSS pure-C path with audit log entry; adopter can re-deploy without losing data |
| Cross-platform ZIP determinism subtle differences (file mtime, entry order, zip64 thresholds) | High (tested in real-world incidents) | Evidence package fails verification on different platform | Drift gate runs on linux-x86_64 + linux-aarch64 + macos-aarch64 + windows-x86_64 producing the SAME bytes; any platform-specific drift = build-time failure |
| Vertical BPE merges drift relative to source corpus (corpus updated without re-training) | Medium | Vertical token cost regression | Tooling watermarks the .bin file with corpus fingerprint; CI lane rebuilds + drift-checks the merges against the watermarked corpus snapshot |
| BSL license restrictions confuse adopters' compliance teams | Medium | Procurement friction | Clear LICENSE.bsl FAQ + adopter-facing decision tree in INTEGRATION_GUIDE; "trial" license with auto-conversion to commercial after trial period |
| License-key enforcement bypassed by adversary | Low | Free-rider on enterprise kernel | Per D13 — soft-fail, not hard gate; primary protection is contractual not technical |
| Audit log mmap concurrency bug (atomic head-pointer race) | Medium | Audit log corruption | TSan + valgrind in CI per OSS Fase 25.i pattern; concurrent-writer test with 8 threads × 10k events; per-block HMAC chain catches corruption at verify time |
| Public-chain anchoring deferred but adopter pre-sales asks for it | Medium | Pre-sales velocity | Document explicitly in INTEGRATION_GUIDE: "public anchor available as a sesión 2 commercial offering"; emit anchor-commitment events even in sesión 1 so adopters can wire their own anchoring tooling |

---

# 9. Cómo fue motivada

El usuario invocó el charter durante el commit-out de Fase 25 OSS (2026-05-09): "Pregunta, estos cambios son profundos, por tanto me deja la pregunta de, qué pasa con axon enterprise que es el sabor de pago, donde habrán features, primitivas, etc que serán explosivas de ese sabor."

La respuesta directa: Fase 25 OSS shipped el infrastructure layer + 4 enterprise-only kernels naturales se identificaron como Tier-2 en el plan vivo de Fase 25 §1.2 pero clasificados "moderate, not top" para OSS — específicamente porque su valor es en *audit posture* (HIPAA / SOC2 / CC-EAL4+ / GDPR / PCI DSS) que es enterprise-grade, no adopter-agnóstico OSS.

Per memoria `project_axon_enterprise_charter.md`: "axon-enterprise NO es solo wrapper multitenant; es capa privilegiada con R&D vertical (Salud/HealthTech/Legal/Fintech) + behaviors enterprise-only; cada fase clasifica sub-fases OSS / ENTERPRISE / SPLIT". Fase 27 materialise ese charter operacionalmente — la primera sesión "Silicon + Cognition Enterprise" lleva el silicio enterprise a paridad con el OSS.

Fase 27 también es el follow-up natural de la lección 25.k (production-grade CI matrix introducido en 25.i debió haber corrido ANTES del v1.19.0 ship). Aplicar la misma disciplina aquí: 27.h CI matrix runs ANTES del 27.k release.

---

# 10. Next operational step

Ratificación del founder sobre las decisiones D1–D14 (especialmente D1 separate crate, D2 license posture BSL vs alternatives, D3 BoringSSL vs OpenSSL-FIPS vs both, D5 in-tenant vs public-chain anchoring, D6 corpus sourcing, D11 public-chain deferral, D13 soft-fail license posture, D14 docs surface).

Cuando estén ratificadas → arrancar 27.b (crate scaffold). Estimado calendario total: 5–7 días focused desde 27.b hasta v1.10.0 publicado.

Foundational policy reminder: post-Fase-27, every NEW enterprise-grade kernel goes to `axon-csys-enterprise`. The boundary between OSS axon-csys and enterprise axon-csys-enterprise is now clearly drawn — OSS = adopter-agnostic + MIT; enterprise = audit-posture + BSL → MIT. Follow-up sesiones extend the enterprise surface progressively (TEE, quantum-resistant crypto, customer-corpus BPE).

Fuera de scope (sesión 2+)
TEE attestation (SGX/SEV/Nitro), quantum-resistant crypto (Dilithium/Falcon), streaming differential privacy, customer-corpus BPE training, public-chain integration, GPU acceleration de enterprise kernels.

Próximo paso operacional: ratificación D1–D14. Las recomendaciones están en el plan doc por si algún D-letter quieres redirigir antes de arrancar 27.b. Cuando ratifiques, arranco con el crate scaffold.
