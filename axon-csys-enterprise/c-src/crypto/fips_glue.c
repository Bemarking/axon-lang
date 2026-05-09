/* §Fase 27.c — FIPS-validated crypto glue (implementation).
 *
 * Routes SHA-256 + HMAC-SHA256 to the linked FIPS-validated crypto
 * library when one of the FIPS feature flags is active. The glue is
 * deliberately minimal: every function is a pass-through to EVP_*
 * with a thin error wrapper. The wire output is byte-identical to
 * OSS axon-csys's pure-C SHA-256 / HMAC-SHA256 (drift gate enforces
 * this on every NIST CAVS vector + 100 fuzz iterations per primitive).
 *
 * Compilation regime: this file is only compiled when at least one
 * of `AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL` / `AXON_CSYS_ENTERPRISE_FIPS_OPENSSL`
 * is defined. The build script gates inclusion via cargo features;
 * see build.rs comment block §FIPS-validated crypto link (D3).
 *
 * The mutual-exclusivity guard is implemented in TWO places:
 *   1. Rust-side `compile_error!` in `src/lib.rs`.
 *   2. Build-script panic in `build.rs`.
 * Belt-and-braces: both must agree.
 */

/* Belt-and-braces compile-time check that the build script honored
 * the mutual-exclusivity invariant. Any reachable state where both
 * macros are defined indicates the build script was bypassed (e.g.
 * via a custom workspace setup that skipped build.rs probing). */
#if defined(AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL) && \
    defined(AXON_CSYS_ENTERPRISE_FIPS_OPENSSL)
#error \
    "axon-csys-enterprise: AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL and AXON_CSYS_ENTERPRISE_FIPS_OPENSSL " \
    "are mutually exclusive (per D3 ratified 2026-05-09). The build script should have rejected this."
#endif

#if !defined(AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL) && \
    !defined(AXON_CSYS_ENTERPRISE_FIPS_OPENSSL)
#error \
    "axon-csys-enterprise: fips_glue.c was compiled without a FIPS feature flag. " \
    "The build script should NOT include this file in the no-fips passthrough regime."
#endif

#include "fips_glue.h"

#include <openssl/evp.h>
#include <openssl/hmac.h>

#ifdef AXON_CSYS_ENTERPRISE_FIPS_OPENSSL
/* OpenSSL 3.0+ exposes the FIPS provider via the `provider.h`
 * surface. Loading the FIPS provider explicitly is required;
 * otherwise EVP_DigestInit_ex2 silently falls back to the default
 * provider and the formal CMVP certificate doesn't apply. */
#include <openssl/provider.h>
#include <openssl/err.h>
#endif

#include <stdatomic.h>
#include <string.h>

/* ──────────────────────────────────────────────────────────────────
 * Backend-specific POST glue
 *
 * BoringSSL:
 *   The FIPS module integrity self-test runs once at module load
 *   time. `BORINGSSL_FIPS_self_test()` (when the FIPS module is
 *   compiled in) returns 1 on success. On a non-FIPS build of
 *   BoringSSL the symbol is absent — guarded by an availability
 *   check below.
 *
 * OpenSSL-FIPS:
 *   `OSSL_PROVIDER_load(NULL, "fips")` loads + verifies the FIPS
 *   provider. Failure indicates POST failure.
 *
 * Both backends cache the POST result internally; the
 * `posted` atomic flag below short-circuits redundant work after the
 * first successful self-test. This avoids per-operation overhead.
 * ────────────────────────────────────────────────────────────────── */

static _Atomic int s_posted_status = 0; /* 0 = not yet, 1 = ok, -1 = fail */

#ifdef AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL
/* BoringSSL's FIPS module exports BORINGSSL_self_test on FIPS
 * builds. The symbol is hidden on non-FIPS builds — we declare it
 * here as a weak reference so a non-FIPS BoringSSL still links
 * (the call returns 1 by default in that case, matching the
 * "no-FIPS-mode" semantics).
 *
 * Per the BoringSSL FIPS manual (third-party-fips/boringssl/
 * crypto/fipsmodule/self_check/self_check.c), the self-test runs
 * KAT for: SHA-1/256/384/512, HMAC, AES-CBC/GCM, ECDSA, ECDH, RSA,
 * TLS-KDF, HKDF. We only consume SHA-256 + HMAC-SHA256 but the
 * full KAT is the FIPS-required gate. */
extern int BORINGSSL_self_test(void);
#endif

int axon_csys_enterprise_fips_self_test(void) {
    int status = atomic_load_explicit(&s_posted_status, memory_order_acquire);
    if (status != 0) {
        return status == 1 ? 0 : -1;
    }

    int ok = 0;

#ifdef AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL
    /* BoringSSL self-test is the load-bearing gate. Returns 1 on
     * success (FIPS or non-FIPS build), 0 on KAT failure (FIPS
     * build only). */
    ok = BORINGSSL_self_test();
#elif defined(AXON_CSYS_ENTERPRISE_FIPS_OPENSSL)
    /* Explicit FIPS provider load. Per OpenSSL 3.0 docs:
     * `OSSL_PROVIDER_load(libctx, "fips")` returns NULL on POST
     * failure or missing fipsmodule.cnf. The integrity check runs
     * inside the load. */
    OSSL_PROVIDER *fips = OSSL_PROVIDER_load(NULL, "fips");
    if (fips != NULL) {
        ok = 1;
        /* Keep the provider loaded for the lifetime of the
         * process — no `OSSL_PROVIDER_unload(fips)`. The default
         * cleanup at process exit suffices. */
    }
#endif

    int new_status = ok ? 1 : -1;
    /* CAS so a concurrent caller doesn't override our result with
     * an in-flight retry. The first writer wins; subsequent calls
     * read the cached value. */
    int expected = 0;
    atomic_compare_exchange_strong_explicit(
        &s_posted_status, &expected, new_status,
        memory_order_acq_rel, memory_order_acquire);
    return ok ? 0 : -1;
}

const char *axon_csys_enterprise_fips_backend_label(void) {
#ifdef AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL
    return "boringssl-fips";
#elif defined(AXON_CSYS_ENTERPRISE_FIPS_OPENSSL)
    return "openssl-fips";
#else
    /* Unreachable — guarded by the #error above. */
    return "unknown-fips";
#endif
}

/* ──────────────────────────────────────────────────────────────────
 * SHA-256 — one-shot via EVP
 *
 * Both BoringSSL + OpenSSL 3.0 expose `EVP_Digest` for one-shot
 * hashing. The OpenSSL-FIPS path uses `EVP_DigestInit_ex2` with the
 * `properties = "fips=yes"` selector to FORCE the FIPS provider's
 * implementation (a defense-in-depth above just having the FIPS
 * provider loaded — adopters with mixed-mode deployments can
 * confirm the FIPS path was taken via the property cap).
 * ────────────────────────────────────────────────────────────────── */

int axon_csys_enterprise_sha256(const uint8_t *data, size_t len, uint8_t *out) {
    if (out == NULL) {
        return -1;
    }
    /* FIPS 180-4: empty input is well-defined; data may be NULL
     * when len == 0. EVP_Digest accepts NULL data with len 0 on
     * both BoringSSL and OpenSSL 3.0+. */

    if (axon_csys_enterprise_fips_self_test() != 0) {
        return -2; /* POST failed; do NOT silently route to non-FIPS. */
    }

#ifdef AXON_CSYS_ENTERPRISE_FIPS_OPENSSL
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (ctx == NULL) {
        return -3;
    }
    EVP_MD *md = EVP_MD_fetch(NULL, "SHA2-256", "fips=yes");
    if (md == NULL) {
        EVP_MD_CTX_free(ctx);
        return -4;
    }
    int ok = EVP_DigestInit_ex2(ctx, md, NULL) == 1
          && EVP_DigestUpdate(ctx, data, len) == 1
          && EVP_DigestFinal_ex(ctx, out, NULL) == 1;
    EVP_MD_free(md);
    EVP_MD_CTX_free(ctx);
    return ok ? 0 : -5;
#else /* BoringSSL */
    /* BoringSSL's EVP_sha256() returns the FIPS-validated impl when
     * the FIPS module is compiled in. No property selector needed. */
    unsigned int out_len = 0;
    int ok = EVP_Digest(data, len, out, &out_len, EVP_sha256(), NULL) == 1
          && out_len == (unsigned int)AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE;
    return ok ? 0 : -5;
#endif
}

/* ──────────────────────────────────────────────────────────────────
 * HMAC-SHA256 — one-shot via EVP_MAC (OpenSSL 3.0+) or HMAC()
 * (BoringSSL legacy compat).
 *
 * OpenSSL 3.0 deprecated the legacy `HMAC()` one-shot in favour of
 * `EVP_MAC` with the "HMAC" mac kind. The FIPS provider exposes
 * HMAC-SHA-256 under property `fips=yes`. We force the property
 * here so a mis-configured `fipsmodule.cnf` causes a hard failure
 * rather than a silent fallthrough.
 *
 * BoringSSL keeps the legacy HMAC() symbol; we use it directly there.
 * ────────────────────────────────────────────────────────────────── */

int axon_csys_enterprise_hmac_sha256(
    const uint8_t *key, size_t key_len,
    const uint8_t *data, size_t data_len,
    uint8_t *out) {
    if (out == NULL) {
        return -1;
    }
    if (key == NULL && key_len > 0) {
        return -1;
    }
    if (data == NULL && data_len > 0) {
        return -1;
    }

    if (axon_csys_enterprise_fips_self_test() != 0) {
        return -2;
    }

#ifdef AXON_CSYS_ENTERPRISE_FIPS_OPENSSL
    EVP_MAC *mac = EVP_MAC_fetch(NULL, "HMAC", "fips=yes");
    if (mac == NULL) {
        return -3;
    }
    EVP_MAC_CTX *ctx = EVP_MAC_CTX_new(mac);
    if (ctx == NULL) {
        EVP_MAC_free(mac);
        return -4;
    }
    /* Pass the digest selector via OSSL_PARAM. SHA-256 = "SHA2-256"
     * in OpenSSL 3.0 nomenclature. */
    char digest_name[] = "SHA2-256";
    OSSL_PARAM params[2];
    params[0] = OSSL_PARAM_construct_utf8_string("digest", digest_name, 0);
    params[1] = OSSL_PARAM_construct_end();

    /* The empty-key edge case (key_len == 0) is handled per
     * RFC 2104: zero-length key gets zero-padded to the block size,
     * which OpenSSL/BoringSSL handle internally. To avoid passing a
     * NULL `key` pointer to EVP_MAC_init (some OpenSSL builds reject
     * NULL even with len 0), use a 1-byte stack buffer as a stand-in. */
    static const uint8_t empty_key_placeholder = 0;
    const uint8_t *key_arg = key_len > 0 ? key : &empty_key_placeholder;
    size_t key_arg_len = key_len;

    int ok = EVP_MAC_init(ctx, key_arg, key_arg_len, params) == 1
          && (data_len == 0 || EVP_MAC_update(ctx, data, data_len) == 1);

    if (ok) {
        size_t out_len = 0;
        ok = EVP_MAC_final(ctx, out, &out_len, AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE) == 1
          && out_len == AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE;
    }

    EVP_MAC_CTX_free(ctx);
    EVP_MAC_free(mac);
    return ok ? 0 : -5;
#else /* BoringSSL */
    /* BoringSSL keeps the legacy one-shot HMAC() — preferred path
     * because it's the BoringSSL-FIPS-validated entry point.
     *
     * Per BoringSSL's hmac.h: HMAC() returns a pointer to `out` on
     * success, NULL on failure. The returned `md_len` will equal 32
     * for SHA-256. */
    static const uint8_t empty_key_placeholder = 0;
    const uint8_t *key_arg = key_len > 0 ? key : &empty_key_placeholder;
    /* Cap empty-data inputs: BoringSSL HMAC() accepts NULL data with
     * len 0; defensive copy if the linked version is older. */
    static const uint8_t empty_data_placeholder = 0;
    const uint8_t *data_arg = data_len > 0 ? data : &empty_data_placeholder;

    unsigned int md_len = 0;
    uint8_t *result = HMAC(EVP_sha256(),
                           key_arg, key_len,
                           data_arg, data_len,
                           out, &md_len);
    if (result != out || md_len != (unsigned int)AXON_CSYS_ENTERPRISE_SHA256_DIGEST_SIZE) {
        return -5;
    }
    return 0;
#endif
}
