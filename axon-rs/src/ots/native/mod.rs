//! Pure-Rust transcoders seeded into the global OTS registry.

pub mod mulaw;
pub mod resample;

use std::sync::Arc;

use crate::ots::pipeline::TransformerRegistry;

/// Install every built-in native transformer into `registry`.
pub fn seed_registry(registry: &mut TransformerRegistry) {
    registry.install(Arc::new(mulaw::MulawToPcm16 {}));
    registry.install(Arc::new(mulaw::Pcm16ToMulaw {}));
    // Standard resample ladders used by Whisper-class consumers
    // (16 kHz) + telephony (8 kHz). Adopters who need 48 kHz or
    // custom rates can install additional Resample transformers
    // at startup without touching this module.
    registry.install(Arc::new(resample::Resample::new(8_000, 16_000)));
    registry.install(Arc::new(resample::Resample::new(16_000, 8_000)));
    registry.install(Arc::new(resample::Resample::new(16_000, 48_000)));
    registry.install(Arc::new(resample::Resample::new(48_000, 16_000)));
}
