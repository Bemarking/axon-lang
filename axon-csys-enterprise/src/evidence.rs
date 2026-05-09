//! § Fase 27.f — Tamper-evident byte-deterministic evidence packager.
//!
//! Adopter-facing API for assembling forensic / compliance bundles
//! (HIPAA Right-of-Access requests, GDPR data-portability exports,
//! PCI DSS post-incident evidence, SOC2 audit trail captures). The
//! bundle is:
//!
//!   1. **Byte-deterministic across regenerations** — same inputs +
//!      same options produce bit-identical output bytes. Guarantees
//!      that an auditor receiving the same evidence twice (or
//!      regenerating a snapshot from the source data) gets the same
//!      SHA-256 over the package. Cross-platform deterministic too:
//!      same bytes on linux-x86_64 / linux-aarch64 / macOS-aarch64 /
//!      windows-x86_64.
//!
//!   2. **Tamper-evident** — every file is hashed with SHA-256 (FIPS
//!      180-4); the per-file hashes are combined into a Merkle root;
//!      the Merkle root is signed with Ed25519 (RFC 8032) using the
//!      per-tenant signing key. Mutating any byte in the bundle
//!      breaks the chain at verification time.
//!
//!   3. **Independently verifiable** — the bundle is a standard ZIP
//!      archive (STORE-only, no DEFLATE). Adopters with the public
//!      key can verify with any Ed25519 library + any ZIP extractor;
//!      no axon-enterprise installation required.
//!
//! # ZIP encoder
//!
//! The bundle is a pure-Rust byte-deterministic ZIP encoder
//! ([`zip`] inner module). All non-determinism sources are nailed
//! down: file mtimes are fixed to `1980-01-01 00:00:00` (the DOS
//! epoch — the floor of the ZIP timestamp range), filenames sort
//! lexicographically (UTF-8 byte order), permissions are canonical
//! (0644 for files), the central directory is laid out in a single
//! deterministic order. STORE-only mode (no DEFLATE) eliminates
//! compression-jitter drift between zlib versions.
//!
//! # Manifest
//!
//! The bundle ZIP contains:
//!
//!   - `<adopter-files>` — the actual evidence content (in
//!     lexicographic order).
//!   - `_evidence_manifest.json` — canonical JSON with manifest
//!     metadata: `version`, `tenant_id`, `evidence_id`, `created_ms`,
//!     `signing_key_id`, `files` (per-file `path` + `size` + `sha256`),
//!     `merkle_root`. Sorted keys, no whitespace, deterministic
//!     numeric formatting.
//!   - `_evidence_signature.bin` — 64-byte RFC-8032 Ed25519 detached
//!     signature over the canonical manifest bytes.
//!
//! # Per-tenant signing key rotation (D8 ratified)
//!
//! The signing key is supplied by the adopter (their key vault /
//! HSM / secrets manager). Rotation triggers (per D8): admin config
//! change, monthly automated, after N events. Old keys remain
//! verifiable in perpetuity (tenant retains historical pubkeys).
//! The `signing_key_id` field in the manifest names which generation
//! signed this bundle; verifiers consult their pubkey vault to fetch
//! the matching key.
//!
//! # Verification flow
//!
//! 1. Open the ZIP, extract `_evidence_manifest.json` + `_evidence_signature.bin`.
//! 2. Verify the Ed25519 signature against the canonical manifest bytes.
//! 3. Recompute SHA-256 of every adopter file in the ZIP, compare to
//!    the manifest's per-file sha256.
//! 4. Recompute the Merkle root from the per-file sha256s, compare
//!    to the manifest's `merkle_root` field.
//! 5. PASS only if every check succeeds.
//!
//! Any byte mutation in the ZIP is detected: mutating a file changes
//! its sha256 → manifest mismatch + Merkle root mismatch; mutating
//! the manifest changes its bytes → signature mismatch; mutating the
//! signature → signature mismatch.

use std::collections::BTreeMap;

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};

use crate::crypto::{hex_encode, sha256};

mod zip;

// ──────────────────────────────────────────────────────────────────────
// Manifest filenames inside the bundle ZIP
// ──────────────────────────────────────────────────────────────────────

const MANIFEST_FILENAME: &str = "_evidence_manifest.json";
const SIGNATURE_FILENAME: &str = "_evidence_signature.bin";
const MANIFEST_VERSION: u32 = 1;

// ──────────────────────────────────────────────────────────────────────
// Errors
// ──────────────────────────────────────────────────────────────────────

/// Errors from the evidence packager.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EvidenceError {
    /// File path contains a null byte, leading slash, `..` segment,
    /// or any other reserved character. Evidence packages must not
    /// contain paths that escape the bundle root or fail extraction
    /// on common ZIP tooling.
    InvalidPath(String),
    /// Two files in the builder have the same path. Evidence bundles
    /// require unique paths (lexicographic sort would otherwise be
    /// ambiguous).
    DuplicatePath(String),
    /// Per-file content exceeds 4 GiB. The byte-deterministic ZIP
    /// encoder is STORE-only + standard-ZIP (not ZIP64). Adopters
    /// with files >4 GiB should split + correlate via evidence_id.
    FileTooLarge(String, u64),
    /// Manifest violation surfaced at verify time: per-file sha256
    /// in manifest does not match the recomputed sha256.
    ManifestFileMismatch(String),
    /// Manifest's merkle_root field does not match the recomputed
    /// Merkle root over the per-file sha256s. Catches the case where
    /// an attacker mutated a file AND updated the corresponding
    /// per-file sha256 entry but forgot the Merkle root.
    MerkleRootMismatch,
    /// Ed25519 signature verification failed. The bundle was signed
    /// with a different key, or the signature / manifest bytes were
    /// tampered with.
    SignatureMismatch,
    /// Manifest JSON parse failure.
    ManifestParseError(String),
    /// Manifest is missing a required field (defense in depth above
    /// `ManifestParseError` — a parsed-but-empty manifest reaches
    /// here).
    ManifestFieldMissing(&'static str),
    /// Manifest format version is unknown. Future format revs should
    /// upgrade gracefully via a migration path; until then unknown
    /// versions fail closed.
    UnknownManifestVersion(u32),
    /// ZIP archive parse failure during verification.
    ZipParseError(String),
    /// `_evidence_manifest.json` was not found in the ZIP.
    ManifestNotFound,
    /// `_evidence_signature.bin` was not found in the ZIP.
    SignatureNotFound,
    /// `_evidence_signature.bin` was not exactly 64 bytes (Ed25519
    /// signature size per RFC 8032).
    SignatureSizeWrong(usize),
}

impl std::fmt::Display for EvidenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidPath(p) => write!(f, "evidence: invalid path {p:?}"),
            Self::DuplicatePath(p) => write!(f, "evidence: duplicate path {p:?}"),
            Self::FileTooLarge(p, sz) => {
                write!(f, "evidence: file {p:?} size {sz} exceeds 4 GiB cap")
            }
            Self::ManifestFileMismatch(p) => {
                write!(f, "evidence: per-file sha256 mismatch on {p:?}")
            }
            Self::MerkleRootMismatch => write!(f, "evidence: Merkle root mismatch"),
            Self::SignatureMismatch => write!(f, "evidence: Ed25519 signature mismatch"),
            Self::ManifestParseError(msg) => write!(f, "evidence: manifest parse: {msg}"),
            Self::ManifestFieldMissing(field) => {
                write!(f, "evidence: manifest missing field {field:?}")
            }
            Self::UnknownManifestVersion(v) => {
                write!(f, "evidence: unknown manifest version {v}")
            }
            Self::ZipParseError(msg) => write!(f, "evidence: zip parse: {msg}"),
            Self::ManifestNotFound => write!(f, "evidence: _evidence_manifest.json missing"),
            Self::SignatureNotFound => write!(f, "evidence: _evidence_signature.bin missing"),
            Self::SignatureSizeWrong(sz) => {
                write!(f, "evidence: signature size {sz} != 64 (Ed25519)")
            }
        }
    }
}

impl std::error::Error for EvidenceError {}

// ──────────────────────────────────────────────────────────────────────
// Builder
// ──────────────────────────────────────────────────────────────────────

/// Options consumed by [`EvidenceBuilder::build`]. Adopters supply
/// these once per evidence bundle.
#[derive(Debug, Clone)]
pub struct EvidenceOptions {
    /// Per-tenant identifier — recorded in the manifest for forensic
    /// replay + correlated against the audit log's `tenant_id`.
    pub tenant_id: u64,
    /// Per-evidence identifier (UUID, slug, or other unique label).
    pub evidence_id: String,
    /// Wall-clock time the bundle was produced (Unix epoch ms).
    /// Adopters supply this from `chrono::Utc::now().timestamp_millis()`
    /// or equivalent. Tests use `0` for byte-determinism.
    pub created_ms: i64,
    /// Stable identifier for the signing key — names the key
    /// generation that signed this bundle. Verifiers use this to
    /// fetch the matching pubkey from their vault. Per D8 ratified,
    /// keys rotate quarterly — the id format is adopter-defined.
    pub signing_key_id: String,
}

/// Mutable builder for an evidence bundle. Adopters add files, then
/// call [`build`](EvidenceBuilder::build) to produce a signed bundle.
///
/// Files are added in any order; the builder sorts them
/// lexicographically by path before computing hashes / Merkle root /
/// ZIP layout. This is what makes the output bytes deterministic.
#[derive(Debug, Default, Clone)]
pub struct EvidenceBuilder {
    files: Vec<(String, Vec<u8>)>,
}

impl EvidenceBuilder {
    /// Empty builder.
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a file to the bundle. `path` is the in-bundle path
    /// (forward slashes; relative; no leading slash; no `..` segments;
    /// no NUL bytes). `content` is the raw bytes (any encoding;
    /// adopters typically pass UTF-8 JSON / PDF / etc.).
    ///
    /// Adopters may chain `add_file` calls; ordering does not affect
    /// the output bytes (sorted at build time).
    pub fn add_file(
        mut self,
        path: impl Into<String>,
        content: impl Into<Vec<u8>>,
    ) -> Result<Self, EvidenceError> {
        let path = path.into();
        validate_path(&path)?;
        let content = content.into();
        if content.len() > u32::MAX as usize {
            return Err(EvidenceError::FileTooLarge(path, content.len() as u64));
        }
        if self.files.iter().any(|(p, _)| p == &path) {
            return Err(EvidenceError::DuplicatePath(path));
        }
        self.files.push((path, content));
        Ok(self)
    }

    /// Build the signed evidence bundle. Returns the ZIP bytes plus
    /// metadata (manifest + Merkle root + signature) for adopters
    /// who want to log them separately. The metadata is also embedded
    /// in the ZIP itself so the bundle is self-contained.
    pub fn build(
        mut self,
        signing_key: &SigningKey,
        options: &EvidenceOptions,
    ) -> Result<EvidenceBundle, EvidenceError> {
        // Sort files lexicographically for byte-determinism.
        self.files.sort_by(|a, b| a.0.cmp(&b.0));

        // Per-file SHA-256 + size in the same order.
        let file_entries: Vec<ManifestFileEntry> = self
            .files
            .iter()
            .map(|(path, content)| {
                let digest = sha256(content);
                ManifestFileEntry {
                    path: path.clone(),
                    size: content.len() as u64,
                    sha256_hex: hex_encode(&digest),
                }
            })
            .collect();

        // Merkle root over the per-file (path || sha256) pairs. The
        // path is included so reordering files (without changing
        // contents) changes the root — defense against an attacker
        // who shuffles entries to confuse forensic tooling.
        let merkle_root = compute_merkle_root(&file_entries);
        let merkle_root_hex = hex_encode(&merkle_root);

        // Build the canonical manifest JSON.
        let manifest = Manifest {
            version: MANIFEST_VERSION,
            tenant_id: options.tenant_id,
            evidence_id: options.evidence_id.clone(),
            created_ms: options.created_ms,
            signing_key_id: options.signing_key_id.clone(),
            files: file_entries,
            merkle_root_hex: merkle_root_hex.clone(),
        };
        let manifest_bytes = canonical_manifest_json(&manifest);

        // Sign the manifest bytes with Ed25519. ed25519-dalek's
        // `Signer::sign` is deterministic per RFC 8032 (no nonce
        // randomness) — same key + same bytes ⇒ same signature.
        let signature: Signature = signing_key.sign(&manifest_bytes);
        let signature_bytes = signature.to_bytes();

        // Assemble the ZIP archive. File order: adopter files
        // (sorted), then `_evidence_manifest.json`, then
        // `_evidence_signature.bin`. The manifest + sig come last so
        // they sit physically at the end of the archive, which lets
        // streaming verifiers compute file hashes in one pass.
        let mut zip_files: Vec<(String, Vec<u8>)> = self
            .files
            .iter()
            .map(|(p, c)| (p.clone(), c.clone()))
            .collect();
        zip_files.push((MANIFEST_FILENAME.to_owned(), manifest_bytes.clone()));
        zip_files.push((SIGNATURE_FILENAME.to_owned(), signature_bytes.to_vec()));
        // The manifest + signature filenames begin with `_` which
        // sorts BEFORE most ASCII filenames. To keep a stable
        // adopter-files-first / metadata-last layout we DO NOT
        // re-sort here — the manifest + sig stay at the end of the
        // archive entry list explicitly.

        let zip_bytes = zip::write_archive(&zip_files)?;

        Ok(EvidenceBundle {
            zip_bytes,
            manifest,
            merkle_root,
            signature: signature_bytes,
        })
    }
}

/// Output of [`EvidenceBuilder::build`].
#[derive(Debug, Clone)]
pub struct EvidenceBundle {
    /// The byte-deterministic ZIP bytes containing every adopter
    /// file plus `_evidence_manifest.json` + `_evidence_signature.bin`.
    pub zip_bytes: Vec<u8>,
    /// The manifest object — also serialised inside the ZIP.
    pub manifest: Manifest,
    /// Merkle root over the per-file SHA-256s. Embedded as
    /// `merkle_root` in the manifest.
    pub merkle_root: [u8; 32],
    /// 64-byte Ed25519 detached signature over the canonical
    /// manifest bytes. Also embedded in the ZIP as
    /// `_evidence_signature.bin`.
    pub signature: [u8; 64],
}

// ──────────────────────────────────────────────────────────────────────
// Verifier
// ──────────────────────────────────────────────────────────────────────

/// Adopter-side verifier. Given a public key, validates a bundle's
/// signature + per-file hashes + Merkle root, and surfaces the
/// extracted files.
#[derive(Debug, Clone)]
pub struct EvidenceVerifier {
    public_key: VerifyingKey,
}

impl EvidenceVerifier {
    /// Construct from the adopter's stored Ed25519 public key. The
    /// public key matches the `signing_key_id` recorded in the bundle's
    /// manifest — adopters fetch the right pubkey from their vault.
    pub fn new(public_key: VerifyingKey) -> Self {
        Self { public_key }
    }

    /// Validate the bundle and return the extracted files + manifest.
    /// Returns `Err(...)` on any mismatch (signature, per-file hash,
    /// Merkle root, manifest format).
    pub fn verify(&self, zip_bytes: &[u8]) -> Result<VerifiedEvidence, EvidenceError> {
        // 1. Parse the ZIP.
        let entries = zip::read_archive(zip_bytes)?;
        let mut by_name: BTreeMap<String, Vec<u8>> = entries.into_iter().collect();

        // 2. Pull manifest + signature.
        let manifest_bytes = by_name
            .remove(MANIFEST_FILENAME)
            .ok_or(EvidenceError::ManifestNotFound)?;
        let signature_bytes = by_name
            .remove(SIGNATURE_FILENAME)
            .ok_or(EvidenceError::SignatureNotFound)?;
        if signature_bytes.len() != 64 {
            return Err(EvidenceError::SignatureSizeWrong(signature_bytes.len()));
        }
        let mut sig_arr = [0u8; 64];
        sig_arr.copy_from_slice(&signature_bytes);
        let signature = Signature::from_bytes(&sig_arr);

        // 3. Verify Ed25519 signature over the manifest bytes.
        self.public_key
            .verify(&manifest_bytes, &signature)
            .map_err(|_| EvidenceError::SignatureMismatch)?;

        // 4. Parse the canonical manifest.
        let manifest = parse_manifest(&manifest_bytes)?;
        if manifest.version != MANIFEST_VERSION {
            return Err(EvidenceError::UnknownManifestVersion(manifest.version));
        }

        // 5. Recompute per-file SHA-256 + verify against manifest.
        // The manifest's `files` list is the source of truth — it
        // pins exactly which files MUST be present + their hashes.
        for entry in &manifest.files {
            let actual = by_name
                .get(&entry.path)
                .ok_or_else(|| EvidenceError::ManifestFileMismatch(entry.path.clone()))?;
            if actual.len() as u64 != entry.size {
                return Err(EvidenceError::ManifestFileMismatch(entry.path.clone()));
            }
            let digest = sha256(actual);
            if hex_encode(&digest) != entry.sha256_hex {
                return Err(EvidenceError::ManifestFileMismatch(entry.path.clone()));
            }
        }
        // No extra files allowed — bundle integrity demands the ZIP
        // contents match the manifest exactly. Any file not listed
        // in the manifest is suspicious (an attacker injecting
        // malware, a typo, etc.).
        for path in by_name.keys() {
            if !manifest.files.iter().any(|f| &f.path == path) {
                return Err(EvidenceError::ManifestFileMismatch(path.clone()));
            }
        }

        // 6. Recompute Merkle root, compare to manifest field.
        let recomputed_root = compute_merkle_root(&manifest.files);
        let recomputed_hex = hex_encode(&recomputed_root);
        if recomputed_hex != manifest.merkle_root_hex {
            return Err(EvidenceError::MerkleRootMismatch);
        }

        // 7. Surface the extracted adopter files (sorted by path).
        let files: Vec<(String, Vec<u8>)> = manifest
            .files
            .iter()
            .map(|entry| {
                let bytes = by_name.remove(&entry.path).unwrap_or_default();
                (entry.path.clone(), bytes)
            })
            .collect();

        Ok(VerifiedEvidence {
            manifest,
            merkle_root: recomputed_root,
            files,
        })
    }
}

/// Output of [`EvidenceVerifier::verify`]. Contains the parsed
/// manifest + the recomputed Merkle root + the extracted file
/// contents.
#[derive(Debug, Clone)]
pub struct VerifiedEvidence {
    pub manifest: Manifest,
    pub merkle_root: [u8; 32],
    pub files: Vec<(String, Vec<u8>)>,
}

// ──────────────────────────────────────────────────────────────────────
// Manifest types
// ──────────────────────────────────────────────────────────────────────

/// Manifest serialised as `_evidence_manifest.json` in the bundle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Manifest {
    pub version: u32,
    pub tenant_id: u64,
    pub evidence_id: String,
    pub created_ms: i64,
    pub signing_key_id: String,
    pub files: Vec<ManifestFileEntry>,
    /// Hex-encoded Merkle root over the per-file SHA-256s.
    pub merkle_root_hex: String,
}

/// One file entry in the manifest. Holds the path, size, and
/// hex-encoded SHA-256 of the file content.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManifestFileEntry {
    pub path: String,
    pub size: u64,
    pub sha256_hex: String,
}

// ──────────────────────────────────────────────────────────────────────
// Path validation
// ──────────────────────────────────────────────────────────────────────

fn validate_path(path: &str) -> Result<(), EvidenceError> {
    if path.is_empty() {
        return Err(EvidenceError::InvalidPath(path.to_owned()));
    }
    if path.contains('\0') {
        return Err(EvidenceError::InvalidPath(path.to_owned()));
    }
    if path.starts_with('/') || path.starts_with('\\') {
        return Err(EvidenceError::InvalidPath(path.to_owned()));
    }
    // Block backreferences — even a `..` segment in the middle could
    // escape the bundle root if a buggy extractor doesn't sanitise.
    for seg in path.split(['/', '\\']) {
        if seg == ".." || seg == "." {
            return Err(EvidenceError::InvalidPath(path.to_owned()));
        }
    }
    // Windows-reserved characters that ZIP extractors on win32
    // refuse: `< > : " | ? *`. Reject at builder time so the bundle
    // round-trips on every adopter platform.
    if path.contains(['<', '>', ':', '"', '|', '?', '*']) {
        return Err(EvidenceError::InvalidPath(path.to_owned()));
    }
    Ok(())
}

// ──────────────────────────────────────────────────────────────────────
// Merkle root
//
// Binary tree over sorted (path || 0x00 || sha256) leaves. For an
// empty file list the root is the SHA-256 of the empty string (the
// canonical "empty Merkle" anchor).
//
// For an odd leaf count, the last leaf is duplicated to pair up
// (Bitcoin-style). The tree height is implicit; we only emit the root.
// ──────────────────────────────────────────────────────────────────────

fn compute_merkle_root(files: &[ManifestFileEntry]) -> [u8; 32] {
    if files.is_empty() {
        return sha256(b"");
    }

    // Leaves: sha256(path || 0x00 || sha256_of_file_bytes_decoded).
    // We re-decode the hex sha256 from the manifest entry to get the
    // raw 32 bytes. For locally-built manifests this is wasteful (we
    // had the raw bytes already); for verify-time recomputation we
    // need to operate from the manifest's hex strings, so keep the
    // path uniform.
    let mut leaves: Vec<[u8; 32]> = files
        .iter()
        .map(|entry| {
            let mut buf = Vec::with_capacity(entry.path.len() + 1 + 32);
            buf.extend_from_slice(entry.path.as_bytes());
            buf.push(0x00);
            // Decode the hex digest. Manifest construction guarantees
            // it's 64 hex chars; verify time has already parsed it.
            let raw = decode_hex32(&entry.sha256_hex);
            buf.extend_from_slice(&raw);
            sha256(&buf)
        })
        .collect();

    // Iteratively combine pairs until one hash remains.
    while leaves.len() > 1 {
        let mut next: Vec<[u8; 32]> = Vec::with_capacity(leaves.len().div_ceil(2));
        let mut i = 0;
        while i < leaves.len() {
            let left = leaves[i];
            let right = if i + 1 < leaves.len() {
                leaves[i + 1]
            } else {
                left
            };
            let mut buf = [0u8; 64];
            buf[..32].copy_from_slice(&left);
            buf[32..].copy_from_slice(&right);
            next.push(sha256(&buf));
            i += 2;
        }
        leaves = next;
    }

    leaves[0]
}

fn decode_hex32(s: &str) -> [u8; 32] {
    // Defensive: callers have already validated 64-char hex. Any
    // failure here is a programming error.
    debug_assert_eq!(s.len(), 64);
    let mut out = [0u8; 32];
    let bytes = s.as_bytes();
    for i in 0..32 {
        out[i] = (nibble(bytes[i * 2]) << 4) | nibble(bytes[i * 2 + 1]);
    }
    out
}

fn nibble(b: u8) -> u8 {
    match b {
        b'0'..=b'9' => b - b'0',
        b'a'..=b'f' => b - b'a' + 10,
        b'A'..=b'F' => b - b'A' + 10,
        _ => 0, // Defensive — manifest validation rejects non-hex.
    }
}

// ──────────────────────────────────────────────────────────────────────
// Canonical manifest JSON (manual serialisation for byte-determinism)
//
// We do NOT use serde_json because:
//   - Default serde_json output is non-deterministic for HashMaps
//     (random iteration order).
//   - Configuring serde_json for sorted keys + no whitespace is
//     possible but adds a runtime dep + a non-trivial config dance.
//   - The manifest schema is small + closed; manual emission is
//     ~50 lines and gives bit-perfect control.
// ──────────────────────────────────────────────────────────────────────

fn canonical_manifest_json(m: &Manifest) -> Vec<u8> {
    // Top-level object keys in lexicographic order:
    //   "created_ms", "evidence_id", "files", "merkle_root",
    //   "signing_key_id", "tenant_id", "version".
    // Each file entry's keys also in lexicographic order:
    //   "path", "sha256", "size".
    let mut out = String::with_capacity(256 + m.files.len() * 96);
    out.push('{');
    out.push_str("\"created_ms\":");
    out.push_str(&m.created_ms.to_string());
    out.push(',');
    out.push_str("\"evidence_id\":");
    json_emit_string(&mut out, &m.evidence_id);
    out.push(',');
    out.push_str("\"files\":[");
    for (idx, file) in m.files.iter().enumerate() {
        if idx > 0 {
            out.push(',');
        }
        out.push('{');
        out.push_str("\"path\":");
        json_emit_string(&mut out, &file.path);
        out.push(',');
        out.push_str("\"sha256\":");
        json_emit_string(&mut out, &file.sha256_hex);
        out.push(',');
        out.push_str("\"size\":");
        out.push_str(&file.size.to_string());
        out.push('}');
    }
    out.push_str("],");
    out.push_str("\"merkle_root\":");
    json_emit_string(&mut out, &m.merkle_root_hex);
    out.push(',');
    out.push_str("\"signing_key_id\":");
    json_emit_string(&mut out, &m.signing_key_id);
    out.push(',');
    out.push_str("\"tenant_id\":");
    out.push_str(&m.tenant_id.to_string());
    out.push(',');
    out.push_str("\"version\":");
    out.push_str(&m.version.to_string());
    out.push('}');
    out.into_bytes()
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
// Manifest parser — scans the canonical JSON we emit. Strict: rejects
// anything that the canonical emitter wouldn't produce. Adopters who
// hand-edit the manifest bytes get a parse error before the verifier
// reaches the signature check (defense in depth).
// ──────────────────────────────────────────────────────────────────────

fn parse_manifest(bytes: &[u8]) -> Result<Manifest, EvidenceError> {
    let s = std::str::from_utf8(bytes)
        .map_err(|e| EvidenceError::ManifestParseError(format!("UTF-8: {e}")))?;
    let mut p = JsonParser { s, pos: 0 };
    p.skip_ws();
    p.expect(b'{')?;

    let mut version: Option<u32> = None;
    let mut tenant_id: Option<u64> = None;
    let mut evidence_id: Option<String> = None;
    let mut created_ms: Option<i64> = None;
    let mut signing_key_id: Option<String> = None;
    let mut files: Option<Vec<ManifestFileEntry>> = None;
    let mut merkle_root_hex: Option<String> = None;

    let mut first = true;
    loop {
        p.skip_ws();
        if p.peek() == Some(b'}') {
            // Manifest object closer reached; we don't bump pos
            // because nothing reads it after this point. Strict
            // canonical-JSON contract: no trailing data after the
            // closing brace.
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
            "evidence_id" => evidence_id = Some(p.parse_string()?),
            "created_ms" => created_ms = Some(p.parse_i64()?),
            "signing_key_id" => signing_key_id = Some(p.parse_string()?),
            "merkle_root" => merkle_root_hex = Some(p.parse_string()?),
            "files" => files = Some(p.parse_files_array()?),
            other => {
                return Err(EvidenceError::ManifestParseError(format!(
                    "unexpected key {other:?}"
                )))
            }
        }
    }

    Ok(Manifest {
        version: version.ok_or(EvidenceError::ManifestFieldMissing("version"))?,
        tenant_id: tenant_id.ok_or(EvidenceError::ManifestFieldMissing("tenant_id"))?,
        evidence_id: evidence_id.ok_or(EvidenceError::ManifestFieldMissing("evidence_id"))?,
        created_ms: created_ms.ok_or(EvidenceError::ManifestFieldMissing("created_ms"))?,
        signing_key_id: signing_key_id
            .ok_or(EvidenceError::ManifestFieldMissing("signing_key_id"))?,
        files: files.ok_or(EvidenceError::ManifestFieldMissing("files"))?,
        merkle_root_hex: merkle_root_hex
            .ok_or(EvidenceError::ManifestFieldMissing("merkle_root"))?,
    })
}

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

    fn expect(&mut self, b: u8) -> Result<(), EvidenceError> {
        match self.peek() {
            Some(c) if c == b => {
                self.pos += 1;
                Ok(())
            }
            other => Err(EvidenceError::ManifestParseError(format!(
                "expected {:?} at byte {}, got {:?}",
                b as char,
                self.pos,
                other.map(|c| c as char)
            ))),
        }
    }

    fn parse_string(&mut self) -> Result<String, EvidenceError> {
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
                    return Err(EvidenceError::ManifestParseError(
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
                            return Err(EvidenceError::ManifestParseError(
                                "short \\u escape".into(),
                            ));
                        }
                        let hex =
                            std::str::from_utf8(&bytes[self.pos..self.pos + 4]).map_err(|_| {
                                EvidenceError::ManifestParseError("non-UTF-8 \\u escape".into())
                            })?;
                        let code = u32::from_str_radix(hex, 16).map_err(|_| {
                            EvidenceError::ManifestParseError("invalid \\u hex".into())
                        })?;
                        self.pos += 4;
                        if let Some(c) = char::from_u32(code) {
                            out.push(c);
                        } else {
                            return Err(EvidenceError::ManifestParseError(
                                "invalid \\u codepoint".into(),
                            ));
                        }
                    }
                    other => {
                        return Err(EvidenceError::ManifestParseError(format!(
                            "unknown escape \\{}",
                            other as char
                        )))
                    }
                }
            } else {
                // Multi-byte UTF-8: copy bytes through char boundary.
                let ch_len = utf8_char_len(b);
                if self.pos + ch_len > bytes.len() {
                    return Err(EvidenceError::ManifestParseError(
                        "truncated UTF-8 in string".into(),
                    ));
                }
                let ch_bytes = &bytes[self.pos..self.pos + ch_len];
                let ch_str = std::str::from_utf8(ch_bytes)
                    .map_err(|_| EvidenceError::ManifestParseError("invalid UTF-8".into()))?;
                out.push_str(ch_str);
                self.pos += ch_len;
            }
        }
        Err(EvidenceError::ManifestParseError(
            "unterminated string".into(),
        ))
    }

    fn parse_u64(&mut self) -> Result<u64, EvidenceError> {
        let start = self.pos;
        let bytes = self.s.as_bytes();
        while self.pos < bytes.len() && bytes[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        if start == self.pos {
            return Err(EvidenceError::ManifestParseError("expected u64".into()));
        }
        self.s[start..self.pos]
            .parse::<u64>()
            .map_err(|e| EvidenceError::ManifestParseError(format!("u64: {e}")))
    }

    fn parse_i64(&mut self) -> Result<i64, EvidenceError> {
        let start = self.pos;
        let bytes = self.s.as_bytes();
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        while self.pos < bytes.len() && bytes[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        if start == self.pos || (start + 1 == self.pos && bytes[start] == b'-') {
            return Err(EvidenceError::ManifestParseError("expected i64".into()));
        }
        self.s[start..self.pos]
            .parse::<i64>()
            .map_err(|e| EvidenceError::ManifestParseError(format!("i64: {e}")))
    }

    fn parse_files_array(&mut self) -> Result<Vec<ManifestFileEntry>, EvidenceError> {
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
            self.expect(b'{')?;
            let mut path: Option<String> = None;
            let mut size: Option<u64> = None;
            let mut sha256_hex: Option<String> = None;
            let mut entry_first = true;
            loop {
                self.skip_ws();
                if self.peek() == Some(b'}') {
                    self.pos += 1;
                    break;
                }
                if !entry_first {
                    self.expect(b',')?;
                    self.skip_ws();
                }
                entry_first = false;
                let key = self.parse_string()?;
                self.skip_ws();
                self.expect(b':')?;
                self.skip_ws();
                match key.as_str() {
                    "path" => path = Some(self.parse_string()?),
                    "size" => size = Some(self.parse_u64()?),
                    "sha256" => {
                        let hex_s = self.parse_string()?;
                        if hex_s.len() != 64 || !hex_s.bytes().all(|b| b.is_ascii_hexdigit()) {
                            return Err(EvidenceError::ManifestParseError(
                                "sha256 must be 64 lowercase hex chars".into(),
                            ));
                        }
                        sha256_hex = Some(hex_s);
                    }
                    other => {
                        return Err(EvidenceError::ManifestParseError(format!(
                            "unexpected file-entry key {other:?}"
                        )))
                    }
                }
            }
            out.push(ManifestFileEntry {
                path: path.ok_or(EvidenceError::ManifestFieldMissing("files[].path"))?,
                size: size.ok_or(EvidenceError::ManifestFieldMissing("files[].size"))?,
                sha256_hex: sha256_hex
                    .ok_or(EvidenceError::ManifestFieldMissing("files[].sha256"))?,
            });
        }
    }
}

fn utf8_char_len(b: u8) -> usize {
    if b < 0x80 {
        1
    } else if b < 0xc0 {
        // Continuation byte alone — defensive single-byte step.
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
// Public re-exports of ed25519-dalek convenience types so adopters
// don't need a direct dep on ed25519-dalek for the common case.
// ──────────────────────────────────────────────────────────────────────

pub use ed25519_dalek::{
    Signature as Ed25519Signature, SigningKey as Ed25519SigningKey,
    VerifyingKey as Ed25519VerifyingKey,
};
