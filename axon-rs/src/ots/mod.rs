//! Ontological Tool Synthesis — §λ-L-E Fase 11.e binary pipeline
//! synthesis.
//!
//! Given a source `BufferKind` and a sink `BufferKind`, OTS finds
//! a transformer path that converts between them — typed, cached,
//! and auditable. The path may be a single pure-Rust transcoder
//! (μ-law ↔ PCM16, linear resample) or a subprocess delegation
//! to `ffmpeg` when no native path exists.
//!
//! Fase 11.e intentionally stays modest: the registry is global +
//! built at startup, not hot-patched at runtime (a transformer
//! appearing mid-flight hurts auditability; see the `@sensitive`
//! + ffmpeg incompatibility the checker enforces). Adopters extend
//! OTS by contributing transformers upstream — same policy as the
//! trust catalogue in 11.a.
//!
//! Composition notes
//! =================
//!
//! - 11.a `Stream<T>` — OTS transformers operate over
//!   `ZeroCopyBuffer`s that originate in a stream; backpressure
//!   policies propagate transparently because each transformer is
//!   a pure `fn buffer → buffer` adapter.
//! - 11.b `ZeroCopyBuffer` + `BufferKind` — OTS is the consumer
//!   of the kind taxonomy. Native transcoders work in-place when
//!   the target kind has identical byte-width; otherwise they
//!   allocate via the pool.
//! - 11.c `LegalBasis` + §ffmpeg subprocess — the checker rejects
//!   the combination `sensitive:... + legal:HIPAA.* +
//!   ots:backend:ffmpeg` because data crosses a process boundary
//!   the auditor cannot observe.
//! - 11.d `CognitiveState` — pipelines can run inside a flow
//!   whose state is snapshot-persisted; they are `Send + Sync`
//!   so the snapshot boundary is unaffected.

pub mod native;
pub mod pipeline;
pub mod subprocess;

pub use self::pipeline::{
    OtsError, Pipeline, PipelineStep, Transformer, TransformerBackend,
    TransformerId, TransformerRegistry,
};

// ── Slug catalogue consumed by the type checker ─────────────────────
//
// §Fase 12.a — the compile-time catalog lives in `axon-frontend` so
// tooling can validate OTS effect slugs without linking the runtime.
// Re-exported here for backward compatibility with existing callers.

pub use axon_frontend::ots_catalog::{
    OTS_BACKEND_CATALOG, OTS_BACKEND_EFFECT_SLUG, OTS_TRANSFORM_EFFECT_SLUG,
};

// ── Factory: startup-seeded global registry ─────────────────────────

use std::sync::OnceLock;

static GLOBAL_REGISTRY: OnceLock<TransformerRegistry> = OnceLock::new();

/// Return the process-wide transformer registry. Seeded on first
/// access with every built-in transcoder; custom transformers land
/// via `axon::ots::install_transformer` at process startup.
pub fn global_registry() -> &'static TransformerRegistry {
    GLOBAL_REGISTRY.get_or_init(|| {
        let mut reg = TransformerRegistry::new();
        native::seed_registry(&mut reg);
        reg
    })
}
