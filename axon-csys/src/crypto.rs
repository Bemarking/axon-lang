//! §Fase 25.h — Crypto kernels (Rust shim).
//!
//! Safe Rust wrappers around the C23 SHA-256 / HMAC-SHA256 /
//! base64url / hex / continuity-wire primitives in
//! `c-src/crypto/`. Pillar split:
//!
//!   - C side: hash transforms, HMAC composition, branch-free
//!     constant-time compare, pure-arithmetic codec for hex +
//!     base64url. NIST FIPS 180-4 + FIPS 198-1 algorithmically
//!     compliant. No allocation in any entry point.
//!   - Rust side: safe API + error typing. The continuity-wire
//!     wrapper exposes a `ContinuityWire::sign` / `verify` pair
//!     that takes / returns an `i64` for the expiry — leaving
//!     time arithmetic (chrono / now() comparison) to the
//!     consumer (axon-rs::pem::continuity_token).
//!
//! # Why "FIPS-friendly" (not "FIPS-validated")
//!
//! The pure-C SHA-256 / HMAC-SHA256 implementations match the
//! algorithm specs exactly (NIST CAVS reference vectors form the
//! load-bearing drift gate) but the C code is not formally
//! certified by a NIST CAVS lab. Adopters who need formal
//! validation can opt in to a future `fips` cargo feature that
//! swaps the implementation to call into BoringSSL or OpenSSL-FIPS;
//! the wire-format + hash output remain byte-identical. This module
//! is the auditable, dep-free default.

use std::os::raw::c_char;

// ──────────────────────────────────────────────────────────────────────
// Raw FFI declarations — must mirror sha256.h / hmac.h / util.h /
// continuity.h byte-for-byte.
// ──────────────────────────────────────────────────────────────────────

pub const SHA256_DIGEST_SIZE: usize = 32;
pub const SHA256_BLOCK_SIZE: usize = 64;

#[repr(C)]
struct AxonCsysSha256Ctx {
    h: [u32; 8],
    total_bits: u64,
    buf: [u8; 64],
    buf_len: u8,
}

#[repr(C)]
struct AxonCsysHmacSha256Ctx {
    inner_ctx: AxonCsysSha256Ctx,
    opad: [u8; 64],
}

extern "C" {
    fn axon_csys_sha256_init(ctx: *mut AxonCsysSha256Ctx);
    fn axon_csys_sha256_update(ctx: *mut AxonCsysSha256Ctx, data: *const u8, len: usize);
    fn axon_csys_sha256_final(ctx: *mut AxonCsysSha256Ctx, out: *mut u8);
    fn axon_csys_sha256(data: *const u8, len: usize, out: *mut u8);

    fn axon_csys_hmac_sha256_init(ctx: *mut AxonCsysHmacSha256Ctx, key: *const u8, key_len: usize);
    fn axon_csys_hmac_sha256_update(ctx: *mut AxonCsysHmacSha256Ctx, data: *const u8, len: usize);
    fn axon_csys_hmac_sha256_final(ctx: *mut AxonCsysHmacSha256Ctx, out: *mut u8);
    fn axon_csys_hmac_sha256(
        key: *const u8,
        key_len: usize,
        data: *const u8,
        data_len: usize,
        out: *mut u8,
    );

    fn axon_csys_ct_eq(a: *const u8, b: *const u8, len: usize) -> i32;

    fn axon_csys_hex_encode(data: *const u8, len: usize, out: *mut c_char);
    fn axon_csys_hex_decode(hex: *const c_char, hex_len: usize, out: *mut u8) -> bool;

    fn axon_csys_b64url_encoded_len(byte_count: usize) -> usize;
    fn axon_csys_b64url_encode(
        data: *const u8,
        len: usize,
        out: *mut c_char,
        out_cap: usize,
        out_len: *mut usize,
    ) -> bool;
    fn axon_csys_b64url_decoded_len(char_count: usize) -> usize;
    fn axon_csys_b64url_decode(
        input: *const c_char,
        len: usize,
        out: *mut u8,
        out_cap: usize,
        out_len: *mut usize,
    ) -> bool;

    fn axon_csys_continuity_sign(
        key: *const u8,
        key_len: usize,
        session_id: *const c_char,
        session_id_len: usize,
        expiry_ms: i64,
        out_wire: *mut c_char,
        out_cap: usize,
        out_len: *mut usize,
    ) -> i32;
    fn axon_csys_continuity_verify(
        key: *const u8,
        key_len: usize,
        wire: *const c_char,
        wire_len: usize,
        out_session_id: *mut c_char,
        session_id_cap: usize,
        out_session_id_len: *mut usize,
        out_expiry_ms: *mut i64,
    ) -> i32;
    fn axon_csys_continuity_max_wire_len(session_id_len: usize) -> usize;
}

const CONT_OK: i32 = 0;
const CONT_BAD_BASE64: i32 = -1;
const CONT_BAD_FIELD_COUNT: i32 = -2;
const CONT_BAD_HEX: i32 = -3;
const CONT_BAD_EXPIRY: i32 = -4;
const CONT_FORGED_OR_ROTATED: i32 = -5;
const CONT_BUFFER_TOO_SMALL: i32 = -6;
const CONT_NULL_ARG: i32 = -7;
const CONT_PAYLOAD_TOO_LARGE: i32 = -8;

// ──────────────────────────────────────────────────────────────────────
// SHA-256
// ──────────────────────────────────────────────────────────────────────

/// Compute the SHA-256 digest of `data` in one shot.
pub fn sha256(data: &[u8]) -> [u8; SHA256_DIGEST_SIZE] {
    let mut out = [0u8; SHA256_DIGEST_SIZE];
    unsafe { axon_csys_sha256(data.as_ptr(), data.len(), out.as_mut_ptr()) };
    out
}

/// Streaming SHA-256 hasher. Equivalent to `Sha256::new()` /
/// `update()` / `finalize()` from the [`sha2`] crate but backed by
/// the in-house C kernel.
pub struct Sha256 {
    ctx: AxonCsysSha256Ctx,
}

impl Sha256 {
    pub fn new() -> Self {
        let mut ctx = AxonCsysSha256Ctx {
            h: [0u32; 8],
            total_bits: 0,
            buf: [0u8; 64],
            buf_len: 0,
        };
        unsafe { axon_csys_sha256_init(&mut ctx as *mut _) };
        Self { ctx }
    }

    pub fn update(&mut self, data: &[u8]) -> &mut Self {
        unsafe { axon_csys_sha256_update(&mut self.ctx as *mut _, data.as_ptr(), data.len()) };
        self
    }

    pub fn finalize(mut self) -> [u8; SHA256_DIGEST_SIZE] {
        let mut out = [0u8; SHA256_DIGEST_SIZE];
        unsafe { axon_csys_sha256_final(&mut self.ctx as *mut _, out.as_mut_ptr()) };
        out
    }
}

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

// ──────────────────────────────────────────────────────────────────────
// HMAC-SHA256
// ──────────────────────────────────────────────────────────────────────

/// Compute HMAC-SHA256 in one shot. Any key length accepted.
pub fn hmac_sha256(key: &[u8], data: &[u8]) -> [u8; SHA256_DIGEST_SIZE] {
    let mut out = [0u8; SHA256_DIGEST_SIZE];
    unsafe {
        axon_csys_hmac_sha256(
            key.as_ptr(),
            key.len(),
            data.as_ptr(),
            data.len(),
            out.as_mut_ptr(),
        )
    };
    out
}

/// Streaming HMAC-SHA256 MAC builder.
pub struct HmacSha256 {
    ctx: AxonCsysHmacSha256Ctx,
}

impl HmacSha256 {
    pub fn new(key: &[u8]) -> Self {
        let mut ctx = AxonCsysHmacSha256Ctx {
            inner_ctx: AxonCsysSha256Ctx {
                h: [0u32; 8],
                total_bits: 0,
                buf: [0u8; 64],
                buf_len: 0,
            },
            opad: [0u8; 64],
        };
        unsafe { axon_csys_hmac_sha256_init(&mut ctx as *mut _, key.as_ptr(), key.len()) };
        Self { ctx }
    }

    pub fn update(&mut self, data: &[u8]) -> &mut Self {
        unsafe { axon_csys_hmac_sha256_update(&mut self.ctx as *mut _, data.as_ptr(), data.len()) };
        self
    }

    pub fn finalize(mut self) -> [u8; SHA256_DIGEST_SIZE] {
        let mut out = [0u8; SHA256_DIGEST_SIZE];
        unsafe { axon_csys_hmac_sha256_final(&mut self.ctx as *mut _, out.as_mut_ptr()) };
        out
    }
}

// ──────────────────────────────────────────────────────────────────────
// Constant-time equality
// ──────────────────────────────────────────────────────────────────────

/// Constant-time byte-slice equality. Returns `true` iff `a` and `b`
/// have the same length AND all bytes match. The implementation runs
/// the same number of memory + arithmetic operations regardless of
/// input contents — timing observation does NOT leak the position of
/// the first byte mismatch.
///
/// Length mismatch returns `false` immediately (a length difference
/// is observable from the wire format itself; constant-time compare
/// is only meaningful for fixed-size MAC outputs).
pub fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let r = unsafe { axon_csys_ct_eq(a.as_ptr(), b.as_ptr(), a.len()) };
    r == 1
}

// ──────────────────────────────────────────────────────────────────────
// Hex codec
// ──────────────────────────────────────────────────────────────────────

/// Encode `data` to lowercase hex.
pub fn hex_encode(data: &[u8]) -> String {
    let len = data.len() * 2;
    let mut buf = vec![0u8; len];
    unsafe {
        axon_csys_hex_encode(data.as_ptr(), data.len(), buf.as_mut_ptr() as *mut c_char);
    }
    // SAFETY: hex emit only writes ASCII digits + lowercase a..f.
    unsafe { String::from_utf8_unchecked(buf) }
}

/// Decode a hex string (case-insensitive). Returns `None` if the
/// input length is odd or any character is not a hex digit.
pub fn hex_decode(hex: &str) -> Option<Vec<u8>> {
    if !hex.len().is_multiple_of(2) {
        return None;
    }
    let mut out = vec![0u8; hex.len() / 2];
    let ok =
        unsafe { axon_csys_hex_decode(hex.as_ptr() as *const c_char, hex.len(), out.as_mut_ptr()) };
    if ok {
        Some(out)
    } else {
        None
    }
}

// ──────────────────────────────────────────────────────────────────────
// Base64url-no-pad codec
// ──────────────────────────────────────────────────────────────────────

/// Encode `data` to base64url-no-pad (RFC 4648 §5 with padding stripped).
pub fn b64url_encode(data: &[u8]) -> String {
    let cap = unsafe { axon_csys_b64url_encoded_len(data.len()) };
    let mut buf = vec![0u8; cap];
    let mut out_len: usize = 0;
    let ok = unsafe {
        axon_csys_b64url_encode(
            data.as_ptr(),
            data.len(),
            buf.as_mut_ptr() as *mut c_char,
            cap,
            &mut out_len as *mut _,
        )
    };
    debug_assert!(ok && out_len == cap);
    buf.truncate(out_len);
    // SAFETY: encoder only emits ASCII alphabet characters.
    unsafe { String::from_utf8_unchecked(buf) }
}

/// Decode a base64url-no-pad string. Returns `None` if the alphabet
/// is violated or the length is `4k+1` (impossible byte count).
pub fn b64url_decode(input: &str) -> Option<Vec<u8>> {
    let cap = unsafe { axon_csys_b64url_decoded_len(input.len()) };
    if cap == usize::MAX {
        return None;
    }
    let mut out = vec![0u8; cap];
    let mut out_len: usize = 0;
    let ok = unsafe {
        axon_csys_b64url_decode(
            input.as_ptr() as *const c_char,
            input.len(),
            out.as_mut_ptr(),
            cap,
            &mut out_len as *mut _,
        )
    };
    if !ok {
        return None;
    }
    out.truncate(out_len);
    Some(out)
}

// ──────────────────────────────────────────────────────────────────────
// Continuity wire format
// ──────────────────────────────────────────────────────────────────────

/// Errors from the continuity-wire primitive. Mapped 1:1 from the
/// C error codes; `axon-rs::pem::continuity_token` adds the
/// `Expired` variant on top after checking the parsed `expiry_ms`
/// against `Utc::now()`.
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
    /// Output buffer (or session_id buffer) was too small.
    BufferTooSmall,
    /// FFI received a NULL pointer where one was required.
    NullArg,
    /// session_id exceeded the C kernel's compile-time limit
    /// (`AXON_CSYS_CONT_MAX_SESSION_ID`, currently 1024 bytes) or
    /// contained a forbidden 0x1e byte.
    PayloadTooLarge,
}

impl std::fmt::Display for ContinuityWireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BadBase64 => write!(f, "continuity wire: base64url decode failed"),
            Self::BadFieldCount => {
                write!(
                    f,
                    "continuity wire: expected exactly 3 0x1e-separated fields"
                )
            }
            Self::BadHex => {
                write!(f, "continuity wire: MAC field must be 64 hex digits")
            }
            Self::BadExpiry => {
                write!(f, "continuity wire: expiry field not parseable as i64")
            }
            Self::ForgedOrRotated => {
                write!(
                    f,
                    "continuity wire: HMAC mismatch (forged or signer key rotated)"
                )
            }
            Self::BufferTooSmall => {
                write!(f, "continuity wire: output buffer too small")
            }
            Self::NullArg => write!(f, "continuity wire: NULL pointer at FFI"),
            Self::PayloadTooLarge => write!(
                f,
                "continuity wire: session_id exceeds limit or contains 0x1e"
            ),
        }
    }
}

impl std::error::Error for ContinuityWireError {}

fn map_cont_error(code: i32) -> ContinuityWireError {
    match code {
        CONT_BAD_BASE64 => ContinuityWireError::BadBase64,
        CONT_BAD_FIELD_COUNT => ContinuityWireError::BadFieldCount,
        CONT_BAD_HEX => ContinuityWireError::BadHex,
        CONT_BAD_EXPIRY => ContinuityWireError::BadExpiry,
        CONT_FORGED_OR_ROTATED => ContinuityWireError::ForgedOrRotated,
        CONT_BUFFER_TOO_SMALL => ContinuityWireError::BufferTooSmall,
        CONT_NULL_ARG => ContinuityWireError::NullArg,
        CONT_PAYLOAD_TOO_LARGE => ContinuityWireError::PayloadTooLarge,
        // Defensive — covers future C-side error codes that arrive
        // before the Rust shim is updated.
        _ => ContinuityWireError::BadFieldCount,
    }
}

/// Continuity wire-format primitive — sign and verify operations.
/// This is the time-agnostic surface; consumers (axon-rs's
/// [`ContinuityTokenSigner`]) wrap it with chrono-flavoured
/// expiry checking.
pub struct ContinuityWire;

impl ContinuityWire {
    /// Sign `(session_id, expiry_ms)` with `key`. Returns the
    /// base64url-no-pad-encoded wire string.
    pub fn sign(
        key: &[u8],
        session_id: &str,
        expiry_ms: i64,
    ) -> Result<String, ContinuityWireError> {
        let cap = unsafe { axon_csys_continuity_max_wire_len(session_id.len()) };
        let mut buf = vec![0u8; cap];
        let mut out_len: usize = 0;
        let code = unsafe {
            axon_csys_continuity_sign(
                key.as_ptr(),
                key.len(),
                session_id.as_ptr() as *const c_char,
                session_id.len(),
                expiry_ms,
                buf.as_mut_ptr() as *mut c_char,
                cap,
                &mut out_len as *mut _,
            )
        };
        if code != CONT_OK {
            return Err(map_cont_error(code));
        }
        buf.truncate(out_len);
        // SAFETY: signer only emits base64url alphabet characters.
        Ok(unsafe { String::from_utf8_unchecked(buf) })
    }

    /// Verify `wire` against `key`, returning `(session_id, expiry_ms)`
    /// on success. Does NOT check whether the token has expired —
    /// the caller compares `expiry_ms` against the current time
    /// (typically via chrono).
    pub fn verify(key: &[u8], wire: &str) -> Result<(String, i64), ContinuityWireError> {
        // Session-id buffer sized to the C kernel's compile-time max.
        let mut sid_buf = vec![0u8; 1024];
        let mut sid_len: usize = 0;
        let mut expiry_ms: i64 = 0;
        let code = unsafe {
            axon_csys_continuity_verify(
                key.as_ptr(),
                key.len(),
                wire.as_ptr() as *const c_char,
                wire.len(),
                sid_buf.as_mut_ptr() as *mut c_char,
                sid_buf.len(),
                &mut sid_len as *mut _,
                &mut expiry_ms as *mut _,
            )
        };
        if code != CONT_OK {
            return Err(map_cont_error(code));
        }
        sid_buf.truncate(sid_len);
        // The session_id was a UTF-8 string when issued; verify bytes
        // are still valid UTF-8 before exposing as &str. The verify
        // path could hit corrupt bytes if a non-axon signer produced
        // the wire — defensive.
        let session_id =
            String::from_utf8(sid_buf).map_err(|_| ContinuityWireError::BadFieldCount)?;
        Ok((session_id, expiry_ms))
    }
}
