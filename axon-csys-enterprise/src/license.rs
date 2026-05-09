//! § Fase 27.j — License-key enforcement runtime check.
//!
//! Per D13 ratified 2026-05-09: runtime check at first use of any
//! enterprise kernel; tenant-id signed config from license server
//! (Ed25519 verify); **soft-fail with degraded-posture warning when
//! license missing/expired/tampered**. NO hard gate that crashes the
//! supervisor — the kernel keeps working but the application emits
//! an audit-log entry stating "running unlicensed" so the adopter
//! is aware + can renew. Hard gate would make the kernel a security
//! risk (an adversary could DoS the supervisor by tampering with
//! the license file).
//!
//! # License binary format
//!
//! Adopter receives a single binary file from Bemarking AI's license
//! server signed against the authoritative Bemarking public key:
//!
//!   offset  bytes  field
//!   ──────  ─────  ─────
//!   0       4      magic "AXLE" (0x41 0x58 0x4C 0x45)
//!   4       4      version u32 (= 1 for v0.1.x)
//!   8       4      manifest_len u32
//!   12      N      manifest bytes (canonical JSON; same emitter as
//!                  evidence packager — sorted keys, no whitespace,
//!                  deterministic numeric formatting)
//!   12+N    64     Ed25519 signature over manifest bytes (RFC 8032)
//!
//! # Manifest schema
//!
//! ```json
//! {
//!   "expires_at_ms": 1746536000000,
//!   "feature_set": ["audit-log", "evidence", "fips-crypto",
//!                   "phi-scrubber", "vertical-bpe"],
//!   "issued_at_ms": 1715000000000,
//!   "tenant_id": 12345,
//!   "tenant_name": "Acme Healthcare LLC",
//!   "version": 1
//! }
//! ```
//!
//! Top-level keys lexicographic; same canonical-JSON convention as
//! the evidence packager so a single canonical-JSON helper covers
//! both. Adopters never edit the file by hand — license server
//! emits it; the binary checker reads it.
//!
//! # Soft-fail posture (D13)
//!
//! Every public entry point in this module returns a [`LicenseStatus`]
//! variant; NONE of them panic, abort, or unconditionally return Err.
//! Adopters MAY (but are not required to) gate enterprise kernels
//! based on the status:
//!
//! ```rust,ignore
//! use axon_csys_enterprise::license::{LicenseChecker, LicenseStatus};
//!
//! let checker = LicenseChecker::from_path("/etc/axon/license.bin", now_ms());
//! match checker.status() {
//!     LicenseStatus::Valid { .. } => { /* proceed normally */ }
//!     other => {
//!         tracing::warn!("axon-enterprise license: {other:?} — running unlicensed");
//!         emit_audit_log_unlicensed_event();
//!         // Continue execution. Per D13 the kernel is NOT gated.
//!     }
//! }
//! ```
//!
//! For commercial license arrangements, contact licensing@bemarking.com.co.

use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use ed25519_dalek::{Signature, Verifier, VerifyingKey};

// ──────────────────────────────────────────────────────────────────────
// Binary format constants
// ──────────────────────────────────────────────────────────────────────

const LICENSE_MAGIC: &[u8; 4] = b"AXLE";
const LICENSE_VERSION_V1: u32 = 1;
const LICENSE_HEADER_SIZE: usize = 12; // magic(4) + version(4) + manifest_len(4)
const ED25519_SIGNATURE_SIZE: usize = 64;
const ED25519_PUBKEY_SIZE: usize = 32;

/// Maximum reasonable license file size (16 KiB). Larger blobs are
/// rejected to prevent untrusted-input DoS via giant manifest_len
/// fields.
pub const MAX_LICENSE_BYTES: usize = 16 * 1024;

// ──────────────────────────────────────────────────────────────────────
// Public surface
// ──────────────────────────────────────────────────────────────────────

/// Parsed license. Returned by [`License::from_bytes`] for callers
/// who want the metadata regardless of validation status. Adopters
/// who want a single status check should use [`LicenseChecker`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct License {
    /// Format version (== 1 for v0.1.x).
    pub version: u32,
    /// Tenant identifier — recorded against every audit-log event +
    /// every evidence-packager bundle so a license can be correlated
    /// against deployments downstream.
    pub tenant_id: u64,
    /// Human-readable tenant name (max 256 bytes UTF-8).
    pub tenant_name: String,
    /// License issuance time, Unix epoch ms.
    pub issued_at_ms: i64,
    /// License expiry time, Unix epoch ms. Past this point the
    /// checker reports [`LicenseStatus::Expired`].
    pub expires_at_ms: i64,
    /// List of enabled feature names. v0.1.0 ships:
    /// `"audit-log"`, `"evidence"`, `"fips-crypto"`, `"phi-scrubber"`,
    /// `"vertical-bpe"`. Future fases may extend this set.
    pub feature_set: Vec<String>,
    /// The canonical-JSON manifest bytes that were signed. Stored so
    /// repeated `check` calls don't re-canonicalize.
    manifest_bytes: Vec<u8>,
    /// Ed25519 signature (64 bytes per RFC 8032).
    signature: [u8; ED25519_SIGNATURE_SIZE],
}

/// Result of a runtime license check. Soft-fail variants carry the
/// detail an adopter audit-log entry needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LicenseStatus {
    /// License signature verified + within expiry window.
    Valid {
        tenant_id: u64,
        tenant_name: String,
        expires_at_ms: i64,
        /// Days until expiry (truncated; negative is impossible here
        /// because Expired is its own variant).
        days_until_expiry: i64,
        feature_set: Vec<String>,
    },
    /// Signature verified but `expires_at_ms < current_time_ms`.
    Expired {
        tenant_id: u64,
        expired_ms_ago: i64,
        feature_set: Vec<String>,
    },
    /// Signature does not verify against the supplied public key.
    /// Likely causes: tampered license file, license signed by a
    /// different key (e.g. adopter forged), key rotation not
    /// reflected in this build.
    SignatureMismatch,
    /// License file not present on disk / could not be read.
    Missing { reason: String },
    /// License file present but did not parse as a v1 license.
    /// Likely cause: corruption / wrong file path / format bump
    /// from a future axon-enterprise version.
    Malformed(String),
    /// Format version is not v1. Future axon-enterprise versions
    /// MAY ship a v2 format (with extended fields); v0.1.x rejects
    /// unknown versions explicitly so an out-of-band format bump
    /// produces a clear status rather than a silent acceptance.
    UnknownVersion(u32),
}

impl LicenseStatus {
    /// Convenience: true iff the variant is [`LicenseStatus::Valid`].
    /// Adopters in the "all features enabled when licensed" pattern
    /// can short-circuit on this.
    pub fn is_valid(&self) -> bool {
        matches!(self, Self::Valid { .. })
    }

    /// Stable label suitable for audit-log emission + telemetry.
    pub fn label(&self) -> &'static str {
        match self {
            Self::Valid { .. } => "valid",
            Self::Expired { .. } => "expired",
            Self::SignatureMismatch => "signature-mismatch",
            Self::Missing { .. } => "missing",
            Self::Malformed(_) => "malformed",
            Self::UnknownVersion(_) => "unknown-version",
        }
    }
}

impl std::fmt::Display for LicenseStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Valid {
                tenant_id,
                tenant_name,
                expires_at_ms,
                days_until_expiry,
                ..
            } => write!(
                f,
                "license valid: tenant_id={tenant_id} name={tenant_name:?} \
                 expires_at_ms={expires_at_ms} (~{days_until_expiry} days)"
            ),
            Self::Expired {
                tenant_id,
                expired_ms_ago,
                ..
            } => write!(
                f,
                "license expired: tenant_id={tenant_id} expired_ms_ago={expired_ms_ago}"
            ),
            Self::SignatureMismatch => {
                write!(f, "license signature mismatch — running unlicensed")
            }
            Self::Missing { reason } => {
                write!(f, "license missing: {reason} — running unlicensed")
            }
            Self::Malformed(msg) => write!(f, "license malformed: {msg}"),
            Self::UnknownVersion(v) => {
                write!(
                    f,
                    "license version {v} unknown to this axon-enterprise build"
                )
            }
        }
    }
}

/// Errors from the LOW-LEVEL parser. Adopters using [`LicenseChecker`]
/// never see these directly — they are mapped into [`LicenseStatus`]
/// soft-fail variants. Exposed here for tooling that wants raw parse
/// diagnostics (e.g. license-issuance test harnesses).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LicenseError {
    /// Buffer too short to contain a license header.
    Truncated,
    /// Magic bytes did not match `"AXLE"`.
    BadMagic,
    /// Format version not recognised by this build.
    UnknownVersion(u32),
    /// manifest_len field exceeds the buffer / `MAX_LICENSE_BYTES`.
    ManifestTooLarge(u32),
    /// Buffer ends before the declared manifest + signature region.
    ShortPayload,
    /// Manifest bytes did not parse as canonical JSON.
    ManifestParseError(String),
    /// Required manifest field missing.
    ManifestFieldMissing(&'static str),
    /// Tenant name exceeds 256 bytes.
    TenantNameTooLong,
    /// Feature name contains invalid characters or exceeds 64 bytes.
    InvalidFeatureName(String),
}

impl std::fmt::Display for LicenseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Truncated => write!(f, "license: buffer too short for header"),
            Self::BadMagic => write!(f, "license: magic bytes did not match AXLE"),
            Self::UnknownVersion(v) => write!(f, "license: format version {v} unknown"),
            Self::ManifestTooLarge(len) => {
                write!(f, "license: manifest_len {len} exceeds {MAX_LICENSE_BYTES}")
            }
            Self::ShortPayload => write!(f, "license: buffer ends before declared payload"),
            Self::ManifestParseError(msg) => {
                write!(f, "license: manifest JSON parse: {msg}")
            }
            Self::ManifestFieldMissing(field) => {
                write!(f, "license: manifest missing field {field:?}")
            }
            Self::TenantNameTooLong => write!(f, "license: tenant_name exceeds 256 bytes"),
            Self::InvalidFeatureName(s) => {
                write!(f, "license: invalid feature name {s:?}")
            }
        }
    }
}

impl std::error::Error for LicenseError {}

// ──────────────────────────────────────────────────────────────────────
// License — parser + verifier
// ──────────────────────────────────────────────────────────────────────

impl License {
    /// Parse a license blob from raw bytes. Validates the magic +
    /// version + manifest layout but does NOT verify the signature.
    /// Use [`License::check`] to perform signature verification +
    /// expiry check together.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, LicenseError> {
        if bytes.len() < LICENSE_HEADER_SIZE {
            return Err(LicenseError::Truncated);
        }
        if bytes.len() > MAX_LICENSE_BYTES {
            return Err(LicenseError::ManifestTooLarge(bytes.len() as u32));
        }
        if &bytes[0..4] != LICENSE_MAGIC {
            return Err(LicenseError::BadMagic);
        }
        let version = u32::from_le_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]);
        if version != LICENSE_VERSION_V1 {
            return Err(LicenseError::UnknownVersion(version));
        }
        let manifest_len = u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]) as usize;
        if manifest_len > MAX_LICENSE_BYTES {
            return Err(LicenseError::ManifestTooLarge(manifest_len as u32));
        }
        let manifest_end = LICENSE_HEADER_SIZE + manifest_len;
        let total_end = manifest_end + ED25519_SIGNATURE_SIZE;
        if bytes.len() < total_end {
            return Err(LicenseError::ShortPayload);
        }

        let manifest_bytes = bytes[LICENSE_HEADER_SIZE..manifest_end].to_vec();
        let mut signature = [0u8; ED25519_SIGNATURE_SIZE];
        signature.copy_from_slice(&bytes[manifest_end..total_end]);

        // Parse the manifest JSON.
        let manifest = parse_manifest(&manifest_bytes)?;

        Ok(Self {
            version: manifest.version,
            tenant_id: manifest.tenant_id,
            tenant_name: manifest.tenant_name,
            issued_at_ms: manifest.issued_at_ms,
            expires_at_ms: manifest.expires_at_ms,
            feature_set: manifest.feature_set,
            manifest_bytes,
            signature,
        })
    }

    /// Run the full check: signature verification against `public_key`,
    /// then expiry comparison against `current_time_ms`. Returns one of
    /// the soft-fail [`LicenseStatus`] variants. Never panics, never
    /// returns Err — D13 soft-fail discipline.
    pub fn check(&self, public_key: &VerifyingKey, current_time_ms: i64) -> LicenseStatus {
        // Signature first — a tampered license is "untrusted" before
        // any expiry decision can be made.
        let sig = Signature::from_bytes(&self.signature);
        if public_key.verify(&self.manifest_bytes, &sig).is_err() {
            return LicenseStatus::SignatureMismatch;
        }
        // Expiry.
        if current_time_ms > self.expires_at_ms {
            return LicenseStatus::Expired {
                tenant_id: self.tenant_id,
                expired_ms_ago: current_time_ms - self.expires_at_ms,
                feature_set: self.feature_set.clone(),
            };
        }
        // Valid.
        let days = (self.expires_at_ms - current_time_ms) / (1000 * 60 * 60 * 24);
        LicenseStatus::Valid {
            tenant_id: self.tenant_id,
            tenant_name: self.tenant_name.clone(),
            expires_at_ms: self.expires_at_ms,
            days_until_expiry: days,
            feature_set: self.feature_set.clone(),
        }
    }

    /// Convenience: true iff `feature` is present in the licensed
    /// feature set. Does NOT verify the license — pair with `check`
    /// for end-to-end licensed-feature dispatch.
    pub fn has_feature(&self, feature: &str) -> bool {
        self.feature_set.iter().any(|f| f == feature)
    }

    /// The signed manifest bytes — exposed for tooling that wants to
    /// re-verify with a different public key.
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest_bytes
    }

    /// The 64-byte Ed25519 signature.
    pub fn signature(&self) -> &[u8; ED25519_SIGNATURE_SIZE] {
        &self.signature
    }
}

// ──────────────────────────────────────────────────────────────────────
// LicenseChecker — adopter-facing soft-fail wrapper
// ──────────────────────────────────────────────────────────────────────

/// Soft-fail wrapper: load a license at startup + cache the status.
/// All entry points return non-error variants; adopters who need
/// raw parse errors should use [`License::from_bytes`].
#[derive(Debug, Clone)]
pub struct LicenseChecker {
    status: LicenseStatus,
    /// Cached for `feature_status` queries.
    license: Option<License>,
}

impl LicenseChecker {
    /// Load a license file from `path`, verify against `public_key`,
    /// and store the status. On any error (file missing, malformed,
    /// signature mismatch) the checker stores the appropriate
    /// soft-fail variant — does NOT propagate an error.
    ///
    /// `current_time_ms` is the wall-clock time used for expiry
    /// comparison. Adopters typically pass
    /// `chrono::Utc::now().timestamp_millis()`.
    pub fn from_path(path: &Path, public_key: &VerifyingKey, current_time_ms: i64) -> Self {
        match std::fs::read(path) {
            Ok(bytes) => Self::from_bytes(&bytes, public_key, current_time_ms),
            Err(e) => Self {
                status: LicenseStatus::Missing {
                    reason: format!("read failed: {e}"),
                },
                license: None,
            },
        }
    }

    /// Same as `from_path` but consumes raw bytes — useful for
    /// adopters who fetch the license blob from a secrets manager
    /// or a vault.
    pub fn from_bytes(bytes: &[u8], public_key: &VerifyingKey, current_time_ms: i64) -> Self {
        if bytes.is_empty() {
            return Self {
                status: LicenseStatus::Missing {
                    reason: "empty buffer".to_owned(),
                },
                license: None,
            };
        }
        match License::from_bytes(bytes) {
            Ok(license) => {
                let status = license.check(public_key, current_time_ms);
                Self {
                    status,
                    license: Some(license),
                }
            }
            Err(LicenseError::UnknownVersion(v)) => Self {
                status: LicenseStatus::UnknownVersion(v),
                license: None,
            },
            Err(other) => Self {
                status: LicenseStatus::Malformed(format!("{other}")),
                license: None,
            },
        }
    }

    /// Construct a checker representing "no license file" — adopter
    /// chose to run unlicensed. Equivalent to `from_bytes(&[])`.
    pub fn unlicensed() -> Self {
        Self {
            status: LicenseStatus::Missing {
                reason: "adopter opted out".to_owned(),
            },
            license: None,
        }
    }

    /// Read the cached check result.
    pub fn status(&self) -> &LicenseStatus {
        &self.status
    }

    /// True iff the cached status is `Valid`. Convenience for
    /// adopters dispatching enterprise kernels in the
    /// "all features enabled when licensed" pattern.
    pub fn is_licensed(&self) -> bool {
        self.status.is_valid()
    }

    /// True iff the license is valid AND `feature` is present in
    /// the feature_set. False on every other status. Use this when
    /// dispatching specific enterprise kernels (e.g. only enable the
    /// FIPS path if the license includes `fips-crypto`).
    pub fn has_feature(&self, feature: &str) -> bool {
        if !self.status.is_valid() {
            return false;
        }
        self.license
            .as_ref()
            .map(|l| l.has_feature(feature))
            .unwrap_or(false)
    }

    /// The cached license (if parsing succeeded). Returns `None` for
    /// `Missing`, `Malformed`, `UnknownVersion`, or `SignatureMismatch`
    /// statuses. Adopters typically don't need this; exposed for
    /// audit-log metadata emission.
    pub fn license(&self) -> Option<&License> {
        self.license.as_ref()
    }

    /// Convenience: emit a single human-readable line for adopter
    /// startup logging. Adopters who use `tracing` / `slog` should
    /// pass this string into a structured field rather than parse
    /// it again.
    pub fn startup_log_line(&self) -> String {
        format!(
            "axon-enterprise license: status={} ({})",
            self.status.label(),
            self.status
        )
    }
}

// ──────────────────────────────────────────────────────────────────────
// Helpers for adopters who want the canonical "now" timestamp.
// ──────────────────────────────────────────────────────────────────────

/// Convenience wrapper around `SystemTime::now()` returning Unix
/// epoch ms as `i64`. Saturates to 0 on clock-before-epoch (which
/// shouldn't happen on any sane host but is defensive).
pub fn current_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

// ──────────────────────────────────────────────────────────────────────
// Internal: canonical JSON manifest emit + parse
//
// Same byte-deterministic posture as the evidence packager — sorted
// keys, no whitespace, deterministic numeric formatting. A separate
// pair of functions (rather than reusing `evidence::canonical_*`)
// because the license schema differs from the evidence manifest, but
// the conventions match exactly.
// ──────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct ParsedManifest {
    version: u32,
    tenant_id: u64,
    tenant_name: String,
    issued_at_ms: i64,
    expires_at_ms: i64,
    feature_set: Vec<String>,
}

fn parse_manifest(bytes: &[u8]) -> Result<ParsedManifest, LicenseError> {
    let s = std::str::from_utf8(bytes)
        .map_err(|e| LicenseError::ManifestParseError(format!("UTF-8: {e}")))?;
    let mut p = JsonParser { s, pos: 0 };
    p.skip_ws();
    p.expect(b'{')?;

    let mut version: Option<u32> = None;
    let mut tenant_id: Option<u64> = None;
    let mut tenant_name: Option<String> = None;
    let mut issued_at_ms: Option<i64> = None;
    let mut expires_at_ms: Option<i64> = None;
    let mut feature_set: Option<Vec<String>> = None;

    let mut first = true;
    loop {
        p.skip_ws();
        if p.peek() == Some(b'}') {
            break;
        }
        if !first {
            p.expect(b',')?;
            p.skip_ws();
        }
        first = false;
        let key = p.parse_string()?;
        p.skip_ws();
        p.expect(b':')?;
        p.skip_ws();
        match key.as_str() {
            "version" => version = Some(p.parse_u64()? as u32),
            "tenant_id" => tenant_id = Some(p.parse_u64()?),
            "tenant_name" => {
                let name = p.parse_string()?;
                if name.len() > 256 {
                    return Err(LicenseError::TenantNameTooLong);
                }
                tenant_name = Some(name);
            }
            "issued_at_ms" => issued_at_ms = Some(p.parse_i64()?),
            "expires_at_ms" => expires_at_ms = Some(p.parse_i64()?),
            "feature_set" => feature_set = Some(p.parse_string_array()?),
            other => {
                return Err(LicenseError::ManifestParseError(format!(
                    "unexpected key {other:?}"
                )))
            }
        }
    }

    Ok(ParsedManifest {
        version: version.ok_or(LicenseError::ManifestFieldMissing("version"))?,
        tenant_id: tenant_id.ok_or(LicenseError::ManifestFieldMissing("tenant_id"))?,
        tenant_name: tenant_name.ok_or(LicenseError::ManifestFieldMissing("tenant_name"))?,
        issued_at_ms: issued_at_ms.ok_or(LicenseError::ManifestFieldMissing("issued_at_ms"))?,
        expires_at_ms: expires_at_ms.ok_or(LicenseError::ManifestFieldMissing("expires_at_ms"))?,
        feature_set: feature_set.ok_or(LicenseError::ManifestFieldMissing("feature_set"))?,
    })
}

/// Emit a canonical-JSON manifest from the supplied fields. Public
/// so license-issuance tooling can re-use it (the test pack uses it
/// to construct test licenses on the fly).
pub fn canonical_license_manifest_json(
    version: u32,
    tenant_id: u64,
    tenant_name: &str,
    issued_at_ms: i64,
    expires_at_ms: i64,
    feature_set: &[String],
) -> Vec<u8> {
    let mut out =
        String::with_capacity(256 + feature_set.iter().map(|f| f.len() + 4).sum::<usize>());
    out.push('{');
    // Keys lexicographic: expires_at_ms, feature_set, issued_at_ms,
    // tenant_id, tenant_name, version.
    out.push_str("\"expires_at_ms\":");
    out.push_str(&expires_at_ms.to_string());
    out.push(',');
    out.push_str("\"feature_set\":[");
    for (i, f) in feature_set.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        json_emit_string(&mut out, f);
    }
    out.push_str("],");
    out.push_str("\"issued_at_ms\":");
    out.push_str(&issued_at_ms.to_string());
    out.push(',');
    out.push_str("\"tenant_id\":");
    out.push_str(&tenant_id.to_string());
    out.push(',');
    out.push_str("\"tenant_name\":");
    json_emit_string(&mut out, tenant_name);
    out.push(',');
    out.push_str("\"version\":");
    out.push_str(&version.to_string());
    out.push('}');
    out.into_bytes()
}

/// Compose the binary license envelope (magic, version, manifest_len,
/// manifest bytes, signature). Mostly useful for license-issuance test
/// harnesses; production licenses are emitted by the Bemarking AI
/// license server which uses an out-of-band Ed25519 signing key.
pub fn assemble_license_blob(manifest: &[u8], signature: &[u8; 64]) -> Vec<u8> {
    let mut out = Vec::with_capacity(LICENSE_HEADER_SIZE + manifest.len() + 64);
    out.extend_from_slice(LICENSE_MAGIC);
    out.extend_from_slice(&LICENSE_VERSION_V1.to_le_bytes());
    out.extend_from_slice(&(manifest.len() as u32).to_le_bytes());
    out.extend_from_slice(manifest);
    out.extend_from_slice(signature);
    out
}

fn json_emit_string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                use std::fmt::Write;
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

// ──────────────────────────────────────────────────────────────────────
// Minimal canonical-JSON parser (subset: object with string keys,
// string / integer / array-of-string values). Same shape as the
// evidence packager's parser; a future refactor could share a single
// helper module, deferred to keep this file self-contained.
// ──────────────────────────────────────────────────────────────────────

struct JsonParser<'a> {
    s: &'a str,
    pos: usize,
}

impl<'a> JsonParser<'a> {
    fn peek(&self) -> Option<u8> {
        self.s.as_bytes().get(self.pos).copied()
    }

    fn skip_ws(&mut self) {
        while let Some(b) = self.peek() {
            if b == b' ' || b == b'\t' || b == b'\n' || b == b'\r' {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn expect(&mut self, b: u8) -> Result<(), LicenseError> {
        match self.peek() {
            Some(c) if c == b => {
                self.pos += 1;
                Ok(())
            }
            other => Err(LicenseError::ManifestParseError(format!(
                "expected {:?} at byte {}, got {:?}",
                b as char,
                self.pos,
                other.map(|c| c as char)
            ))),
        }
    }

    fn parse_string(&mut self) -> Result<String, LicenseError> {
        self.expect(b'"')?;
        let mut out = String::new();
        let bytes = self.s.as_bytes();
        while self.pos < bytes.len() {
            let b = bytes[self.pos];
            if b == b'"' {
                self.pos += 1;
                return Ok(out);
            }
            if b == b'\\' {
                self.pos += 1;
                if self.pos >= bytes.len() {
                    return Err(LicenseError::ManifestParseError(
                        "unterminated escape".into(),
                    ));
                }
                let esc = bytes[self.pos];
                self.pos += 1;
                match esc {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'b' => out.push('\x08'),
                    b'f' => out.push('\x0c'),
                    b'u' => {
                        if self.pos + 4 > bytes.len() {
                            return Err(LicenseError::ManifestParseError(
                                "short \\u escape".into(),
                            ));
                        }
                        let hex =
                            std::str::from_utf8(&bytes[self.pos..self.pos + 4]).map_err(|_| {
                                LicenseError::ManifestParseError("non-UTF-8 \\u escape".into())
                            })?;
                        let code = u32::from_str_radix(hex, 16).map_err(|_| {
                            LicenseError::ManifestParseError("invalid \\u hex".into())
                        })?;
                        self.pos += 4;
                        if let Some(c) = char::from_u32(code) {
                            out.push(c);
                        } else {
                            return Err(LicenseError::ManifestParseError(
                                "invalid \\u codepoint".into(),
                            ));
                        }
                    }
                    other => {
                        return Err(LicenseError::ManifestParseError(format!(
                            "unknown escape \\{}",
                            other as char
                        )))
                    }
                }
            } else {
                let ch_len = utf8_char_len(b);
                if self.pos + ch_len > bytes.len() {
                    return Err(LicenseError::ManifestParseError(
                        "truncated UTF-8 in string".into(),
                    ));
                }
                let ch_bytes = &bytes[self.pos..self.pos + ch_len];
                let ch_str = std::str::from_utf8(ch_bytes)
                    .map_err(|_| LicenseError::ManifestParseError("invalid UTF-8".into()))?;
                out.push_str(ch_str);
                self.pos += ch_len;
            }
        }
        Err(LicenseError::ManifestParseError(
            "unterminated string".into(),
        ))
    }

    fn parse_u64(&mut self) -> Result<u64, LicenseError> {
        let start = self.pos;
        let bytes = self.s.as_bytes();
        while self.pos < bytes.len() && bytes[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        if start == self.pos {
            return Err(LicenseError::ManifestParseError("expected u64".into()));
        }
        self.s[start..self.pos]
            .parse::<u64>()
            .map_err(|e| LicenseError::ManifestParseError(format!("u64: {e}")))
    }

    fn parse_i64(&mut self) -> Result<i64, LicenseError> {
        let start = self.pos;
        let bytes = self.s.as_bytes();
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        while self.pos < bytes.len() && bytes[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        if start == self.pos || (start + 1 == self.pos && bytes[start] == b'-') {
            return Err(LicenseError::ManifestParseError("expected i64".into()));
        }
        self.s[start..self.pos]
            .parse::<i64>()
            .map_err(|e| LicenseError::ManifestParseError(format!("i64: {e}")))
    }

    fn parse_string_array(&mut self) -> Result<Vec<String>, LicenseError> {
        self.expect(b'[')?;
        let mut out = Vec::new();
        let mut first = true;
        loop {
            self.skip_ws();
            if self.peek() == Some(b']') {
                self.pos += 1;
                return Ok(out);
            }
            if !first {
                self.expect(b',')?;
                self.skip_ws();
            }
            first = false;
            let s = self.parse_string()?;
            // Validate feature name: ASCII alphanumeric + dash; max
            // 64 bytes. Rejects anything that could be a "wildcard"
            // or path-traversal-style escape.
            if s.len() > 64
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
            {
                return Err(LicenseError::InvalidFeatureName(s));
            }
            out.push(s);
        }
    }
}

fn utf8_char_len(b: u8) -> usize {
    // Branches collapsed for clippy::if_same_then_else: ASCII (0x00..0x7F)
    // and stray continuation bytes (0x80..0xBF) both consume a single
    // byte step in the parser. We treat invalid leading bytes as a
    // single-byte step too — defensive for malformed UTF-8 in the
    // manifest (which the parser will then reject downstream).
    if b < 0xc0 {
        1
    } else if b < 0xe0 {
        2
    } else if b < 0xf0 {
        3
    } else {
        4
    }
}

// ──────────────────────────────────────────────────────────────────────
// Re-export the Ed25519 types from `evidence` so adopters who already
// imported them for evidence signing don't need a second `use`.
// ──────────────────────────────────────────────────────────────────────

pub use crate::evidence::{Ed25519SigningKey, Ed25519VerifyingKey};

#[doc(hidden)]
pub const ED25519_PUBKEY_LEN: usize = ED25519_PUBKEY_SIZE;
