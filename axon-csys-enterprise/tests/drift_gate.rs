//! § Fase 27.i — Cross-kernel drift gate.
//!
//! Consolidated drift gate for the entire axon-csys-enterprise
//! surface. Pins the load-bearing consistency contracts:
//!
//!   1. Crypto: SHA-256 + HMAC-SHA256 byte-identity vs OSS axon-csys
//!      (pure-C path) AND vs independently-implemented Rust
//!      (`sha2`, `hmac`) crates. Under FIPS features the routed
//!      path joins the equivalence — D7 ratified.
//!   2. Continuity wire: ContinuityWire::sign + verify cross-validate
//!      with OSS axon-csys 0.1.x — tokens issued by either crate
//!      verify on the other.
//!   3. Audit log: byte-identity across two writers seeded with the
//!      same key + tenant_id + segment_id + prev_hash + payload
//!      sequence. The HMAC-rooted chain produces deterministic
//!      bytes (modulo the segment header's `created_ms` field which
//!      is wall-clock; tests pin a wrapper that ignores it).
//!   4. Evidence packager: byte-determinism across two builders
//!      seeded with the same files + options + signing key. The
//!      Ed25519 signature is RFC-8032-deterministic, so same key +
//!      same canonical manifest bytes → same signature → same ZIP
//!      bytes.
//!   5. Vertical BPE encoders: encode/decode bijection on 100-iter
//!      seeded random text + cross-validate that the v1 seed
//!      `.bin` blob format is byte-compatible with the OSS BPE
//!      engine (the OSS `Tokenizer::from_blob` accepts the
//!      enterprise blobs).
//!   6. PHI scrub determinism: same input + same pattern mask →
//!      same output bytes (no hidden randomness in the scrubber).
//!   7. Cross-kernel composition: build an evidence bundle whose
//!      content is an audit log segment; verify the cross-kernel
//!      hash chain is intact end-to-end.
//!
//! Fuzz iterations use a deterministic seeded `StdRng` so failures
//! reproduce verbatim on every CI run. Failures here are
//! load-bearing — any drift indicates a wire-format break that
//! propagates to every adopter integration.

#![allow(clippy::needless_range_loop)]

use axon_csys_enterprise::audit_log::{
    AuditLogVerifier, AuditLogWriter, DEFAULT_SEGMENT_BYTES, HASH_SIZE,
};
use axon_csys_enterprise::crypto::{
    backend_label, hmac_sha256, sha256, ContinuityWire, SHA256_DIGEST_SIZE,
};
use axon_csys_enterprise::evidence::{
    Ed25519SigningKey, EvidenceBuilder, EvidenceOptions, EvidenceVerifier,
};
use axon_csys_enterprise::phi_scrub::{scrub, PhiPatterns};
use axon_csys_enterprise::tokens::{fintech_base, legal_base, medical_base};

use hmac::{Hmac, Mac as _};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use sha2::Digest as _;

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

// ──────────────────────────────────────────────────────────────────────
// 1. Crypto SHA-256 + HMAC-SHA256 byte-identity drift gate
// ──────────────────────────────────────────────────────────────────────
//
// Re-asserts the contract that integration tests in tests/crypto.rs
// already cover. Consolidated here so the load-bearing equivalence
// (enterprise crypto path = OSS axon-csys = sha2/hmac crate) is
// visible in one file. Fuzz uses a seed distinct from tests/crypto.rs
// so combined CI exercises ~200 iterations per primitive.

#[test]
fn sha256_drift_gate_consolidated_500_iter() {
    let mut rng = StdRng::seed_from_u64(0x4452_4946_5448_3531); // "DRIFTH51"
    for iter in 0..500 {
        let len = rng.random_range(0..=2048);
        let mut input = vec![0u8; len];
        rng.fill(&mut input[..]);

        let local = sha256(&input);
        let oss = axon_csys::sha256(&input);
        let reference = {
            let mut h = sha2::Sha256::new();
            h.update(&input);
            let out = h.finalize();
            let mut arr = [0u8; SHA256_DIGEST_SIZE];
            arr.copy_from_slice(&out);
            arr
        };

        assert_eq!(
            local,
            oss,
            "SHA-256 drift gate failed at iter {iter}: enterprise(backend={}) != OSS",
            backend_label()
        );
        assert_eq!(
            local, reference,
            "SHA-256 drift gate failed vs sha2 crate at iter {iter}"
        );
    }
}

#[test]
fn hmac_sha256_drift_gate_consolidated_500_iter() {
    let mut rng = StdRng::seed_from_u64(0x484d_4143_4452_4946); // "HMACDRIF"
    for iter in 0..500 {
        let key_len = rng.random_range(0..=300);
        let data_len = rng.random_range(0..=2048);
        let mut key = vec![0u8; key_len];
        let mut data = vec![0u8; data_len];
        rng.fill(&mut key[..]);
        rng.fill(&mut data[..]);

        let local = hmac_sha256(&key, &data);
        let oss = axon_csys::hmac_sha256(&key, &data);
        let reference = {
            let mut mac =
                Hmac::<sha2::Sha256>::new_from_slice(&key).expect("Hmac accepts any key length");
            mac.update(&data);
            let out = mac.finalize().into_bytes();
            let mut arr = [0u8; SHA256_DIGEST_SIZE];
            arr.copy_from_slice(&out);
            arr
        };

        assert_eq!(
            local, oss,
            "HMAC drift gate failed at iter {iter}: enterprise != OSS"
        );
        assert_eq!(
            local, reference,
            "HMAC drift gate failed vs hmac crate at iter {iter}"
        );
    }
}

// ──────────────────────────────────────────────────────────────────────
// 2. ContinuityWire cross-stack drift gate
// ──────────────────────────────────────────────────────────────────────

#[test]
fn continuity_wire_drift_gate_50_iter() {
    let mut rng = StdRng::seed_from_u64(0x434f_4e54_5749_5245); // "CONTWIRE"
    for iter in 0..50 {
        let key_len = rng.random_range(1..=64);
        let mut key = vec![0u8; key_len];
        rng.fill(&mut key[..]);

        // ASCII printable session_id, no 0x1e separator.
        let session_len = rng.random_range(0..=128);
        let session: String = (0..session_len)
            .map(|_| rng.random_range(0x20u8..0x7eu8) as char)
            .collect();
        let expiry_ms: i64 = rng.random();

        let ours = ContinuityWire::sign(&key, &session, expiry_ms).unwrap();
        let theirs = axon_csys::ContinuityWire::sign(&key, &session, expiry_ms).unwrap();

        assert_eq!(
            ours, theirs,
            "ContinuityWire drift at iter {iter}: bytes diverged"
        );

        // Cross-verify both directions.
        let (ours_session, ours_expiry) = axon_csys::ContinuityWire::verify(&key, &ours).unwrap();
        let (theirs_session, theirs_expiry) = ContinuityWire::verify(&key, &theirs).unwrap();
        assert_eq!(ours_session, session);
        assert_eq!(ours_expiry, expiry_ms);
        assert_eq!(theirs_session, session);
        assert_eq!(theirs_expiry, expiry_ms);
    }
}

// ──────────────────────────────────────────────────────────────────────
// 3. Audit log cross-writer determinism
//
// Two writers seeded with the same per-tenant key + same segment
// parameters + same payload sequence MUST produce byte-identical
// segment bodies (everything past the segment header). The header
// includes a wall-clock `created_ms` field that differs between
// writers; we exclude it from the comparison.
// ──────────────────────────────────────────────────────────────────────

const TENANT_KEY_TEST: &[u8] = b"drift-gate-tenant-key-2026-05-09-q2";

static SCRATCH_COUNTER: AtomicU64 = AtomicU64::new(0xD714_D31E_0000_0000);

fn scratch_path(label: &str) -> PathBuf {
    let n = SCRATCH_COUNTER.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();
    let mut p = std::env::temp_dir();
    p.push(format!("axon-drift-{label}-{pid}-{n}.log"));
    let _ = std::fs::remove_file(&p);
    p
}

fn build_audit_log(path: &std::path::Path, payloads: &[Vec<u8>]) {
    let writer = AuditLogWriter::open(
        path,
        0xDEAD_BEEF_CAFE_F00D,
        7, // segment_id
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY_TEST,
        Some(&[0x42u8; HASH_SIZE]), // fixed prev_segment_tail_hash
    )
    .expect("open writer");
    for (i, p) in payloads.iter().enumerate() {
        writer
            .append(1_700_000_000_000 + i as i64, p)
            .expect("append");
    }
    writer.sync().unwrap();
    drop(writer);
}

fn segment_body_bytes(path: &std::path::Path) -> Vec<u8> {
    // Skip the first 256 bytes (segment header — contains wall-clock
    // `created_ms` at offset 40..48 which differs between writers).
    let bytes = std::fs::read(path).unwrap();
    bytes[256..].to_vec()
}

#[test]
fn audit_log_drift_gate_two_writers_produce_identical_body_bytes() {
    let payloads: Vec<Vec<u8>> = (0..10)
        .map(|i| format!("event-{i:03}").into_bytes())
        .collect();

    let path_a = scratch_path("auditA");
    let path_b = scratch_path("auditB");
    build_audit_log(&path_a, &payloads);
    build_audit_log(&path_b, &payloads);

    let body_a = segment_body_bytes(&path_a);
    let body_b = segment_body_bytes(&path_b);
    assert_eq!(body_a, body_b, "audit log body drift between writers");

    let _ = std::fs::remove_file(&path_a);
    let _ = std::fs::remove_file(&path_b);
}

#[test]
fn audit_log_drift_gate_seal_mac_byte_identical_to_userspace_hmac() {
    // The seal_mac on each block is HMAC-SHA256 over the block
    // header (64 B) + payload. Recompute via crate::crypto::hmac_sha256
    // on a known-payload block + assert byte-identical to what the
    // writer emitted via append's out_seal_mac.
    let path = scratch_path("auditC");
    let writer =
        AuditLogWriter::open(&path, 1, 1, DEFAULT_SEGMENT_BYTES, TENANT_KEY_TEST, None).unwrap();
    let payload = b"drift-gate-payload";
    let r = writer.append(42, payload).unwrap();

    // Reconstruct the 64-byte block header that the writer wrote
    // for event_id 0 (first append after no prior seal).
    let mut header = [0u8; 64];
    // prev_hash[0..32]: zeros (None passed for prev_segment_tail_hash).
    let ts: i64 = 42;
    header[32..40].copy_from_slice(&(ts as u64).to_le_bytes());
    // event_id = 0, payload_len = 18 → indexed at byte 48.
    let plen: u32 = payload.len() as u32;
    header[48..52].copy_from_slice(&plen.to_le_bytes());
    // reserved[52..64] zeros.

    let mut blob = Vec::with_capacity(header.len() + payload.len());
    blob.extend_from_slice(&header);
    blob.extend_from_slice(payload);
    let expected = hmac_sha256(TENANT_KEY_TEST, &blob);
    assert_eq!(
        r.seal_mac, expected,
        "audit log seal_mac drift vs user-space HMAC computation"
    );

    drop(writer);
    let _ = std::fs::remove_file(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 4. Evidence packager byte-determinism drift gate
// ──────────────────────────────────────────────────────────────────────

fn make_evidence_options() -> EvidenceOptions {
    EvidenceOptions {
        tenant_id: 0xCAFE_BABE,
        evidence_id: "drift-gate-001".to_owned(),
        created_ms: 0,
        signing_key_id: "drift-test-key-q2-2026".to_owned(),
    }
}

#[test]
fn evidence_drift_gate_two_builders_produce_identical_zip_bytes() {
    let key = Ed25519SigningKey::from_bytes(&[0x99u8; 32]);
    let opts = make_evidence_options();

    let make_bundle = || {
        EvidenceBuilder::new()
            .add_file("notes/intake.txt", b"patient intake".to_vec())
            .unwrap()
            .add_file("labs/cbc.csv", b"date,value\n2026-05-01,12.4".to_vec())
            .unwrap()
            .add_file("ekg/strip.bin", vec![0xFFu8; 256])
            .unwrap()
            .build(&key, &opts)
            .unwrap()
    };

    let b1 = make_bundle();
    let b2 = make_bundle();

    assert_eq!(b1.zip_bytes, b2.zip_bytes, "evidence bundle byte drift");
    assert_eq!(b1.merkle_root, b2.merkle_root, "Merkle root drift");
    assert_eq!(b1.signature, b2.signature, "Ed25519 signature drift");
}

#[test]
fn evidence_drift_gate_sha256_of_bundle_is_stable_across_runs() {
    // The full ZIP bundle's SHA-256 is the strongest end-to-end
    // determinism assertion — captures every header field, every
    // file order, every padding byte.
    let key = Ed25519SigningKey::from_bytes(&[0x55u8; 32]);
    let opts = make_evidence_options();
    let bundle = EvidenceBuilder::new()
        .add_file("doc.txt", b"deterministic content".to_vec())
        .unwrap()
        .build(&key, &opts)
        .unwrap();
    let h1 = sha256(&bundle.zip_bytes);

    let bundle2 = EvidenceBuilder::new()
        .add_file("doc.txt", b"deterministic content".to_vec())
        .unwrap()
        .build(&key, &opts)
        .unwrap();
    let h2 = sha256(&bundle2.zip_bytes);
    assert_eq!(h1, h2);
}

#[test]
fn evidence_drift_gate_round_trip_50_iter() {
    let key = Ed25519SigningKey::from_bytes(&[0x33u8; 32]);
    let pk = key.verifying_key();
    let verifier = EvidenceVerifier::new(pk);
    let mut rng = StdRng::seed_from_u64(0x4556_4944_454e_4345); // "EVIDENCE"

    for iter in 0..50 {
        let n_files = rng.random_range(0..=8);
        let mut builder = EvidenceBuilder::new();
        let mut expected: Vec<(String, Vec<u8>)> = Vec::new();
        for i in 0..n_files {
            // Path: ASCII alphanumeric + extension to keep within
            // the path validator.
            let name = format!("file-{iter:03}-{i:02}.bin");
            let len = rng.random_range(0..=512);
            let mut content = vec![0u8; len];
            rng.fill(&mut content[..]);
            builder = builder.add_file(name.clone(), content.clone()).unwrap();
            expected.push((name, content));
        }
        let opts = EvidenceOptions {
            tenant_id: iter as u64,
            evidence_id: format!("ev-{iter}"),
            created_ms: iter as i64 * 1000,
            signing_key_id: "drift".to_owned(),
        };
        let bundle = builder.build(&key, &opts).unwrap();

        // Build twice → bytes must match.
        // (Skipped to keep the iter count fast; covered by the
        // dedicated test above.)

        // Round-trip through verifier.
        let verified = verifier.verify(&bundle.zip_bytes).unwrap();
        // Sort expected by path for comparison (verifier returns
        // lexicographic order).
        expected.sort_by(|a, b| a.0.cmp(&b.0));
        assert_eq!(
            verified.files.len(),
            expected.len(),
            "iter {iter} file count mismatch"
        );
        for (got, want) in verified.files.iter().zip(expected.iter()) {
            assert_eq!(got.0, want.0, "iter {iter} path mismatch");
            assert_eq!(got.1, want.1, "iter {iter} content mismatch");
        }
    }
}

// ──────────────────────────────────────────────────────────────────────
// 5. Vertical BPE drift gate
// ──────────────────────────────────────────────────────────────────────

#[test]
fn vertical_encoders_round_trip_50_iter_random_text() {
    // 50 iterations × 3 encoders = 150 encode/decode round-trips
    // verifying byte-bijection holds for arbitrary text.
    let mut rng = StdRng::seed_from_u64(0x4252_4946_5442_5045); // "DRIFTBPE"

    let encoders = [
        ("medical", medical_base().unwrap()),
        ("legal", legal_base().unwrap()),
        ("fintech", fintech_base().unwrap()),
    ];

    for iter in 0..50 {
        // ASCII printable text with newlines + spaces (covers the
        // pretokenizer regex pattern).
        let text_len = rng.random_range(0..=512);
        let text: String = (0..text_len)
            .map(|_| {
                let r = rng.random_range(0u32..100u32);
                if r < 80 {
                    rng.random_range(0x20u8..0x7eu8) as char
                } else {
                    ' '
                }
            })
            .collect();

        for (name, enc) in &encoders {
            let ranks = enc
                .encode_with_special_tokens(&text)
                .unwrap_or_else(|e| panic!("encode failed at iter {iter} ({name}): {e:?}"));
            let bytes = enc
                .decode_bytes(&ranks)
                .unwrap_or_else(|e| panic!("decode failed at iter {iter} ({name}): {e:?}"));
            let recovered = std::str::from_utf8(&bytes)
                .unwrap_or_else(|_| panic!("decoded bytes invalid UTF-8 at iter {iter}"));
            assert_eq!(
                recovered, text,
                "vertical encoder {name} round-trip failed at iter {iter}"
            );
        }
    }
}

#[test]
fn vertical_encoders_share_bin_format_with_oss_bpe_engine() {
    // The .bin files load via OSS axon-csys's `Tokenizer::from_blob`
    // (already exercised by the public accessors). This test is a
    // belt-and-braces assertion that the magic + version bytes match
    // the OSS BPE engine's expectations — if OSS bumps the wire
    // format, these tests fail loudly so adopters know to retrain.
    let medical_bytes: &[u8] = include_bytes!("../c-src/tokens/merges_medical_v1_seed.bin");
    let legal_bytes: &[u8] = include_bytes!("../c-src/tokens/merges_legal_v1_seed.bin");
    let fintech_bytes: &[u8] = include_bytes!("../c-src/tokens/merges_fintech_v1_seed.bin");

    for (name, blob) in [
        ("medical", medical_bytes),
        ("legal", legal_bytes),
        ("fintech", fintech_bytes),
    ] {
        // Magic = "AXBP" (0x42505841 little-endian → bytes A, X, B, P).
        assert_eq!(&blob[0..4], b"AXBP", "{name}: AXBP magic missing");
        // Version u32 LE = 1.
        assert_eq!(
            u32::from_le_bytes([blob[4], blob[5], blob[6], blob[7]]),
            1,
            "{name}: format version != 1"
        );
    }
}

// ──────────────────────────────────────────────────────────────────────
// 6. PHI scrub determinism
// ──────────────────────────────────────────────────────────────────────

#[test]
fn phi_scrub_drift_gate_deterministic_output() {
    // 100-iter fuzz: same input + same mask → same output bytes.
    let mut rng = StdRng::seed_from_u64(0x5048_4953_4352_5542); // "PHISCRUB"

    for iter in 0..100 {
        let n_lines = rng.random_range(1..=10);
        let mut input = String::new();
        for _ in 0..n_lines {
            let pick = rng.random_range(0u32..6u32);
            match pick {
                0 => input.push_str(&format!(
                    "Patient SSN {:03}-{:02}-{:04}\n",
                    rng.random_range(100u32..999u32),
                    rng.random_range(10u32..99u32),
                    rng.random_range(1000u32..9999u32),
                )),
                1 => input.push_str(&format!(
                    "phone ({:03}) {:03}-{:04}\n",
                    rng.random_range(200u32..999u32),
                    rng.random_range(200u32..999u32),
                    rng.random_range(1000u32..9999u32),
                )),
                2 => input.push_str("contact: doc@hospital.org\n"),
                3 => input.push_str(&format!(
                    "ip {}.{}.{}.{}\n",
                    rng.random_range(1u32..254u32),
                    rng.random_range(0u32..255u32),
                    rng.random_range(0u32..255u32),
                    rng.random_range(1u32..254u32),
                )),
                4 => input.push_str("plain English with no PHI tokens here.\n"),
                _ => input.push_str("MRN: 1234567 admitted today.\n"),
            }
        }
        let (out1, stats1) = scrub(&input, PhiPatterns::all()).unwrap();
        let (out2, stats2) = scrub(&input, PhiPatterns::all()).unwrap();
        assert_eq!(out1, out2, "PHI scrub non-deterministic at iter {iter}");
        assert_eq!(stats1.matches_found, stats2.matches_found);
    }
}

// ──────────────────────────────────────────────────────────────────────
// 7. Cross-kernel composition — audit log inside an evidence bundle
// ──────────────────────────────────────────────────────────────────────

#[test]
fn cross_kernel_audit_log_inside_evidence_bundle() {
    // Build a small audit log segment + bundle it into an evidence
    // package. Verify the package, then verify the audit log inside.
    // End-to-end cross-kernel hash chain assertion: the evidence
    // bundle's per-file SHA-256 covers the audit log bytes; the
    // audit log's HMAC chain covers the events; the Ed25519 sig
    // covers the manifest. Mutating any byte breaks at least one
    // of the three layers.
    let key = Ed25519SigningKey::from_bytes(&[0x77u8; 32]);
    let pk = key.verifying_key();

    // Stage 1: build an audit log segment.
    let path = scratch_path("xkernel");
    let writer =
        AuditLogWriter::open(&path, 99, 1, DEFAULT_SEGMENT_BYTES, TENANT_KEY_TEST, None).unwrap();
    for i in 0..5 {
        writer
            .append(i, format!("xk-event-{i}").as_bytes())
            .unwrap();
    }
    writer.sync().unwrap();
    drop(writer);

    let segment_bytes = std::fs::read(&path).unwrap();

    // Stage 2: package the audit log into an evidence bundle.
    let opts = EvidenceOptions {
        tenant_id: 99,
        evidence_id: "xk-001".to_owned(),
        created_ms: 0,
        signing_key_id: "xk-key-q2".to_owned(),
    };
    let bundle = EvidenceBuilder::new()
        .add_file("audit/segment-001.log", segment_bytes.clone())
        .unwrap()
        .build(&key, &opts)
        .unwrap();

    // Stage 3: verify the bundle (Ed25519 sig + per-file SHA-256 +
    // Merkle root).
    let verifier = EvidenceVerifier::new(pk);
    let verified = verifier.verify(&bundle.zip_bytes).unwrap();
    assert_eq!(verified.files.len(), 1);
    assert_eq!(verified.files[0].0, "audit/segment-001.log");
    assert_eq!(verified.files[0].1, segment_bytes);

    // Stage 4: re-write the audit log bytes to a temp file and
    // verify the HMAC chain still validates.
    let extracted_path = scratch_path("xkernel-extract");
    std::fs::write(&extracted_path, &verified.files[0].1).unwrap();
    let audit_verifier = AuditLogVerifier::open(&extracted_path, TENANT_KEY_TEST).unwrap();
    audit_verifier.verify().expect("audit chain verifies");
    let stats = audit_verifier.stats().unwrap();
    assert_eq!(stats.event_count, 5);

    drop(audit_verifier);
    let _ = std::fs::remove_file(&path);
    let _ = std::fs::remove_file(&extracted_path);
}

// ──────────────────────────────────────────────────────────────────────
// 8. Backend label is consistent across drift-gate test entry points
// ──────────────────────────────────────────────────────────────────────

#[test]
fn drift_gate_records_active_backend_label() {
    // The backend label is emitted alongside drift-gate failures
    // (see assertion messages above). On the no-fips path it must
    // be `axon-csys-oss-pure-c`; under FIPS features one of
    // `boringssl-fips` / `openssl-fips`.
    let label = backend_label();
    assert!(
        matches!(
            label,
            "axon-csys-oss-pure-c" | "boringssl-fips" | "openssl-fips"
        ),
        "unexpected backend label: {label}"
    );
}
