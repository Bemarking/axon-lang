/* §Fase 27.c — FIPS-validated crypto glue (header).
 *
 * Declares the C ABI the Rust shim binds to under the
 * `fips-boringssl` or `fips-openssl` cargo features. Mirrors the
 * shape of the OSS axon-csys SHA-256 / HMAC-SHA256 surface so the
 * Rust shim can swap implementations behind a `#[cfg]` gate without
 * touching any consumer code.
 *
 * Compilation regime:
 *
 *   AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL → routes to BoringSSL EVP_*
 *                                          (Apache-2; FIPS 140-3
 *                                          module integrity self-
 *                                          test runs at first call)
 *   AXON_CSYS_ENTERPRISE_FIPS_OPENSSL   → routes to OpenSSL-FIPS
 *                                          provider (CMVP cert per
 *                                          release; currently #4282
 *                                          for OpenSSL 3.0 FIPS
 *                                          Provider)
 *   (else)                              → file is NOT compiled (the
 *                                          build script gates
 *                                          inclusion); the OSS
 *                                          axon-csys re-export path
 *                                          is used instead.
 *
 * The function names are deliberately distinct from OSS
 * `axon_csys_*` so the FIPS-routed glue and the OSS C kernel can
 * coexist in the same final binary (e.g. ContinuityWire's audit log
 * may want to record both backends' answers during a FIPS rollout).
 *
 * SAFETY: every function takes `data` / `key` pointers + lengths.
 * Empty inputs (`len == 0`) are handled per FIPS 180-4: `data` may
 * be NULL when `len == 0`. The implementations explicitly guard
 * NULL pointers when the linked FIPS lib's EVP API requires a
 * non-NULL data pointer (BoringSSL is strict; OpenSSL is permissive).
 */

#ifndef AXON_CSYS_ENTERPRISE_FIPS_GLUE_H
#define AXON_CSYS_ENTERPRISE_FIPS_GLUE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Mirrors OSS axon-csys's SHA-256 sizing constants. Kept in sync
 * by the cross-stack drift gate — any change here is a wire-format
 * break and bumps the enterprise crate's ABI version. */
#define AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE ((size_t)32)
#define AXON_CSYS_ENTERPRISE_SHA256_BLOCK_SIZE  ((size_t)64)

/* SHA-256 — one-shot.
 *
 * Computes the digest of `data[0 .. len]` and writes 32 bytes to
 * `out`. `out` must point to at least `AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE`
 * bytes. `data` may be NULL when `len == 0`.
 *
 * Returns 0 on success, non-zero on FIPS-lib failure (e.g. integrity
 * self-test fail at first call). The Rust shim treats non-zero as
 * a soft-fail and emits an audit-log entry per D13.
 */
int axon_csys_enterprise_sha256(const uint8_t *data, size_t len, uint8_t *out);

/* HMAC-SHA256 — one-shot.
 *
 * Computes HMAC-SHA256 of `data[0 .. data_len]` keyed by
 * `key[0 .. key_len]` and writes 32 bytes to `out`. Per RFC 2104:
 * any key length is accepted; keys longer than the block size (64
 * bytes) are first compressed via SHA-256.
 *
 * Returns 0 on success, non-zero on failure.
 */
int axon_csys_enterprise_hmac_sha256(
    const uint8_t *key, size_t key_len,
    const uint8_t *data, size_t data_len,
    uint8_t *out);

/* FIPS module integrity self-test.
 *
 * Forces the linked FIPS module to run its power-on self-tests
 * (POST). On BoringSSL this triggers the integrity check + KAT
 * (known-answer tests) per FIPS 140-3. On OpenSSL-FIPS this loads
 * the FIPS provider explicitly and runs its POST.
 *
 * Returns 0 on success, non-zero on POST failure. Adopters running
 * federal workloads MUST gate startup on this returning 0.
 *
 * Calling this multiple times is safe: subsequent calls are no-ops
 * (the FIPS lib caches POST state internally).
 */
int axon_csys_enterprise_fips_self_test(void);

/* Returns a stable C string label for the linked FIPS backend.
 *
 *   "boringssl-fips" — BoringSSL-FIPS module
 *   "openssl-fips"   — OpenSSL-FIPS provider
 *
 * Useful for the audit-log emission in `ContinuityWire::sign` so
 * historical events stay parseable across a backend rotation. The
 * returned pointer is to a `static const` string with program
 * lifetime — caller MUST NOT free.
 */
const char *axon_csys_enterprise_fips_backend_label(void);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* AXON_CSYS_ENTERPRISE_FIPS_GLUE_H */
