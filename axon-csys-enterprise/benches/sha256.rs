//! § Fase 27.i — SHA-256 benchmark suite.
//!
//! Measures throughput of the locally-routed `crypto::sha256` against
//! OSS `axon_csys::sha256` (pure-C) and `sha2::Sha256` (RustCrypto)
//! on inputs of 64 B, 1 KiB, 64 KiB, 1 MiB.
//!
//! Expected outcomes:
//!   - no-fips path: parity with OSS axon-csys (same C kernel under
//!     the hood — re-exported), parity ±10% with sha2 crate.
//!   - FIPS path (when feature enabled): ≤2× overhead vs OSS pure-C
//!     per the plan vivo §6 target. The overhead comes from EVP
//!     dispatch + provider property lookup; the SHA-256 transform
//!     itself is the same FIPS-validated implementation.

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use sha2::Digest as _;

const SIZES: &[(&str, usize)] = &[
    ("64B", 64),
    ("1KiB", 1024),
    ("64KiB", 65_536),
    ("1MiB", 1_048_576),
];

fn fixed_pattern(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i as u8).wrapping_mul(31)).collect()
}

fn bench_sha256(c: &mut Criterion) {
    let mut group = c.benchmark_group("sha256");
    for &(label, len) in SIZES {
        let data = fixed_pattern(len);
        group.throughput(Throughput::Bytes(len as u64));

        // Locally-routed (no-fips → OSS pure-C; FIPS → BoringSSL/OpenSSL).
        group.bench_with_input(
            BenchmarkId::new("axon-enterprise", label),
            &data,
            |b, data| {
                b.iter(|| axon_csys_enterprise::crypto::sha256(criterion::black_box(data)));
            },
        );
        // OSS axon-csys reference.
        group.bench_with_input(
            BenchmarkId::new("axon-csys-oss", label),
            &data,
            |b, data| {
                b.iter(|| axon_csys::sha256(criterion::black_box(data)));
            },
        );
        // sha2 crate reference.
        group.bench_with_input(BenchmarkId::new("sha2-crate", label), &data, |b, data| {
            b.iter(|| {
                let _: [u8; 32] = sha2::Sha256::digest(criterion::black_box(data)).into();
            });
        });
    }
    group.finish();
}

criterion_group!(benches, bench_sha256);
criterion_main!(benches);
