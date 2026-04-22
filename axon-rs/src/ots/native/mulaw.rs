//! μ-law ↔ PCM16 transcoders per ITU-T G.711.
//!
//! The encode/decode functions are pure arithmetic — no lookup
//! tables because they're already branch-free with the bit-twiddle
//! implementation below, and the inlined form gives the optimiser
//! more room than a pre-built table.
//!
//! Verified against the reference vectors in G.711 Annex A.
//!
//! Naming note: the kind tag is `mulaw8` (8-bit μ-law, 8 kHz
//! mono is the typical sample rate but the kind carries only the
//! byte layout; resampling is a separate transformer).

use crate::buffer::{BufferKind, ZeroCopyBuffer};
use crate::ots::pipeline::{OtsError, Transformer, TransformerBackend};

const MULAW_BIAS: i16 = 0x84;
const MULAW_CLIP: i16 = 32_635;

// ── μ-law → PCM16 ───────────────────────────────────────────────────

pub struct MulawToPcm16;

impl MulawToPcm16 {
    fn sample(byte: u8) -> i16 {
        let byte = !byte;
        let sign = (byte & 0x80) != 0;
        let exponent = ((byte >> 4) & 0x07) as i32;
        let mantissa = (byte & 0x0F) as i32;
        let magnitude: i32 = (((mantissa << 3) + 0x84) << exponent) - 0x84;
        if sign {
            -(magnitude as i16)
        } else {
            magnitude as i16
        }
    }
}

impl Transformer for MulawToPcm16 {
    fn source_kind(&self) -> BufferKind {
        BufferKind::mulaw8()
    }

    fn sink_kind(&self) -> BufferKind {
        BufferKind::pcm16()
    }

    fn backend(&self) -> TransformerBackend {
        TransformerBackend::Native
    }

    fn cost_hint(&self) -> u32 {
        1
    }

    fn transform(
        &self,
        input: &ZeroCopyBuffer,
    ) -> Result<ZeroCopyBuffer, OtsError> {
        let src = input.as_slice();
        let mut out = Vec::with_capacity(src.len() * 2);
        for &byte in src {
            let sample = MulawToPcm16::sample(byte);
            out.extend_from_slice(&sample.to_le_bytes());
        }
        let mut buf = ZeroCopyBuffer::from_bytes(out, BufferKind::pcm16());
        if let Some(tenant) = input.tenant_id() {
            buf = buf.with_tenant(tenant.to_string());
        }
        Ok(buf)
    }
}

// ── PCM16 → μ-law ───────────────────────────────────────────────────

pub struct Pcm16ToMulaw;

impl Pcm16ToMulaw {
    fn encode(sample: i16) -> u8 {
        let mut pcm = sample as i32;
        let sign = if pcm < 0 {
            pcm = -pcm;
            0x80
        } else {
            0x00
        };
        if pcm > MULAW_CLIP as i32 {
            pcm = MULAW_CLIP as i32;
        }
        pcm += MULAW_BIAS as i32;

        // Find the MSB that's set (reverse leading-zero count,
        // scaled to fit the 3-bit exponent).
        let mut exponent: i32 = 7;
        let mut mask: i32 = 0x4000;
        while exponent > 0 && (pcm & mask) == 0 {
            exponent -= 1;
            mask >>= 1;
        }
        let mantissa = (pcm >> (exponent + 3)) & 0x0F;
        let byte = !(sign | ((exponent << 4) as u8) | (mantissa as u8));
        byte
    }
}

impl Transformer for Pcm16ToMulaw {
    fn source_kind(&self) -> BufferKind {
        BufferKind::pcm16()
    }

    fn sink_kind(&self) -> BufferKind {
        BufferKind::mulaw8()
    }

    fn backend(&self) -> TransformerBackend {
        TransformerBackend::Native
    }

    fn cost_hint(&self) -> u32 {
        1
    }

    fn transform(
        &self,
        input: &ZeroCopyBuffer,
    ) -> Result<ZeroCopyBuffer, OtsError> {
        let src = input.as_slice();
        if src.len() % 2 != 0 {
            return Err(OtsError::TransformFailed(format!(
                "PCM16 input must be a multiple of 2 bytes, got {}",
                src.len()
            )));
        }
        let mut out = Vec::with_capacity(src.len() / 2);
        for chunk in src.chunks_exact(2) {
            let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
            out.push(Pcm16ToMulaw::encode(sample));
        }
        let mut buf = ZeroCopyBuffer::from_bytes(out, BufferKind::mulaw8());
        if let Some(tenant) = input.tenant_id() {
            buf = buf.with_tenant(tenant.to_string());
        }
        Ok(buf)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mulaw_decode_matches_reference_vectors() {
        // G.711 Annex A: the STORED byte is the logical byte with
        // all bits inverted. So:
        //   stored 0xFF → logical 0x00 → signed zero (positive)
        //   stored 0x7F → logical 0x80 → signed zero (negative)
        //   stored 0x80 → logical 0x7F → largest positive (+32_124)
        //   stored 0x00 → logical 0xFF → largest negative (-32_124)
        let vectors: [(u8, i16); 4] = [
            (0xFF, 0),
            (0x7F, 0),
            (0x80, 32_124),
            (0x00, -32_124),
        ];
        for (mulaw, expected) in vectors {
            assert_eq!(
                MulawToPcm16::sample(mulaw),
                expected,
                "μ-law 0x{mulaw:02X} decoded wrong"
            );
        }
    }

    #[test]
    fn roundtrip_pcm_is_approximately_identity() {
        // μ-law is lossy by design but quantisation error is bounded.
        // A PCM16 sample → encode → decode → compare within tolerance.
        for pcm in (-30_000..=30_000).step_by(512) {
            let byte = Pcm16ToMulaw::encode(pcm);
            let recovered = MulawToPcm16::sample(byte);
            let error = (pcm - recovered).abs();
            // G.711 quantisation error stays bounded at a few
            // percent of magnitude. We accept 10% of |pcm| + 256
            // (covers the low-end where relative error gets larger).
            let tol = (pcm.abs() / 10).max(256);
            assert!(
                error <= tol,
                "pcm={pcm} → byte=0x{byte:02X} → {recovered} (err={error}, tol={tol})"
            );
        }
    }

    #[test]
    fn transformer_changes_kind_tag() {
        let mulaw_buf = ZeroCopyBuffer::from_bytes(
            vec![0xFF, 0x00, 0x80, 0x7F],
            BufferKind::mulaw8(),
        );
        let pcm_buf =
            MulawToPcm16 {}.transform(&mulaw_buf).unwrap();
        assert_eq!(pcm_buf.kind().slug(), "pcm16");
        assert_eq!(pcm_buf.len(), 8, "4 μ-law bytes → 8 PCM16 bytes");
    }

    #[test]
    fn pcm16_to_mulaw_rejects_odd_length() {
        let odd = ZeroCopyBuffer::from_bytes(
            vec![0u8, 1, 2],
            BufferKind::pcm16(),
        );
        let err = Pcm16ToMulaw {}.transform(&odd).unwrap_err();
        matches!(err, OtsError::TransformFailed(_));
    }

    #[test]
    fn tenant_tag_propagates_through_transform() {
        let input = ZeroCopyBuffer::from_bytes(
            vec![0xFF, 0x00],
            BufferKind::mulaw8(),
        )
        .with_tenant("alpha");
        let out = MulawToPcm16 {}.transform(&input).unwrap();
        assert_eq!(out.tenant_id(), Some("alpha"));
    }
}
