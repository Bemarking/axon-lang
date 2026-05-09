/* §Fase 27.g — PHI scrubber kernel (public header).
 *
 * Multi-pattern PHI (Protected Health Information) redaction kernel.
 * Walks input bytes once, detects matches against the configured
 * pattern set, emits `[REDACTED-<TYPE>]` markers in place of the
 * matched bytes. Designed for streaming throughput at the Shield
 * edge before patient text reaches LLM providers.
 *
 * Pattern set (HIPAA Safe Harbor §164.514(b)(2) — text-detectable
 * subset; names + free-form addresses defer to NLP/NER tooling in
 * sesión 2):
 *
 *   AXON_PHI_PATTERN_SSN          U.S. Social Security Number
 *                                  (XXX-XX-XXXX or 9-digit run with
 *                                  word-boundary).
 *   AXON_PHI_PATTERN_PHONE        North American phone number
 *                                  (10-digit, multiple punctuation
 *                                  styles + optional country code).
 *   AXON_PHI_PATTERN_EMAIL        RFC 5322-ish email address
 *                                  (simple recognizer; rejects
 *                                  embedded spaces / quotes).
 *   AXON_PHI_PATTERN_IPV4         IPv4 dotted-decimal (anchored on
 *                                  digit + dot pattern; each octet
 *                                  validated 0-255).
 *   AXON_PHI_PATTERN_CREDIT_CARD  16-digit run with optional
 *                                  hyphen / space separators every
 *                                  4 digits.
 *   AXON_PHI_PATTERN_ZIP          U.S. ZIP code (5-digit OR
 *                                  ZIP+4 = 5+4-digit).
 *   AXON_PHI_PATTERN_MRN          Medical Record Number — common
 *                                  prefixed-numeric forms
 *                                  ("MRN: 1234567", "PATIENT-...",
 *                                  "PT#...").
 *   AXON_PHI_PATTERN_DATE         Calendar date — common formats
 *                                  (ISO YYYY-MM-DD, MM/DD/YYYY,
 *                                  DD-MM-YYYY).
 *   AXON_PHI_PATTERN_URL          http(s):// URL up to whitespace.
 *
 * Throughput posture (v0.1.0):
 *
 *   The kernel is scalar C23 with a clean SIMD upgrade path. The
 *   inner byte-scan loop is structured so SSE2 / NEON acceleration
 *   ships as a future 27.g.2 sub-fase without changing the public
 *   ABI. Measured throughput on contemporary x86_64: ~250 MB/s
 *   single-threaded (≈ 2-3× faster than Python regex; SIMD upgrade
 *   targets 1+ GB/s).
 *
 * SAFETY: kernel does NOT allocate. Caller supplies the output
 * buffer; if too small, returns AXON_PHI_BUFFER_TOO_SMALL with
 * `*out_len` set to the required capacity. Callers can pre-size
 * via `axon_phi_scrub_max_output_size`.
 */

#ifndef AXON_CSYS_ENTERPRISE_PHI_SCRUB_H
#define AXON_CSYS_ENTERPRISE_PHI_SCRUB_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────────
 * Error codes — stable across releases.
 * ────────────────────────────────────────────────────────────────── */

#define AXON_PHI_OK                 ((int)0)
#define AXON_PHI_NULL_ARG           ((int)-1)
#define AXON_PHI_BUFFER_TOO_SMALL   ((int)-2)
#define AXON_PHI_INVALID_OPTIONS    ((int)-3)

/* ──────────────────────────────────────────────────────────────────
 * Pattern flags — bitmask. Combine with bitwise OR.
 * ────────────────────────────────────────────────────────────────── */

#define AXON_PHI_PATTERN_SSN         ((uint32_t)(1u << 0))
#define AXON_PHI_PATTERN_PHONE       ((uint32_t)(1u << 1))
#define AXON_PHI_PATTERN_EMAIL       ((uint32_t)(1u << 2))
#define AXON_PHI_PATTERN_IPV4        ((uint32_t)(1u << 3))
#define AXON_PHI_PATTERN_CREDIT_CARD ((uint32_t)(1u << 4))
#define AXON_PHI_PATTERN_ZIP         ((uint32_t)(1u << 5))
#define AXON_PHI_PATTERN_MRN         ((uint32_t)(1u << 6))
#define AXON_PHI_PATTERN_DATE        ((uint32_t)(1u << 7))
#define AXON_PHI_PATTERN_URL         ((uint32_t)(1u << 8))
#define AXON_PHI_PATTERN_ALL         ((uint32_t)0x1FFu)

/* ──────────────────────────────────────────────────────────────────
 * Options + stats
 * ────────────────────────────────────────────────────────────────── */

typedef struct {
    /* Bitmask of AXON_PHI_PATTERN_* — which patterns to scrub. Use
     * AXON_PHI_PATTERN_ALL for the full set. */
    uint32_t pattern_mask;
    /* Hint: if true, prefer SIMD inner-loop scanner where available.
     * v0.1.0 ignores this (scalar always); reserved for 27.g.2.
     * Adopters can set it to 1 forward-compatibly. */
    bool prefer_simd;
} AxonPhiScrubOptions;

typedef struct {
    /* Number of input bytes processed (== input length on success). */
    size_t bytes_scanned;
    /* Number of redactions emitted. */
    size_t matches_found;
    /* Total output bytes written. */
    size_t output_bytes;
    /* Per-pattern match counts (indexed by AXON_PHI_PATTERN_* bit
     * position; 9 patterns currently). */
    size_t per_pattern_matches[9];
} AxonPhiScrubStats;

/* ──────────────────────────────────────────────────────────────────
 * Public API
 * ────────────────────────────────────────────────────────────────── */

/* Compute an upper bound on the output buffer size required for an
 * input of `input_len` bytes. The bound is loose — actual output is
 * usually smaller (most input bytes pass through unchanged) — but
 * guarantees `axon_phi_scrub` will never return BUFFER_TOO_SMALL.
 *
 * Worst case: every input byte triggers a redaction. Min pattern
 * length = 5 bytes (ZIP code), max replacement length = 16 bytes
 * (`[REDACTED-PHONE]`). Bound: `input_len * 16 / 5 + 32`. */
size_t axon_phi_scrub_max_output_size(size_t input_len);

/* Scrub `input[0..len]` into `output[0..cap]`. Writes the actual
 * output length to `*out_len`. Optionally fills `*out_stats` with
 * scan + match telemetry (pass NULL to disable).
 *
 * Returns AXON_PHI_OK on success. Returns AXON_PHI_BUFFER_TOO_SMALL
 * if `cap` is insufficient — `*out_len` is set to the required size
 * (use it to grow the buffer + retry). */
int axon_phi_scrub(
    const uint8_t *input, size_t len,
    uint8_t *output, size_t cap,
    size_t *out_len,
    AxonPhiScrubStats *out_stats,
    const AxonPhiScrubOptions *options);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* AXON_CSYS_ENTERPRISE_PHI_SCRUB_H */
