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
  Python integration of these kernels via ctypes wrappers ships as
  v1.11.0 (27.k.1 followup); v1.10.0 ships the Rust foundation +
  the Python package version bump signaling the crate is part of
  the platform.
"""

__version__ = "1.10.0"
