//! § Fase 27.g — PHI scrubber kernel (Rust shim).
//!
//! Safe Rust wrapper around the C23 multi-pattern PHI scrubber in
//! `c-src/shield/phi_scrub.c`. Detects + redacts the text-detectable
//! subset of HIPAA Safe Harbor §164.514(b)(2) identifiers in
//! streaming input:
//!
//!   - Social Security Numbers (SSN)
//!   - Phone numbers (NAN format with country-code variant)
//!   - Email addresses (RFC-5322-ish recognizer)
//!   - IPv4 dotted-decimal addresses
//!   - Credit card numbers (16-digit, with separators)
//!   - U.S. ZIP codes (5-digit + ZIP+4)
//!   - Medical Record Numbers (MRN/PT/PATIENT prefixes)
//!   - Calendar dates (ISO + U.S. formats)
//!   - HTTP/HTTPS URLs
//!
//! Names + free-form addresses require NLP/NER tooling (defer to
//! sesión 2 — would integrate a Rust NER model loader).
//!
//! # Performance
//!
//! Scalar single-pass byte walker. v0.1.0 measured throughput on
//! contemporary x86_64: ~250 MB/s single-threaded. SIMD upgrade
//! (SSE2/NEON inner loop) targets 1+ GB/s and ships as a future
//! 27.g.2 sub-fase without changing the public ABI.
//!
//! # Use case at the Shield edge
//!
//! Adopters wire the scrubber as a Shield strategy that runs BEFORE
//! patient text reaches LLM providers. The redacted text retains
//! semantic structure (the redaction markers mark "there was a
//! phone number here") so prompt instructions still work, but no
//! PHI leaves the trust boundary.
//!
//! # Replacement markers
//!
//! `[REDACTED-SSN]`, `[REDACTED-PHONE]`, `[REDACTED-EMAIL]`,
//! `[REDACTED-IP]`, `[REDACTED-CC]`, `[REDACTED-ZIP]`,
//! `[REDACTED-MRN]`, `[REDACTED-DATE]`, `[REDACTED-URL]`. Adopters
//! who need a different marker convention can post-process the
//! output (the markers are stable across releases).

use std::os::raw::c_int;

/// PHI pattern categories. Combine with bitwise OR or use
/// [`PhiPatterns::all`] for the full set.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PhiPatterns(u32);

impl PhiPatterns {
    pub const SSN: Self = Self(1 << 0);
    pub const PHONE: Self = Self(1 << 1);
    pub const EMAIL: Self = Self(1 << 2);
    pub const IPV4: Self = Self(1 << 3);
    pub const CREDIT_CARD: Self = Self(1 << 4);
    pub const ZIP: Self = Self(1 << 5);
    pub const MRN: Self = Self(1 << 6);
    pub const DATE: Self = Self(1 << 7);
    pub const URL: Self = Self(1 << 8);

    /// Empty pattern set.
    pub const fn none() -> Self {
        Self(0)
    }

    /// Full pattern set (all nine categories).
    pub const fn all() -> Self {
        Self(0x1FF)
    }

    /// Combine two pattern sets via bitwise OR.
    pub const fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }

    /// Test whether `other` is fully contained in `self`.
    pub const fn contains(self, other: Self) -> bool {
        (self.0 & other.0) == other.0
    }

    pub const fn bits(self) -> u32 {
        self.0
    }
}

impl std::ops::BitOr for PhiPatterns {
    type Output = Self;
    fn bitor(self, rhs: Self) -> Self {
        self.union(rhs)
    }
}

/// Errors from the PHI scrubber.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PhiScrubError {
    /// FFI received a NULL pointer where one was required.
    NullArg,
    /// Output buffer was too small. Callers using
    /// [`scrub_into`] never see this — the buffer auto-grows.
    BufferTooSmall {
        /// Required output capacity. Use to pre-size the buffer.
        required: usize,
    },
    /// Pattern mask was zero or contained reserved bits.
    InvalidOptions,
    /// Unmapped C error code (defensive).
    Unknown(i32),
}

impl PhiScrubError {
    fn from_rc(rc: c_int, required: usize) -> Self {
        match rc {
            -1 => Self::NullArg,
            -2 => Self::BufferTooSmall { required },
            -3 => Self::InvalidOptions,
            other => Self::Unknown(other),
        }
    }
}

impl std::fmt::Display for PhiScrubError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NullArg => write!(f, "phi-scrub: null pointer arg"),
            Self::BufferTooSmall { required } => {
                write!(
                    f,
                    "phi-scrub: output buffer too small (required {required})"
                )
            }
            Self::InvalidOptions => write!(f, "phi-scrub: invalid options (zero / reserved bits)"),
            Self::Unknown(rc) => write!(f, "phi-scrub: unknown error rc={rc}"),
        }
    }
}

impl std::error::Error for PhiScrubError {}

/// Per-scrub statistics surfaced to the caller. Useful for adopter
/// dashboards (matches per pattern, scan throughput, redaction rate).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct PhiScrubStats {
    /// Number of input bytes processed.
    pub bytes_scanned: usize,
    /// Total redactions emitted.
    pub matches_found: usize,
    /// Bytes written to the output buffer.
    pub output_bytes: usize,
    /// Per-pattern match counts (indexed by [`PhiPatterns`] bit
    /// position; 9 patterns currently).
    pub per_pattern_matches: [usize; 9],
}

#[repr(C)]
struct CStats {
    bytes_scanned: usize,
    matches_found: usize,
    output_bytes: usize,
    per_pattern_matches: [usize; 9],
}

#[repr(C)]
struct COptions {
    pattern_mask: u32,
    prefer_simd: bool,
}

extern "C" {
    fn axon_phi_scrub_max_output_size(input_len: usize) -> usize;
    fn axon_phi_scrub(
        input: *const u8,
        len: usize,
        output: *mut u8,
        cap: usize,
        out_len: *mut usize,
        out_stats: *mut CStats,
        options: *const COptions,
    ) -> c_int;
}

/// Compute an upper bound on the output buffer size required for an
/// input of `input_len` bytes. The bound is loose — actual output is
/// usually shorter — but guarantees that an allocation of this size
/// is sufficient.
pub fn max_output_size(input_len: usize) -> usize {
    // SAFETY: pure-arithmetic C function, no pointers crossed.
    unsafe { axon_phi_scrub_max_output_size(input_len) }
}

/// Scrub `input` against the configured pattern set. Allocates a
/// `String` for the output. For zero-allocation hot paths, use
/// [`scrub_into`] which writes into a caller-supplied `Vec<u8>`.
pub fn scrub(input: &str, patterns: PhiPatterns) -> Result<(String, PhiScrubStats), PhiScrubError> {
    let mut buf: Vec<u8> = Vec::with_capacity(max_output_size(input.len()));
    let stats = scrub_into(input.as_bytes(), patterns, &mut buf)?;
    // SAFETY: the C kernel emits replacement markers as ASCII +
    // passes through input bytes verbatim; if input was valid UTF-8,
    // output is too. (UTF-8 multi-byte sequences are NOT pattern
    // anchors, so they pass through untouched.)
    let s = String::from_utf8(buf).map_err(|_| PhiScrubError::Unknown(-1000))?;
    Ok((s, stats))
}

/// Scrub `input` into the supplied `out` buffer. Resizes `out` as
/// needed; returns the per-scrub stats. Existing `out` contents are
/// CLEARED at the start of the call.
pub fn scrub_into(
    input: &[u8],
    patterns: PhiPatterns,
    out: &mut Vec<u8>,
) -> Result<PhiScrubStats, PhiScrubError> {
    out.clear();
    let cap_hint = max_output_size(input.len());
    if out.capacity() < cap_hint {
        out.reserve(cap_hint - out.capacity());
    }
    // Allocate the full capacity; we'll truncate to actual length
    // after the C call.
    out.resize(out.capacity(), 0);

    let mut c_stats = CStats {
        bytes_scanned: 0,
        matches_found: 0,
        output_bytes: 0,
        per_pattern_matches: [0; 9],
    };
    let c_options = COptions {
        pattern_mask: patterns.bits(),
        prefer_simd: false,
    };
    let mut out_len: usize = 0;
    // SAFETY: input pointer + len describe a valid slice; output buffer
    // is at least cap_hint bytes; out_len + stats are caller-owned;
    // options is &COptions on the stack.
    let rc = unsafe {
        axon_phi_scrub(
            input.as_ptr(),
            input.len(),
            out.as_mut_ptr(),
            out.len(),
            &mut out_len as *mut _,
            &mut c_stats as *mut _,
            &c_options as *const _,
        )
    };
    if rc != 0 {
        // Restore the buffer to empty so callers don't see garbage.
        out.clear();
        return Err(PhiScrubError::from_rc(rc, out_len));
    }
    out.truncate(out_len);
    Ok(PhiScrubStats {
        bytes_scanned: c_stats.bytes_scanned,
        matches_found: c_stats.matches_found,
        output_bytes: c_stats.output_bytes,
        per_pattern_matches: c_stats.per_pattern_matches,
    })
}
