//! § Fase 27.b — axon-csys-enterprise build-infrastructure probe tests.
//!
//! Mirrors the OSS Fase 25.b probe test pack but in the enterprise
//! namespace. Verifies the C build pipeline + FFI link work end-to-end
//! before later sub-fases (27.c onward) depend on them.

use axon_csys_enterprise::probe::{
    add, c_standard, cacheline_marker, cacheline_size, features, version, version_round_trip,
    AxonCsysEnterpriseVersion,
};
use axon_csys_enterprise::FipsBackend;

// ──────────────────────────────────────────────────────────────────────
// 1. ABI version surface
// ──────────────────────────────────────────────────────────────────────

#[test]
fn abi_version_matches_compile_time_constants() {
    let v = version();
    assert_eq!(
        v,
        AxonCsysEnterpriseVersion {
            major: 0,
            minor: 1,
            patch: 0,
        },
        "ABI version drifted from the documented 0.1.0 — \
         coordinate the bump in the C source + Rust shim + plan vivo"
    );
}

#[test]
fn abi_version_round_trip_through_repr_c() {
    // Validates that `#[repr(C)]` on `AxonCsysEnterpriseVersion`
    // matches the C struct layout. If the layout drifts, the round
    // trip returns garbage.
    assert_eq!(version_round_trip(2, 4, 8), 2 + 4 + 8);
    assert_eq!(version_round_trip(0, 0, 0), 0);
    assert_eq!(version_round_trip(u32::MAX, 0, 0), u32::MAX);
}

// ──────────────────────────────────────────────────────────────────────
// 2. Compile-time feature flags
// ──────────────────────────────────────────────────────────────────────

#[test]
fn feature_flags_match_cargo_features() {
    let f = features();
    assert_eq!(
        f.fips_boringssl,
        cfg!(feature = "fips-boringssl"),
        "C-side feature flag for fips-boringssl drifted from cargo"
    );
    assert_eq!(
        f.fips_openssl,
        cfg!(feature = "fips-openssl"),
        "C-side feature flag for fips-openssl drifted from cargo"
    );
    assert_eq!(
        f.public_anchor,
        cfg!(feature = "public-anchor"),
        "C-side feature flag for public-anchor drifted from cargo"
    );
    assert_eq!(
        f.phi_scrubber_c,
        cfg!(feature = "phi-scrubber-c"),
        "C-side feature flag for phi-scrubber-c drifted from cargo"
    );
}

#[test]
fn fips_backends_are_mutually_exclusive() {
    let f = features();
    // Both flags being true at once would mean the build script
    // failed to enforce mutual exclusivity. Per D3 ratified
    // 2026-05-09, this is a hard error.
    assert!(
        !(f.fips_boringssl && f.fips_openssl),
        "fips-boringssl and fips-openssl are mutually exclusive (D3)"
    );
}

#[test]
fn fips_backend_enum_matches_active_features() {
    let backend = FipsBackend::current();
    let f = features();
    let expected = if f.fips_boringssl {
        FipsBackend::BoringSsl
    } else if f.fips_openssl {
        FipsBackend::OpenSsl
    } else {
        FipsBackend::None
    };
    assert_eq!(backend, expected);
    // The audit-log label is fixed across releases — guard the
    // strings so a refactor doesn't accidentally rotate them.
    let label = backend.label();
    assert!(matches!(
        label,
        "axon-csys-oss-pure-c" | "boringssl-fips" | "openssl-fips"
    ));
}

// ──────────────────────────────────────────────────────────────────────
// 3. C standard realisation
// ──────────────────────────────────────────────────────────────────────

#[test]
fn c_standard_is_c23_or_c2x() {
    let std = c_standard();
    // C23 official ratification = 202311L; MSVC `/std:clatest`
    // reports 202312L per its own quirk (documented in OSS
    // axon-csys probe + accepted in this test pack); C2x
    // pre-ratification = 202000L.
    let allowed = [202311_i64, 202312_i64, 202000_i64];
    let std_i64 = std as i64;
    assert!(
        allowed.contains(&std_i64),
        "Unexpected __STDC_VERSION__: {std} (want one of {allowed:?})"
    );
}

// ──────────────────────────────────────────────────────────────────────
// 4. Cache-line alignment (D for audit log mmap kernel 27.d)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn cacheline_size_is_canonical_for_target() {
    let size = cacheline_size();
    // Apple Silicon M-series → 128; mainstream x86-64 + non-Apple
    // ARM64 → 64. Anything outside this set is suspicious.
    assert!(
        size == 64 || size == 128,
        "Unexpected cache-line size: {size} (want 64 or 128)"
    );
}

#[test]
fn alignas_64_works_under_active_toolchain() {
    let modulo = cacheline_marker();
    assert_eq!(
        modulo, 0,
        "_Alignas(64) marker is at offset {modulo} mod 64; the \
         compiler did not honor the alignment attribute. Audit log \
         mmap kernel (27.d) depends on this — bail loudly."
    );
}

// ──────────────────────────────────────────────────────────────────────
// 5. Pure-arithmetic ABI smoke
// ──────────────────────────────────────────────────────────────────────

#[test]
fn ffi_smoke_add_returns_correct_sum() {
    assert_eq!(add(0, 0), 0);
    assert_eq!(add(1, 2), 3);
    assert_eq!(add(u64::MAX - 1, 1), u64::MAX);
    // Wrapping semantics — the C side is `uint64_t + uint64_t` which
    // wraps on overflow.
    assert_eq!(add(u64::MAX, 1), 0);
}

// ──────────────────────────────────────────────────────────────────────
// 6. OSS axon-csys re-export round-trip
// ──────────────────────────────────────────────────────────────────────

#[test]
fn oss_axon_csys_reexport_works_under_no_fips_default() {
    // The crate's no-fips default re-exports OSS axon-csys verbatim.
    // Verify a few canonical entry points are reachable through this
    // crate's namespace AND produce the exact same bytes the OSS
    // crate produces directly.
    use axon_csys_enterprise::{hex_encode, sha256, FipsBackend};

    let our_digest = sha256(b"axon-csys-enterprise probe");
    let oss_digest = axon_csys::sha256(b"axon-csys-enterprise probe");
    assert_eq!(
        our_digest, oss_digest,
        "Re-exported sha256 produced different output from OSS axon-csys"
    );

    // hex_encode is a pure-arithmetic helper; its output should be
    // identical regardless of which crate exposes it.
    assert_eq!(hex_encode(&our_digest), axon_csys::hex_encode(&oss_digest));

    // FipsBackend::current() reflects the active feature set. With
    // no feature enabled, expect None + the OSS pure-C label.
    if !cfg!(feature = "fips-boringssl") && !cfg!(feature = "fips-openssl") {
        assert_eq!(FipsBackend::current(), FipsBackend::None);
        assert_eq!(FipsBackend::current().label(), "axon-csys-oss-pure-c");
    }
}
