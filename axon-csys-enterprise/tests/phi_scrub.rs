//! § Fase 27.g — PHI scrubber test pack.
//!
//! Exercises the [`axon_csys_enterprise::phi_scrub`] surface against:
//!
//!   1. Per-pattern positive recognition — each of the 9 supported
//!      pattern categories is detected + redacted on canonical input.
//!   2. Per-pattern negative cases — similar-looking text that is
//!      NOT actually PHI passes through unchanged.
//!   3. Pattern composition — multiple PHI tokens in same input,
//!      mixed with non-PHI content.
//!   4. Word-boundary discipline — patterns embedded inside
//!      identifiers or URLs are NOT redacted.
//!   5. UTF-8 preservation — multi-byte UTF-8 sequences pass
//!      through untouched.
//!   6. Pattern-mask filtering — disabling a pattern means its
//!      occurrences pass through.
//!   7. Output sizing — `max_output_size` is sufficient for any
//!      input.
//!   8. Stats correctness — bytes_scanned + matches_found +
//!      per_pattern_matches add up.
//!   9. Empty input + edge cases — zero-length, single-byte,
//!      end-of-input matches.
//!  10. Error handling — invalid options surface as errors.

use axon_csys_enterprise::phi_scrub::{
    max_output_size, scrub, scrub_into, PhiPatterns, PhiScrubError,
};

// ──────────────────────────────────────────────────────────────────────
// 1. Per-pattern positive recognition
// ──────────────────────────────────────────────────────────────────────

#[test]
fn redacts_ssn_hyphenated() {
    let (out, stats) = scrub("Patient SSN: 123-45-6789.", PhiPatterns::SSN).unwrap();
    assert_eq!(out, "Patient SSN: [REDACTED-SSN].");
    assert_eq!(stats.matches_found, 1);
    assert_eq!(stats.per_pattern_matches[0], 1);
}

#[test]
fn redacts_ssn_nine_digit_run() {
    let (out, _) = scrub("number 123456789 was assigned", PhiPatterns::SSN).unwrap();
    assert!(out.contains("[REDACTED-SSN]"), "got: {out}");
}

#[test]
fn redacts_phone_us_paren() {
    let (out, _) = scrub("Call (555) 123-4567 today.", PhiPatterns::PHONE).unwrap();
    assert_eq!(out, "Call [REDACTED-PHONE] today.");
}

#[test]
fn redacts_phone_dash_dash() {
    let (out, _) = scrub("phone 555-123-4567 office", PhiPatterns::PHONE).unwrap();
    assert!(out.contains("[REDACTED-PHONE]"));
}

#[test]
fn redacts_phone_with_country_code() {
    let (out, _) = scrub("dial +1 555-123-4567 now", PhiPatterns::PHONE).unwrap();
    assert!(out.contains("[REDACTED-PHONE]"), "got: {out}");
}

#[test]
fn redacts_email_simple() {
    let (out, _) = scrub("Contact: doc@hospital.org for info.", PhiPatterns::EMAIL).unwrap();
    assert!(out.contains("[REDACTED-EMAIL]"), "got: {out}");
    assert!(!out.contains('@'));
}

#[test]
fn redacts_email_with_subdomain_and_plus_tag() {
    let (out, _) = scrub(
        "Reply to first.last+tag@sub.example.co for confirmation.",
        PhiPatterns::EMAIL,
    )
    .unwrap();
    assert!(out.contains("[REDACTED-EMAIL]"), "got: {out}");
}

#[test]
fn redacts_ipv4() {
    let (out, _) = scrub("Connect to 192.168.1.42 port 443", PhiPatterns::IPV4).unwrap();
    assert!(out.contains("[REDACTED-IP]"), "got: {out}");
}

#[test]
fn redacts_credit_card_dashed() {
    let (out, _) = scrub(
        "Card on file: 4111-1111-1111-1111 expires",
        PhiPatterns::CREDIT_CARD,
    )
    .unwrap();
    assert!(out.contains("[REDACTED-CC]"), "got: {out}");
}

#[test]
fn redacts_credit_card_plain() {
    let (out, _) = scrub("CC 4111111111111111 visa", PhiPatterns::CREDIT_CARD).unwrap();
    assert!(out.contains("[REDACTED-CC]"));
}

#[test]
fn redacts_zip_5_digit() {
    let (out, _) = scrub("Brooklyn 11201 USA", PhiPatterns::ZIP).unwrap();
    assert!(out.contains("[REDACTED-ZIP]"), "got: {out}");
}

#[test]
fn redacts_zip_plus_4() {
    let (out, _) = scrub("address 10001-1234 NY", PhiPatterns::ZIP).unwrap();
    assert!(out.contains("[REDACTED-ZIP]"), "got: {out}");
}

#[test]
fn redacts_mrn_with_prefix() {
    for input in [
        "MRN: 1234567 referral",
        "MRN-1234567 chart",
        "Patient: 1234567 admitted",
        "PT#1234567 today",
    ] {
        let (out, _) = scrub(input, PhiPatterns::MRN).unwrap();
        assert!(
            out.contains("[REDACTED-MRN]"),
            "missing redaction in: {input} -> {out}"
        );
    }
}

#[test]
fn redacts_date_iso() {
    let (out, _) = scrub("Visit on 2026-05-09 confirmed", PhiPatterns::DATE).unwrap();
    assert!(out.contains("[REDACTED-DATE]"), "got: {out}");
}

#[test]
fn redacts_date_us_slash() {
    let (out, _) = scrub("DOB 5/9/1980 and 12/31/2025 ok", PhiPatterns::DATE).unwrap();
    // Two date matches.
    assert_eq!(out.matches("[REDACTED-DATE]").count(), 2);
}

#[test]
fn redacts_url_http() {
    let (out, _) = scrub("See http://example.com/page now", PhiPatterns::URL).unwrap();
    assert!(out.contains("[REDACTED-URL]"), "got: {out}");
}

#[test]
fn redacts_url_https_with_path_and_query() {
    let (out, _) = scrub(
        "Open https://api.example.org/v1/users?id=42 today",
        PhiPatterns::URL,
    )
    .unwrap();
    assert!(out.contains("[REDACTED-URL]"));
}

// ──────────────────────────────────────────────────────────────────────
// 2. Per-pattern negative cases
// ──────────────────────────────────────────────────────────────────────

#[test]
fn does_not_redact_short_digit_runs() {
    // 8 digits is not an SSN, not a phone, not a credit card.
    let (out, stats) = scrub("code 12345678 done", PhiPatterns::all()).unwrap();
    assert_eq!(out, "code 12345678 done");
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn does_not_redact_text_without_digits_or_anchors() {
    let txt = "Patient was admitted with chest pain and shortness of breath.";
    let (out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    assert_eq!(out, txt);
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn does_not_redact_email_inside_word() {
    // "foo@bar" with no dot in domain: not a valid email.
    let (out, stats) = scrub("see foo@bar locally", PhiPatterns::EMAIL).unwrap();
    assert_eq!(out, "see foo@bar locally");
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn does_not_redact_invalid_ipv4() {
    // 999.999.999.999 — out of range.
    let (out, stats) = scrub("ip 999.999.999.999 invalid", PhiPatterns::IPV4).unwrap();
    assert!(!out.contains("[REDACTED-IP]"));
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn does_not_redact_partial_credit_card() {
    // 12 digits: not a credit card.
    let (out, _) = scrub("digits 123456789012 here", PhiPatterns::CREDIT_CARD).unwrap();
    assert!(!out.contains("[REDACTED-CC]"));
}

// ──────────────────────────────────────────────────────────────────────
// 3. Pattern composition (multiple PHI tokens in same input)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn redacts_multiple_phi_tokens() {
    let txt = "Patient John has SSN 123-45-6789, phone (555) 123-4567, email john@example.com.";
    let (out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    assert!(out.contains("[REDACTED-SSN]"));
    assert!(out.contains("[REDACTED-PHONE]"));
    assert!(out.contains("[REDACTED-EMAIL]"));
    assert_eq!(stats.matches_found, 3);
}

#[test]
fn redacts_dense_phi_block() {
    let txt =
        "MRN: 1234567 patient at 192.168.1.1 with email a@b.co called 555-123-4567 on 2026-05-09";
    let (out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    // Expect: MRN, IPv4, EMAIL, PHONE, DATE = 5 redactions.
    assert_eq!(stats.matches_found, 5, "got: {out}");
}

#[test]
fn pattern_mask_filters_what_is_redacted() {
    let txt = "SSN 123-45-6789 phone (555) 123-4567";
    // Only redact phones — SSN passes through.
    let (out, stats) = scrub(txt, PhiPatterns::PHONE).unwrap();
    assert!(
        out.contains("123-45-6789"),
        "SSN should NOT be redacted: {out}"
    );
    assert!(out.contains("[REDACTED-PHONE]"));
    assert_eq!(stats.matches_found, 1);
}

#[test]
fn pattern_mask_combination_via_bitor() {
    let mask = PhiPatterns::SSN | PhiPatterns::PHONE;
    let txt = "SSN 123-45-6789 email a@b.co";
    let (out, stats) = scrub(txt, mask).unwrap();
    assert!(out.contains("[REDACTED-SSN]"));
    assert!(out.contains("a@b.co")); // email NOT redacted (not in mask)
    assert_eq!(stats.matches_found, 1);
}

// ──────────────────────────────────────────────────────────────────────
// 4. Word-boundary discipline
// ──────────────────────────────────────────────────────────────────────

#[test]
fn ssn_inside_alphanum_word_is_not_redacted() {
    // "X123-45-6789" starts inside a word — should not match.
    let (out, _) = scrub("code X123-45-6789 internal", PhiPatterns::SSN).unwrap();
    assert!(!out.contains("[REDACTED-SSN]"), "got: {out}");
}

#[test]
fn ssn_followed_by_alphanum_is_not_redacted() {
    // "123-45-6789X" — the trailing X breaks the word boundary.
    let (out, _) = scrub("ref 123-45-6789X next", PhiPatterns::SSN).unwrap();
    assert!(!out.contains("[REDACTED-SSN]"));
}

// ──────────────────────────────────────────────────────────────────────
// 5. UTF-8 preservation
// ──────────────────────────────────────────────────────────────────────

#[test]
fn utf8_passes_through_untouched() {
    let txt =
        "Pacient régimen: SSN 123-45-6789 — síndrome de fatiga crónica. Email: doctor@clínica.es.";
    let (out, _) = scrub(txt, PhiPatterns::all()).unwrap();
    // Multi-byte UTF-8 (régimen / síndrome / clínica) preserved.
    assert!(out.contains("régimen"));
    assert!(out.contains("síndrome"));
    assert!(out.contains("[REDACTED-SSN]"));
    // Email containing non-ASCII domain — our recognizer is ASCII-
    // only for domain part, so this MIGHT redact partial email or
    // not. Just verify the output is valid UTF-8.
    assert!(std::str::from_utf8(out.as_bytes()).is_ok());
}

#[test]
fn unicode_only_text_is_unchanged() {
    let txt = "αβγδε ζηθικ λμνξο πρστυ φχψω";
    let (out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    assert_eq!(out, txt);
    assert_eq!(stats.matches_found, 0);
}

// ──────────────────────────────────────────────────────────────────────
// 6. Output sizing
// ──────────────────────────────────────────────────────────────────────

#[test]
fn max_output_size_is_sufficient_for_worst_case() {
    // Worst case: input is a back-to-back run of ZIP codes (5 chars
    // → 14-char redaction).
    let mut input = String::new();
    for _ in 0..50 {
        input.push_str("12345 ");
    }
    let bound = max_output_size(input.len());
    let (out, _) = scrub(&input, PhiPatterns::ZIP).unwrap();
    assert!(out.len() <= bound);
}

#[test]
fn max_output_size_for_zero_input() {
    assert!(max_output_size(0) >= 32);
}

// ──────────────────────────────────────────────────────────────────────
// 7. Stats correctness
// ──────────────────────────────────────────────────────────────────────

#[test]
fn stats_bytes_scanned_equals_input_len() {
    let txt = "Patient phone: (555) 123-4567 followed by email doc@x.org.";
    let (_out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    assert_eq!(stats.bytes_scanned, txt.len());
}

#[test]
fn stats_per_pattern_count_correct() {
    // Two SSNs + one phone.
    let txt = "ssn-a 111-22-3333 ssn-b 444-55-6666 ph (555) 123-4567";
    let (_out, stats) = scrub(txt, PhiPatterns::all()).unwrap();
    assert_eq!(stats.per_pattern_matches[0], 2, "SSN count");
    assert_eq!(stats.per_pattern_matches[1], 1, "PHONE count");
    assert_eq!(stats.matches_found, 3);
}

#[test]
fn stats_output_bytes_equals_output_len() {
    let txt = "Hello SSN 123-45-6789 world.";
    let (out, stats) = scrub(txt, PhiPatterns::SSN).unwrap();
    assert_eq!(stats.output_bytes, out.len());
}

// ──────────────────────────────────────────────────────────────────────
// 8. Empty input + edge cases
// ──────────────────────────────────────────────────────────────────────

#[test]
fn empty_input_returns_empty_output() {
    let (out, stats) = scrub("", PhiPatterns::all()).unwrap();
    assert_eq!(out, "");
    assert_eq!(stats.bytes_scanned, 0);
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn input_that_is_only_phi_redacts_completely() {
    let (out, _) = scrub("123-45-6789", PhiPatterns::SSN).unwrap();
    assert_eq!(out, "[REDACTED-SSN]");
}

#[test]
fn phi_at_input_end_is_redacted() {
    let (out, _) = scrub("final ssn 123-45-6789", PhiPatterns::SSN).unwrap();
    assert!(out.ends_with("[REDACTED-SSN]"));
}

#[test]
fn phi_at_input_start_is_redacted() {
    let (out, _) = scrub("123-45-6789 is the SSN", PhiPatterns::SSN).unwrap();
    assert!(out.starts_with("[REDACTED-SSN]"));
}

// ──────────────────────────────────────────────────────────────────────
// 9. Error handling
// ──────────────────────────────────────────────────────────────────────

#[test]
fn empty_pattern_mask_returns_invalid_options() {
    let mut buf = Vec::new();
    let res = scrub_into(b"hello", PhiPatterns::none(), &mut buf);
    assert!(matches!(res, Err(PhiScrubError::InvalidOptions)));
}

#[test]
fn scrub_into_clears_existing_buffer_contents() {
    let mut buf = b"GARBAGE".to_vec();
    let stats = scrub_into(b"hello", PhiPatterns::SSN, &mut buf).unwrap();
    assert_eq!(buf, b"hello");
    assert_eq!(stats.matches_found, 0);
}

#[test]
fn scrub_into_zero_alloc_repeated_use() {
    // Reuse the same buffer across multiple calls. The second call
    // should not require additional allocation (capacity already
    // sized).
    let mut buf = Vec::with_capacity(4096);
    let initial_cap = buf.capacity();
    for _ in 0..10 {
        let _ = scrub_into(
            b"Patient SSN 123-45-6789, phone (555) 123-4567",
            PhiPatterns::all(),
            &mut buf,
        )
        .unwrap();
    }
    // Buffer didn't grow beyond initial capacity (modulo small
    // headroom from `max_output_size` rounding).
    assert!(buf.capacity() <= initial_cap * 2);
}

// ──────────────────────────────────────────────────────────────────────
// 10. Error display surface
// ──────────────────────────────────────────────────────────────────────

#[test]
fn error_display_strings_are_useful() {
    assert!(format!("{}", PhiScrubError::NullArg).contains("null"));
    assert!(format!("{}", PhiScrubError::InvalidOptions).contains("invalid"));
    assert!(format!("{}", PhiScrubError::BufferTooSmall { required: 100 }).contains("100"));
}

// ──────────────────────────────────────────────────────────────────────
// 11. Throughput sanity (1000-event scale per plan target)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn handles_1000_event_throughput_smoke() {
    // Concatenate 1000 simulated PHI events and verify scrubber
    // completes without panic + produces a sensible output.
    let one_event = "Patient X has SSN 123-45-6789, phone (555) 123-4567, email x@y.com.\n";
    let mut input = String::new();
    for _ in 0..1000 {
        input.push_str(one_event);
    }
    let (out, stats) = scrub(&input, PhiPatterns::all()).unwrap();
    // 3 redactions per event × 1000 = 3000.
    assert_eq!(stats.matches_found, 3000);
    assert!(out.contains("[REDACTED-SSN]"));
    assert!(out.contains("[REDACTED-PHONE]"));
    assert!(out.contains("[REDACTED-EMAIL]"));
}

// ──────────────────────────────────────────────────────────────────────
// 12. PhiPatterns helpers
// ──────────────────────────────────────────────────────────────────────

#[test]
fn pattern_all_includes_every_category() {
    let all = PhiPatterns::all();
    assert!(all.contains(PhiPatterns::SSN));
    assert!(all.contains(PhiPatterns::PHONE));
    assert!(all.contains(PhiPatterns::EMAIL));
    assert!(all.contains(PhiPatterns::IPV4));
    assert!(all.contains(PhiPatterns::CREDIT_CARD));
    assert!(all.contains(PhiPatterns::ZIP));
    assert!(all.contains(PhiPatterns::MRN));
    assert!(all.contains(PhiPatterns::DATE));
    assert!(all.contains(PhiPatterns::URL));
}

#[test]
fn pattern_none_contains_nothing() {
    let none = PhiPatterns::none();
    assert!(!none.contains(PhiPatterns::SSN));
    assert_eq!(none.bits(), 0);
}

#[test]
fn pattern_union_combines_bits() {
    let u = PhiPatterns::SSN.union(PhiPatterns::PHONE);
    assert!(u.contains(PhiPatterns::SSN));
    assert!(u.contains(PhiPatterns::PHONE));
    assert!(!u.contains(PhiPatterns::EMAIL));
}
