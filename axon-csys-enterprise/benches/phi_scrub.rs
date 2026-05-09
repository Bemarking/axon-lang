//! § Fase 27.i — PHI scrubber throughput benchmark.
//!
//! Plan vivo §6 target: ~250 MB/s scalar baseline (≈ 2-3× faster
//! than Python regex). 27.g.2 SIMD upgrade targets 1+ GB/s.
//!
//! Two input regimes:
//!   - jargon-DENSE clinical text — every line contains a PHI
//!     pattern (SSN / phone / email / IP / MRN / date). Worst-case
//!     work: scalar verifier fires per anchor byte.
//!   - PHI-SPARSE general English — most bytes pass through
//!     unchanged. Best-case work: anchor-byte scan + word-boundary
//!     check + advance.

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};

use axon_csys_enterprise::phi_scrub::{scrub, scrub_into, PhiPatterns};

fn dense_phi_text() -> String {
    // ~5 KB block where almost every line contains a PHI token.
    let line = "Patient SSN 123-45-6789 phone (555) 123-4567 email doc@hospital.org \
         IP 192.168.1.42 MRN: 1234567 admitted on 2026-05-09 with chief complaint.\n";
    line.repeat(50)
}

fn sparse_text() -> String {
    // ~5 KB of generic clinical narrative. Few PHI anchors.
    let line = "Patient was admitted with chief complaint of dyspnea on exertion. \
                Past medical history includes congestive heart failure with reduced \
                ejection fraction, atrial fibrillation, and chronic kidney disease.\n";
    line.repeat(50)
}

fn bench_phi_scrub(c: &mut Criterion) {
    let mut group = c.benchmark_group("phi_scrub");

    let dense = dense_phi_text();
    let sparse = sparse_text();

    for (label, text) in [("dense", &dense), ("sparse", &sparse)] {
        group.throughput(Throughput::Bytes(text.len() as u64));

        // Allocating variant — exercises the public `scrub` entry.
        group.bench_with_input(BenchmarkId::new("scrub-alloc", label), text, |b, text| {
            b.iter(|| {
                let _ = scrub(criterion::black_box(text), PhiPatterns::all()).unwrap();
            });
        });

        // Zero-alloc variant — adopters in the streaming hot path.
        group.bench_with_input(
            BenchmarkId::new("scrub-zero-alloc", label),
            text,
            |b, text| {
                let mut buf: Vec<u8> = Vec::with_capacity(text.len() * 4 + 64);
                b.iter(|| {
                    let _ = scrub_into(
                        criterion::black_box(text.as_bytes()),
                        PhiPatterns::all(),
                        &mut buf,
                    )
                    .unwrap();
                });
            },
        );
    }
    group.finish();
}

criterion_group!(benches, bench_phi_scrub);
criterion_main!(benches);
