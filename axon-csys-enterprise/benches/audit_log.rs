//! § Fase 27.i — Audit log mmap throughput benchmark.
//!
//! Measures append latency + throughput of the tamper-evident audit
//! log kernel. Plan vivo §6 target: **≥10k events/sec single-threaded**
//! on contemporary hardware. The bench exercises three payload sizes
//! representative of Shield deployments:
//!
//!   - 32 B   (heartbeat / minimal trace span)
//!   - 256 B  (typical request metadata)
//!   - 4 KiB  (decoded LLM response with headers)
//!
//! Per-append work:
//!   - HMAC-SHA256 over (block_header || payload) — 64 + N bytes
//!   - mmap write at the reserved offset
//!   - atomic store on head_offset + event_count
//!   - mutex acquire + release
//!
//! 10k events/sec single-threaded → 100 µs per event budget. The
//! kernel typically runs ~1-5 µs per event in the warm case;
//! benchmark numbers feed plan vivo §6 sign-off.

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};

use axon_csys_enterprise::audit_log::{AuditLogWriter, DEFAULT_SEGMENT_BYTES};

const PAYLOAD_SIZES: &[(&str, usize)] = &[("32B", 32), ("256B", 256), ("4KiB", 4096)];

fn scratch_path(label: &str) -> std::path::PathBuf {
    let pid = std::process::id();
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mut p = std::env::temp_dir();
    p.push(format!("axon-bench-audit-{label}-{pid}-{ts}.log"));
    let _ = std::fs::remove_file(&p);
    p
}

const TENANT_KEY: &[u8] = b"audit-log-bench-tenant-key-2026-05-09";

fn bench_audit_log_append(c: &mut Criterion) {
    let mut group = c.benchmark_group("audit_log_append");

    for &(label, plen) in PAYLOAD_SIZES {
        let payload = vec![0xCDu8; plen];
        group.throughput(Throughput::Elements(1));

        // Use a SINGLE writer instance per measurement run so the
        // mmap setup cost is amortised. Each `iter` call does ONE
        // append. The segment is sized large enough to hold ~50k
        // events of the largest payload size (avoids segment-full
        // mid-bench).
        let segment_bytes = DEFAULT_SEGMENT_BYTES * 64; // 64 MiB
        group.bench_with_input(BenchmarkId::new("append", label), &payload, |b, payload| {
            let path = scratch_path(label);
            let writer = AuditLogWriter::open(&path, 1, 1, segment_bytes, TENANT_KEY, None)
                .expect("open writer");
            let mut counter: i64 = 0;
            b.iter(|| {
                counter += 1;
                writer
                    .append(criterion::black_box(counter), criterion::black_box(payload))
                    .expect("append");
            });
            drop(writer);
            let _ = std::fs::remove_file(&path);
        });
    }
    group.finish();
}

fn bench_audit_log_verify(c: &mut Criterion) {
    let mut group = c.benchmark_group("audit_log_verify");

    for &(label, plen) in PAYLOAD_SIZES {
        let payload = vec![0xCDu8; plen];
        let n_events: usize = 1000; // 1k events per verify run.

        let path = scratch_path(&format!("verify-{label}"));
        // Pre-fill segment.
        let segment_bytes = DEFAULT_SEGMENT_BYTES * 64;
        {
            let writer =
                AuditLogWriter::open(&path, 1, 1, segment_bytes, TENANT_KEY, None).unwrap();
            for i in 0..n_events {
                writer.append(i as i64, &payload).unwrap();
            }
            writer.sync().unwrap();
        }
        group.throughput(Throughput::Elements(n_events as u64));
        group.bench_function(BenchmarkId::new("verify-1k-events", label), |b| {
            b.iter(|| {
                let v = axon_csys_enterprise::audit_log::AuditLogVerifier::open(&path, TENANT_KEY)
                    .unwrap();
                v.verify().unwrap();
            });
        });
        let _ = std::fs::remove_file(&path);
    }
    group.finish();
}

criterion_group!(benches, bench_audit_log_append, bench_audit_log_verify);
criterion_main!(benches);
