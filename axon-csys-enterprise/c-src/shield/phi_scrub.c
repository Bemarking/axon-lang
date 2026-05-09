/* §Fase 27.g — PHI scrubber kernel (implementation).
 *
 * Single-pass byte walker. At each position, if the current byte is
 * a candidate "anchor" for one or more enabled patterns, run the
 * scalar verifier for those patterns; on a match, emit the redaction
 * marker + advance past the match; otherwise emit the byte and
 * advance one position.
 *
 * Anchor bytes per pattern (worst case for "interesting" set):
 *
 *   SSN          digit
 *   PHONE        digit, '('
 *   EMAIL        '@' (we backtrack to find the local-part start)
 *   IPV4         digit
 *   CREDIT_CARD  digit
 *   ZIP          digit
 *   MRN          'M', 'P' (case-insensitive prefix recognizers)
 *   DATE         digit
 *   URL          'h' (for http://, https://)
 *
 * The scanner walks left-to-right. When EMAIL pattern is enabled
 * and the current byte is '@', we look BACKWARDS to find the start
 * of the local-part — but we never emit redaction for bytes already
 * emitted. To handle this, the algorithm uses a one-pass buffered
 * scheme: instead of emitting bytes immediately, we maintain an
 * `emitted_up_to` cursor tracking the last byte safely committed to
 * output. When EMAIL '@' is detected, we look back from the current
 * position to find the local-part start; if it starts at position
 * `p_start < emitted_up_to`, we cannot redact (the bytes already
 * shipped). In practice, the local-part start is always within the
 * current "pending" window because non-email anchors (digits, etc.)
 * would have triggered their own verifiers earlier. v0.1.0
 * implementation: emit bytes through a one-byte-look-ahead buffer
 * that we hold until we know none of the patterns will pull it back.
 * Simpler design: scan at start position, dispatch based on byte
 * class, advance by match length on hit; for emails, recognize the
 * local-part FIRST (digit/letter run + dot/underscore) and enter
 * email recognition only after seeing '@'. So the recognizer for
 * email IS a left-to-right scan that triggers on local-part bytes
 * + lookahead for '@'.
 *
 * Match length policy: greedy (longest match wins per starting
 * position). Pattern priority on overlapping matches: SSN > CREDIT
 * > PHONE > IPV4 > DATE > ZIP. Email > URL (URL might contain '@').
 * MRN priority: high (specific prefix recognizes unambiguous).
 */

#include "phi_scrub.h"

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

/* ──────────────────────────────────────────────────────────────────
 * Replacement strings — fixed length, byte-deterministic across
 * regenerations. Short labels keep output size manageable.
 * ────────────────────────────────────────────────────────────────── */

static const char REDACT_SSN[]   = "[REDACTED-SSN]";
static const char REDACT_PHONE[] = "[REDACTED-PHONE]";
static const char REDACT_EMAIL[] = "[REDACTED-EMAIL]";
static const char REDACT_IPV4[]  = "[REDACTED-IP]";
static const char REDACT_CC[]    = "[REDACTED-CC]";
static const char REDACT_ZIP[]   = "[REDACTED-ZIP]";
static const char REDACT_MRN[]   = "[REDACTED-MRN]";
static const char REDACT_DATE[]  = "[REDACTED-DATE]";
static const char REDACT_URL[]   = "[REDACTED-URL]";

/* Pattern-bit-position index used into stats.per_pattern_matches[].
 * Must stay in lockstep with AXON_PHI_PATTERN_* in the header. */
enum {
    PIDX_SSN = 0,
    PIDX_PHONE = 1,
    PIDX_EMAIL = 2,
    PIDX_IPV4 = 3,
    PIDX_CC = 4,
    PIDX_ZIP = 5,
    PIDX_MRN = 6,
    PIDX_DATE = 7,
    PIDX_URL = 8,
};

/* ──────────────────────────────────────────────────────────────────
 * Character class predicates — branchless where it matters.
 * ────────────────────────────────────────────────────────────────── */

static inline bool is_digit(uint8_t c) {
    return c >= '0' && c <= '9';
}

static inline bool is_alpha(uint8_t c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

static inline bool is_alnum(uint8_t c) {
    return is_digit(c) || is_alpha(c);
}

/* "Word boundary" character: NOT alphanumeric and NOT '_'. Used to
 * anchor pattern start/end so partial matches inside identifiers
 * don't false-positive. The classical word-character class is
 * [A-Za-z0-9_] — anything else is a boundary. */
static inline bool is_wordlike(uint8_t c) {
    return is_alnum(c) || c == '_';
}

/* True if position `p` in `input[0..len]` is at a word boundary
 * (start of input, or preceded by non-word character). */
static inline bool at_word_start(const uint8_t *input, size_t p) {
    return p == 0 || !is_wordlike(input[p - 1]);
}

/* True if `input[end]` (or end-of-input) is a non-word character.
 * Caller ensures end <= len. */
static inline bool at_word_end(const uint8_t *input, size_t len, size_t end) {
    return end == len || !is_wordlike(input[end]);
}

/* Lowercase ASCII (for case-insensitive prefix match on MRN/URL). */
static inline uint8_t to_lower(uint8_t c) {
    return (c >= 'A' && c <= 'Z') ? (c + 32) : c;
}

/* ──────────────────────────────────────────────────────────────────
 * Per-pattern matchers. Each matcher inspects `input[p..len]` and
 * returns the match length on success (positive) or 0 on no match.
 *
 * Word boundaries are checked at the START by the caller. Each
 * matcher checks the END boundary itself (which is more
 * pattern-specific — e.g. an SSN may end at a hyphen which is the
 * start of an MRN, or at a period that ends a sentence).
 * ────────────────────────────────────────────────────────────────── */

/* SSN: XXX-XX-XXXX OR XXXXXXXXX (9 digits). Word-bounded.
 * Fails if all-zero (000-00-0000) per SSA's invalid-SSN rules.  */
static size_t match_ssn(const uint8_t *p, size_t avail) {
    /* Hyphenated form first. */
    if (avail >= 11
        && is_digit(p[0]) && is_digit(p[1]) && is_digit(p[2])
        && p[3] == '-'
        && is_digit(p[4]) && is_digit(p[5])
        && p[6] == '-'
        && is_digit(p[7]) && is_digit(p[8]) && is_digit(p[9]) && is_digit(p[10])) {
        return 11;
    }
    /* 9-digit run. */
    if (avail >= 9) {
        for (int i = 0; i < 9; ++i) {
            if (!is_digit(p[i])) return 0;
        }
        return 9;
    }
    return 0;
}

/* Credit card: 16 digits in groups of 4 with optional '-' or ' '
 * separators. Examples: "4111111111111111", "4111-1111-1111-1111",
 * "4111 1111 1111 1111". */
static size_t match_credit_card(const uint8_t *p, size_t avail) {
    /* Plain 16-digit run. */
    if (avail >= 16) {
        bool ok = true;
        for (int i = 0; i < 16; ++i) {
            if (!is_digit(p[i])) { ok = false; break; }
        }
        if (ok) return 16;
    }
    /* Separated form: 4-sep-4-sep-4-sep-4 = 19 bytes. */
    if (avail >= 19
        && is_digit(p[0]) && is_digit(p[1]) && is_digit(p[2]) && is_digit(p[3])
        && (p[4] == '-' || p[4] == ' ')
        && is_digit(p[5]) && is_digit(p[6]) && is_digit(p[7]) && is_digit(p[8])
        && p[9] == p[4]
        && is_digit(p[10]) && is_digit(p[11]) && is_digit(p[12]) && is_digit(p[13])
        && p[14] == p[4]
        && is_digit(p[15]) && is_digit(p[16]) && is_digit(p[17]) && is_digit(p[18])) {
        return 19;
    }
    return 0;
}

/* Phone (US/NAN): area code + 7-digit. Forms:
 *   "(XXX) XXX-XXXX"   = 14 (with optional space after `)`)
 *   "(XXX)XXX-XXXX"    = 13
 *   "XXX-XXX-XXXX"     = 12
 *   "XXX.XXX.XXXX"     = 12
 *   "XXX XXX XXXX"     = 12
 *   "+1 XXX-XXX-XXXX"  = 15 (country code variant — captured as
 *                            pure digits + separators)
 * Returns the longest match starting at p, or 0. */
static size_t match_phone(const uint8_t *p, size_t avail) {
    /* "(XXX) XXX-XXXX" or "(XXX)XXX-XXXX". */
    if (avail >= 13 && p[0] == '(' && is_digit(p[1]) && is_digit(p[2]) && is_digit(p[3])
        && p[4] == ')') {
        size_t pos = 5;
        if (pos < avail && p[pos] == ' ') pos += 1;
        if (pos + 8 <= avail
            && is_digit(p[pos]) && is_digit(p[pos + 1]) && is_digit(p[pos + 2])
            && (p[pos + 3] == '-' || p[pos + 3] == '.' || p[pos + 3] == ' ')
            && is_digit(p[pos + 4]) && is_digit(p[pos + 5])
            && is_digit(p[pos + 6]) && is_digit(p[pos + 7])) {
            return pos + 8;
        }
    }
    /* "+1 XXX-XXX-XXXX" — country code. */
    if (avail >= 15 && p[0] == '+' && p[1] == '1' && (p[2] == ' ' || p[2] == '-')) {
        size_t pos = 3;
        if (pos + 12 <= avail
            && is_digit(p[pos]) && is_digit(p[pos + 1]) && is_digit(p[pos + 2])
            && (p[pos + 3] == '-' || p[pos + 3] == '.' || p[pos + 3] == ' ')
            && is_digit(p[pos + 4]) && is_digit(p[pos + 5]) && is_digit(p[pos + 6])
            && p[pos + 7] == p[pos + 3]
            && is_digit(p[pos + 8]) && is_digit(p[pos + 9])
            && is_digit(p[pos + 10]) && is_digit(p[pos + 11])) {
            return pos + 12;
        }
    }
    /* "XXX-XXX-XXXX" / "XXX.XXX.XXXX" / "XXX XXX XXXX". */
    if (avail >= 12
        && is_digit(p[0]) && is_digit(p[1]) && is_digit(p[2])
        && (p[3] == '-' || p[3] == '.' || p[3] == ' ')
        && is_digit(p[4]) && is_digit(p[5]) && is_digit(p[6])
        && p[7] == p[3]
        && is_digit(p[8]) && is_digit(p[9]) && is_digit(p[10]) && is_digit(p[11])) {
        return 12;
    }
    return 0;
}

/* IPv4 dotted decimal — 4 octets each 0-255 separated by '.'. */
static size_t match_ipv4(const uint8_t *p, size_t avail) {
    size_t pos = 0;
    for (int oct = 0; oct < 4; ++oct) {
        size_t start = pos;
        uint32_t val = 0;
        int digits = 0;
        while (pos < avail && is_digit(p[pos]) && digits < 3) {
            val = val * 10 + (uint32_t)(p[pos] - '0');
            pos += 1;
            digits += 1;
        }
        if (digits == 0) return 0;
        if (val > 255) return 0;
        /* Reject leading-zero forms (e.g. "01") to avoid ambiguity
         * with octal interpretation in legacy ZIP-style apps. */
        if (digits > 1 && p[start] == '0') return 0;
        if (oct < 3) {
            if (pos >= avail || p[pos] != '.') return 0;
            pos += 1;
        }
    }
    return pos;
}

/* ZIP code: 5 digits, optionally followed by '-' + 4 digits. */
static size_t match_zip(const uint8_t *p, size_t avail) {
    if (avail < 5) return 0;
    for (int i = 0; i < 5; ++i) {
        if (!is_digit(p[i])) return 0;
    }
    /* ZIP+4 extension. */
    if (avail >= 10 && p[5] == '-'
        && is_digit(p[6]) && is_digit(p[7]) && is_digit(p[8]) && is_digit(p[9])) {
        return 10;
    }
    return 5;
}

/* Date — ISO YYYY-MM-DD or US-style M/D/YYYY or D-M-YYYY. */
static size_t match_date(const uint8_t *p, size_t avail) {
    /* ISO YYYY-MM-DD. */
    if (avail >= 10
        && is_digit(p[0]) && is_digit(p[1]) && is_digit(p[2]) && is_digit(p[3])
        && p[4] == '-'
        && is_digit(p[5]) && is_digit(p[6])
        && p[7] == '-'
        && is_digit(p[8]) && is_digit(p[9])) {
        return 10;
    }
    /* M/D/YYYY or MM/DD/YYYY (also '-' separator). */
    int m_digits = 0;
    while (m_digits < 2 && (size_t)m_digits < avail && is_digit(p[m_digits])) m_digits += 1;
    if (m_digits < 1 || m_digits > 2) return 0;
    if ((size_t)m_digits >= avail) return 0;
    uint8_t sep1 = p[m_digits];
    if (sep1 != '/' && sep1 != '-') return 0;
    size_t pos = (size_t)m_digits + 1;
    int d_digits = 0;
    while (d_digits < 2 && pos < avail && is_digit(p[pos])) {
        d_digits += 1;
        pos += 1;
    }
    if (d_digits < 1 || d_digits > 2) return 0;
    if (pos >= avail) return 0;
    if (p[pos] != sep1) return 0;
    pos += 1;
    int y_digits = 0;
    while (y_digits < 4 && pos < avail && is_digit(p[pos])) {
        y_digits += 1;
        pos += 1;
    }
    if (y_digits != 2 && y_digits != 4) return 0;
    return pos;
}

/* MRN: case-insensitive prefix "MRN", "PT", or "PATIENT" followed
 * by an optional separator and 6-10 digit run. */
static size_t match_mrn(const uint8_t *p, size_t avail) {
    /* "MRN" prefix. */
    size_t pos = 0;
    if (avail >= 3
        && to_lower(p[0]) == 'm' && to_lower(p[1]) == 'r' && to_lower(p[2]) == 'n') {
        pos = 3;
    } else if (avail >= 7
        && to_lower(p[0]) == 'p' && to_lower(p[1]) == 'a' && to_lower(p[2]) == 't'
        && to_lower(p[3]) == 'i' && to_lower(p[4]) == 'e' && to_lower(p[5]) == 'n'
        && to_lower(p[6]) == 't') {
        pos = 7;
    } else if (avail >= 3
        && to_lower(p[0]) == 'p' && to_lower(p[1]) == 't' && p[2] == '#') {
        pos = 3;
    } else {
        return 0;
    }
    /* Optional separator(s): ':', '#', '-', ' '. */
    while (pos < avail && (p[pos] == ':' || p[pos] == '#' || p[pos] == '-' || p[pos] == ' ')) {
        pos += 1;
        /* Cap the separator run at 2 chars to avoid runaway. */
        if (pos > 9) break;
    }
    /* 6-10 digit run. */
    size_t digit_start = pos;
    while (pos < avail && is_digit(p[pos]) && (pos - digit_start) < 10) {
        pos += 1;
    }
    if ((pos - digit_start) < 6) return 0;
    return pos;
}

/* URL: http:// or https:// up to next whitespace / closing bracket /
 * end-of-input. */
static size_t match_url(const uint8_t *p, size_t avail) {
    size_t pos = 0;
    if (avail >= 7
        && to_lower(p[0]) == 'h' && to_lower(p[1]) == 't' && to_lower(p[2]) == 't'
        && to_lower(p[3]) == 'p' && p[4] == ':' && p[5] == '/' && p[6] == '/') {
        pos = 7;
    } else if (avail >= 8
        && to_lower(p[0]) == 'h' && to_lower(p[1]) == 't' && to_lower(p[2]) == 't'
        && to_lower(p[3]) == 'p' && to_lower(p[4]) == 's'
        && p[5] == ':' && p[6] == '/' && p[7] == '/') {
        pos = 8;
    } else {
        return 0;
    }
    /* Walk forward until a stop character. URL must have at least
     * one non-stop byte after `//` to be a real URL. */
    size_t start_path = pos;
    while (pos < avail) {
        uint8_t c = p[pos];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r'
            || c == ')' || c == ']' || c == '<' || c == '>' || c == '"') {
            break;
        }
        pos += 1;
    }
    if (pos == start_path) return 0;
    /* Strip trailing punctuation that's typically a sentence
     * terminator, not part of the URL. */
    while (pos > start_path) {
        uint8_t c = p[pos - 1];
        if (c == '.' || c == ',' || c == ';' || c == ':' || c == '!' || c == '?') {
            pos -= 1;
        } else {
            break;
        }
    }
    return pos;
}

/* Email: local-part '@' domain. The walker triggers EMAIL when the
 * current byte is in [A-Za-z0-9._%+-] AND there's an '@' within the
 * next 64 bytes. We then validate the full local-part + domain. */
static size_t match_email(const uint8_t *p, size_t avail) {
    /* Local-part: 1+ of [A-Za-z0-9._%+-] */
    size_t pos = 0;
    size_t local_start = 0;
    while (pos < avail) {
        uint8_t c = p[pos];
        if (is_alnum(c) || c == '.' || c == '_' || c == '%' || c == '+' || c == '-') {
            pos += 1;
        } else {
            break;
        }
    }
    if (pos == local_start) return 0;
    /* '@' separator. */
    if (pos >= avail || p[pos] != '@') return 0;
    pos += 1;
    /* Domain: 1+ of [A-Za-z0-9.-], must contain at least one '.'. */
    size_t domain_start = pos;
    bool seen_dot = false;
    while (pos < avail) {
        uint8_t c = p[pos];
        if (is_alnum(c) || c == '-') {
            pos += 1;
        } else if (c == '.') {
            seen_dot = true;
            pos += 1;
        } else {
            break;
        }
    }
    if (pos == domain_start) return 0;
    if (!seen_dot) return 0;
    /* Domain must not end with '.' or '-'. Strip trailing if so. */
    while (pos > domain_start && (p[pos - 1] == '.' || p[pos - 1] == '-')) {
        pos -= 1;
    }
    /* Domain TLD must be at least 2 characters past the last dot. */
    size_t last_dot = pos;
    while (last_dot > domain_start && p[last_dot - 1] != '.') {
        last_dot -= 1;
    }
    if (last_dot == domain_start || (pos - last_dot) < 2) return 0;
    return pos;
}

/* ──────────────────────────────────────────────────────────────────
 * Replacement emit helper
 * ────────────────────────────────────────────────────────────────── */

typedef struct {
    uint8_t *out;
    size_t cap;
    size_t pos;
    bool overflow;
} OutBuf;

static void emit_byte(OutBuf *o, uint8_t b) {
    if (o->pos >= o->cap) { o->overflow = true; return; }
    o->out[o->pos++] = b;
}

static void emit_bytes(OutBuf *o, const uint8_t *src, size_t n) {
    if (o->pos + n > o->cap) { o->overflow = true; return; }
    memcpy(o->out + o->pos, src, n);
    o->pos += n;
}

static void emit_replacement(OutBuf *o, const char *s) {
    size_t n = strlen(s);
    emit_bytes(o, (const uint8_t *)s, n);
}

/* ──────────────────────────────────────────────────────────────────
 * Main scrubber — single-pass byte walker
 * ────────────────────────────────────────────────────────────────── */

size_t axon_phi_scrub_max_output_size(size_t input_len) {
    /* Worst case: every input byte triggers a redaction. Min match
     * length = 5 bytes (ZIP), max replacement = strlen("[REDACTED-PHONE]") = 16.
     * Bound = ceil(input_len * 16 / 5) + 32 safety margin. */
    if (input_len == 0) return 32;
    /* Avoid integer overflow on large inputs. */
    if (input_len > (SIZE_MAX - 32) / 4) return SIZE_MAX;
    return input_len * 4 + 32;
}

int axon_phi_scrub(
    const uint8_t *input, size_t len,
    uint8_t *output, size_t cap,
    size_t *out_len,
    AxonPhiScrubStats *out_stats,
    const AxonPhiScrubOptions *options) {
    if (output == NULL || out_len == NULL || options == NULL) {
        return AXON_PHI_NULL_ARG;
    }
    if (len > 0 && input == NULL) {
        return AXON_PHI_NULL_ARG;
    }
    uint32_t mask = options->pattern_mask;
    if (mask == 0 || (mask & ~AXON_PHI_PATTERN_ALL) != 0) {
        return AXON_PHI_INVALID_OPTIONS;
    }

    OutBuf ob = { .out = output, .cap = cap, .pos = 0, .overflow = false };
    AxonPhiScrubStats stats = {0};

    size_t i = 0;
    while (i < len) {
        uint8_t c = input[i];
        size_t avail = len - i;
        size_t match_len = 0;
        const char *replacement = NULL;
        int matched_pidx = -1;

        /* Pattern dispatch. Word-boundary check at start where
         * needed (digit-anchored patterns like SSN/PHONE/IPV4/CC/
         * ZIP/DATE).
         *
         * Priority order: most-specific first, so e.g. SSN "123-45-6789"
         * is recognized as SSN not as DATE "123-45-6789" (which
         * wouldn't parse as a date anyway). */

        if ((mask & AXON_PHI_PATTERN_EMAIL) && (is_alnum(c) || c == '_')) {
            size_t n = match_email(input + i, avail);
            if (n > 0 && at_word_start(input, i) && at_word_end(input, len, i + n)) {
                match_len = n; replacement = REDACT_EMAIL; matched_pidx = PIDX_EMAIL;
            }
        }

        if (match_len == 0 && (mask & AXON_PHI_PATTERN_URL)
            && (c == 'h' || c == 'H')) {
            size_t n = match_url(input + i, avail);
            if (n > 0 && at_word_start(input, i)) {
                match_len = n; replacement = REDACT_URL; matched_pidx = PIDX_URL;
            }
        }

        if (match_len == 0 && (mask & AXON_PHI_PATTERN_MRN)
            && (c == 'M' || c == 'm' || c == 'P' || c == 'p')) {
            size_t n = match_mrn(input + i, avail);
            if (n > 0 && at_word_start(input, i) && at_word_end(input, len, i + n)) {
                match_len = n; replacement = REDACT_MRN; matched_pidx = PIDX_MRN;
            }
        }

        if (match_len == 0 && (c == '+' || c == '(' || is_digit(c))
            && at_word_start(input, i)) {
            /* Phone with country code + parenthesized variant. */
            if (mask & AXON_PHI_PATTERN_PHONE) {
                size_t n = match_phone(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_PHONE; matched_pidx = PIDX_PHONE;
                }
            }
            if (match_len == 0 && (mask & AXON_PHI_PATTERN_SSN) && is_digit(c)) {
                size_t n = match_ssn(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_SSN; matched_pidx = PIDX_SSN;
                }
            }
            if (match_len == 0 && (mask & AXON_PHI_PATTERN_CREDIT_CARD) && is_digit(c)) {
                size_t n = match_credit_card(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_CC; matched_pidx = PIDX_CC;
                }
            }
            if (match_len == 0 && (mask & AXON_PHI_PATTERN_IPV4) && is_digit(c)) {
                size_t n = match_ipv4(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_IPV4; matched_pidx = PIDX_IPV4;
                }
            }
            if (match_len == 0 && (mask & AXON_PHI_PATTERN_DATE) && is_digit(c)) {
                size_t n = match_date(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_DATE; matched_pidx = PIDX_DATE;
                }
            }
            if (match_len == 0 && (mask & AXON_PHI_PATTERN_ZIP) && is_digit(c)) {
                size_t n = match_zip(input + i, avail);
                if (n > 0 && at_word_end(input, len, i + n)) {
                    match_len = n; replacement = REDACT_ZIP; matched_pidx = PIDX_ZIP;
                }
            }
        }

        if (match_len > 0 && replacement != NULL) {
            emit_replacement(&ob, replacement);
            stats.matches_found += 1;
            if (matched_pidx >= 0 && matched_pidx < 9) {
                stats.per_pattern_matches[matched_pidx] += 1;
            }
            i += match_len;
        } else {
            emit_byte(&ob, c);
            i += 1;
        }

        if (ob.overflow) {
            /* Compute required size + bail. We've consumed `i` bytes
             * of input; the remaining input could in worst case
             * triple in size after redaction. */
            size_t needed = ob.pos + (len - i) * 4 + 32;
            *out_len = needed;
            return AXON_PHI_BUFFER_TOO_SMALL;
        }
    }

    *out_len = ob.pos;
    stats.bytes_scanned = len;
    stats.output_bytes = ob.pos;
    if (out_stats != NULL) {
        *out_stats = stats;
    }
    return AXON_PHI_OK;
}
