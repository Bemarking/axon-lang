/*
 * §Fase 27.b — axon-csys-enterprise build-infrastructure probe.
 *
 * Mirrors the OSS Fase 25.b probe but in the enterprise namespace.
 * The probe verifies (a) the C23 flag chain works for this crate
 * (gcc/clang `-std=c23` with c2x fallback, MSVC `/std:clatest`), (b)
 * the strict-warning posture compiles clean (`-Wall -Wextra
 * -Wpedantic -Werror -Wshadow -Wcast-align -Wconversion
 * -Wstrict-prototypes` on Unix, `/W4 /WX` on MSVC), and (c) the
 * cache-line alignment + struct round-trip mechanics that later
 * kernels (audit log mmap, evidence packager) depend on.
 *
 * No real crypto in 27.b — that's 27.c. The probe is the smallest
 * possible compile + link that proves the build pipeline works
 * end-to-end before we depend on it.
 *
 * §axon-enterprise charter: this file is BSL-licensed (see
 * ../../LICENSE.bsl); auto-converts to MIT on the Change Date
 * (2030-05-09).
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#if defined(__has_c_attribute) && __has_c_attribute(nodiscard)
#  define AXON_CSYS_ENTERPRISE_NODISCARD [[nodiscard]]
#else
#  define AXON_CSYS_ENTERPRISE_NODISCARD
#endif

/* §Fase 27.b — public ABI version. The major.minor.patch values
 * here are the BUILD-SYSTEM ABI version; they are independent of
 * the crate's semver in Cargo.toml. They change whenever a kernel
 * added in a later sub-fase (27.c onward) breaks the FFI surface. */
#define AXON_CSYS_ENTERPRISE_ABI_MAJOR 0u
#define AXON_CSYS_ENTERPRISE_ABI_MINOR 1u
#define AXON_CSYS_ENTERPRISE_ABI_PATCH 0u

typedef struct {
    uint32_t major;
    uint32_t minor;
    uint32_t patch;
} AxonCsysEnterpriseVersion;

/* §Fase 27.b — feature flags compiled into this build. The Rust
 * shim reads these to verify the link wired up correctly. */
typedef struct {
    bool fips_boringssl;
    bool fips_openssl;
    bool public_anchor;
    bool phi_scrubber_c;
} AxonCsysEnterpriseFeatures;

#ifdef __cplusplus
extern "C" {
#endif

/* §Fase 27.b — ABI version surface. */
AXON_CSYS_ENTERPRISE_NODISCARD
AxonCsysEnterpriseVersion axon_csys_enterprise_probe_version(void) {
    return (AxonCsysEnterpriseVersion){
        .major = AXON_CSYS_ENTERPRISE_ABI_MAJOR,
        .minor = AXON_CSYS_ENTERPRISE_ABI_MINOR,
        .patch = AXON_CSYS_ENTERPRISE_ABI_PATCH,
    };
}

/* §Fase 27.b — compile-time feature flags. The build.rs sets
 * `AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL=1` etc when the matching
 * cargo feature is active; this function lets the Rust shim probe
 * which paths are linked. */
AXON_CSYS_ENTERPRISE_NODISCARD
AxonCsysEnterpriseFeatures axon_csys_enterprise_probe_features(void) {
    return (AxonCsysEnterpriseFeatures){
#ifdef AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL
        .fips_boringssl = true,
#else
        .fips_boringssl = false,
#endif
#ifdef AXON_CSYS_ENTERPRISE_FIPS_OPENSSL
        .fips_openssl = true,
#else
        .fips_openssl = false,
#endif
#ifdef AXON_CSYS_ENTERPRISE_PUBLIC_ANCHOR
        .public_anchor = true,
#else
        .public_anchor = false,
#endif
#ifdef AXON_CSYS_ENTERPRISE_PHI_SCRUBBER_C
        .phi_scrubber_c = true,
#else
        .phi_scrubber_c = false,
#endif
    };
}

/* §Fase 27.b — C standard realisation probe.
 *
 * Returns the value of `__STDC_VERSION__` as the compiler sees it.
 * The Rust shim asserts it matches the documented floor (C23 =
 * 202311L per ISO ratification, but MSVC reports 202312L per its
 * own quirk; OSS axon-csys probe documents this). */
AXON_CSYS_ENTERPRISE_NODISCARD
long axon_csys_enterprise_probe_c_standard(void) {
#ifdef __STDC_VERSION__
    return (long) __STDC_VERSION__;
#else
    return 0L;
#endif
}

/* §Fase 27.b — cache-line size detection.
 *
 * Returns the architecturally-canonical cache-line size for the
 * target. x86-64 + aarch64 most cores → 64; Apple M-series → 128.
 * The audit log mmap kernel (27.d) aligns its block boundary to
 * this value to avoid false-sharing on concurrent writes. */
AXON_CSYS_ENTERPRISE_NODISCARD
size_t axon_csys_enterprise_probe_cacheline_size(void) {
#if defined(__APPLE__) && defined(__arm64__)
    /* Apple Silicon M-series cores carry 128 B cache lines. */
    return 128u;
#elif defined(__x86_64__) || defined(_M_X64) || defined(__aarch64__) || defined(_M_ARM64)
    /* Mainstream x86-64 + non-Apple ARM64. */
    return 64u;
#else
    /* Conservative fallback. The audit log will still work; just
     * may have suboptimal cache behaviour on unusual targets. */
    return 64u;
#endif
}

/* §Fase 27.b — alignment marker.
 *
 * Allocates a stack-resident, cache-line-aligned probe buffer +
 * returns the pointer-modulo-alignment. Used by tests/probe.rs to
 * verify `_Alignas(64)` works under the active toolchain. */
AXON_CSYS_ENTERPRISE_NODISCARD
size_t axon_csys_enterprise_probe_cacheline_alignment(void) {
    _Alignas(64) static volatile uint8_t marker[64];
    return ((size_t) (uintptr_t) marker) % 64u;
}

/* §Fase 27.b — struct round-trip probe.
 *
 * Verifies the FFI struct layout the Rust shim depends on. Future
 * kernels add their own structs to this surface. The version-info
 * struct is the simplest stable example. */
AXON_CSYS_ENTERPRISE_NODISCARD
uint32_t axon_csys_enterprise_probe_version_round_trip(uint32_t major,
                                                       uint32_t minor,
                                                       uint32_t patch)
{
    AxonCsysEnterpriseVersion v = { .major = major, .minor = minor, .patch = patch };
    return v.major + v.minor + v.patch;
}

/* §Fase 27.b — pure-arithmetic add (smoke).
 *
 * The simplest possible C function. Verifies the link surface is
 * actually wired up (Rust calls C, gets the right answer back). */
AXON_CSYS_ENTERPRISE_NODISCARD
uint64_t axon_csys_enterprise_probe_add(uint64_t a, uint64_t b) {
    return a + b;
}

#ifdef __cplusplus
}
#endif
