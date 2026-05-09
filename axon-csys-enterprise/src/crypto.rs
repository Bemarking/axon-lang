//! § Fase 27.c — Enterprise crypto module.
//!
//! Adopter-facing crypto API. Under the no-fips passthrough regime
//! (default features) every public symbol is a verbatim re-export
//! from the OSS [`axon_csys`] crate. Under either FIPS feature
//! (`fips-boringssl` or `fips-openssl`) the SHA-256 + HMAC-SHA256
//! primitives are routed through the linked NIST-CAVS-validated
//! crypto library instead — the wire output is byte-identical
//! (drift gate enforces this on every NIST CAVS reference vector +
//! 100 fuzz iterations per primitive), so existing tokens issued by
//! a non-FIPS deployment verify on a FIPS deployment and vice
//! versa.
//!
//! # Why the wire output is byte-identical
//!
//! SHA-256 and HMAC-SHA256 are deterministic algorithms specified
//! by NIST FIPS 180-4 + FIPS 198-1. Two implementations claiming
//! to compute SHA-256 MUST produce the same 32-byte digest for the
//! same input — otherwise one of them is non-compliant. The drift
//! gate (Fase 27.i) makes this guarantee load-bearing: any single-
//! byte difference between the OSS pure-C path and the FIPS-
//! validated path is a build-time CI failure.
//!
//! The differentiator between the OSS path and the FIPS-validated
//! path is therefore NOT the bytes on the wire but the formal
//! CMVP / FIPS 140-3 certificate that adopters embed in their
//! compliance documentation. For audits requiring "FIPS-validated
//! cryptography in transit and at rest" the OSS path fails the
//! audit despite being algorithmically correct; the FIPS-validated
//! path passes.
//!
//! # Backend routing matrix
//!
//! | Cargo features active | SHA-256 / HMAC-SHA256 path | Backend label |
//! |---|---|---|
//! | (none — default) | OSS pure-C (axon-csys 0.1.x) | `axon-csys-oss-pure-c` |
//! | `fips-boringssl` | BoringSSL-FIPS module | `boringssl-fips` |
//! | `fips-openssl` | OpenSSL-FIPS provider | `openssl-fips` |
//! | both | (rejected at build time per D3) | — |
//!
//! # ContinuityWire backward-compat
//!
//! The continuity wire format (3 RFC-record-separator-delimited
//! fields, base64url-no-pad outer envelope, hex-encoded MAC) is
//! defined in OSS axon-csys and frozen as the v0.1.x ABI. This
//! crate's [`ContinuityWire`] re-implements `sign` / `verify`
//! using the locally-routed HMAC primitive — so under a FIPS
//! feature the resulting MAC bytes flow through the FIPS-validated
//! lib while the wire format stays bit-for-bit compatible with
//! tokens issued by any OSS deployment.

// ──────────────────────────────────────────────────────────────────────
// Sizing constants — re-exported from OSS so adopters import the same
// pair regardless of feature flag.
// ──────────────────────────────────────────────────────────────────────

pub use axon_csys::{SHA256_BLOCK_SIZE, SHA256_DIGEST_SIZE};

// ──────────────────────────────────────────────────────────────────────
// Pure-arithmetic codecs — always re-exported from OSS. These are
// not crypto primitives (no FIPS-validated alternative is
// meaningful) so the OSS implementation is the single source of
// truth across both regimes.
// ──────────────────────────────────────────────────────────────────────

pub use axon_csys::{b64url_decode, b64url_encode, ct_eq, hex_decode, hex_encode};

// ──────────────────────────────────────────────────────────────────────
// SHA-256 + HMAC-SHA256 — feature-gated routing.
//
// no-fips → re-export OSS verbatim.
// FIPS → wrap the FIPS-routed C glue in `fips_glue.c`.
// ──────────────────────────────────────────────────────────────────────

#[cfg(not(any(feature = "fips-boringssl", feature = "fips-openssl")))]
mod backend {
    pub use axon_csys::{hmac_sha256, sha256, HmacSha256, Sha256};
}

#[cfg(any(feature = "fips-boringssl", feature = "fips-openssl"))]
mod backend {
    use super::SHA256_DIGEST_SIZE;

    extern "C" {
        fn axon_csys_enterprise_sha256(data: *const u8, len: usize, out: *mut u8) -> i32;
        fn axon_csys_enterprise_hmac_sha256(
            key: *const u8,
            key_len: usize,
            data: *const u8,
            data_len: usize,
            out: *mut u8,
        ) -> i32;
        pub(super) fn axon_csys_enterprise_fips_self_test() -> i32;
        pub(super) fn axon_csys_enterprise_fips_backend_label() -> *const std::os::raw::c_char;
    }

    /// Compute the SHA-256 digest of `data` in one shot. Routes
    /// through the linked FIPS-validated crypto library; on POST
    /// failure the call panics with a clear message (per D13 the
    /// soft-fail policy applies to license enforcement, NOT to
    /// FIPS POST: a FIPS-required deployment that silently falls
    /// through to non-FIPS would be a compliance violation).
    pub fn sha256(data: &[u8]) -> [u8; SHA256_DIGEST_SIZE] {
        let mut out = [0u8; SHA256_DIGEST_SIZE];
        // SAFETY: `data.as_ptr()` is valid for `data.len()` bytes
        // (or null when len == 0; the C glue handles both). `out`
        // is a stack-resident array of the documented size.
        let rc =
            unsafe { axon_csys_enterprise_sha256(data.as_ptr(), data.len(), out.as_mut_ptr()) };
        if rc != 0 {
            fips_failure_panic("axon_csys_enterprise_sha256", rc);
        }
        out
    }

    /// Compute HMAC-SHA256 in one shot.
    pub fn hmac_sha256(key: &[u8], data: &[u8]) -> [u8; SHA256_DIGEST_SIZE] {
        let mut out = [0u8; SHA256_DIGEST_SIZE];
        // SAFETY: ditto SHA-256.
        let rc = unsafe {
            axon_csys_enterprise_hmac_sha256(
                key.as_ptr(),
                key.len(),
                data.as_ptr(),
                data.len(),
                out.as_mut_ptr(),
            )
        };
        if rc != 0 {
            fips_failure_panic("axon_csys_enterprise_hmac_sha256", rc);
        }
        out
    }

    /// Streaming SHA-256 hasher — buffered accumulator on top of the
    /// FIPS one-shot. Byte-identical to OSS streaming output (SHA-
    /// 256 is a deterministic algorithm — streaming vs. buffered
    /// produces the same digest by definition).
    ///
    /// This is intentionally simpler than the OSS streaming (which
    /// keeps a fixed-size internal Merkle-Damgård state). The trade
    /// is one allocation grow on long inputs in exchange for keeping
    /// the FIPS surface to a single one-shot EVP entry point —
    /// which is the entry point CMVP certified.
    pub struct Sha256 {
        accumulated: Vec<u8>,
    }

    impl Sha256 {
        pub fn new() -> Self {
            Self {
                accumulated: Vec::new(),
            }
        }

        pub fn update(&mut self, data: &[u8]) -> &mut Self {
            self.accumulated.extend_from_slice(data);
            self
        }

        pub fn finalize(self) -> [u8; SHA256_DIGEST_SIZE] {
            sha256(&self.accumulated)
        }
    }

    impl Default for Sha256 {
        fn default() -> Self {
            Self::new()
        }
    }

    /// Streaming HMAC-SHA256 — buffered accumulator on top of the
    /// FIPS one-shot. See [`Sha256`] for the rationale.
    pub struct HmacSha256 {
        key: Vec<u8>,
        accumulated: Vec<u8>,
    }

    impl HmacSha256 {
        pub fn new(key: &[u8]) -> Self {
            Self {
                key: key.to_vec(),
                accumulated: Vec::new(),
            }
        }

        pub fn update(&mut self, data: &[u8]) -> &mut Self {
            self.accumulated.extend_from_slice(data);
            self
        }

        pub fn finalize(self) -> [u8; SHA256_DIGEST_SIZE] {
            hmac_sha256(&self.key, &self.accumulated)
        }
    }

    fn fips_failure_panic(symbol: &str, rc: i32) -> ! {
        panic!(
            "axon-csys-enterprise: FIPS-routed `{symbol}` returned non-zero (rc={rc}). \
             This is a hard error in FIPS deployments — see D13: the FIPS POST \
             soft-fail policy applies to license enforcement, NOT to crypto operations. \
             Adopter compliance documentation REQUIRES the FIPS path; falling \
             through silently would void the CMVP certificate. Common causes: \
             missing fipsmodule.cnf (OpenSSL-FIPS), tampered FIPS lib, or a \
             POST failure at first call (rc=-2)."
        );
    }
}

pub use backend::{hmac_sha256, sha256, HmacSha256, Sha256};

/// Force the FIPS module to run its power-on self-test (POST) and
/// load the FIPS provider. Returns `Ok(())` on success, `Err(rc)`
/// with the C-level return code on failure.
///
/// This is a no-op on the OSS pure-C path — the OSS axon-csys
/// implementation is algorithmically correct but not formally
/// CMVP-certified, so there's no POST to run.
///
/// Adopters running federal workloads SHOULD call this at process
/// startup to surface POST failures before serving traffic. The
/// crypto entry points call it lazily on first invocation so this
/// is purely a defense-in-depth gate.
#[cfg(any(feature = "fips-boringssl", feature = "fips-openssl"))]
pub fn fips_self_test() -> Result<(), i32> {
    // SAFETY: the C function is pure; no pointers in/out.
    let rc = unsafe { backend::axon_csys_enterprise_fips_self_test() };
    if rc == 0 {
        Ok(())
    } else {
        Err(rc)
    }
}

#[cfg(not(any(feature = "fips-boringssl", feature = "fips-openssl")))]
pub fn fips_self_test() -> Result<(), i32> {
    Ok(())
}

/// Stable string label for the linked FIPS backend, suitable for
/// audit-log emission. Returns `"axon-csys-oss-pure-c"` on the OSS
/// path. Matches [`crate::FipsBackend::label`] verbatim — exposed
/// here as a free function so adopters can include it in trace
/// spans without constructing the enum first.
pub fn backend_label() -> &'static str {
    #[cfg(any(feature = "fips-boringssl", feature = "fips-openssl"))]
    {
        // SAFETY: the C function returns a pointer to a `static
        // const` string literal with program lifetime; no need to
        // free or check for NULL. The string is a known-set ASCII
        // literal so UTF-8 conversion is infallible.
        let ptr = unsafe { backend::axon_csys_enterprise_fips_backend_label() };
        let cstr = unsafe { std::ffi::CStr::from_ptr(ptr) };
        cstr.to_str().expect(
            "axon_csys_enterprise_fips_backend_label returned non-UTF-8 string — \
                     the C glue must keep these labels ASCII",
        )
    }
    #[cfg(not(any(feature = "fips-boringssl", feature = "fips-openssl")))]
    {
        "axon-csys-oss-pure-c"
    }
}

// ──────────────────────────────────────────────────────────────────────
// Continuity wire-format primitive — re-implemented in pure Rust so
// the underlying HMAC routes through whichever backend is active
// (FIPS-validated or OSS pure-C). The wire format stays byte-
// identical to OSS axon-csys 0.1.x (drift gate enforces this).
//
// The wire layout is:
//
//   b64url_no_pad(
//     session_id || 0x1e ||
//     decimal_ascii(expiry_ms) || 0x1e ||
//     hex_lower(hmac_sha256(key, session_id || 0x1e || decimal_ascii(expiry_ms)))
//   )
//
// 0x1e is the ASCII Record-Separator character, which cannot appear
// in the session_id payload (validated at sign time).
// ──────────────────────────────────────────────────────────────────────

/// Errors from the continuity-wire primitive. Mirrored 1:1 from the
/// OSS [`axon_csys::ContinuityWireError`] surface so adopters can
/// migrate without changing match arms.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ContinuityWireError {
    /// base64url decode failed (alphabet violation or invalid length).
    BadBase64,
    /// Decoded text did not contain exactly two record-separator (0x1e)
    /// characters.
    BadFieldCount,
    /// The MAC field was not exactly 64 lowercase hex digits.
    BadHex,
    /// The expiry field was not parseable as a base-10 i64.
    BadExpiry,
    /// HMAC verification failed — token was forged or the signer key
    /// rotated since the token was issued.
    ForgedOrRotated,
    /// Output buffer (or session_id buffer) was too small. (Reserved
    /// for compat with the OSS error surface; the Rust impl
    /// allocates so this variant is unreachable here.)
    BufferTooSmall,
    /// FFI received a NULL pointer where one was required. (Reserved
    /// for compat; unreachable in this pure-Rust impl.)
    NullArg,
    /// session_id contained a forbidden 0x1e byte.
    PayloadTooLarge,
}

impl std::fmt::Display for ContinuityWireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BadBase64 => write!(f, "continuity wire: base64url decode failed"),
            Self::BadFieldCount => write!(
                f,
                "continuity wire: expected exactly 3 0x1e-separated fields"
            ),
            Self::BadHex => write!(f, "continuity wire: MAC field must be 64 hex digits"),
            Self::BadExpiry => write!(f, "continuity wire: expiry field not parseable as i64"),
            Self::ForgedOrRotated => write!(
                f,
                "continuity wire: HMAC mismatch (forged or signer key rotated)"
            ),
            Self::BufferTooSmall => write!(f, "continuity wire: output buffer too small"),
            Self::NullArg => write!(f, "continuity wire: NULL pointer at FFI"),
            Self::PayloadTooLarge => {
                write!(
                    f,
                    "continuity wire: session_id contains forbidden 0x1e byte"
                )
            }
        }
    }
}

impl std::error::Error for ContinuityWireError {}

const RECORD_SEPARATOR: u8 = 0x1e;

/// Continuity wire-format primitive — sign + verify operations.
///
/// This is the time-agnostic surface; consumers (e.g. axon-rs
/// `ContinuityTokenSigner`) wrap it with chrono-flavoured expiry
/// checking. The MAC routes through the locally-active crypto
/// backend (FIPS-validated when a feature is enabled, OSS pure-C
/// otherwise). The wire format is bit-for-bit compatible with
/// tokens signed by OSS axon-csys 0.1.x — drift gate verified.
pub struct ContinuityWire;

impl ContinuityWire {
    /// Sign `(session_id, expiry_ms)` with `key`. Returns the
    /// base64url-no-pad-encoded wire string.
    pub fn sign(
        key: &[u8],
        session_id: &str,
        expiry_ms: i64,
    ) -> Result<String, ContinuityWireError> {
        if session_id.as_bytes().contains(&RECORD_SEPARATOR) {
            return Err(ContinuityWireError::PayloadTooLarge);
        }
        let expiry_str = expiry_ms.to_string();

        // Build the MAC payload: session_id || 0x1e || decimal_ascii(expiry_ms).
        let mut payload = Vec::with_capacity(session_id.len() + 1 + expiry_str.len());
        payload.extend_from_slice(session_id.as_bytes());
        payload.push(RECORD_SEPARATOR);
        payload.extend_from_slice(expiry_str.as_bytes());

        let mac = hmac_sha256(key, &payload);
        let mac_hex = hex_encode(&mac);

        // Build the full pre-base64 envelope.
        let mut envelope = Vec::with_capacity(payload.len() + 1 + mac_hex.len());
        envelope.extend_from_slice(&payload);
        envelope.push(RECORD_SEPARATOR);
        envelope.extend_from_slice(mac_hex.as_bytes());

        Ok(b64url_encode(&envelope))
    }

    /// Verify `wire` against `key`, returning `(session_id, expiry_ms)`
    /// on success. Does NOT check whether the token has expired —
    /// the caller compares `expiry_ms` against the current time.
    pub fn verify(key: &[u8], wire: &str) -> Result<(String, i64), ContinuityWireError> {
        let decoded = b64url_decode(wire).ok_or(ContinuityWireError::BadBase64)?;

        // Split on 0x1e. Expecting exactly 3 fields (session_id,
        // expiry, mac). The `splitn` form is bounded so we never
        // walk past the third separator (a malformed payload with
        // 4+ fields fails the field-count check below).
        let mut iter = decoded.split(|&b| b == RECORD_SEPARATOR);
        let session_bytes = iter.next().ok_or(ContinuityWireError::BadFieldCount)?;
        let expiry_bytes = iter.next().ok_or(ContinuityWireError::BadFieldCount)?;
        let mac_bytes = iter.next().ok_or(ContinuityWireError::BadFieldCount)?;
        if iter.next().is_some() {
            return Err(ContinuityWireError::BadFieldCount);
        }

        // The MAC field must be 64 lowercase hex digits.
        if mac_bytes.len() != 64 {
            return Err(ContinuityWireError::BadHex);
        }
        let mac_hex_str =
            std::str::from_utf8(mac_bytes).map_err(|_| ContinuityWireError::BadHex)?;
        let mac_decoded = hex_decode(mac_hex_str).ok_or(ContinuityWireError::BadHex)?;
        if mac_decoded.len() != SHA256_DIGEST_SIZE {
            return Err(ContinuityWireError::BadHex);
        }

        // Reconstruct the MAC payload (session_id || 0x1e || expiry).
        let mut payload = Vec::with_capacity(session_bytes.len() + 1 + expiry_bytes.len());
        payload.extend_from_slice(session_bytes);
        payload.push(RECORD_SEPARATOR);
        payload.extend_from_slice(expiry_bytes);

        let computed = hmac_sha256(key, &payload);
        // Constant-time compare — pure-arithmetic ct_eq from OSS.
        if !ct_eq(&computed, &mac_decoded) {
            return Err(ContinuityWireError::ForgedOrRotated);
        }

        // Parse the session_id back to UTF-8 and the expiry to i64.
        let session_id = std::str::from_utf8(session_bytes)
            .map_err(|_| ContinuityWireError::BadFieldCount)?
            .to_owned();
        let expiry_str =
            std::str::from_utf8(expiry_bytes).map_err(|_| ContinuityWireError::BadExpiry)?;
        let expiry_ms: i64 = expiry_str
            .parse()
            .map_err(|_| ContinuityWireError::BadExpiry)?;
        Ok((session_id, expiry_ms))
    }
}
