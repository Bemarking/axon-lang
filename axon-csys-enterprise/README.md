# axon-csys-enterprise

Enterprise companion to the OSS [`axon-csys`](https://crates.io/crates/axon-csys)
crate. Adds the kernels whose value is in audit posture (HIPAA / SOC2 /
CC-EAL4+ / GDPR / PCI DSS), not in adopter-agnostic OSS.

§ Fase 27 — *Silicon + Cognition Enterprise (sesión 1)*. Companion to
the OSS Fase 25 release shipped 2026-05-08.

## What ships in v0.1.x (sesión 1)

| Sub-fase | Kernel | Status |
|---|---|---|
| 27.b | Build-infra probe + LICENSE.bsl + cargo features | ✅ shipped |
| 27.c | FIPS-validated crypto link (BoringSSL OR OpenSSL-FIPS) | pending |
| 27.d | Audit log mmap append-only + Merkle chain + tenant seal | pending |
| 27.e | Vertical BPE templates (medical / legal / fintech) | pending |
| 27.f | Tamper-evident byte-deterministic evidence packager | pending |
| 27.g | (optional) PHI scrubber SIMD kernel | pending |

## License

[Business Source License v1.1](LICENSE.bsl) with a 4-year delay to
the [MIT License](https://opensource.org/license/mit). Source-
available; commercial use restricted during the active lifecycle;
auto-converts to MIT on the Change Date (`2030-05-09` for v0.1.x).
Pattern matches HashiCorp / Sentry / MariaDB.

NOT publishable to crates.io (which rejects non-OSI licenses).
Distributed via a private Cargo registry to licensed adopters.

For commercial licensing arrangements, contact
[`licensing@bemarking.com.co`](mailto:licensing@bemarking.com.co).

## Quick start

Default usage — no feature flags — gives a transparent passthrough
to OSS `axon-csys`:

```rust
use axon_csys_enterprise::{sha256, hex_encode, ContinuityWire};
use axon_csys_enterprise::FipsBackend;

let digest = sha256(b"hello world");
println!("digest: {}", hex_encode(&digest));
println!("backend: {}", FipsBackend::current().label());
// → "axon-csys-oss-pure-c"
```

Enable a FIPS-validated crypto backend at the dependency declaration:

```toml
[dependencies]
axon-csys-enterprise = { version = "=0.1.0", features = ["fips-openssl"] }
```

The wire format stays byte-identical: a `ContinuityToken` issued by
an OSS deployment verifies on a FIPS-validated deployment and
vice-versa. The differentiator is the formal CMVP certificate
embedded in the adopter's compliance documentation, not the bytes
on the wire.

## Cargo features

| Feature | Effect |
|---|---|
| (default) | Pass-through; re-exports OSS axon-csys verbatim |
| `fips-boringssl` | Statically link BoringSSL-FIPS module (Apache-2; FIPS 140-3 module integrity self-test) |
| `fips-openssl` | Statically link OpenSSL-FIPS Provider (CMVP certificate per release; currently #4282 for OpenSSL 3.0 FIPS Provider) |
| `phi-scrubber-c` | Activate the SIMD-accelerated PHI scrubber kernel (27.g) |
| `public-anchor` | Activate the public-chain audit-log anchoring (27.d / 27.f optional) |

`fips-boringssl` and `fips-openssl` are mutually exclusive; the
build script + `compile_error!` enforce this at build time.

## Toolchain matrix

Same posture as OSS axon-csys 0.1.x:

| OS | Compilers | C standard target |
|---|---|---|
| Ubuntu (latest)  | gcc 13+, clang 17+   | C23 (fallback C2x) |
| macOS (latest)   | Apple clang 15+      | C23 (fallback C2x) |
| Windows          | MSVC 19.41+, clang-cl | `/std:clatest`    |

Rust toolchain floor: 1.95 (matches OSS axon-csys + axon-lang).

## Provenance

Plan vivo: [`docs/fase_27_silicon_cognition_enterprise.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/fase_27_silicon_cognition_enterprise.md)
(in the axon-lang repo per convention with prior enterprise-only
fases — Fase 20 production_shield_runtime, Fase 21 integration_surface).
Founder ratification of D1–D14: 2026-05-09 ("No MVP, todo full
robusto 100% producción + Enterprise").

Companion to the OSS Fase 25 plan: [`docs/fase_25_silicon_cognition.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/fase_25_silicon_cognition.md).
