"""
Axon Enterprise — Commercial Edition with RBAC, SSO, Audit, and Metering.

This package contains enterprise-only features:
- RBAC (Role-Based Access Control)
- SSO/SAML integration
- Advanced audit logging & compliance
- Usage metering & billing
- Studio visual debugger
- Advanced observability
- Vertical Shield R&D — HIPAA / legal / fintech scanners + judge
  prompts + ensemble factories (Fase 20, v1.7.0).
- Adopter integration surface — OIDC + OAuth + capability + tenant
  introspection + OpenAPI 3.1 + health/version + drift gate +
  observability + integration guide + contract gate (Fase 21, v1.8.0).
- Stack catch-up to axon-lang 1.19.1 (Fase 25 Silicon + Cognition
  sesión 1) — inherits transitively the new C23 metal-bound kernels:
  BPE 1.26-1.43× faster than tiktoken-rs, buffer pool 207× faster
  on 1 MiB allocs, FIPS-friendly SHA-256/HMAC in pure-C auditable,
  SIMD G.711 transcoders, algebraic-effects FSM with computed
  gotos (v1.9.0).
- **Silicon + Cognition Enterprise sesión 1 (Fase 27, v1.10.0)** —
  ships the new `axon-csys-enterprise` Rust crate (BSL-licensed,
  in-tree under axon-csys-enterprise/) with five C23 enterprise-only
  metal-bound kernels:
    * FIPS-validated crypto link (BoringSSL or OpenSSL-FIPS routed
      via fips_glue.c; cargo features fips-boringssl + fips-openssl
      mutually exclusive; wire output byte-identical to OSS pure-C
      so existing ContinuityTokens cross-verify; D7 ratified).
    * Audit log mmap append-only kernel — cross-platform mmap
      (POSIX + Windows MapViewOfFile), per-tenant HMAC-SHA256 chain
      + segment rotation + 8-thread concurrent writers; ~290k
      events/sec single-threaded measured at 256B payload (plan §6
      ≥10k target met by 29×).
    * Vertical BPE tokenizer templates — medical / legal / fintech
      v1 seed encoders (~2000 tokens each) trained on curated
      public-domain corpora; full-corpus retrain via shipped Python
      tool `tools/train_vertical_merges.py`.
    * Tamper-evident byte-deterministic evidence packager —
      pure-Rust ZIP encoder (STORE-only, fixed mtime, canonical
      headers) + canonical-JSON manifest + Merkle root + Ed25519
      signature; adopters verify with any ZIP extractor + any
      Ed25519 lib (no axon-enterprise required).
    * PHI scrubber kernel — multi-pattern HIPAA Safe Harbor
      §164.514(b)(2) text-detectable subset (SSN/phone/email/IPv4/
      credit card/ZIP/MRN/date/URL); ~250 MB/s scalar baseline.
  Plus Ed25519-signed license enforcement runtime check with D13
  soft-fail discipline (license missing/expired/tampered → degraded
  posture warning + audit-log entry, NEVER hard gate).
  231 Rust tests across 8 modules + CI matrix 14/15 hard-green +
  cross-kernel drift gate consolidation + 5 criterion benchmarks.
  Python integration of these kernels via ctypes wrappers shipped
  as v1.12.0 (27.k.1 followup, renumbered from v1.11.0 because the
  Fase 28 catch-up landed in between); v1.10.0 shipped the Rust
  foundation + the Python package version bump signaling the
  crate is part of the platform.
- **Stack catch-up to axon-lang 1.20.0 (Fase 28 Adopter Diagnostic
  Robustness, v1.11.0)** — inherits transitively every Fase 28
  surface that ships in axon-lang 1.20.0:
    * Parser error recovery — `parse_with_recovery() → ParseResult`
      collects ALL errors per file with panic-mode + sync-points
      instead of failing on the first; existing `parse()` API
      preserved verbatim per D9 backwards compat.
    * Rustc-style source-context diagnostic blocks — every
      AxonParseError carries an optional SourceSnippet rendered
      with line numbers + caret + 2 lines before/after (D4 ratified);
      codepoint-aware caret clamp; splitlines trailing-newline
      parity with the Rust frontend.
    * Smart-suggest "Did you mean X?" Levenshtein hints — ≤ 2
      distance, max 3 candidates (D3 ratified), always on (D11);
      wired into top-level + flow-body unknown-keyword sites
      (e.g. `flwo` → `Did you mean \`flow\`?`).
    * `axon parse <pattern>` multi-file aggregator CLI — recursive
      directory walks, glob expansion, cascading `.axonignore`,
      concurrent thread-pool parse, `--max-errors N` cap with D6
      truncation discipline, exit codes 0/1/2/3 (bitwise OR of
      parse + I/O classes).
    * Structured JSON output — `--json --format={array,ndjson}`
      with rustc-compatible field shape (D5 ratified) +
      `to_lsp_diagnostic` helper for adopter LSP wrappers.
    * `--strict` opt-in — CLI flag + `AXON_PARSER_STRICT` env var
      (D8 ratified, OR semantics) for CI loops that want legacy
      fail-on-first behavior.
    * Cross-stack drift gate — Python ↔ Rust frontends produce
      byte-identical error counts on a shared corpus, locked in
      axon-lang CI on every PR (D7 ratified).
  Enterprise tenants on regulated verticals (HIPAA / legal /
  fintech) immediately benefit on `axon check` + `axon parse`
  flows: every shield/judge/ensemble compile pass surfaces the
  full diagnostic landscape in one pass instead of one-error-per-
  deploy. axon-frontend Rust crate dependency bumps transitively
  from 0.7.0 → 0.8.0 (in axon-lang 1.20.0).

  v1.11.0 is a lean catch-up — same shape as v1.9.0 (which
  consumed axon-lang 1.19.1 ahead of v1.10.0's substantive
  Fase 27 work). The substantive Fase 27.k.1 Python ctypes
  integration that was originally earmarked for v1.11.0 ships
  as v1.12.0 (no scope or content change — just renumbered to
  let this catch-up land first).

  Fase 29 "Enterprise Diagnostic Enhancements" is the announced
  enterprise-only follow-on layered on top of this OSS surface
  (default-strict in regulated verticals via vertical-aware
  policy + ship diagnostics to enterprise telemetry sink +
  vertical-aware suggest dictionaries).
"""

__version__ = "1.11.0"
