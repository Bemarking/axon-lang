//! § Fase 27.d — Tamper-evident mmap audit log (Rust shim).
//!
//! Safe Rust wrappers around the C23 audit-log kernel in
//! `c-src/audit/log.c`. The C kernel implements:
//!
//!   - Cross-platform mmap-backed append-only ring buffer (POSIX
//!     `mmap` + Windows `MapViewOfFile`).
//!   - Per-block HMAC-SHA256 chain over `prev_hash || header || payload`,
//!     producing tamper-evident on-disk segments.
//!   - Per-tenant key + per-tenant `tenant_id` field for forensic
//!     replay.
//!   - Atomic head-pointer + event-count fields in the segment
//!     header so readers can walk a snapshot consistent with what
//!     the writer has committed (lock-free read, mutex-protected
//!     append).
//!
//! Threading model:
//!
//!   - Writer: thread-safe within a single process. Multiple
//!     producer threads can share an [`AuditLogWriter`] safely; the
//!     C kernel's append path holds an internal mutex.
//!   - Reader: [`AuditLogVerifier`] is independent of the writer.
//!     A reader on the same machine can verify a segment while the
//!     writer is still appending — they see a snapshot up to the
//!     committed event count.
//!   - Multi-process writers on the same segment file are NOT
//!     supported (an undefined-behaviour zone). Use one segment
//!     per process.
//!
//! Tamper-evidence model:
//!
//!   Each block's `seal_mac = HMAC-SHA256(tenant_key, block_header || payload)`.
//!   Mutating any byte in the segment (header field, prev_hash,
//!   timestamp, payload, or seal_mac itself) breaks the chain at
//!   verify time. The first block's `prev_hash` is the segment's
//!   `prev_segment_tail_hash` field — segments chain transitively
//!   so a tampered byte in segment N is detected even if segment
//!   N's HMAC is forged (the auditor cross-checks N+1's prev_hash
//!   against a known good source).

use std::ffi::CString;
use std::os::raw::{c_char, c_int, c_void};
use std::path::Path;

/// Length of the per-block tamper-evident HMAC seal (32 bytes —
/// SHA-256 output).
pub const HASH_SIZE: usize = 32;

/// Fixed-size segment header (256 bytes — cache-line-aligned to
/// 4× cacheline on x86 / 2× on Apple Silicon).
pub const HEADER_SIZE: usize = 256;

/// Default segment capacity if the caller doesn't specify (1 MiB).
pub const DEFAULT_SEGMENT_BYTES: usize = 1024 * 1024;

/// Minimum segment capacity. Below this the kernel cannot fit a
/// header + at least one block.
pub const MIN_SEGMENT_BYTES: usize = 4096;

/// Maximum payload size (16 MiB). Adopters appending payloads
/// larger than this should chunk + correlate via event_id.
pub const MAX_PAYLOAD_BYTES: usize = 16 * 1024 * 1024;

/// Errors from the audit log kernel. Mirrors the C-side
/// `AXON_AUDIT_ERR_*` codes 1:1.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuditLogError {
    /// FFI received a NULL pointer where one was required.
    NullArg,
    /// Path could not be converted to a C string.
    InvalidPath,
    /// open()/CreateFileA() failed.
    OpenFailed,
    /// mmap()/MapViewOfFile() failed.
    MmapFailed,
    /// Segment header magic bytes did not match `"AXENALOG"`.
    BadMagic,
    /// Format version on disk does not match the runtime kernel.
    BadVersion,
    /// Segment is full (rotate to a new segment).
    SegmentFull,
    /// Payload exceeds the 16 MiB cap.
    PayloadTooLarge,
    /// Tenant key length is zero or > 256 bytes.
    KeyTooLarge,
    /// Segment capacity below the 4 KiB minimum.
    SegmentTooSmall,
    /// HMAC chain broken (tamper detected or wrong tenant key).
    ChainBroken,
    /// Segment truncated mid-block (incomplete write).
    Truncated,
    /// Block header reports a payload_len exceeding the cap.
    BadPayloadLen,
    /// Tenant id on disk does not match the writer's tenant id.
    TenantMismatch,
    /// I/O failure (read/write/sync).
    Io,
    /// Out of memory allocating the writer/verifier struct.
    OutOfMemory,
    /// User-supplied buffer too small for the requested operation.
    BufferTooSmall,
    /// Unknown/unmapped error code.
    Unknown(i32),
}

impl AuditLogError {
    fn from_rc(rc: c_int) -> Self {
        match rc {
            -1 => Self::NullArg,
            -2 => Self::InvalidPath,
            -3 => Self::OpenFailed,
            -4 => Self::MmapFailed,
            -5 => Self::BadMagic,
            -6 => Self::BadVersion,
            -7 => Self::SegmentFull,
            -8 => Self::PayloadTooLarge,
            -9 => Self::KeyTooLarge,
            -10 => Self::SegmentTooSmall,
            -11 => Self::ChainBroken,
            -12 => Self::Truncated,
            -13 => Self::BadPayloadLen,
            -14 => Self::TenantMismatch,
            -15 => Self::Io,
            -16 => Self::OutOfMemory,
            -17 => Self::BufferTooSmall,
            other => Self::Unknown(other),
        }
    }
}

impl std::fmt::Display for AuditLogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NullArg => write!(f, "audit log: null pointer arg"),
            Self::InvalidPath => write!(f, "audit log: invalid path"),
            Self::OpenFailed => write!(f, "audit log: file open failed"),
            Self::MmapFailed => write!(f, "audit log: mmap failed"),
            Self::BadMagic => write!(f, "audit log: bad magic"),
            Self::BadVersion => write!(f, "audit log: format version mismatch"),
            Self::SegmentFull => write!(f, "audit log: segment full (rotate)"),
            Self::PayloadTooLarge => write!(f, "audit log: payload exceeds 16 MiB cap"),
            Self::KeyTooLarge => write!(f, "audit log: tenant key length out of range"),
            Self::SegmentTooSmall => write!(f, "audit log: segment below 4 KiB minimum"),
            Self::ChainBroken => write!(
                f,
                "audit log: HMAC chain broken (tamper detected or wrong tenant key)"
            ),
            Self::Truncated => write!(f, "audit log: segment truncated mid-block"),
            Self::BadPayloadLen => write!(f, "audit log: block payload_len exceeds cap"),
            Self::TenantMismatch => write!(f, "audit log: tenant_id mismatch"),
            Self::Io => write!(f, "audit log: I/O failure"),
            Self::OutOfMemory => write!(f, "audit log: out of memory"),
            Self::BufferTooSmall => write!(f, "audit log: user buffer too small"),
            Self::Unknown(rc) => write!(f, "audit log: unknown error rc={rc}"),
        }
    }
}

impl std::error::Error for AuditLogError {}

#[repr(C)]
#[derive(Debug, Clone, Copy)]
struct CStats {
    tenant_id: u64,
    segment_id: u64,
    segment_capacity_bytes: u64,
    head_offset: u64,
    event_count: u64,
    created_ms: i64,
}

/// Snapshot of segment counters. Read lock-free from the segment
/// header — represents what the writer has committed up to the
/// moment of the call.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AuditLogStats {
    pub tenant_id: u64,
    pub segment_id: u64,
    pub segment_capacity_bytes: u64,
    pub head_offset: u64,
    pub event_count: u64,
    pub created_ms: i64,
}

#[repr(C)]
struct CBlock {
    timestamp_ms: i64,
    event_id: u64,
    payload_len: u32,
    payload: *const u8,
    prev_hash: [u8; HASH_SIZE],
    seal_mac: [u8; HASH_SIZE],
}

/// One audit-log block surfaced by [`AuditLogVerifier::iterate`].
///
/// `payload` is borrowed from the verifier's mmap region — its
/// lifetime is tied to the verifier instance. Adopters that need
/// to retain the bytes past the iterate call must clone them.
#[derive(Debug, Clone)]
pub struct AuditLogBlock<'v> {
    pub timestamp_ms: i64,
    pub event_id: u64,
    pub payload: &'v [u8],
    pub prev_hash: [u8; HASH_SIZE],
    pub seal_mac: [u8; HASH_SIZE],
}

/// Opaque writer handle from the C kernel.
#[repr(C)]
struct CWriter {
    _private: [u8; 0],
}

/// Opaque verifier handle from the C kernel.
#[repr(C)]
struct CVerifier {
    _private: [u8; 0],
}

extern "C" {
    fn axon_audit_log_writer_open(
        path: *const c_char,
        tenant_id: u64,
        segment_id: u64,
        segment_capacity_bytes: usize,
        tenant_key: *const u8,
        tenant_key_len: usize,
        prev_segment_tail_hash: *const u8,
        out_writer: *mut *mut CWriter,
    ) -> c_int;
    fn axon_audit_log_writer_append(
        writer: *mut CWriter,
        timestamp_ms: i64,
        payload: *const u8,
        payload_len: usize,
        out_seal_mac: *mut u8,
        out_event_id: *mut u64,
    ) -> c_int;
    fn axon_audit_log_writer_stats(writer: *const CWriter, out_stats: *mut CStats) -> c_int;
    fn axon_audit_log_writer_sync(writer: *mut CWriter) -> c_int;
    fn axon_audit_log_writer_close(writer: *mut CWriter);

    fn axon_audit_log_verifier_open(
        path: *const c_char,
        tenant_key: *const u8,
        tenant_key_len: usize,
        out_verifier: *mut *mut CVerifier,
    ) -> c_int;
    fn axon_audit_log_verifier_stats(verifier: *const CVerifier, out_stats: *mut CStats) -> c_int;
    fn axon_audit_log_verifier_verify(
        verifier: *mut CVerifier,
        out_failure_event_id: *mut u64,
    ) -> c_int;
    fn axon_audit_log_verifier_iterate(
        verifier: *mut CVerifier,
        callback: extern "C" fn(block: *const CBlock, user: *mut c_void) -> c_int,
        user: *mut c_void,
    ) -> c_int;
    fn axon_audit_log_verifier_tail_hash(verifier: *const CVerifier, out_hash: *mut u8) -> c_int;
    fn axon_audit_log_verifier_close(verifier: *mut CVerifier);
}

fn stats_from_c(c: CStats) -> AuditLogStats {
    AuditLogStats {
        tenant_id: c.tenant_id,
        segment_id: c.segment_id,
        segment_capacity_bytes: c.segment_capacity_bytes,
        head_offset: c.head_offset,
        event_count: c.event_count,
        created_ms: c.created_ms,
    }
}

fn path_to_cstring(path: &Path) -> Result<CString, AuditLogError> {
    let s = path.to_str().ok_or(AuditLogError::InvalidPath)?;
    CString::new(s).map_err(|_| AuditLogError::InvalidPath)
}

/// Tamper-evident audit log writer. Wraps the C-side opaque handle
/// with a Rust-flavoured safe API.
///
/// # Concurrency
///
/// Sharing an `AuditLogWriter` across threads requires wrapping it
/// in `Arc<...>` and ensuring `&AuditLogWriter` operations are safe
/// (the C kernel uses an internal mutex). The struct is `Send +
/// Sync` because the C kernel's append path is thread-safe.
pub struct AuditLogWriter {
    handle: *mut CWriter,
}

// SAFETY: the C kernel's append path holds an internal mutex around
// every mmap mutation. Multiple threads sharing `&AuditLogWriter` are
// safe by C-side contract.
unsafe impl Send for AuditLogWriter {}
unsafe impl Sync for AuditLogWriter {}

impl AuditLogWriter {
    /// Open or create a segment file. If the file exists, the
    /// header is validated + the writer resumes appending after
    /// the last committed event. If the file is fresh, the
    /// header is initialized with the supplied parameters.
    ///
    /// `prev_segment_tail_hash` is the seal_mac of the last block
    /// in the preceding segment (when rotating segments). Pass
    /// `None` for a brand-new audit log — the chain anchor will
    /// be all-zeros.
    pub fn open(
        path: &Path,
        tenant_id: u64,
        segment_id: u64,
        segment_capacity_bytes: usize,
        tenant_key: &[u8],
        prev_segment_tail_hash: Option<&[u8; HASH_SIZE]>,
    ) -> Result<Self, AuditLogError> {
        let cpath = path_to_cstring(path)?;
        let mut handle: *mut CWriter = std::ptr::null_mut();
        let prev_ptr = prev_segment_tail_hash
            .map(|h| h.as_ptr())
            .unwrap_or(std::ptr::null());
        // SAFETY: All pointers are either valid for the indicated
        // length or NULL where the C contract permits. `cpath` has
        // a static-string-style C-compatible NUL terminator. `out`
        // is a valid pointer to a NULL handle slot.
        let rc = unsafe {
            axon_audit_log_writer_open(
                cpath.as_ptr(),
                tenant_id,
                segment_id,
                segment_capacity_bytes,
                tenant_key.as_ptr(),
                tenant_key.len(),
                prev_ptr,
                &mut handle as *mut _,
            )
        };
        if rc == 0 {
            Ok(Self { handle })
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Append one event. Returns the assigned `event_id` + the
    /// computed `seal_mac` (useful for segment-rotation handoff).
    pub fn append(
        &self,
        timestamp_ms: i64,
        payload: &[u8],
    ) -> Result<AuditLogAppendResult, AuditLogError> {
        let mut seal_mac = [0u8; HASH_SIZE];
        let mut event_id: u64 = 0;
        // SAFETY: handle is valid (constructed by `open`); payload
        // points to len bytes; out buffers are caller-owned.
        let rc = unsafe {
            axon_audit_log_writer_append(
                self.handle,
                timestamp_ms,
                payload.as_ptr(),
                payload.len(),
                seal_mac.as_mut_ptr(),
                &mut event_id as *mut _,
            )
        };
        if rc == 0 {
            Ok(AuditLogAppendResult { event_id, seal_mac })
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Read a snapshot of segment stats.
    pub fn stats(&self) -> Result<AuditLogStats, AuditLogError> {
        let mut c = CStats {
            tenant_id: 0,
            segment_id: 0,
            segment_capacity_bytes: 0,
            head_offset: 0,
            event_count: 0,
            created_ms: 0,
        };
        // SAFETY: handle valid; out_stats is caller-owned.
        let rc = unsafe { axon_audit_log_writer_stats(self.handle, &mut c as *mut _) };
        if rc == 0 {
            Ok(stats_from_c(c))
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Force pending mmap pages to disk (msync/FlushViewOfFile).
    pub fn sync(&self) -> Result<(), AuditLogError> {
        // SAFETY: handle valid.
        let rc = unsafe { axon_audit_log_writer_sync(self.handle) };
        if rc == 0 {
            Ok(())
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }
}

impl Drop for AuditLogWriter {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            // SAFETY: handle owned by us; C close releases mmap +
            // mutex + heap memory. Setting to null is defensive only
            // (Drop runs once per allocation).
            unsafe { axon_audit_log_writer_close(self.handle) };
            self.handle = std::ptr::null_mut();
        }
    }
}

/// Result of one `append` call.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AuditLogAppendResult {
    pub event_id: u64,
    pub seal_mac: [u8; HASH_SIZE],
}

/// Read-only verifier. Walks every committed block, recomputes the
/// HMAC chain, and surfaces the events to the caller.
pub struct AuditLogVerifier {
    handle: *mut CVerifier,
}

// SAFETY: the C kernel's verifier path is read-only; concurrent
// reads from multiple threads against the same verifier handle are
// safe.
unsafe impl Send for AuditLogVerifier {}
unsafe impl Sync for AuditLogVerifier {}

impl AuditLogVerifier {
    /// Open a segment file read-only with the per-tenant seal key.
    pub fn open(path: &Path, tenant_key: &[u8]) -> Result<Self, AuditLogError> {
        let cpath = path_to_cstring(path)?;
        let mut handle: *mut CVerifier = std::ptr::null_mut();
        // SAFETY: cpath valid C string; out points to a NULL handle slot.
        let rc = unsafe {
            axon_audit_log_verifier_open(
                cpath.as_ptr(),
                tenant_key.as_ptr(),
                tenant_key.len(),
                &mut handle as *mut _,
            )
        };
        if rc == 0 {
            Ok(Self { handle })
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Read a snapshot of segment stats.
    pub fn stats(&self) -> Result<AuditLogStats, AuditLogError> {
        let mut c = CStats {
            tenant_id: 0,
            segment_id: 0,
            segment_capacity_bytes: 0,
            head_offset: 0,
            event_count: 0,
            created_ms: 0,
        };
        // SAFETY: handle valid; out_stats caller-owned.
        let rc = unsafe { axon_audit_log_verifier_stats(self.handle, &mut c as *mut _) };
        if rc == 0 {
            Ok(stats_from_c(c))
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Verify every committed block. Returns `Ok(())` if the chain
    /// is intact + every seal_mac matches; otherwise the failure
    /// reason. On `ChainBroken` / `Truncated` the `event_id` of the
    /// first failing block is included in the error context — pull
    /// it from [`Self::verify_with_failure_event_id`].
    pub fn verify(&self) -> Result<(), AuditLogError> {
        self.verify_with_failure_event_id().map(|_| ())
    }

    /// Verify + return the `event_id` of the last successfully
    /// validated block, or the first failing event id on error.
    pub fn verify_with_failure_event_id(&self) -> Result<u64, AuditLogError> {
        let mut failure_event_id: u64 = u64::MAX;
        // SAFETY: handle valid; failure_event_id slot caller-owned.
        let rc =
            unsafe { axon_audit_log_verifier_verify(self.handle, &mut failure_event_id as *mut _) };
        if rc == 0 {
            Ok(failure_event_id)
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Iterate every committed block, calling `callback(block)` per
    /// event. Stops on first user-callback `Err(...)` return; the
    /// error is propagated as the iterate result. The chain is NOT
    /// re-verified during iterate — call [`Self::verify`] separately
    /// if you need both.
    pub fn iterate<F>(&self, mut callback: F) -> Result<(), AuditLogError>
    where
        F: FnMut(AuditLogBlock<'_>) -> Result<(), AuditLogError>,
    {
        // The trampoline boxes the closure as a trait object so the
        // extern "C" function is a non-generic, single-instantiation
        // fn pointer the C kernel can call. Boxing avoids monomorphisation
        // of the C callback per closure type, keeps build artifacts small,
        // and dodges some rustc edge cases around generic extern "C" fns.
        type CbBox<'a> = &'a mut dyn FnMut(AuditLogBlock<'_>) -> Result<(), AuditLogError>;

        struct State<'a> {
            cb: CbBox<'a>,
            user_err: Option<AuditLogError>,
        }

        extern "C" fn trampoline(block: *const CBlock, user: *mut c_void) -> c_int {
            // SAFETY: `user` is a `&mut State` pointer set by the
            // outer call; the C kernel doesn't escape it past the
            // invocation.
            let state = unsafe { &mut *(user as *mut State<'_>) };
            // SAFETY: `block` points to a struct populated by the
            // C kernel; payload pointer is valid for `payload_len`
            // bytes until the verifier drops.
            let blk = unsafe { &*block };
            let payload: &[u8] = if blk.payload_len == 0 {
                &[]
            } else {
                // SAFETY: payload is non-null per C contract on len > 0.
                unsafe { std::slice::from_raw_parts(blk.payload, blk.payload_len as usize) }
            };
            let view = AuditLogBlock {
                timestamp_ms: blk.timestamp_ms,
                event_id: blk.event_id,
                payload,
                prev_hash: blk.prev_hash,
                seal_mac: blk.seal_mac,
            };
            match (state.cb)(view) {
                Ok(()) => 0,
                Err(e) => {
                    state.user_err = Some(e);
                    1
                }
            }
        }

        let mut state = State {
            cb: &mut callback as CbBox,
            user_err: None,
        };
        // SAFETY: handle valid; trampoline matches the C callback
        // signature; state is alive for the duration of the call.
        let rc = unsafe {
            axon_audit_log_verifier_iterate(
                self.handle,
                trampoline,
                &mut state as *mut _ as *mut c_void,
            )
        };
        if let Some(e) = state.user_err {
            return Err(e);
        }
        if rc == 0 {
            Ok(())
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }

    /// Read the seal_mac of the last committed block — the value
    /// to feed as `prev_segment_tail_hash` when opening the next
    /// segment in a chain.
    ///
    /// On a brand-new empty segment this returns the segment header's
    /// `prev_segment_tail_hash` (the chain anchor).
    pub fn tail_hash(&self) -> Result<[u8; HASH_SIZE], AuditLogError> {
        let mut out = [0u8; HASH_SIZE];
        // SAFETY: handle valid; out is a stack-resident array.
        let rc = unsafe { axon_audit_log_verifier_tail_hash(self.handle, out.as_mut_ptr()) };
        if rc == 0 {
            Ok(out)
        } else {
            Err(AuditLogError::from_rc(rc))
        }
    }
}

impl Drop for AuditLogVerifier {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            // SAFETY: handle owned by us; C close releases mmap.
            unsafe { axon_audit_log_verifier_close(self.handle) };
            self.handle = std::ptr::null_mut();
        }
    }
}
