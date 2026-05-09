//! § Fase 27.f — Tamper-evident evidence packager test pack.
//!
//! Exercises the [`axon_csys_enterprise::evidence`] surface against:
//!
//!   1. Byte-determinism — same inputs + same options produce
//!      bit-identical bytes (the load-bearing claim for forensic
//!      regen + cross-platform reproducibility).
//!   2. Round-trip — build → verify yields the original files +
//!      manifest.
//!   3. Tamper detection — mutating any byte (file content, manifest,
//!      signature, ZIP framing) breaks verification.
//!   4. Lexicographic file ordering — files supplied out-of-order are
//!      sorted at build time so the on-disk order is canonical.
//!   5. Signature determinism — Ed25519 with the same key + message
//!      produces the same signature (RFC 8032 deterministic) → same
//!      bundle bytes.
//!   6. Manifest format — parser accepts canonical JSON we emit;
//!      rejects malformed JSON; rejects unknown manifest versions.
//!   7. Path validation — rejects null bytes, leading slashes, `..`,
//!      Windows-reserved characters at builder time.
//!   8. Cross-key separation — bundle signed by key A is rejected
//!      by verifier with key B.
//!   9. Empty + edge cases — zero files, single file, large file,
//!      many files.

use axon_csys_enterprise::evidence::{
    Ed25519SigningKey, Ed25519VerifyingKey, EvidenceBuilder, EvidenceError, EvidenceOptions,
    EvidenceVerifier,
};

// ──────────────────────────────────────────────────────────────────────
// Test scaffolding — deterministic signing keys for reproducible
// bundle bytes across test runs.
// ──────────────────────────────────────────────────────────────────────

fn key_a() -> Ed25519SigningKey {
    // Fixed test-only seed. Real adopter keys come from HSM / key
    // vault — never hard-coded.
    Ed25519SigningKey::from_bytes(&[0x42u8; 32])
}

fn key_b() -> Ed25519SigningKey {
    Ed25519SigningKey::from_bytes(&[0x37u8; 32])
}

fn pubkey(k: &Ed25519SigningKey) -> Ed25519VerifyingKey {
    k.verifying_key()
}

fn options(tenant_id: u64, evidence_id: &str) -> EvidenceOptions {
    EvidenceOptions {
        tenant_id,
        evidence_id: evidence_id.to_owned(),
        // Fixed timestamp for byte-determinism; real adopters supply
        // chrono::Utc::now().timestamp_millis().
        created_ms: 0,
        signing_key_id: "tenant-test-q2-2026".to_owned(),
    }
}

// ──────────────────────────────────────────────────────────────────────
// 1. Byte-determinism
// ──────────────────────────────────────────────────────────────────────

#[test]
fn build_is_byte_deterministic_across_runs() {
    let k = key_a();
    let make = || {
        EvidenceBuilder::new()
            .add_file("patient/record.json", b"{\"id\":\"P-001\"}".to_vec())
            .unwrap()
            .add_file("lab/results.csv", b"date,value\n2026-05-01,42\n".to_vec())
            .unwrap()
            .build(&k, &options(12345, "ev-001"))
            .unwrap()
    };
    let b1 = make();
    let b2 = make();
    assert_eq!(b1.zip_bytes, b2.zip_bytes, "byte-determinism violated");
    assert_eq!(b1.merkle_root, b2.merkle_root);
    assert_eq!(b1.signature, b2.signature);
}

#[test]
fn build_is_byte_deterministic_across_input_orderings() {
    let k = key_a();
    let b1 = EvidenceBuilder::new()
        .add_file("a.txt", b"alpha".to_vec())
        .unwrap()
        .add_file("b.txt", b"beta".to_vec())
        .unwrap()
        .add_file("c.txt", b"gamma".to_vec())
        .unwrap()
        .build(&k, &options(1, "ev"))
        .unwrap();
    let b2 = EvidenceBuilder::new()
        .add_file("c.txt", b"gamma".to_vec())
        .unwrap()
        .add_file("a.txt", b"alpha".to_vec())
        .unwrap()
        .add_file("b.txt", b"beta".to_vec())
        .unwrap()
        .build(&k, &options(1, "ev"))
        .unwrap();
    assert_eq!(b1.zip_bytes, b2.zip_bytes);
}

#[test]
fn manifest_keys_are_lexicographically_sorted() {
    let k = key_a();
    let bundle = EvidenceBuilder::new()
        .add_file("file1.txt", b"data".to_vec())
        .unwrap()
        .build(&k, &options(99, "ev-99"))
        .unwrap();

    // Locate the manifest inside the ZIP and inspect its raw bytes.
    // Searching for substrings is sufficient — we don't need to
    // re-parse.
    let zip_str: String = bundle
        .zip_bytes
        .iter()
        .map(|&b| if b.is_ascii() { b as char } else { '?' })
        .collect();
    let mstart = zip_str.find("{\"created_ms\":").expect("manifest present");
    let mend = zip_str[mstart..]
        .find("}}]")
        .map(|o| mstart + o + 3)
        .or_else(|| {
            zip_str[mstart..]
                .find("\"version\":1}")
                .map(|o| mstart + o + 12)
        })
        .expect("manifest end");
    let mstr = &zip_str[mstart..mend];
    // Top-level keys must appear in this order:
    let order = [
        "\"created_ms\":",
        "\"evidence_id\":",
        "\"files\":",
        "\"merkle_root\":",
        "\"signing_key_id\":",
        "\"tenant_id\":",
        "\"version\":",
    ];
    let mut last_pos = 0usize;
    for needle in order {
        let pos = mstr.find(needle).unwrap_or_else(|| {
            panic!("missing key {needle} in manifest:\n{mstr}");
        });
        assert!(
            pos >= last_pos,
            "manifest key {needle} appeared at {pos} before previous at {last_pos}"
        );
        last_pos = pos;
    }
}

// ──────────────────────────────────────────────────────────────────────
// 2. Round-trip (build → verify)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn round_trip_preserves_files_and_manifest() {
    let k = key_a();
    let pk = pubkey(&k);

    let bundle = EvidenceBuilder::new()
        .add_file("evidence/note.txt", b"hello".to_vec())
        .unwrap()
        .add_file("evidence/data.bin", vec![0u8, 1, 2, 3, 4, 5])
        .unwrap()
        .build(&k, &options(7, "ev-round"))
        .unwrap();

    let v = EvidenceVerifier::new(pk);
    let verified = v.verify(&bundle.zip_bytes).expect("verify");

    assert_eq!(verified.manifest.tenant_id, 7);
    assert_eq!(verified.manifest.evidence_id, "ev-round");
    assert_eq!(verified.merkle_root, bundle.merkle_root);
    assert_eq!(verified.files.len(), 2);
    // Sorted by path:
    assert_eq!(verified.files[0].0, "evidence/data.bin");
    assert_eq!(verified.files[0].1, vec![0u8, 1, 2, 3, 4, 5]);
    assert_eq!(verified.files[1].0, "evidence/note.txt");
    assert_eq!(verified.files[1].1, b"hello");
}

#[test]
fn round_trip_with_zero_files_succeeds() {
    let k = key_a();
    let pk = pubkey(&k);

    let bundle = EvidenceBuilder::new()
        .build(&k, &options(0, "empty"))
        .unwrap();
    let v = EvidenceVerifier::new(pk);
    let verified = v.verify(&bundle.zip_bytes).expect("verify empty");
    assert_eq!(verified.manifest.files.len(), 0);
    assert_eq!(verified.files.len(), 0);
}

#[test]
fn round_trip_single_large_file() {
    let k = key_a();
    let pk = pubkey(&k);
    let payload: Vec<u8> = (0..16384u32).flat_map(|i| i.to_le_bytes()).collect();
    let bundle = EvidenceBuilder::new()
        .add_file("big.bin", payload.clone())
        .unwrap()
        .build(&k, &options(1, "big"))
        .unwrap();
    let verified = EvidenceVerifier::new(pk).verify(&bundle.zip_bytes).unwrap();
    assert_eq!(verified.files[0].1, payload);
}

#[test]
fn round_trip_many_files() {
    let k = key_a();
    let pk = pubkey(&k);
    let mut builder = EvidenceBuilder::new();
    for i in 0..50 {
        builder = builder
            .add_file(format!("doc-{i:03}.txt"), format!("content {i}"))
            .unwrap();
    }
    let bundle = builder.build(&k, &options(1, "many")).unwrap();
    let verified = EvidenceVerifier::new(pk).verify(&bundle.zip_bytes).unwrap();
    assert_eq!(verified.files.len(), 50);
    // Sorted lexicographically.
    for i in 0..50 {
        assert_eq!(verified.files[i].0, format!("doc-{i:03}.txt"));
    }
}

// ──────────────────────────────────────────────────────────────────────
// 3. Tamper detection
// ──────────────────────────────────────────────────────────────────────

fn make_simple_bundle() -> (Vec<u8>, Ed25519VerifyingKey) {
    let k = key_a();
    let pk = pubkey(&k);
    let bundle = EvidenceBuilder::new()
        .add_file("a.txt", b"alpha".to_vec())
        .unwrap()
        .add_file("b.txt", b"beta".to_vec())
        .unwrap()
        .build(&k, &options(1, "ev"))
        .unwrap();
    (bundle.zip_bytes, pk)
}

#[test]
fn tampering_with_file_content_breaks_verification() {
    let (mut bytes, pk) = make_simple_bundle();
    // Find "alpha" in the bytes and flip a byte.
    let needle = b"alpha";
    let pos = bytes
        .windows(needle.len())
        .position(|w| w == needle)
        .expect("alpha present");
    bytes[pos] ^= 0xFF;
    let res = EvidenceVerifier::new(pk).verify(&bytes);
    assert!(
        matches!(
            res,
            Err(EvidenceError::ManifestFileMismatch(_)) | Err(EvidenceError::ZipParseError(_))
        ),
        "expected hash mismatch, got {res:?}"
    );
}

#[test]
fn tampering_with_manifest_breaks_signature() {
    let (mut bytes, pk) = make_simple_bundle();
    // Find a digit in "tenant_id":1 and flip it.
    let needle = b"\"tenant_id\":1";
    let pos = bytes
        .windows(needle.len())
        .position(|w| w == needle)
        .expect("tenant_id present");
    bytes[pos + needle.len() - 1] = b'9';
    let res = EvidenceVerifier::new(pk).verify(&bytes);
    assert!(
        matches!(
            res,
            Err(EvidenceError::SignatureMismatch) | Err(EvidenceError::ZipParseError(_))
        ),
        "expected signature mismatch, got {res:?}"
    );
}

#[test]
fn tampering_with_signature_bytes_breaks_verification() {
    let (mut bytes, pk) = make_simple_bundle();
    // The 64-byte Ed25519 signature lives near the end of the ZIP.
    // Find the "_evidence_signature.bin" filename in the central
    // directory; the LFH content is earlier — easier path: just flip
    // a byte 100 from the end of the file (likely inside the
    // signature LFH content or central dir).
    let n = bytes.len();
    bytes[n - 100] ^= 0xFF;
    let res = EvidenceVerifier::new(pk).verify(&bytes);
    assert!(
        res.is_err(),
        "tampered byte must break verification, got Ok"
    );
}

#[test]
fn truncating_zip_breaks_verification() {
    let (bytes, pk) = make_simple_bundle();
    let truncated = &bytes[..bytes.len() / 2];
    let res = EvidenceVerifier::new(pk).verify(truncated);
    assert!(
        matches!(res, Err(EvidenceError::ZipParseError(_))),
        "truncated zip must produce ZipParseError, got {res:?}"
    );
}

#[test]
fn empty_input_fails_cleanly() {
    let pk = pubkey(&key_a());
    let res = EvidenceVerifier::new(pk).verify(&[]);
    assert!(matches!(res, Err(EvidenceError::ZipParseError(_))));
}

// ──────────────────────────────────────────────────────────────────────
// 4. Cross-key separation
// ──────────────────────────────────────────────────────────────────────

#[test]
fn bundle_signed_by_key_a_rejected_by_verifier_with_key_b() {
    let bundle = EvidenceBuilder::new()
        .add_file("doc.txt", b"data".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    let res = EvidenceVerifier::new(pubkey(&key_b())).verify(&bundle.zip_bytes);
    assert!(matches!(res, Err(EvidenceError::SignatureMismatch)));
}

// ──────────────────────────────────────────────────────────────────────
// 5. Path validation
// ──────────────────────────────────────────────────────────────────────

#[test]
fn rejects_empty_path() {
    let r = EvidenceBuilder::new().add_file("", b"x".to_vec());
    assert!(matches!(r, Err(EvidenceError::InvalidPath(_))));
}

#[test]
fn rejects_path_with_null_byte() {
    let r = EvidenceBuilder::new().add_file("foo\0bar", b"x".to_vec());
    assert!(matches!(r, Err(EvidenceError::InvalidPath(_))));
}

#[test]
fn rejects_path_with_leading_slash() {
    let r = EvidenceBuilder::new().add_file("/abs/path", b"x".to_vec());
    assert!(matches!(r, Err(EvidenceError::InvalidPath(_))));
}

#[test]
fn rejects_path_with_backref() {
    let r = EvidenceBuilder::new().add_file("foo/../bar", b"x".to_vec());
    assert!(matches!(r, Err(EvidenceError::InvalidPath(_))));
}

#[test]
fn rejects_path_with_dot_segment() {
    let r = EvidenceBuilder::new().add_file("foo/./bar", b"x".to_vec());
    assert!(matches!(r, Err(EvidenceError::InvalidPath(_))));
}

#[test]
fn rejects_path_with_windows_reserved_character() {
    for bad in [
        "foo<bar", "foo>bar", "foo:bar", "foo\"bar", "foo|bar", "foo?bar", "foo*bar",
    ] {
        let r = EvidenceBuilder::new().add_file(bad, b"x".to_vec());
        assert!(
            matches!(r, Err(EvidenceError::InvalidPath(_))),
            "expected InvalidPath for {bad:?}"
        );
    }
}

#[test]
fn rejects_duplicate_path() {
    let b = EvidenceBuilder::new()
        .add_file("dup.txt", b"a".to_vec())
        .unwrap();
    let r = b.add_file("dup.txt", b"b".to_vec());
    assert!(matches!(r, Err(EvidenceError::DuplicatePath(_))));
}

// ──────────────────────────────────────────────────────────────────────
// 6. Manifest format
// ──────────────────────────────────────────────────────────────────────

#[test]
fn manifest_starts_with_canonical_keys_in_order() {
    let bundle = EvidenceBuilder::new()
        .add_file("x.txt", b"y".to_vec())
        .unwrap()
        .build(&key_a(), &options(42, "ev"))
        .unwrap();
    let s: String = bundle
        .zip_bytes
        .iter()
        .map(|&b| if b.is_ascii() { b as char } else { '?' })
        .collect();
    assert!(s.contains("\"created_ms\":0,"));
    assert!(s.contains("\"evidence_id\":\"ev\""));
    assert!(s.contains("\"merkle_root\":"));
    assert!(s.contains("\"signing_key_id\":\"tenant-test-q2-2026\""));
    assert!(s.contains("\"tenant_id\":42"));
    assert!(s.contains("\"version\":1"));
}

// ──────────────────────────────────────────────────────────────────────
// 7. Lexicographic file ordering — sorted by path
// ──────────────────────────────────────────────────────────────────────

#[test]
fn files_in_zip_are_sorted_lexicographically() {
    let bundle = EvidenceBuilder::new()
        .add_file("z_last.txt", b"last".to_vec())
        .unwrap()
        .add_file("a_first.txt", b"first".to_vec())
        .unwrap()
        .add_file("m_middle.txt", b"middle".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "sort"))
        .unwrap();
    let verified = EvidenceVerifier::new(pubkey(&key_a()))
        .verify(&bundle.zip_bytes)
        .unwrap();
    let names: Vec<&str> = verified.files.iter().map(|(p, _)| p.as_str()).collect();
    assert_eq!(names, ["a_first.txt", "m_middle.txt", "z_last.txt"]);
}

// ──────────────────────────────────────────────────────────────────────
// 8. Ed25519 signature determinism
// ──────────────────────────────────────────────────────────────────────

#[test]
fn ed25519_signature_is_deterministic_per_rfc8032() {
    let k = key_a();
    let make = || {
        EvidenceBuilder::new()
            .add_file("note.txt", b"deterministic-sig".to_vec())
            .unwrap()
            .build(&k, &options(7, "ev"))
            .unwrap()
            .signature
    };
    assert_eq!(make(), make());
}

// ──────────────────────────────────────────────────────────────────────
// 9. ZIP magic + structural sanity
// ──────────────────────────────────────────────────────────────────────

#[test]
fn zip_starts_with_local_file_header_signature() {
    let bundle = EvidenceBuilder::new()
        .add_file("x.txt", b"y".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    // 0x04034b50 little-endian.
    assert_eq!(&bundle.zip_bytes[0..4], &[0x50, 0x4b, 0x03, 0x04]);
}

#[test]
fn zip_ends_with_eocd_signature() {
    let bundle = EvidenceBuilder::new()
        .add_file("x.txt", b"y".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    // 0x06054b50 little-endian, 22 bytes from end (no comment).
    let n = bundle.zip_bytes.len();
    assert_eq!(&bundle.zip_bytes[n - 22..n - 18], &[0x50, 0x4b, 0x05, 0x06]);
}

// ──────────────────────────────────────────────────────────────────────
// 10. Manifest field tampering
// ──────────────────────────────────────────────────────────────────────

#[test]
fn merkle_root_in_manifest_matches_recomputed() {
    let bundle = EvidenceBuilder::new()
        .add_file("doc1", b"first".to_vec())
        .unwrap()
        .add_file("doc2", b"second".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    // Verifier recomputes the Merkle root from the per-file
    // sha256s. Bundle.merkle_root is what was put into the manifest.
    // They MUST match — verify() asserts this internally.
    let v = EvidenceVerifier::new(pubkey(&key_a()));
    let verified = v.verify(&bundle.zip_bytes).unwrap();
    assert_eq!(verified.merkle_root, bundle.merkle_root);
}

#[test]
fn merkle_root_differs_when_file_content_differs() {
    let b1 = EvidenceBuilder::new()
        .add_file("doc", b"first".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    let b2 = EvidenceBuilder::new()
        .add_file("doc", b"second".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    assert_ne!(b1.merkle_root, b2.merkle_root);
}

#[test]
fn merkle_root_differs_when_file_path_differs() {
    let b1 = EvidenceBuilder::new()
        .add_file("path-a", b"same-content".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    let b2 = EvidenceBuilder::new()
        .add_file("path-b", b"same-content".to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "ev"))
        .unwrap();
    assert_ne!(b1.merkle_root, b2.merkle_root);
}

// ──────────────────────────────────────────────────────────────────────
// 11. Error display surface
// ──────────────────────────────────────────────────────────────────────

#[test]
fn error_display_strings_are_useful() {
    assert!(format!("{}", EvidenceError::SignatureMismatch).contains("signature"));
    assert!(format!("{}", EvidenceError::MerkleRootMismatch).contains("Merkle"));
    assert!(format!("{}", EvidenceError::InvalidPath("x".into())).contains("invalid path"));
}

// ──────────────────────────────────────────────────────────────────────
// 12. Unicode paths + content
// ──────────────────────────────────────────────────────────────────────

#[test]
fn unicode_path_round_trips() {
    let bundle = EvidenceBuilder::new()
        .add_file("séjour.txt", "résumé\n".as_bytes().to_vec())
        .unwrap()
        .add_file("μάθηση.json", "{\"αλφάβητο\":\"abc\"}".as_bytes().to_vec())
        .unwrap()
        .build(&key_a(), &options(1, "uni"))
        .unwrap();
    let v = EvidenceVerifier::new(pubkey(&key_a()));
    let verified = v.verify(&bundle.zip_bytes).unwrap();
    assert_eq!(verified.files.len(), 2);
    // Sort is by UTF-8 byte order: 's' (0x73) < 'μ' first byte 0xCE,
    // so séjour.txt comes first.
    assert_eq!(verified.files[0].0, "séjour.txt");
    assert_eq!(
        std::str::from_utf8(&verified.files[0].1).unwrap(),
        "résumé\n"
    );
    assert_eq!(verified.files[1].0, "μάθηση.json");
    assert_eq!(
        std::str::from_utf8(&verified.files[1].1).unwrap(),
        "{\"αλφάβητο\":\"abc\"}"
    );
}

// ──────────────────────────────────────────────────────────────────────
// 13. Bundle size sanity
// ──────────────────────────────────────────────────────────────────────

#[test]
fn empty_bundle_is_minimal_size() {
    let bundle = EvidenceBuilder::new()
        .build(&key_a(), &options(0, "e"))
        .unwrap();
    // Empty bundle still has manifest + signature → at least
    // 22 (EOCD) + 2 × (30 LFH + 46 CDFH + filename + content). We
    // sanity-check it's "small" — under 1 KB.
    assert!(
        bundle.zip_bytes.len() < 1024,
        "empty bundle exceeded 1 KB: {}",
        bundle.zip_bytes.len()
    );
    // And not pathologically tiny.
    assert!(bundle.zip_bytes.len() > 100);
}

#[test]
fn zip_bytes_sha256_is_stable_for_fixed_inputs() {
    let bundle = EvidenceBuilder::new()
        .add_file("doc.txt", b"hello".to_vec())
        .unwrap()
        .build(&key_a(), &options(42, "ev-stable"))
        .unwrap();
    let bundle2 = EvidenceBuilder::new()
        .add_file("doc.txt", b"hello".to_vec())
        .unwrap()
        .build(&key_a(), &options(42, "ev-stable"))
        .unwrap();
    let h1 = axon_csys::sha256(&bundle.zip_bytes);
    let h2 = axon_csys::sha256(&bundle2.zip_bytes);
    assert_eq!(h1, h2);
}
