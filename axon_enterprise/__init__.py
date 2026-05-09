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
  gotos. No enterprise-only kernels in v1.9.0; "Silicon + Cognition
  Enterprise" R&D charter (FIPS-validated crypto via BoringSSL/
  OpenSSL-FIPS, audit log mmap, vertical-specific BPE, tamper-
  evident evidence packager) tracked separately for a future fase
  (v1.9.0).
"""

__version__ = "1.9.0"
