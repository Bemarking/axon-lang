//! Linear resampler for PCM16 audio.
//!
//! Polyphase FIR would preserve spectral content better; linear
//! interpolation is what telephony-tier audio (μ-law, 8 kHz) can
//! tolerate and that's the 11.e use case. Adopters needing
//! studio-quality rate conversion register a higher-quality
//! transformer at startup; our native path yields in cost to
//! anything they declare with `cost_hint() < self.cost_hint()`.
//!
//! The kind tags `pcm16_8k`, `pcm16_16k`, `pcm16_48k` encode both
//! byte layout AND sample rate. This is deliberate: a Whisper-class
//! consumer that wants 16 kHz PCM16 declares `pcm16_16k` and OTS
//! resolves the resample step automatically.

use crate::buffer::{BufferKind, ZeroCopyBuffer};
use crate::ots::pipeline::{OtsError, Transformer, TransformerBackend};

pub struct Resample {
    pub from_hz: u32,
    pub to_hz: u32,
}

impl Resample {
    pub fn new(from_hz: u32, to_hz: u32) -> Self {
        assert!(from_hz > 0 && to_hz > 0, "rates must be positive");
        Resample { from_hz, to_hz }
    }

    fn source_slug(&self) -> String {
        format!("pcm16_{}k", self.from_hz / 1000)
    }

    fn sink_slug(&self) -> String {
        format!("pcm16_{}k", self.to_hz / 1000)
    }

    fn resample_linear(samples: &[i16], from_hz: u32, to_hz: u32) -> Vec<i16> {
        if samples.is_empty() || from_hz == to_hz {
            return samples.to_vec();
        }
        let output_len =
            ((samples.len() as u64 * to_hz as u64) / from_hz as u64)
                .max(1) as usize;
        let mut out = Vec::with_capacity(output_len);
        for i in 0..output_len {
            // Map the output index back into the input timeline.
            let src_pos =
                (i as u64 * from_hz as u64) as f64 / to_hz as f64;
            let src_idx = src_pos.floor() as usize;
            let frac = src_pos - src_idx as f64;
            if src_idx + 1 >= samples.len() {
                out.push(samples[samples.len() - 1]);
            } else {
                let a = samples[src_idx] as f64;
                let b = samples[src_idx + 1] as f64;
                out.push((a + (b - a) * frac).round() as i16);
            }
        }
        out
    }
}

impl Transformer for Resample {
    fn source_kind(&self) -> BufferKind {
        BufferKind::new(self.source_slug())
    }

    fn sink_kind(&self) -> BufferKind {
        BufferKind::new(self.sink_slug())
    }

    fn backend(&self) -> TransformerBackend {
        TransformerBackend::Native
    }

    fn cost_hint(&self) -> u32 {
        // Resample is cheaper than the μ-law/PCM codecs because
        // the per-sample work is just a multiply-add; we still
        // bias toward shorter paths when an adopter declares a
        // higher-quality alternative.
        1
    }

    fn transform(
        &self,
        input: &ZeroCopyBuffer,
    ) -> Result<ZeroCopyBuffer, OtsError> {
        let src = input.as_slice();
        if src.len() % 2 != 0 {
            return Err(OtsError::TransformFailed(format!(
                "PCM16 input must be even-length, got {}",
                src.len()
            )));
        }
        let samples: Vec<i16> = src
            .chunks_exact(2)
            .map(|c| i16::from_le_bytes([c[0], c[1]]))
            .collect();
        let resampled =
            Resample::resample_linear(&samples, self.from_hz, self.to_hz);
        let mut out = Vec::with_capacity(resampled.len() * 2);
        for sample in resampled {
            out.extend_from_slice(&sample.to_le_bytes());
        }
        let mut buf = ZeroCopyBuffer::from_bytes(out, self.sink_kind());
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
    fn identity_resample_returns_same_samples() {
        let samples = vec![100i16, 200, 300, -100, -200];
        let result =
            Resample::resample_linear(&samples, 16_000, 16_000);
        assert_eq!(result, samples);
    }

    #[test]
    fn upsample_doubles_length_approximately() {
        let samples = vec![0i16; 100];
        let result =
            Resample::resample_linear(&samples, 8_000, 16_000);
        // 100 samples at 8 kHz → 200 samples at 16 kHz.
        assert!(result.len() >= 199 && result.len() <= 201);
    }

    #[test]
    fn downsample_halves_length_approximately() {
        let samples = vec![0i16; 200];
        let result =
            Resample::resample_linear(&samples, 16_000, 8_000);
        assert!(result.len() >= 99 && result.len() <= 101);
    }

    #[test]
    fn kind_tags_follow_rate_convention() {
        let r = Resample::new(8_000, 16_000);
        assert_eq!(r.source_kind().slug(), "pcm16_8k");
        assert_eq!(r.sink_kind().slug(), "pcm16_16k");
    }

    #[test]
    fn transform_rejects_odd_length() {
        let r = Resample::new(8_000, 16_000);
        let odd = ZeroCopyBuffer::from_bytes(
            vec![0u8, 1, 2],
            r.source_kind(),
        );
        let err = r.transform(&odd).unwrap_err();
        matches!(err, OtsError::TransformFailed(_));
    }

    #[test]
    fn transform_preserves_tenant_tag() {
        let r = Resample::new(8_000, 16_000);
        let input = ZeroCopyBuffer::from_bytes(
            vec![0u8; 16],
            r.source_kind(),
        )
        .with_tenant("alpha");
        let out = r.transform(&input).unwrap();
        assert_eq!(out.tenant_id(), Some("alpha"));
    }
}
