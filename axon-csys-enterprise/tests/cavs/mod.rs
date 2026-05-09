//! § Fase 27.c — NIST CAVS reference test vectors (D10 ratified).
//!
//! NIST publishes the Cryptographic Algorithm Validation Suite
//! (CAVS) vectors as part of the public FIPS Algorithm Testing
//! programme. They are in the public domain; reproducing them here
//! requires no licensing.
//!
//! Sources:
//!   - SHA-256: NIST FIPS 180-2 / 180-4 §B.1 — B.4 worked examples;
//!     plus widely-cited canonical reference inputs (the "quick
//!     brown fox" pair has been used as a SHA-256 reference since
//!     the FIPS publication).
//!   - HMAC-SHA256: RFC 4231 test cases (canonical reference, used
//!     by NIST CAVS as the verification-pack baseline).
//!
//! The drift gate (Fase 27.i) runs these vectors against BOTH the
//! locally-routed crypto path and the OSS axon-csys pure-C path,
//! asserting byte-equality. Any difference is a CMVP-violation
//! signal.

#![allow(dead_code)] // Each test file imports a subset.

/// One row of the SHA-256 NIST CAVS vector set.
pub struct Sha256Vector {
    /// Description (matches the source `.rsp` Len field).
    pub label: &'static str,
    /// Input bytes.
    pub msg: &'static [u8],
    /// Expected lowercase-hex SHA-256 digest (64 chars).
    pub digest: &'static str,
}

/// One row of the HMAC-SHA256 RFC 4231 test pack.
pub struct HmacSha256Vector {
    /// Description (matches the RFC 4231 Test Case number).
    pub label: &'static str,
    /// HMAC key.
    pub key: &'static [u8],
    /// HMAC data.
    pub data: &'static [u8],
    /// Expected lowercase-hex HMAC-SHA256 MAC (64 chars).
    pub mac: &'static str,
}

// ──────────────────────────────────────────────────────────────────────
// SHA-256 vectors — only the load-bearing canonical inputs whose
// digests appear in NIST FIPS 180-4 / RFC literature. Synthetic
// edge-case inputs are exercised in `tests/crypto.rs` via the
// drift-gate-style "compute vs OSS axon-csys" path so we don't have
// to hand-verify the digest off-line.
// ──────────────────────────────────────────────────────────────────────

pub const SHA256_VECTORS: &[Sha256Vector] = &[
    // FIPS 180-4 §B.0 — empty input.
    Sha256Vector {
        label: "fips180-4 empty",
        msg: b"",
        digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    },
    // FIPS 180-4 §B.1 — single block, "abc".
    Sha256Vector {
        label: "fips180-4 §B.1 (one block, abc)",
        msg: b"abc",
        digest: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    },
    // FIPS 180-4 §B.2 — two blocks (56-byte input padded to 2 blocks).
    Sha256Vector {
        label: "fips180-4 §B.2 (two blocks, alphabet seq)",
        msg: b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
        digest: "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    },
    // Widely-cited "quick brown fox" reference pair.
    Sha256Vector {
        label: "quick brown fox (no period)",
        msg: b"The quick brown fox jumps over the lazy dog",
        digest: "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592",
    },
    Sha256Vector {
        label: "quick brown fox (with period — single-bit avalanche test)",
        msg: b"The quick brown fox jumps over the lazy dog.",
        digest: "ef537f25c895bfa782526529a9b63d97aa631564d5d789c2b765448c8635fb6c",
    },
];

// ──────────────────────────────────────────────────────────────────────
// HMAC-SHA256 vectors — RFC 4231 Test Cases 1, 2, 3, 4, 6, 7 (TC5
// is the truncation case which we don't expose in our API).
// ──────────────────────────────────────────────────────────────────────

pub const HMAC_SHA256_VECTORS: &[HmacSha256Vector] = &[
    HmacSha256Vector {
        label: "RFC 4231 TC1",
        key: &[0x0b; 20],
        data: b"Hi There",
        mac: "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
    },
    HmacSha256Vector {
        label: "RFC 4231 TC2",
        key: b"Jefe",
        data: b"what do ya want for nothing?",
        mac: "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843",
    },
    HmacSha256Vector {
        label: "RFC 4231 TC3",
        key: &[0xaa; 20],
        data: &[0xdd; 50],
        mac: "773ea91e36800e46854db8ebd09181a72959098b3ef8c122d9635514ced565fe",
    },
    HmacSha256Vector {
        label: "RFC 4231 TC4",
        key: &[
            0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
            0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
        ],
        data: &[0xcd; 50],
        mac: "82558a389a443c0ea4cc819899f2083a85f0faa3e578f8077a2e3ff46729665b",
    },
    HmacSha256Vector {
        label: "RFC 4231 TC6 (key > block size)",
        key: &[0xaa; 131],
        data: b"Test Using Larger Than Block-Size Key - Hash Key First",
        mac: "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54",
    },
    HmacSha256Vector {
        label: "RFC 4231 TC7 (key + data > block size)",
        key: &[0xaa; 131],
        data: b"This is a test using a larger than block-size key and a larger than block-size data. The key needs to be hashed before being used by the HMAC algorithm.",
        mac: "9b09ffa71b942fcb27635fbcd5b0e944bfdc63644f0713938a7f51535c3a35e2",
    },
];

/// Decode a 64-char lowercase-hex string to a [u8; 32] digest.
/// Asserts on bad input — these are compile-time-known vectors.
pub fn decode_hex32(hex: &str) -> [u8; 32] {
    assert_eq!(hex.len(), 64, "expected 64-char hex digest");
    let mut out = [0u8; 32];
    let bytes = hex.as_bytes();
    for i in 0..32 {
        let hi = nibble(bytes[i * 2]);
        let lo = nibble(bytes[i * 2 + 1]);
        out[i] = (hi << 4) | lo;
    }
    out
}

fn nibble(b: u8) -> u8 {
    match b {
        b'0'..=b'9' => b - b'0',
        b'a'..=b'f' => b - b'a' + 10,
        b'A'..=b'F' => b - b'A' + 10,
        _ => panic!("invalid hex character: 0x{:02x}", b),
    }
}
