//! § Fase 27.i — Evidence packager benchmark suite.
//!
//! Measures bundle build + verify throughput at varying file counts.
//! Per-bundle work:
//!   - Sort files lexicographically.
//!   - Per-file SHA-256 hash.
//!   - Merkle-tree root over the sorted (path || 0x00 || sha256) leaves.
//!   - Canonical JSON manifest emit.
//!   - Ed25519 detached signature.
//!   - Byte-deterministic ZIP encode (CRC-32 + STORE).
//!
//! Verify symmetric: ZIP parse + manifest parse + signature verify +
//! per-file SHA-256 recompute + Merkle root recompute.
//!
//! Adopter use case: HIPAA Right-of-Access bundles typically contain
//! 5-50 files (encounters, labs, imaging metadata, billing). Bench
//! covers 1 / 10 / 50 file counts.

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};

use axon_csys_enterprise::evidence::{
    Ed25519SigningKey, EvidenceBuilder, EvidenceOptions, EvidenceVerifier,
};

const FILE_COUNTS: &[usize] = &[1, 10, 50];
const FILE_SIZE_BYTES: usize = 1024;

fn make_files(count: usize) -> Vec<(String, Vec<u8>)> {
    (0..count)
        .map(|i| {
            let path = format!("evidence/file-{i:03}.bin");
            let content: Vec<u8> = (0..FILE_SIZE_BYTES)
                .map(|j| (j as u8).wrapping_add(i as u8))
                .collect();
            (path, content)
        })
        .collect()
}

fn opts() -> EvidenceOptions {
    EvidenceOptions {
        tenant_id: 0xCAFE,
        evidence_id: "bench".to_owned(),
        created_ms: 0,
        signing_key_id: "bench-key".to_owned(),
    }
}

fn bench_evidence_build(c: &mut Criterion) {
    let mut group = c.benchmark_group("evidence_build");
    let key = Ed25519SigningKey::from_bytes(&[0x42u8; 32]);

    for &count in FILE_COUNTS {
        let files = make_files(count);
        // Throughput as bytes-of-content (excludes manifest + headers).
        let bytes = files.iter().map(|(_, c)| c.len()).sum::<usize>();
        group.throughput(Throughput::Bytes(bytes as u64));

        group.bench_with_input(BenchmarkId::new("files", count), &files, |b, files| {
            b.iter(|| {
                let mut builder = EvidenceBuilder::new();
                for (p, c) in files {
                    builder = builder.add_file(p.clone(), c.clone()).unwrap();
                }
                let _bundle = builder
                    .build(criterion::black_box(&key), criterion::black_box(&opts()))
                    .unwrap();
            });
        });
    }
    group.finish();
}

fn bench_evidence_verify(c: &mut Criterion) {
    let mut group = c.benchmark_group("evidence_verify");
    let key = Ed25519SigningKey::from_bytes(&[0x42u8; 32]);
    let pk = key.verifying_key();

    for &count in FILE_COUNTS {
        let files = make_files(count);
        let mut builder = EvidenceBuilder::new();
        for (p, c) in &files {
            builder = builder.add_file(p.clone(), c.clone()).unwrap();
        }
        let bundle = builder.build(&key, &opts()).unwrap();
        let bytes = files.iter().map(|(_, c)| c.len()).sum::<usize>();
        group.throughput(Throughput::Bytes(bytes as u64));

        group.bench_with_input(
            BenchmarkId::new("files", count),
            &bundle.zip_bytes,
            |b, zip| {
                let v = EvidenceVerifier::new(pk);
                b.iter(|| {
                    let _ = v.verify(criterion::black_box(zip)).unwrap();
                });
            },
        );
    }
    group.finish();
}

criterion_group!(benches, bench_evidence_build, bench_evidence_verify);
criterion_main!(benches);
