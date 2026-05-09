//! § Fase 27.c — FIPS-validated crypto link test pack.
//!
//! Exercises the [`axon_csys_enterprise::crypto`] surface against:
//!   1. Canonical NIST CAVS-style reference vectors (SHA-256 from
//!      FIPS 180-4 §B.1/§B.2 + RFC 4231 HMAC test cases) — D10
//!      ratified.
//!   2. Drift-gate parity vs OSS axon-csys 0.1.x. Even on the no-fips
//!      passthrough this is non-trivial coverage because it pins
//!      the wire format byte-identity guarantee (D7 ratified).
//!   3. Streaming-vs-one-shot equivalence on both SHA-256 and HMAC.
//!   4. Backend identification (FipsBackend enum + backend_label
//!      free function consistency).
//!   5. ContinuityWire round-trip + tamper detection + payload edge
//!      cases (forbidden 0x1e byte in session_id, malformed wire).
//!   6. Cross-validation vs `sha2::Sha256` + `hmac::Hmac<Sha256>` —
//!      independently-implemented Rust crypto crates not derived from
//!      the same C source. Catches the case where both axon-csys and
//!      axon-csys-enterprise ship the same bug from a shared base.
//!   7. Deterministic-seeded fuzz parity vs OSS axon-csys (100
//!      iterations per primitive, deterministic RNG so failures
//!      reproduce on every CI run).
//!
//! On a no-fips build (default), these tests run against the OSS
//! pure-C path. On a `fips-boringssl` or `fips-openssl` build with
//! a prebuilt FIPS lib supplied via env var, they run against the
//! FIPS-routed path. The pass-criterion is identical in both regimes
//! — that's the core "FIPS-validated link is byte-identical" claim.

#![allow(clippy::needless_range_loop)]

use axon_csys_enterprise::crypto::{
    backend_label, fips_self_test, hex_encode, hmac_sha256, sha256, ContinuityWire,
    ContinuityWireError, HmacSha256, Sha256, SHA256_BLOCK_SIZE, SHA256_DIGEST_SIZE,
};
use axon_csys_enterprise::FipsBackend;

// Reference Rust impls — independently-implemented. If our C routes
// to a buggy lib we'd still catch it here.
use hmac::{Hmac, Mac as _};
use sha2::Digest as _;

mod cavs;

// ──────────────────────────────────────────────────────────────────────
// 1. NIST CAVS-style reference vectors (SHA-256)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn sha256_canonical_vectors() {
    for v in cavs::SHA256_VECTORS {
        let expected = cavs::decode_hex32(v.digest);
        let got = sha256(v.msg);
        assert_eq!(
            got,
            expected,
            "SHA-256 mismatch on `{}`: got {} expected {}",
            v.label,
            hex_encode(&got),
            v.digest
        );
    }
}

#[test]
fn sha256_canonical_vectors_via_streaming() {
    // Streaming SHA-256 must produce the same digest as one-shot
    // for every reference input. This pins both the FIPS-routed
    // streaming buffer accumulator AND the OSS streaming kernel.
    for v in cavs::SHA256_VECTORS {
        let expected = cavs::decode_hex32(v.digest);
        let mut hasher = Sha256::new();
        hasher.update(v.msg);
        let got = hasher.finalize();
        assert_eq!(got, expected, "Sha256 streaming mismatch on `{}`", v.label);
    }
}

#[test]
fn sha256_streaming_split_reassembles_to_one_shot() {
    // A 200-byte input split at every byte-boundary boundary should
    // produce the same digest as one-shot.
    let input: Vec<u8> = (0..200u16).map(|i| (i & 0xff) as u8).collect();
    let expected = sha256(&input);

    for split in [0usize, 1, 31, 32, 33, 63, 64, 65, 100, 199, 200] {
        let mut hasher = Sha256::new();
        hasher.update(&input[..split]);
        hasher.update(&input[split..]);
        let got = hasher.finalize();
        assert_eq!(got, expected, "split at {split} drifted");
    }
}

#[test]
fn sha256_constants_match_published_sizes() {
    assert_eq!(
        SHA256_DIGEST_SIZE, 32,
        "FIPS 180-4 SHA-256 digest = 256 bits = 32 bytes"
    );
    assert_eq!(
        SHA256_BLOCK_SIZE, 64,
        "FIPS 180-4 SHA-256 block = 512 bits = 64 bytes"
    );
}

// ──────────────────────────────────────────────────────────────────────
// 2. NIST CAVS-style reference vectors (HMAC-SHA256)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn hmac_sha256_canonical_vectors() {
    for v in cavs::HMAC_SHA256_VECTORS {
        let expected = cavs::decode_hex32(v.mac);
        let got = hmac_sha256(v.key, v.data);
        assert_eq!(
            got,
            expected,
            "HMAC-SHA256 mismatch on `{}`: got {} expected {}",
            v.label,
            hex_encode(&got),
            v.mac
        );
    }
}

#[test]
fn hmac_sha256_canonical_vectors_via_streaming() {
    for v in cavs::HMAC_SHA256_VECTORS {
        let expected = cavs::decode_hex32(v.mac);
        let mut mac = HmacSha256::new(v.key);
        mac.update(v.data);
        let got = mac.finalize();
        assert_eq!(
            got, expected,
            "HmacSha256 streaming mismatch on `{}`",
            v.label
        );
    }
}

#[test]
fn hmac_sha256_streaming_split_reassembles_to_one_shot() {
    let key = b"key-rotation-test-2026-05-09";
    let data: Vec<u8> = (0..300u16).map(|i| (i & 0xff) as u8).collect();
    let expected = hmac_sha256(key, &data);

    for split in [0usize, 1, 31, 32, 33, 63, 64, 65, 100, 200, 299, 300] {
        let mut mac = HmacSha256::new(key);
        mac.update(&data[..split]);
        mac.update(&data[split..]);
        let got = mac.finalize();
        assert_eq!(got, expected, "HMAC split at {split} drifted");
    }
}

#[test]
fn hmac_sha256_empty_inputs() {
    // Edge case: empty key, empty data. RFC 2104 + FIPS 198-1 both
    // permit zero-length inputs; the key gets zero-padded to the
    // block size; the data is hashed as-is.
    let mac_empty_key = hmac_sha256(b"", b"data");
    let mac_empty_data = hmac_sha256(b"key", b"");
    let mac_both_empty = hmac_sha256(b"", b"");

    // Cross-validation against a separate Rust impl. SimpleHmac is
    // generic over digests; we instantiate over sha2::Sha256 for
    // FIPS 198-1 conformance.
    let reference = |k: &[u8], d: &[u8]| -> [u8; 32] {
        let mut mac =
            Hmac::<sha2::Sha256>::new_from_slice(k).expect("SimpleHmac accepts any key length");
        mac.update(d);
        let out = mac.finalize().into_bytes();
        let mut arr = [0u8; 32];
        arr.copy_from_slice(&out);
        arr
    };

    assert_eq!(mac_empty_key, reference(b"", b"data"));
    assert_eq!(mac_empty_data, reference(b"key", b""));
    assert_eq!(mac_both_empty, reference(b"", b""));
}

#[test]
fn hmac_sha256_long_key_compression() {
    // RFC 2104 §2: keys longer than the block size are first
    // compressed via SHA-256 to derive the actual MAC key. Verify
    // by computing both paths and asserting they produce the same MAC.
    let oversized_key = vec![0x42u8; 200]; // 200 > 64 (block size)
    let data = b"the data to MAC";

    let direct = hmac_sha256(&oversized_key, data);

    // Manually pre-compress the key per RFC 2104.
    let compressed_key = sha256(&oversized_key);
    let compressed_then_macd = hmac_sha256(&compressed_key, data);

    assert_eq!(
        direct, compressed_then_macd,
        "HMAC long-key auto-compression deviates from RFC 2104 §2"
    );
}

// ──────────────────────────────────────────────────────────────────────
// 3. Drift-gate parity vs OSS axon-csys + reference Rust impls
// ──────────────────────────────────────────────────────────────────────

#[test]
fn sha256_drift_gate_vs_oss_axon_csys() {
    // For every CAVS vector, both the local crypto path AND the OSS
    // axon-csys path must produce the same bytes. On a no-fips
    // build these are the same path; on a FIPS build they are
    // distinct paths that MUST converge byte-for-byte (D7).
    for v in cavs::SHA256_VECTORS {
        let local = sha256(v.msg);
        let oss = axon_csys::sha256(v.msg);
        assert_eq!(
            local, oss,
            "SHA-256 drift gate failed on `{}`: local backend={} but OSS pure-C produced different bytes",
            v.label,
            backend_label(),
        );
    }
}

#[test]
fn sha256_drift_gate_vs_sha2_crate() {
    // Independent reference impl — sha2 is RustCrypto's pure-Rust
    // SHA-256. If our C lib is buggy we catch it here.
    for v in cavs::SHA256_VECTORS {
        let local = sha256(v.msg);
        let mut hasher = sha2::Sha256::new();
        hasher.update(v.msg);
        let reference = hasher.finalize();
        assert_eq!(
            local.as_slice(),
            reference.as_slice(),
            "SHA-256 drift gate vs sha2 crate failed on `{}`",
            v.label
        );
    }
}

#[test]
fn hmac_sha256_drift_gate_vs_oss_axon_csys() {
    for v in cavs::HMAC_SHA256_VECTORS {
        let local = hmac_sha256(v.key, v.data);
        let oss = axon_csys::hmac_sha256(v.key, v.data);
        assert_eq!(
            local, oss,
            "HMAC-SHA256 drift gate failed on `{}`: local backend={} but OSS pure-C produced different bytes",
            v.label,
            backend_label(),
        );
    }
}

#[test]
fn hmac_sha256_drift_gate_vs_hmac_crate() {
    for v in cavs::HMAC_SHA256_VECTORS {
        let local = hmac_sha256(v.key, v.data);
        let mut mac =
            Hmac::<sha2::Sha256>::new_from_slice(v.key).expect("SimpleHmac accepts any key length");
        mac.update(v.data);
        let reference = mac.finalize().into_bytes();
        assert_eq!(
            local.as_slice(),
            reference.as_slice(),
            "HMAC-SHA256 drift gate vs hmac crate failed on `{}`",
            v.label
        );
    }
}

// ──────────────────────────────────────────────────────────────────────
// 4. Deterministic-seeded fuzz drift gate (100 iterations per primitive)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn sha256_fuzz_drift_gate_100_iter() {
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};

    // Deterministic seed — failures reproduce verbatim on every CI run.
    let mut rng = StdRng::seed_from_u64(0x4178_4f4e_2043_5953); // "AXON CYS"

    for iter in 0..100 {
        let len = rng.random_range(0..=512);
        let mut input = vec![0u8; len];
        rng.fill(&mut input[..]);

        let local = sha256(&input);
        let oss = axon_csys::sha256(&input);
        let reference = {
            let mut h = sha2::Sha256::new();
            h.update(&input);
            let out = h.finalize();
            let mut arr = [0u8; 32];
            arr.copy_from_slice(&out);
            arr
        };

        assert_eq!(local, oss, "fuzz iter {iter}: local vs OSS");
        assert_eq!(local, reference, "fuzz iter {iter}: local vs sha2");
    }
}

#[test]
fn hmac_sha256_fuzz_drift_gate_100_iter() {
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};

    let mut rng = StdRng::seed_from_u64(0x484d_4143_4453_4843); // "HMACDSHC"

    for iter in 0..100 {
        let key_len = rng.random_range(0..=200);
        let data_len = rng.random_range(0..=512);
        let mut key = vec![0u8; key_len];
        let mut data = vec![0u8; data_len];
        rng.fill(&mut key[..]);
        rng.fill(&mut data[..]);

        let local = hmac_sha256(&key, &data);
        let oss = axon_csys::hmac_sha256(&key, &data);
        let reference = {
            let mut mac = Hmac::<sha2::Sha256>::new_from_slice(&key)
                .expect("SimpleHmac accepts any key length");
            mac.update(&data);
            let out = mac.finalize().into_bytes();
            let mut arr = [0u8; 32];
            arr.copy_from_slice(&out);
            arr
        };

        assert_eq!(local, oss, "fuzz iter {iter}: local vs OSS");
        assert_eq!(local, reference, "fuzz iter {iter}: local vs hmac");
    }
}

// ──────────────────────────────────────────────────────────────────────
// 5. Backend identification + label consistency
// ──────────────────────────────────────────────────────────────────────

#[test]
fn backend_label_consistent_across_surfaces() {
    // FipsBackend::current().label() and crypto::backend_label()
    // must agree. The audit log emits one of them; if they disagree
    // historical events become un-replayable.
    let enum_label = FipsBackend::current().label();
    let free_fn_label = backend_label();
    assert_eq!(
        enum_label, free_fn_label,
        "FipsBackend::label() and crypto::backend_label() disagree"
    );
}

#[test]
fn backend_label_is_in_known_set() {
    // The label MUST be one of the three documented values. A
    // refactor that introduces a new backend should be flagged here
    // so the audit-log emission stays parseable.
    let label = backend_label();
    assert!(
        matches!(
            label,
            "axon-csys-oss-pure-c" | "boringssl-fips" | "openssl-fips"
        ),
        "Unknown backend label: {label}"
    );
}

#[test]
fn backend_label_matches_active_features() {
    let label = backend_label();
    if cfg!(feature = "fips-boringssl") {
        assert_eq!(label, "boringssl-fips");
    } else if cfg!(feature = "fips-openssl") {
        assert_eq!(label, "openssl-fips");
    } else {
        assert_eq!(label, "axon-csys-oss-pure-c");
    }
}

#[test]
fn fips_self_test_succeeds_on_no_fips_path() {
    // On the OSS pure-C path, fips_self_test() is a no-op stub that
    // always returns Ok. On a FIPS build, the underlying lib's POST
    // runs; failures here are CMVP gate violations.
    let result = fips_self_test();
    assert!(
        result.is_ok(),
        "fips_self_test failed (rc={result:?}); on no-fips this is a stub bug, on FIPS this is a CMVP violation"
    );
}

#[test]
fn fips_self_test_idempotent() {
    // Calling fips_self_test() multiple times must always return Ok
    // — the FIPS lib caches the POST result internally; the OSS
    // stub returns Ok unconditionally.
    for _ in 0..5 {
        assert!(fips_self_test().is_ok());
    }
}

// ──────────────────────────────────────────────────────────────────────
// 6. ContinuityWire — round-trip + tamper detection + edge cases
// ──────────────────────────────────────────────────────────────────────

#[test]
fn continuity_wire_round_trip() {
    let key = b"continuity-key-v1";
    let session_id = "session-2026-05-09-axon";
    let expiry_ms: i64 = 1_810_000_000_000;

    let wire = ContinuityWire::sign(key, session_id, expiry_ms)
        .expect("sign should succeed on canonical inputs");
    let (got_session, got_expiry) =
        ContinuityWire::verify(key, &wire).expect("verify should succeed on round-trip");

    assert_eq!(got_session, session_id);
    assert_eq!(got_expiry, expiry_ms);
}

#[test]
fn continuity_wire_byte_identity_with_oss_axon_csys() {
    // The wire format MUST be bit-for-bit compatible with OSS
    // axon-csys 0.1.x — that's the D7 ratified contract.
    let key = b"shared-key-byte-identity-test";
    let session_id = "byte-identity-session";
    let expiry_ms: i64 = 1_799_999_999_999;

    let ours = ContinuityWire::sign(key, session_id, expiry_ms).expect("our sign should succeed");
    let theirs = axon_csys::ContinuityWire::sign(key, session_id, expiry_ms)
        .expect("OSS sign should succeed");

    assert_eq!(
        ours, theirs,
        "ContinuityWire byte-identity broken: drift gate failed on key-len={} session-len={} expiry={}",
        key.len(),
        session_id.len(),
        expiry_ms
    );
}

#[test]
fn continuity_wire_cross_verify_with_oss() {
    // A token signed by OSS verifies under our impl, and vice versa.
    // This is the deployment-mixing guarantee.
    let key = b"cross-verify-key";
    let session_id = "cross-verify-session";
    let expiry_ms: i64 = 1_700_000_000_000;

    let oss_wire = axon_csys::ContinuityWire::sign(key, session_id, expiry_ms).unwrap();
    let (our_session, our_expiry) =
        ContinuityWire::verify(key, &oss_wire).expect("our verify should accept OSS-signed wire");
    assert_eq!(our_session, session_id);
    assert_eq!(our_expiry, expiry_ms);

    let our_wire = ContinuityWire::sign(key, session_id, expiry_ms).unwrap();
    let (oss_session, oss_expiry) = axon_csys::ContinuityWire::verify(key, &our_wire)
        .expect("OSS verify should accept our wire");
    assert_eq!(oss_session, session_id);
    assert_eq!(oss_expiry, expiry_ms);
}

#[test]
fn continuity_wire_rejects_tampered_mac() {
    let key = b"tamper-test-key";
    let session_id = "victim-session";
    let expiry_ms: i64 = 1_700_000_000_000;

    let wire = ContinuityWire::sign(key, session_id, expiry_ms).unwrap();

    // Flip a bit in the wire — the resulting MAC won't validate.
    // The wire is base64url, so flipping any character changes the
    // payload. Do it deterministically.
    let mut bytes = wire.into_bytes();
    let last = bytes.len() - 1;
    bytes[last] = if bytes[last] == b'A' { b'B' } else { b'A' };
    let tampered = String::from_utf8(bytes).unwrap();

    let res = ContinuityWire::verify(key, &tampered);
    assert!(
        matches!(
            res,
            Err(ContinuityWireError::ForgedOrRotated)
                | Err(ContinuityWireError::BadHex)
                | Err(ContinuityWireError::BadFieldCount)
                | Err(ContinuityWireError::BadBase64)
        ),
        "Tampered wire was accepted (or returned wrong error type): {res:?}"
    );
}

#[test]
fn continuity_wire_rejects_wrong_key() {
    let key1 = b"key-one";
    let key2 = b"key-two-different";
    let session_id = "session";
    let expiry_ms: i64 = 1_700_000_000_000;

    let wire = ContinuityWire::sign(key1, session_id, expiry_ms).unwrap();
    let res = ContinuityWire::verify(key2, &wire);
    assert!(
        matches!(res, Err(ContinuityWireError::ForgedOrRotated)),
        "Wrong-key verify did not return ForgedOrRotated: {res:?}"
    );
}

#[test]
fn continuity_wire_rejects_session_id_with_separator() {
    // 0x1e is the wire field separator and must not appear in the
    // session_id payload (per the OSS surface — verified at sign
    // time).
    let key = b"key";
    let bad_session = "session\x1ewith-separator";
    let expiry_ms: i64 = 1_700_000_000_000;

    let res = ContinuityWire::sign(key, bad_session, expiry_ms);
    assert!(
        matches!(res, Err(ContinuityWireError::PayloadTooLarge)),
        "session_id with embedded 0x1e was accepted: {res:?}"
    );
}

#[test]
fn continuity_wire_rejects_malformed_base64() {
    let key = b"key";
    // base64url alphabet is [A-Za-z0-9_-]; '?' is outside the
    // alphabet and decode must fail.
    let res = ContinuityWire::verify(key, "this!is?not%base64url");
    assert!(
        matches!(res, Err(ContinuityWireError::BadBase64)),
        "Malformed base64 was not flagged: {res:?}"
    );
}

#[test]
fn continuity_wire_round_trip_negative_expiry() {
    // i64 expiries can be negative (e.g. far in the past for
    // testing). The wire format encodes the i64 in base-10 ASCII
    // including the minus sign — verify the round-trip still works.
    let key = b"negative-expiry-key";
    let session_id = "session-id";
    let expiry_ms: i64 = -1_000_000_000;

    let wire = ContinuityWire::sign(key, session_id, expiry_ms).unwrap();
    let (got_session, got_expiry) = ContinuityWire::verify(key, &wire).unwrap();
    assert_eq!(got_session, session_id);
    assert_eq!(got_expiry, expiry_ms);
}

#[test]
fn continuity_wire_round_trip_extreme_expiry_bounds() {
    let key = b"extreme-bounds-key";
    let session_id = "session";

    for expiry_ms in [i64::MIN, 0, 1, i64::MAX, i64::MIN + 1, i64::MAX - 1] {
        let wire = ContinuityWire::sign(key, session_id, expiry_ms)
            .unwrap_or_else(|_| panic!("sign failed at expiry={expiry_ms}"));
        let (got_session, got_expiry) = ContinuityWire::verify(key, &wire).unwrap();
        assert_eq!(got_session, session_id);
        assert_eq!(got_expiry, expiry_ms);
    }
}

#[test]
fn continuity_wire_session_id_with_unicode() {
    // session_id is a &str; UTF-8 multi-byte sequences must round-trip
    // without corruption.
    let key = b"unicode-key";
    let session_id = "sesión-de-2026-axón-üñïçødé-Ω≈ç√∫";
    let expiry_ms: i64 = 1_700_000_000_000;

    let wire = ContinuityWire::sign(key, session_id, expiry_ms).unwrap();
    let (got_session, got_expiry) = ContinuityWire::verify(key, &wire).unwrap();
    assert_eq!(got_session, session_id);
    assert_eq!(got_expiry, expiry_ms);
}

#[test]
fn continuity_wire_empty_session_id() {
    // Per OSS contract: empty session_id is a valid degenerate
    // payload (HMAC over "0x1e<expiry>"). The wire still round-trips.
    let key = b"empty-session-key";
    let expiry_ms: i64 = 42;

    let wire = ContinuityWire::sign(key, "", expiry_ms).unwrap();
    let (got_session, got_expiry) = ContinuityWire::verify(key, &wire).unwrap();
    assert_eq!(got_session, "");
    assert_eq!(got_expiry, expiry_ms);
}

// ──────────────────────────────────────────────────────────────────────
// 7. Sanity — public API surface compiles + a smoke fuzz on
//    ContinuityWire crossed against the locally-routed primitives.
// ──────────────────────────────────────────────────────────────────────

#[test]
fn continuity_wire_fuzz_round_trip_50_iter() {
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};

    let mut rng = StdRng::seed_from_u64(0x434f_4e54_494e_5549); // "CONTINUI"

    for iter in 0..50 {
        let key_len = rng.random_range(0..=64);
        let mut key = vec![0u8; key_len];
        rng.fill(&mut key[..]);

        let session_len = rng.random_range(0..=128);
        // Build session_id from ASCII printable to keep it str-safe
        // and avoid colliding with the 0x1e separator.
        let session: String = (0..session_len)
            .map(|_| {
                let b = rng.random_range(0x20u8..0x7eu8);
                // Skip 0x1e — doesn't fall in this range, but defensive.
                b as char
            })
            .collect();
        let expiry_ms: i64 = rng.random();

        let wire = ContinuityWire::sign(&key, &session, expiry_ms)
            .unwrap_or_else(|_| panic!("sign failed at iter {iter}"));
        let (got_session, got_expiry) = ContinuityWire::verify(&key, &wire)
            .unwrap_or_else(|_| panic!("verify failed at iter {iter}"));

        assert_eq!(got_session, session, "iter {iter} session mismatch");
        assert_eq!(got_expiry, expiry_ms, "iter {iter} expiry mismatch");
    }
}
