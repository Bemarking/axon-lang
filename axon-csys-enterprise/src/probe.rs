//! § Fase 27.b — build-infrastructure probe (Rust shim).
//!
//! Mirrors the OSS [`axon_csys::probe`] shape but in the enterprise
//! namespace. The probe gives downstream tests a stable surface to
//! verify (a) the C23 build pipeline works, (b) the strict-warning
//! posture compiled clean, (c) the cache-line alignment + struct
//! round-trip mechanics that later kernels (audit log mmap,
//! evidence packager) depend on.
//!
//! No real crypto here — that's 27.c. This is the smallest possible
//! end-to-end "C ↔ Rust" link that proves the build pipeline works
//! before later sub-fases depend on it.

use std::os::raw::c_long;

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AxonCsysEnterpriseVersion {
    pub major: u32,
    pub minor: u32,
    pub patch: u32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AxonCsysEnterpriseFeatures {
    pub fips_boringssl: bool,
    pub fips_openssl: bool,
    pub public_anchor: bool,
    pub phi_scrubber_c: bool,
}

extern "C" {
    fn axon_csys_enterprise_probe_version() -> AxonCsysEnterpriseVersion;
    fn axon_csys_enterprise_probe_features() -> AxonCsysEnterpriseFeatures;
    fn axon_csys_enterprise_probe_c_standard() -> c_long;
    fn axon_csys_enterprise_probe_cacheline_size() -> usize;
    fn axon_csys_enterprise_probe_cacheline_alignment() -> usize;
    fn axon_csys_enterprise_probe_version_round_trip(major: u32, minor: u32, patch: u32) -> u32;
    fn axon_csys_enterprise_probe_add(a: u64, b: u64) -> u64;
}

/// ABI version compiled into the C kernel. Independent of the crate's
/// semver in `Cargo.toml`; changes only when later sub-fases (27.c
/// onward) break the FFI surface.
pub fn version() -> AxonCsysEnterpriseVersion {
    // SAFETY: pure-arithmetic returning a POD by value; no
    // pointers, no allocator, no global state.
    unsafe { axon_csys_enterprise_probe_version() }
}

/// Compile-time feature flags as the C kernel saw them. The Rust
/// shim cross-validates these against `cfg!(feature = ...)` to
/// catch build-script ↔ Cargo.toml drift early.
pub fn features() -> AxonCsysEnterpriseFeatures {
    // SAFETY: pure POD return.
    unsafe { axon_csys_enterprise_probe_features() }
}

/// Value of `__STDC_VERSION__` as the toolchain compiles it.
/// Documented C23 = 202311L per ISO ratification, but MSVC
/// `/std:clatest` reports 202312L (per its own quirk; OSS
/// axon-csys probe documents this and the test pack accepts it).
pub fn c_standard() -> c_long {
    // SAFETY: pure POD return.
    unsafe { axon_csys_enterprise_probe_c_standard() }
}

/// Architecturally-canonical cache-line size for this target.
/// Used by 27.d audit log mmap to align block boundaries +
/// avoid false-sharing on concurrent writes.
pub fn cacheline_size() -> usize {
    // SAFETY: pure POD return.
    unsafe { axon_csys_enterprise_probe_cacheline_size() }
}

/// Pointer-modulo-64 of a stack-resident `_Alignas(64)` buffer.
/// Tests/probe.rs asserts == 0 to verify `_Alignas` works under
/// the active toolchain (it has historically broken on some MSVC
/// versions when /experimental flags interact poorly).
pub fn cacheline_marker() -> usize {
    // SAFETY: pure POD return.
    unsafe { axon_csys_enterprise_probe_cacheline_alignment() }
}

/// Returns `major + minor + patch` after passing them through the
/// C struct round-trip. Validates the `#[repr(C)]` layout matches
/// the C definition.
pub fn version_round_trip(major: u32, minor: u32, patch: u32) -> u32 {
    // SAFETY: pure POD args + return.
    unsafe { axon_csys_enterprise_probe_version_round_trip(major, minor, patch) }
}

/// Pure-arithmetic add. Smoke test that the C ABI is wired up
/// at all — if this returns the wrong number, every other kernel
/// is suspect.
pub fn add(a: u64, b: u64) -> u64 {
    // SAFETY: pure POD args + return.
    unsafe { axon_csys_enterprise_probe_add(a, b) }
}
