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
  in a future release (no scope or content change — just
  re-sequenced after this Fase 30+31 catch-up lands).

- **Stack catch-up to axon-lang 1.22.0 (Fase 30 HTTP Transport +
  Fase 31 Type-Driven Wire Inference, v1.12.0)** — inherits
  transitively the v1.21.0 + v1.21.1 + v1.22.0 surface cascade:

    * **Fase 30 (axon-lang v1.21.0)** — HTTP Transport for
      Algebraic Stream Effects. The Stream<T> algebraic effect
      from Fase 11.a now has a first-class HTTP wire format. New
      axonendpoint fields `transport: {json,sse,ndjson}` + `keepalive:
      {5s,15s,30s,60s}` declare the wire shape and the SSE comment
      interval. New routes `POST /v1/execute/sse` (single-shot) +
      content-negotiated promotion on legacy `POST /v1/execute`
      (D4 fallback). Type-checker enforces `transport: sse|ndjson`
      requires a stream-producing flow (D3 soundness). 9 sub-fases,
      D1–D8 ratificadas.

    * **Fase 30.f patches (axon-lang v1.21.1)** — multi-arch
      binary fixes in `rust_release.yml`: pre-C23 GCC compat in
      axon-csys (7 `__has_c_attribute` refactors using nested
      `#ifdef` instead of `defined(...) && ...(arg)` to defeat
      pre-C23 GCC eager short-circuit), x86_64-musl linker via
      explicit `CC_*_LINKER` env vars, wasm32 pivot from axon-rs
      (impossible target — tokio full) to axon-frontend cdylib.
      First green `rust_release.yml` end-to-end since v1.18.0.

    * **Fase 31 (axon-lang v1.22.0)** — Type-Driven Wire Inference.
      The Kivi enterprise adopter case 2026-05-11 (7 version
      iterations searching for SSE because the Fase 30 D4 fallback
      required an `Accept:` header the client didn't send) revealed
      that the language internally inferred SSE for stream-effect
      flows yet refused to surface that inference at the wire
      layer without an `Accept:` opt-in. Fase 31 closes the gap:

        * D1 inference rule —
            `implicit_transport(F, E) =
              declared_transport(E)   if transport_explicit
              "sse"                    if produces_stream(F) ∧ ¬explicit
              "json"                   otherwise`
          The 3-disjunct `produces_stream` predicate from Fase 30.c
          is extended to ALSO resolve `apply: <tool_name>` step-
          body references (the Kivi-shape pattern Fase 30.c missed
          at compile time + the AST-visible disjunct (b) path the
          Fase 30.e runtime source-text fallback was carrying
          alone).

        * D4 compile-time warning `axon-W001` — non-fatal warning
          surfaces the inference at build time with disjunct-
          specific origin (`step '<n>' applies tool '<t>' with
          effects <stream:<policy>>`) so adopters paste fixes
          without re-reading source. Opens the new `axon-Wnnn`
          warnings namespace. Strict mode (Fase 28.h `--strict`)
          promotes to error.

        * D5 runtime header `X-Axon-Stream-Available: 1;
          reason=<flag_off|declared_json>; flow=<name>;
          opt_in=transport:sse,Accept:text/event-stream` — fires
          on JSON responses for stream-effect flows; informational
          only (body byte-identical).

        * D6 flag-gated runtime — `ServerConfig.strict_type_driven_
          transport: bool` (default false v1.22.x per D6 backwards-
          compat; flips to default true in v2.0.0 per D9). When ON,
          the inference rules the wire — every stream-effect flow
          on `POST /v1/execute` returns SSE regardless of `Accept:`
          header. Adopters opt in via two converging surfaces:
          `axon serve --strict-type-driven-transport` CLI flag OR
          `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1` env var (D7 cross-
          stack contract — Python `axon serve` + Rust `axon-rs`
          read the same env var name verbatim; truthy alphabet
          `{1,true,yes,on}` case-insensitive, intentionally
          constrained to refuse drift like `y`/`t`/`enabled`).

        * D3 ratified sacred — explicit `transport: json` always
          wins in both modes. Adopters who intentionally wrap
          stream tokens in a single JSON response keep that
          behavior unchanged. The runtime header still fires with
          `reason=declared_json` so clients see the trade-off.

        * D8 backwards-compat absolute — when the strict flag is
          off (v1.22.x default), the Fase 30 D4 + D5 + D9
          negotiation matrix is preserved byte-identically. Every
          v1.21.x adopter sees zero behavior change on `axon
          parse` + `axon serve` (other than the new informational
          header on JSON responses for stream-effect flows).

  Enterprise tenants on regulated verticals (HIPAA / legal /
  fintech) immediately benefit on streaming compliance audit
  flows: the shield + audit pipelines that synthesise final
  answers from streaming tokens now emit the streaming wire
  format BY DEFAULT (when the strict flag is on) — no per-
  axonendpoint declaration churn required. The vertical
  ensembles in `axon_enterprise.shield` (healthcare / legal /
  fintech ensembles) all consume `Stream<T>` upstream of their
  judge LLM calls; v1.12.0 surfaces that streaming at the
  wire automatically. axon-frontend Rust crate dependency
  bumps transitively from 0.9.0 → 0.10.0 (in axon-lang
  1.22.0).

  v1.12.0 is a lean catch-up — same shape as v1.9.0 + v1.11.0.
  The substantive Fase 27.k.1 Python ctypes integration (FFI
  foundation already on `feature/27k1-ctypes-foundation`
  branch) ships in a future release once its Python wrapper
  modules + supervisor wiring + audit_engine integration land.

  Fase 29 "Enterprise Diagnostic Enhancements" remains the
  announced enterprise-only follow-on layered on top of this
  OSS surface (default-strict in regulated verticals via
  vertical-aware policy + ship diagnostics to enterprise
  telemetry sink + vertical-aware suggest dictionaries).
"""

__version__ = "1.25.0"
