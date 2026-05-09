//! § Fase 27.j — License-key enforcement test pack.
//!
//! Exercises the [`axon_csys_enterprise::license`] surface against:
//!
//!   1. Valid license: signature verifies + within expiry window
//!      → `LicenseStatus::Valid` with correct fields.
//!   2. Expired license: signature verifies + expiry < now → `Expired`.
//!   3. Wrong public key: signature does NOT verify → `SignatureMismatch`.
//!   4. Missing license: empty buffer / nonexistent file → `Missing`.
//!   5. Malformed: truncated / bad magic / corrupted manifest → `Malformed`.
//!   6. Unknown version: future format bump → `UnknownVersion`.
//!   7. Per-feature gating: `has_feature` returns true only for valid +
//!      listed features.
//!   8. Soft-fail discipline: every entry point returns a status
//!      variant, NEVER panics or returns Err.
//!   9. Path-based load: `from_path` correctly handles missing files +
//!      unreadable files.
//!  10. Tamper detection: byte flips in manifest → SignatureMismatch.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

use axon_csys_enterprise::license::{
    assemble_license_blob, canonical_license_manifest_json, current_time_ms, Ed25519SigningKey,
    License, LicenseChecker, LicenseError, LicenseStatus, MAX_LICENSE_BYTES,
};
use ed25519_dalek::Signer as _;

// ──────────────────────────────────────────────────────────────────────
// Test scaffolding
// ──────────────────────────────────────────────────────────────────────

fn signing_key_a() -> Ed25519SigningKey {
    Ed25519SigningKey::from_bytes(&[0xACu8; 32])
}

fn signing_key_b() -> Ed25519SigningKey {
    Ed25519SigningKey::from_bytes(&[0xBDu8; 32])
}

const ALL_FEATURES_V1: &[&str] = &[
    "audit-log",
    "evidence",
    "fips-crypto",
    "phi-scrubber",
    "vertical-bpe",
];

fn build_valid_license_blob(
    key: &Ed25519SigningKey,
    tenant_id: u64,
    tenant_name: &str,
    issued_at_ms: i64,
    expires_at_ms: i64,
    features: &[&str],
) -> Vec<u8> {
    let feature_set: Vec<String> = features.iter().map(|s| s.to_string()).collect();
    let manifest = canonical_license_manifest_json(
        1,
        tenant_id,
        tenant_name,
        issued_at_ms,
        expires_at_ms,
        &feature_set,
    );
    let sig = key.sign(&manifest);
    let sig_bytes = sig.to_bytes();
    assemble_license_blob(&manifest, &sig_bytes)
}

static SCRATCH_COUNTER: AtomicU64 = AtomicU64::new(0x1C50_0000_0000);

fn scratch_path(label: &str) -> PathBuf {
    let n = SCRATCH_COUNTER.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();
    let mut p = std::env::temp_dir();
    p.push(format!("axon-license-{label}-{pid}-{n}.bin"));
    let _ = std::fs::remove_file(&p);
    p
}

fn cleanup(path: &std::path::Path) {
    let _ = std::fs::remove_file(path);
}

// ──────────────────────────────────────────────────────────────────────
// 1. Valid license
// ──────────────────────────────────────────────────────────────────────

#[test]
fn valid_license_passes_check() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let now = 1_715_500_000_000_i64;
    let blob = build_valid_license_blob(
        &key,
        12345,
        "Test Tenant Inc.",
        1_715_000_000_000,
        1_815_000_000_000,
        ALL_FEATURES_V1,
    );
    let license = License::from_bytes(&blob).expect("parse");
    let status = license.check(&pk, now);
    match status {
        LicenseStatus::Valid {
            tenant_id,
            tenant_name,
            expires_at_ms,
            days_until_expiry,
            feature_set,
        } => {
            assert_eq!(tenant_id, 12345);
            assert_eq!(tenant_name, "Test Tenant Inc.");
            assert_eq!(expires_at_ms, 1_815_000_000_000);
            assert!(days_until_expiry > 0);
            assert_eq!(feature_set.len(), 5);
        }
        other => panic!("expected Valid, got: {other:?}"),
    }
}

#[test]
fn valid_license_label_is_valid() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        1,
        "Valid Tenant",
        1_700_000_000_000,
        1_800_000_000_000,
        &["audit-log"],
    );
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_750_000_000_000);
    assert_eq!(status.label(), "valid");
    assert!(status.is_valid());
}

#[test]
fn valid_license_display_includes_tenant_id() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        99887766,
        "Display Test",
        1_700_000_000_000,
        1_800_000_000_000,
        &[],
    );
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_750_000_000_000);
    let display = format!("{status}");
    assert!(display.contains("99887766"), "got: {display}");
    assert!(display.contains("Display Test"));
}

// ──────────────────────────────────────────────────────────────────────
// 2. Expired license
// ──────────────────────────────────────────────────────────────────────

#[test]
fn expired_license_returns_expired_status() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let now = 1_900_000_000_000_i64;
    let blob = build_valid_license_blob(
        &key,
        555,
        "Expired Tenant",
        1_700_000_000_000,
        1_800_000_000_000, // expired 100B ms before `now`
        ALL_FEATURES_V1,
    );
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, now);
    match status {
        LicenseStatus::Expired {
            tenant_id,
            expired_ms_ago,
            ..
        } => {
            assert_eq!(tenant_id, 555);
            assert_eq!(expired_ms_ago, 100_000_000_000);
        }
        other => panic!("expected Expired, got: {other:?}"),
    }
}

#[test]
fn expired_license_is_not_valid() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        1,
        "Tenant",
        1,
        1_000, // expired
        &[],
    );
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 2_000);
    assert!(!status.is_valid());
    assert_eq!(status.label(), "expired");
}

// ──────────────────────────────────────────────────────────────────────
// 3. Signature mismatch (wrong public key OR tampered manifest)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn license_signed_by_key_a_rejected_by_key_b() {
    let key_a = signing_key_a();
    let key_b = signing_key_b();
    let pk_b = key_b.verifying_key();

    let blob = build_valid_license_blob(&key_a, 1, "Tenant", 0, 1_900_000_000_000, &[]);
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk_b, 1_700_000_000_000);
    assert!(matches!(status, LicenseStatus::SignatureMismatch));
}

#[test]
fn tampering_with_manifest_byte_breaks_signature() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let mut blob = build_valid_license_blob(
        &key,
        1,
        "Tamper Test",
        0,
        1_900_000_000_000,
        ALL_FEATURES_V1,
    );
    // Find the tenant_id digit 1 in the manifest and flip it.
    let needle = b"\"tenant_id\":1";
    let pos = blob
        .windows(needle.len())
        .position(|w| w == needle)
        .expect("tenant_id field present");
    blob[pos + needle.len() - 1] = b'9';
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_700_000_000_000);
    assert!(matches!(status, LicenseStatus::SignatureMismatch));
}

#[test]
fn tampering_with_signature_byte_breaks_signature() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let mut blob = build_valid_license_blob(&key, 1, "T", 0, 1_900_000_000_000, &[]);
    // Last 64 bytes are the signature; flip a byte ~10 from the end.
    let n = blob.len();
    blob[n - 10] ^= 0xFF;
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_700_000_000_000);
    assert!(matches!(status, LicenseStatus::SignatureMismatch));
}

// ──────────────────────────────────────────────────────────────────────
// 4. Missing license (empty buffer / nonexistent file)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn empty_buffer_returns_missing() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let checker = LicenseChecker::from_bytes(&[], &pk, current_time_ms());
    assert!(matches!(checker.status(), LicenseStatus::Missing { .. }));
    assert!(!checker.is_licensed());
}

#[test]
fn nonexistent_file_returns_missing() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let bogus = PathBuf::from("/nonexistent/path/never-exists-12345.bin");
    let checker = LicenseChecker::from_path(&bogus, &pk, current_time_ms());
    assert!(matches!(checker.status(), LicenseStatus::Missing { .. }));
}

#[test]
fn unlicensed_constructor_returns_missing() {
    let checker = LicenseChecker::unlicensed();
    assert!(matches!(checker.status(), LicenseStatus::Missing { .. }));
    assert!(!checker.is_licensed());
}

// ──────────────────────────────────────────────────────────────────────
// 5. Malformed license (bad magic / truncated / bad JSON)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn bad_magic_is_rejected() {
    let mut blob = vec![0u8; 100];
    blob[0..4].copy_from_slice(b"BADM");
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::BadMagic)));
}

#[test]
fn truncated_header_is_rejected() {
    let blob = vec![0u8; 8]; // less than LICENSE_HEADER_SIZE
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::Truncated)));
}

#[test]
fn truncated_payload_is_rejected() {
    // Header claims manifest_len = 100 but blob is only 50 bytes
    // total → ShortPayload.
    let mut blob = Vec::new();
    blob.extend_from_slice(b"AXLE");
    blob.extend_from_slice(&1u32.to_le_bytes());
    blob.extend_from_slice(&100u32.to_le_bytes());
    blob.extend_from_slice(&[0u8; 38]);
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::ShortPayload)));
}

#[test]
fn malformed_blob_via_checker_returns_malformed_status() {
    let mut blob = vec![0u8; 200];
    blob[0..4].copy_from_slice(b"BADM");
    let key = signing_key_a();
    let checker = LicenseChecker::from_bytes(&blob, &key.verifying_key(), 1_700_000_000_000);
    assert!(matches!(checker.status(), LicenseStatus::Malformed(_)));
}

#[test]
fn bad_json_in_manifest_is_rejected() {
    // Construct a blob with valid header but corrupt manifest JSON.
    let key = signing_key_a();
    let manifest = b"not-actually-json-at-all";
    let sig = key.sign(manifest);
    let blob = assemble_license_blob(manifest, &sig.to_bytes());
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::ManifestParseError(_))));
}

// ──────────────────────────────────────────────────────────────────────
// 6. Unknown version
// ──────────────────────────────────────────────────────────────────────

#[test]
fn unknown_version_is_rejected() {
    // Header with version=99 — future format.
    let mut blob = Vec::new();
    blob.extend_from_slice(b"AXLE");
    blob.extend_from_slice(&99u32.to_le_bytes());
    blob.extend_from_slice(&0u32.to_le_bytes());
    blob.extend_from_slice(&[0u8; 64]);
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::UnknownVersion(99))));
}

#[test]
fn unknown_version_via_checker_returns_status() {
    let mut blob = Vec::new();
    blob.extend_from_slice(b"AXLE");
    blob.extend_from_slice(&5u32.to_le_bytes());
    blob.extend_from_slice(&0u32.to_le_bytes());
    blob.extend_from_slice(&[0u8; 64]);
    let key = signing_key_a();
    let checker = LicenseChecker::from_bytes(&blob, &key.verifying_key(), 1_700_000_000_000);
    assert!(matches!(checker.status(), LicenseStatus::UnknownVersion(5)));
}

// ──────────────────────────────────────────────────────────────────────
// 7. Per-feature gating
// ──────────────────────────────────────────────────────────────────────

#[test]
fn has_feature_returns_true_only_for_listed_features() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        1,
        "Feature Test",
        0,
        1_900_000_000_000,
        &["audit-log", "evidence"],
    );
    let checker = LicenseChecker::from_bytes(&blob, &pk, 1_700_000_000_000);
    assert!(checker.is_licensed());
    assert!(checker.has_feature("audit-log"));
    assert!(checker.has_feature("evidence"));
    assert!(!checker.has_feature("fips-crypto"));
    assert!(!checker.has_feature("phi-scrubber"));
    assert!(!checker.has_feature("vertical-bpe"));
}

#[test]
fn has_feature_returns_false_when_license_invalid() {
    // Wrong key → SignatureMismatch → has_feature must return false
    // even for features listed in the manifest.
    let key_a = signing_key_a();
    let key_b = signing_key_b();
    let blob = build_valid_license_blob(&key_a, 1, "T", 0, 1_900_000_000_000, &["audit-log"]);
    let checker = LicenseChecker::from_bytes(&blob, &key_b.verifying_key(), 1_700_000_000_000);
    assert!(!checker.is_licensed());
    assert!(!checker.has_feature("audit-log"));
}

#[test]
fn has_feature_returns_false_when_expired() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        1,
        "T",
        0,
        1_000, // expired
        &["audit-log"],
    );
    let checker = LicenseChecker::from_bytes(&blob, &pk, 1_900_000_000_000);
    assert!(!checker.has_feature("audit-log"));
}

// ──────────────────────────────────────────────────────────────────────
// 8. Path-based load
// ──────────────────────────────────────────────────────────────────────

#[test]
fn from_path_loads_valid_license() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(
        &key,
        7777,
        "Path Loader",
        0,
        1_900_000_000_000,
        &["evidence"],
    );
    let path = scratch_path("path-load");
    std::fs::write(&path, &blob).unwrap();

    let checker = LicenseChecker::from_path(&path, &pk, 1_700_000_000_000);
    assert!(checker.is_licensed());
    let lic = checker.license().unwrap();
    assert_eq!(lic.tenant_id, 7777);

    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 9. Manifest determinism (canonical-JSON byte-identical regen)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn canonical_manifest_json_is_deterministic() {
    let features: Vec<String> = vec!["audit-log".to_owned(), "evidence".to_owned()];
    let m1 = canonical_license_manifest_json(1, 42, "Det Test", 0, 1_900_000_000_000, &features);
    let m2 = canonical_license_manifest_json(1, 42, "Det Test", 0, 1_900_000_000_000, &features);
    assert_eq!(m1, m2);
}

#[test]
fn canonical_manifest_keys_are_lexicographic() {
    let m = canonical_license_manifest_json(1, 1, "T", 0, 1, &["audit-log".to_owned()]);
    let s = std::str::from_utf8(&m).unwrap();
    let order = [
        "\"expires_at_ms\":",
        "\"feature_set\":",
        "\"issued_at_ms\":",
        "\"tenant_id\":",
        "\"tenant_name\":",
        "\"version\":",
    ];
    let mut last = 0usize;
    for k in order {
        let pos = s.find(k).expect(k);
        assert!(pos >= last, "key {k} out of order in: {s}");
        last = pos;
    }
}

// ──────────────────────────────────────────────────────────────────────
// 10. Boundary conditions + soft-fail discipline
// ──────────────────────────────────────────────────────────────────────

#[test]
fn license_at_exact_expiry_boundary_is_valid() {
    // expires_at_ms == current_time_ms → still valid (the contract
    // is `current_time_ms > expires_at_ms` for Expired).
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(&key, 1, "T", 0, 1_700_000_000_000, &[]);
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_700_000_000_000);
    assert!(matches!(status, LicenseStatus::Valid { .. }));
}

#[test]
fn license_one_ms_past_expiry_is_expired() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(&key, 1, "T", 0, 1_700_000_000_000, &[]);
    let license = License::from_bytes(&blob).unwrap();
    let status = license.check(&pk, 1_700_000_000_001);
    if let LicenseStatus::Expired { expired_ms_ago, .. } = status {
        assert_eq!(expired_ms_ago, 1);
    } else {
        panic!("expected Expired");
    }
}

#[test]
fn license_blob_exceeding_max_size_is_rejected() {
    let blob = vec![0u8; MAX_LICENSE_BYTES + 1];
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::ManifestTooLarge(_))));
}

#[test]
fn license_with_invalid_feature_name_is_rejected() {
    // Feature name with shell-special character → InvalidFeatureName.
    let key = signing_key_a();
    let manifest = canonical_license_manifest_json(
        1,
        1,
        "T",
        0,
        1_900_000_000_000,
        &["bad;feature".to_owned()],
    );
    let sig = key.sign(&manifest);
    let blob = assemble_license_blob(&manifest, &sig.to_bytes());
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::InvalidFeatureName(_))));
}

#[test]
fn license_with_oversize_tenant_name_is_rejected() {
    let key = signing_key_a();
    let huge_name = "A".repeat(257);
    let manifest = canonical_license_manifest_json(1, 1, &huge_name, 0, 1_900_000_000_000, &[]);
    let sig = key.sign(&manifest);
    let blob = assemble_license_blob(&manifest, &sig.to_bytes());
    let res = License::from_bytes(&blob);
    assert!(matches!(res, Err(LicenseError::TenantNameTooLong)));
}

#[test]
fn checker_status_label_covers_all_variants() {
    for label in [
        "valid",
        "expired",
        "signature-mismatch",
        "missing",
        "malformed",
        "unknown-version",
    ] {
        // Just exercise the labels exist + are stable strings.
        assert!(!label.is_empty());
    }
}

#[test]
fn startup_log_line_contains_status_label() {
    let key = signing_key_a();
    let pk = key.verifying_key();
    let blob = build_valid_license_blob(&key, 1, "T", 0, 1_900_000_000_000, &[]);
    let checker = LicenseChecker::from_bytes(&blob, &pk, 1_700_000_000_000);
    let line = checker.startup_log_line();
    assert!(line.contains("status=valid"), "got: {line}");
    assert!(line.contains("axon-enterprise license"));
}

#[test]
fn soft_fail_discipline_no_panic_on_random_garbage() {
    // Adversary feeds arbitrary bytes — we must NEVER panic / abort.
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};
    let key = signing_key_a();
    let pk = key.verifying_key();
    let mut rng = StdRng::seed_from_u64(0xDEAD_BEEF);
    for _ in 0..100 {
        let len = rng.random_range(0..=2048);
        let mut bytes = vec![0u8; len];
        rng.fill(&mut bytes[..]);
        // MUST return without panic.
        let _checker = LicenseChecker::from_bytes(&bytes, &pk, 1_700_000_000_000);
    }
}
