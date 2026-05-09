//! axon-csys — C23 metal-bound kernels for axon-lang.
//!
//! Fase 25 — Silicon + Cognition (sesión 1). This crate is the Rust shim
//! around a small set of carefully chosen C23 kernels. The C side handles
//! what C does best — cache-line layout, bit twiddling, hardware
//! intrinsics, FSM dispatch with computed gotos. The Rust side handles
//! correctness, ownership, and async glue, exposing a safe API that
//! adopters consume without ever writing `unsafe` themselves.
//!
//! ## Layout
//!
//! - `c-src/probe/`   — build-infra probe (25.b)  ✅ shipped
//! - `c-src/audio/`   — G.711 + resample (25.c)   — pending
//! - `c-src/buffer/`  — slab allocator (25.d)     — pending
//! - `c-src/effects/` — FSM dispatcher (25.e)     — pending
//! - `c-src/tokens/`  — BPE + #embed (25.g)       — pending
//! - `c-src/crypto/`  — HMAC continuity (25.h)    — pending
//!
//! ## Founder principle
//!
//! Per the four-pillar reminder (2026-05-08), every C kernel must preserve
//! the Mathematics / Philosophy / Logic / Computing pillars of the module
//! it ports. The Rust shim layer is responsible for asserting the byte-
//! identical / epsilon-bounded drift gate that catches divergence before
//! it leaves CI.

pub mod audio;
pub mod buffer;
pub mod effects;
pub mod probe;
pub mod tokens;

pub use audio::{
    mulaw_decode, mulaw_encode, resample_linear_pcm16, resample_linear_pcm16_output_len,
    ResampleError,
};
pub use buffer::{BufferPool, BufferPoolSnapshot, PoolClass, Slab};
pub use effects::{
    BuiltWire, Clause, DispatchError, DispatchResult, Dispatcher, EffectDecl, Frame, Instruction,
    Opcode, TraceEvent, Value as EffectValue, WireBuilder,
};
pub use probe::{
    probe_add, probe_c_standard, probe_cacheline_alignment, probe_cacheline_marker,
    probe_cacheline_size, probe_features, probe_version, AxonCsysFeatures, AxonCsysVersion,
};
pub use tokens::{
    cl100k_base, count_tokens, estimate, o200k_base, utf8_boundary_floor, utf8_count_chars,
    BpeError, CountKind, TokenCount, Tokenizer,
};
