//! § Fase 27.i — HMAC-SHA256 benchmark suite.
//!
//! Measures throughput of the locally-routed `crypto::hmac_sha256`
//! against OSS `axon_csys::hmac_sha256` and `hmac::Hmac<sha2::Sha256>`.
//!
//! Two key-length regimes:
//!   - 32-byte key (typical session key, no precompression)
//!   - 200-byte key (exceeds 64-byte HMAC block; first compressed
//!     to 32 bytes via SHA-256 per RFC 2104 §2)
//!
//! Data sizes: 64 B, 1 KiB, 64 KiB, 1 MiB.

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use hmac::{Hmac, Mac as _};

const SIZES: &[(&str, usize)] = &[
    ("64B", 64),
    ("1KiB", 1024),
    ("64KiB", 65_536),
    ("1MiB", 1_048_576),
];

const KEY_LENGTHS: &[(&str, usize)] = &[("k32", 32), ("k200", 200)];

fn fixed_pattern(seed: u8, len: usize) -> Vec<u8> {
    (0..len)
        .map(|i| ((i as u8).wrapping_mul(31)).wrapping_add(seed))
        .collect()
}

fn bench_hmac(c: &mut Criterion) {
    let mut group = c.benchmark_group("hmac_sha256");
    for &(klabel, klen) in KEY_LENGTHS {
        let key = fixed_pattern(0xAA, klen);
        for &(dlabel, dlen) in SIZES {
            let data = fixed_pattern(0x55, dlen);
            let label = format!("{klabel}-{dlabel}");
            group.throughput(Throughput::Bytes(dlen as u64));

            group.bench_with_input(
                BenchmarkId::new("axon-enterprise", &label),
                &(key.clone(), data.clone()),
                |b, (k, d)| {
                    b.iter(|| {
                        axon_csys_enterprise::crypto::hmac_sha256(
                            criterion::black_box(k),
                            criterion::black_box(d),
                        )
                    });
                },
            );
            group.bench_with_input(
                BenchmarkId::new("axon-csys-oss", &label),
                &(key.clone(), data.clone()),
                |b, (k, d)| {
                    b.iter(|| {
                        axon_csys::hmac_sha256(criterion::black_box(k), criterion::black_box(d))
                    });
                },
            );
            group.bench_with_input(
                BenchmarkId::new("hmac-crate", &label),
                &(key.clone(), data.clone()),
                |b, (k, d)| {
                    b.iter(|| {
                        let mut mac = Hmac::<sha2::Sha256>::new_from_slice(k).unwrap();
                        mac.update(d);
                        let _ = mac.finalize().into_bytes();
                    });
                },
            );
        }
    }
    group.finish();
}

criterion_group!(benches, bench_hmac);
criterion_main!(benches);
