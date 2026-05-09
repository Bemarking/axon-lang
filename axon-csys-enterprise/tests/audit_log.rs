//! § Fase 27.d — Audit log mmap test pack.
//!
//! Exercises the [`axon_csys_enterprise::audit_log`] surface against:
//!   1. Append-only invariants — head_offset is monotonic, event_count
//!      is monotonic, event_id is dense + sequential.
//!   2. HMAC chain integrity — every block's seal_mac is the HMAC of
//!      `prev_hash || header || payload` keyed by the tenant key.
//!   3. Tamper detection — mutating any byte (header, prev_hash,
//!      timestamp, payload, seal_mac) breaks verify.
//!   4. Per-tenant key separation — wrong key fails verify with
//!      ChainBroken; tenant_id mismatch fails open.
//!   5. Reopen + resume — close + re-open the writer keeps the chain.
//!   6. Segment-rotation handoff — tail_hash from segment N feeds
//!      segment N+1's prev_segment_tail_hash; cross-segment chain
//!      verifies.
//!   7. Concurrent writers (8 threads × 100 events) — all events
//!      land safely + verify passes.
//!   8. Iterate matches append — bytes round-trip exactly.
//!   9. Cross-platform mmap behaviour — segment file is the same
//!      bytes regardless of OS (drift gate covers this in 27.i;
//!      here we just smoke the platform-specific mmap path).
//!
//! Each test creates a temporary segment file under `target/` and
//! removes it on success. Failed tests leave artifacts for forensic
//! inspection.

use axon_csys_enterprise::audit_log::{
    AuditLogError, AuditLogVerifier, AuditLogWriter, DEFAULT_SEGMENT_BYTES, HASH_SIZE,
    MIN_SEGMENT_BYTES,
};
use axon_csys_enterprise::crypto::hmac_sha256;

use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

// ──────────────────────────────────────────────────────────────────────
// Test scaffolding
// ──────────────────────────────────────────────────────────────────────

static SCRATCH_COUNTER: AtomicU64 = AtomicU64::new(0);

fn scratch_path(label: &str) -> PathBuf {
    let n = SCRATCH_COUNTER.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();
    let mut p = std::env::temp_dir();
    p.push(format!("axon-audit-test-{label}-{pid}-{n}.log"));
    let _ = std::fs::remove_file(&p);
    p
}

fn cleanup(path: &std::path::Path) {
    let _ = std::fs::remove_file(path);
}

const TENANT_ID: u64 = 0xCAFE_BEEF_DEAD_F00D;
const SEGMENT_ID: u64 = 1;
const TENANT_KEY: &[u8] = b"per-tenant-seal-key-v1-rotated-2026-05-09";

// ──────────────────────────────────────────────────────────────────────
// 1. Append-only invariants
// ──────────────────────────────────────────────────────────────────────

#[test]
fn append_increments_event_count_and_head_offset() {
    let path = scratch_path("invariants");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    )
    .expect("open");

    let stats0 = writer.stats().expect("stats0");
    assert_eq!(stats0.event_count, 0);
    assert_eq!(stats0.head_offset, 256, "header occupies first 256 bytes");
    assert_eq!(stats0.tenant_id, TENANT_ID);
    assert_eq!(stats0.segment_id, SEGMENT_ID);

    for i in 0..10u64 {
        let payload = format!("event-{i}").into_bytes();
        let r = writer.append(1_000 + i as i64, &payload).expect("append");
        assert_eq!(r.event_id, i);
        let stats = writer.stats().expect("stats");
        assert_eq!(stats.event_count, i + 1);
        assert!(stats.head_offset > stats0.head_offset);
    }

    drop(writer);
    cleanup(&path);
}

#[test]
fn append_assigns_dense_event_ids() {
    let path = scratch_path("dense-ids");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    )
    .unwrap();
    let mut last_id = None;
    for i in 0..50i64 {
        let r = writer.append(i, &[i as u8; 32]).unwrap();
        if let Some(prev) = last_id {
            assert_eq!(r.event_id, prev + 1);
        } else {
            assert_eq!(r.event_id, 0);
        }
        last_id = Some(r.event_id);
    }
    drop(writer);
    cleanup(&path);
}

#[test]
fn append_returns_seal_mac_matching_local_hmac() {
    let path = scratch_path("seal-mac-matches");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    )
    .unwrap();

    // First block — prev_hash is the segment's prev_segment_tail_hash
    // (zero, since we passed None at open).
    let payload = b"first event";
    let r = writer.append(42, payload).unwrap();
    assert_eq!(r.event_id, 0);

    // Recompute the seal_mac in user-space:
    //   seal_mac = HMAC(tenant_key, header[..64] || payload)
    // where header is 64 bytes of:
    //   prev_hash[32]     = zeros (first block, no prior seal)
    //   timestamp_ms[8]   = 42 LE
    //   event_id[8]       = 0  LE
    //   payload_len[4]    = 11 LE
    //   reserved[12]      = zeros
    let mut header = [0u8; 64];
    // prev_hash already zeroed.
    let ts: i64 = 42;
    header[32..40].copy_from_slice(&(ts as u64).to_le_bytes());
    // event_id = 0 already zeroed.
    let plen: u32 = payload.len() as u32;
    header[48..52].copy_from_slice(&plen.to_le_bytes());
    // reserved already zeroed.

    let mut blob = Vec::with_capacity(header.len() + payload.len());
    blob.extend_from_slice(&header);
    blob.extend_from_slice(payload);
    let expected = hmac_sha256(TENANT_KEY, &blob);
    assert_eq!(
        r.seal_mac, expected,
        "seal_mac diverges from user-space HMAC computation"
    );

    drop(writer);
    cleanup(&path);
}

#[test]
fn append_rejects_oversized_payload() {
    let path = scratch_path("oversize");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    )
    .unwrap();
    let huge = vec![0u8; 17 * 1024 * 1024]; // > 16 MiB cap
    let r = writer.append(1, &huge);
    assert!(matches!(r, Err(AuditLogError::PayloadTooLarge)));
    drop(writer);
    cleanup(&path);
}

#[test]
fn append_returns_segment_full_when_capacity_exhausted() {
    let path = scratch_path("seg-full");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        MIN_SEGMENT_BYTES, // 4 KiB — fits maybe ~30 small events.
        TENANT_KEY,
        None,
    )
    .unwrap();
    let payload = vec![0xABu8; 64];
    // Append until we hit segment full.
    let mut total_appended: u64 = 0;
    loop {
        match writer.append(0, &payload) {
            Ok(_) => total_appended += 1,
            Err(AuditLogError::SegmentFull) => break,
            Err(e) => panic!("unexpected error: {e:?}"),
        }
        // Hard upper bound — a 4 KiB segment cannot host >40 events
        // of (64 header + 64 payload + 32 mac = 160 bytes each).
        if total_appended > 50 {
            panic!("segment capacity should have been hit by now");
        }
    }
    assert!(
        total_appended > 0 && total_appended < 50,
        "expected partial fill before segment-full; got {total_appended}"
    );
    drop(writer);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 2. HMAC chain integrity (verifier walks every block)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn verifier_accepts_clean_segment() {
    let path = scratch_path("clean-segment");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        for i in 0..20u64 {
            let payload = format!("event #{i}").into_bytes();
            writer.append(1000 + i as i64, &payload).unwrap();
        }
        writer.sync().unwrap();
    }

    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).expect("open verifier");
    let stats = verifier.stats().unwrap();
    assert_eq!(stats.event_count, 20);
    verifier.verify().expect("clean chain must verify");
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verifier_chain_with_prev_segment_tail_hash() {
    let path = scratch_path("with-prev-anchor");
    let prev_tail = [0x42u8; HASH_SIZE];
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID + 1,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            Some(&prev_tail),
        )
        .unwrap();
        writer.append(1, b"linked event").unwrap();
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier
        .verify()
        .expect("chain with explicit anchor should verify");
    let tail = verifier.tail_hash().unwrap();
    assert_ne!(tail, prev_tail, "tail should be the new block's seal_mac");
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verifier_iterate_returns_appended_payloads_in_order() {
    let path = scratch_path("iterate");
    let payloads: Vec<Vec<u8>> = (0..15)
        .map(|i| format!("payload-{i:03}-{}", "x".repeat(i)).into_bytes())
        .collect();
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        for (i, p) in payloads.iter().enumerate() {
            writer.append(1_000_000 + i as i64, p).unwrap();
        }
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    let mut got: Vec<Vec<u8>> = Vec::new();
    let mut last_event_id: Option<u64> = None;
    verifier
        .iterate(|blk| {
            assert_eq!(blk.timestamp_ms, 1_000_000 + got.len() as i64);
            if let Some(prev) = last_event_id {
                assert_eq!(blk.event_id, prev + 1);
            } else {
                assert_eq!(blk.event_id, 0);
            }
            last_event_id = Some(blk.event_id);
            got.push(blk.payload.to_vec());
            Ok(())
        })
        .unwrap();
    assert_eq!(got, payloads);
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verifier_iterate_stops_on_user_err() {
    let path = scratch_path("iterate-stop");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        for i in 0..10 {
            writer.append(i, &[i as u8; 16]).unwrap();
        }
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    let mut count = 0;
    let res = verifier.iterate(|_| {
        count += 1;
        if count == 3 {
            Err(AuditLogError::Io)
        } else {
            Ok(())
        }
    });
    assert_eq!(count, 3);
    assert!(matches!(res, Err(AuditLogError::Io)));
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 3. Tamper detection
// ──────────────────────────────────────────────────────────────────────

fn flip_byte(path: &std::path::Path, offset: u64) {
    let mut f = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("reopen for tamper");
    f.seek(SeekFrom::Start(offset)).unwrap();
    let mut b = [0u8; 1];
    f.read_exact(&mut b).unwrap();
    b[0] ^= 0xFF;
    f.seek(SeekFrom::Start(offset)).unwrap();
    f.write_all(&b).unwrap();
    f.sync_all().unwrap();
}

#[test]
fn verify_detects_tampered_payload_byte() {
    let path = scratch_path("tamper-payload");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, &[0xAA; 64]).unwrap();
        writer.append(2, &[0xBB; 64]).unwrap();
        writer.append(3, &[0xCC; 64]).unwrap();
        writer.sync().unwrap();
    }

    // Block 0 starts at offset 256 (header). Block layout:
    //   [prev_hash:32][hdr:32][payload:64][seal_mac:32]
    // So payload byte 0 of block 0 is at offset 256 + 64 = 320.
    flip_byte(&path, 320);

    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    let res = verifier.verify_with_failure_event_id();
    assert!(matches!(res, Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verify_detects_tampered_timestamp_byte() {
    let path = scratch_path("tamper-timestamp");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(0xDEAD_BEEF_i64, b"x").unwrap();
        writer.sync().unwrap();
    }
    // Block 0 timestamp_ms is at header_offset_in_block 32 → file offset 256+32 = 288.
    flip_byte(&path, 288);
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    assert!(matches!(verifier.verify(), Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verify_detects_tampered_seal_mac_byte() {
    let path = scratch_path("tamper-seal");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        let payload = vec![0u8; 16];
        writer.append(1, &payload).unwrap();
        writer.sync().unwrap();
    }
    // Block 0 seal_mac is at file offset 256 + 64 (hdr) + 16 (payload) = 336.
    flip_byte(&path, 336);
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    assert!(matches!(verifier.verify(), Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verify_detects_tampered_segment_header_anchor() {
    let path = scratch_path("tamper-anchor");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"anchor target").unwrap();
        writer.sync().unwrap();
    }
    // Header field prev_segment_tail_hash is at offset 48..80 (32 bytes).
    // Flipping any byte in that range desynchronizes the chain anchor.
    flip_byte(&path, 48 + 5);
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    assert!(matches!(verifier.verify(), Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verify_detects_tampered_prev_hash_byte_in_block() {
    let path = scratch_path("tamper-prevhash");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"first").unwrap();
        writer.append(2, b"second").unwrap();
        writer.sync().unwrap();
    }
    // Block 1 starts after block 0 (size 64 hdr + 5 payload + 32 mac = 101 bytes).
    let block1_offset = 256 + 64 + 5 + 32; // 357
                                           // prev_hash field of block 1 is at block_offset + 0 (first 32 bytes).
    flip_byte(&path, block1_offset as u64 + 7);
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    assert!(matches!(verifier.verify(), Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 4. Per-tenant key separation
// ──────────────────────────────────────────────────────────────────────

#[test]
fn verify_with_wrong_tenant_key_fails() {
    let path = scratch_path("wrong-key");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"sealed-by-tenant-A").unwrap();
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, b"different-tenant-key").unwrap();
    assert!(matches!(verifier.verify(), Err(AuditLogError::ChainBroken)));
    drop(verifier);
    cleanup(&path);
}

#[test]
fn open_writer_with_wrong_tenant_id_on_existing_segment_fails() {
    let path = scratch_path("tenant-mismatch");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"event").unwrap();
        writer.sync().unwrap();
    }
    let res = AuditLogWriter::open(
        &path,
        TENANT_ID + 1, // different tenant!
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    );
    assert!(matches!(res, Err(AuditLogError::TenantMismatch)));
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 5. Reopen + resume
// ──────────────────────────────────────────────────────────────────────

#[test]
fn reopen_writer_resumes_chain() {
    let path = scratch_path("reopen");
    let mut tail_hash_after_first_open: [u8; HASH_SIZE];
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        let r1 = writer.append(1, b"first").unwrap();
        let r2 = writer.append(2, b"second").unwrap();
        tail_hash_after_first_open = r2.seal_mac;
        assert_eq!(r1.event_id, 0);
        assert_eq!(r2.event_id, 1);
        writer.sync().unwrap();
    }
    {
        // Reopen on the existing segment; new appends must chain to
        // the in-disk tail (event_id 1's seal_mac).
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        let stats = writer.stats().unwrap();
        assert_eq!(stats.event_count, 2);
        let r3 = writer.append(3, b"third").unwrap();
        assert_eq!(r3.event_id, 2);
        // seal_mac chained off of tail_hash_after_first_open.
        assert_ne!(r3.seal_mac, tail_hash_after_first_open);
        tail_hash_after_first_open = r3.seal_mac; // suppress unused mut.
        let _ = tail_hash_after_first_open;
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier.verify().expect("reopened chain should verify");
    let stats = verifier.stats().unwrap();
    assert_eq!(stats.event_count, 3);
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 6. Segment-rotation handoff
// ──────────────────────────────────────────────────────────────────────

#[test]
fn segment_rotation_chains_via_tail_hash() {
    let path_a = scratch_path("seg-A");
    let path_b = scratch_path("seg-B");
    let tail: [u8; HASH_SIZE] = {
        let writer = AuditLogWriter::open(
            &path_a,
            TENANT_ID,
            1,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        let r1 = writer.append(1, b"in-A-1").unwrap();
        let r2 = writer.append(2, b"in-A-2").unwrap();
        assert_eq!(r1.event_id, 0);
        assert_eq!(r2.event_id, 1);
        writer.sync().unwrap();
        r2.seal_mac
    };
    {
        let writer = AuditLogWriter::open(
            &path_b,
            TENANT_ID,
            2,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            Some(&tail),
        )
        .unwrap();
        let r1 = writer.append(3, b"in-B-1").unwrap();
        // Event id is per-segment (not transitive across segments).
        assert_eq!(r1.event_id, 0);
        writer.sync().unwrap();
    }

    // Each segment verifies independently.
    let v_a = AuditLogVerifier::open(&path_a, TENANT_KEY).unwrap();
    v_a.verify().expect("segment A verifies");
    let tail_from_a = v_a.tail_hash().unwrap();
    drop(v_a);

    let v_b = AuditLogVerifier::open(&path_b, TENANT_KEY).unwrap();
    v_b.verify().expect("segment B verifies");
    drop(v_b);

    // Cross-segment chain: segment A's tail equals what we passed as
    // segment B's prev_segment_tail_hash.
    assert_eq!(tail_from_a, tail);

    cleanup(&path_a);
    cleanup(&path_b);
}

// ──────────────────────────────────────────────────────────────────────
// 7. Concurrent writers (8 threads × 100 events)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn concurrent_writers_stay_consistent() {
    let path = scratch_path("concurrent");
    let writer = Arc::new(
        AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES * 4, // 4 MiB headroom for 800 events
            TENANT_KEY,
            None,
        )
        .unwrap(),
    );
    let threads = 8;
    let per_thread = 100;
    let handles: Vec<_> = (0..threads)
        .map(|t| {
            let w = writer.clone();
            std::thread::spawn(move || {
                for i in 0..per_thread {
                    let payload = format!("t{t}-i{i}").into_bytes();
                    w.append(t * 1000 + i, &payload).unwrap();
                }
            })
        })
        .collect();
    for h in handles {
        h.join().unwrap();
    }
    let stats = writer.stats().unwrap();
    assert_eq!(stats.event_count, threads as u64 * per_thread as u64);
    writer.sync().unwrap();
    drop(writer);

    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier
        .verify()
        .expect("concurrent appends must produce a verifiable chain");
    let stats = verifier.stats().unwrap();
    assert_eq!(stats.event_count, threads as u64 * per_thread as u64);
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 8. Iterate matches append (round-trip bytes)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn iterate_returns_byte_identical_payloads() {
    let path = scratch_path("byte-identical");
    let payloads: Vec<Vec<u8>> = vec![
        b"".to_vec(),
        b"a".to_vec(),
        vec![0xFFu8; 1024],
        b"hello world".to_vec(),
        (0..256u16).map(|i| (i & 0xff) as u8).collect(),
    ];
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        for (i, p) in payloads.iter().enumerate() {
            writer.append(i as i64 + 1, p).unwrap();
        }
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    let mut got = Vec::new();
    verifier
        .iterate(|blk| {
            got.push(blk.payload.to_vec());
            Ok(())
        })
        .unwrap();
    assert_eq!(got, payloads);
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 9. Cross-platform mmap smoke (just exercise the platform path)
// ──────────────────────────────────────────────────────────────────────

#[test]
fn segment_file_starts_with_magic_axenalog() {
    let path = scratch_path("magic");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"first").unwrap();
        writer.sync().unwrap();
    }
    let mut buf = vec![0u8; 8];
    let mut f = std::fs::File::open(&path).unwrap();
    f.read_exact(&mut buf).unwrap();
    assert_eq!(&buf, b"AXENALOG");
    cleanup(&path);
}

#[test]
fn segment_capacity_reflected_in_stats() {
    let path = scratch_path("capacity");
    let cap = MIN_SEGMENT_BYTES * 4;
    {
        let writer = AuditLogWriter::open(&path, TENANT_ID, 1, cap, TENANT_KEY, None).unwrap();
        let stats = writer.stats().unwrap();
        assert_eq!(stats.segment_capacity_bytes as usize, cap);
    }
    cleanup(&path);
}

#[test]
fn open_with_zero_key_is_rejected() {
    let path = scratch_path("zero-key");
    let res = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        b"",
        None,
    );
    assert!(matches!(res, Err(AuditLogError::KeyTooLarge)));
}

#[test]
fn open_with_too_small_segment_is_rejected() {
    let path = scratch_path("too-small");
    let res = AuditLogWriter::open(&path, TENANT_ID, SEGMENT_ID, 100, TENANT_KEY, None);
    assert!(matches!(res, Err(AuditLogError::SegmentTooSmall)));
}

#[test]
fn empty_payload_round_trips() {
    let path = scratch_path("empty-payload");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"").unwrap();
        writer.append(2, b"").unwrap();
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier.verify().expect("empty payloads still chain");
    let stats = verifier.stats().unwrap();
    assert_eq!(stats.event_count, 2);
    let mut count = 0;
    verifier
        .iterate(|blk| {
            assert_eq!(blk.payload.len(), 0);
            count += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(count, 2);
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 10. Verifier robustness — degenerate paths
// ──────────────────────────────────────────────────────────────────────

#[test]
fn verifier_open_on_nonexistent_file_fails_cleanly() {
    let path = scratch_path("nonexistent");
    // Path does not exist.
    let res = AuditLogVerifier::open(&path, TENANT_KEY);
    assert!(matches!(
        res,
        Err(AuditLogError::OpenFailed) | Err(AuditLogError::Io)
    ));
}

#[test]
fn verifier_open_on_empty_segment_with_no_events_returns_clean_zero_count() {
    let path = scratch_path("empty-seg");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    let stats = verifier.stats().unwrap();
    assert_eq!(stats.event_count, 0);
    verifier.verify().expect("empty segment is trivially valid");
    let mut iter_count = 0;
    verifier
        .iterate(|_| {
            iter_count += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(iter_count, 0);
    drop(verifier);
    cleanup(&path);
}

#[test]
fn verifier_open_on_corrupted_magic_fails() {
    let path = scratch_path("corrupted-magic");
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"x").unwrap();
        writer.sync().unwrap();
    }
    // Corrupt the magic.
    flip_byte(&path, 0);
    let res = AuditLogVerifier::open(&path, TENANT_KEY);
    assert!(matches!(res, Err(AuditLogError::BadMagic)));
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 11. Error display surface
// ──────────────────────────────────────────────────────────────────────

#[test]
fn error_display_strings_are_useful() {
    let cases = [
        (AuditLogError::ChainBroken, "tamper"),
        (AuditLogError::SegmentFull, "rotate"),
        (AuditLogError::PayloadTooLarge, "16 MiB"),
        (AuditLogError::TenantMismatch, "tenant_id mismatch"),
    ];
    for (e, fragment) in cases {
        let s = format!("{e}");
        assert!(
            s.to_lowercase().contains(&fragment.to_lowercase()),
            "error display `{s}` missing expected fragment `{fragment}`"
        );
    }
}

#[test]
fn append_after_sync_produces_consistent_state() {
    let path = scratch_path("sync-then-append");
    let writer = AuditLogWriter::open(
        &path,
        TENANT_ID,
        SEGMENT_ID,
        DEFAULT_SEGMENT_BYTES,
        TENANT_KEY,
        None,
    )
    .unwrap();
    writer.append(1, b"first").unwrap();
    writer.sync().unwrap();
    writer.append(2, b"second").unwrap();
    writer.sync().unwrap();
    writer.append(3, b"third").unwrap();
    writer.sync().unwrap();
    let stats = writer.stats().unwrap();
    assert_eq!(stats.event_count, 3);
    drop(writer);

    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier
        .verify()
        .expect("sync-interleaved appends must verify");
    drop(verifier);
    cleanup(&path);
}

// ──────────────────────────────────────────────────────────────────────
// 12. Iterate + verify decoupled — verify mutates internal state
// ──────────────────────────────────────────────────────────────────────

#[test]
fn tail_hash_matches_last_event_seal_mac() {
    let path = scratch_path("tail-equals-seal");
    let last_seal: [u8; HASH_SIZE];
    {
        let writer = AuditLogWriter::open(
            &path,
            TENANT_ID,
            SEGMENT_ID,
            DEFAULT_SEGMENT_BYTES,
            TENANT_KEY,
            None,
        )
        .unwrap();
        writer.append(1, b"a").unwrap();
        let r = writer.append(2, b"b").unwrap();
        last_seal = r.seal_mac;
        writer.sync().unwrap();
    }
    let verifier = AuditLogVerifier::open(&path, TENANT_KEY).unwrap();
    verifier.verify().unwrap();
    let tail = verifier.tail_hash().unwrap();
    assert_eq!(tail, last_seal);
    drop(verifier);
    cleanup(&path);
}
