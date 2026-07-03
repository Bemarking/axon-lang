//! §Fase 80.b/c — drift gate for the `upstream` primitive doc.
//!
//! The canonical program published in `knowledge/primitives/upstream.md`
//! must round-trip through the same `axon-frontend` pipeline the `axon`
//! CLI uses — the "published grammar MUST compile" discipline, applied to
//! the outbound-vendor-connection primitive.
//!
//! Mirrors the pattern from `phase2/6b/6c/6d/fase77_canonical_programs.rs`.

use axon_emcp::compiler_pipeline::{run, Outcome};

fn must_compile(label: &str, source: &str) {
    match run(source, label) {
        Outcome::Ok { .. } => { /* well-formed — the whole assertion */ }
        Outcome::Err {
            stage,
            errors,
            warnings,
        } => panic!(
            "{label}: expected well-formed program, got {stage:?} failure:\n\
             errors   = {errors:#?}\n\
             warnings = {warnings:#?}\n\
             source   = {source}"
        ),
    }
}

/// The design-doc §1 shape: a cascaded-STT upstream — binary audio out,
/// JSON transcripts in, header auth, fail-closed reconnect policy.
#[test]
fn upstream_canonical_program_compiles() {
    let src = r#"
session SttDialogue {
    axon:   [ send AudioChunk, loop, receive Transcript, end ]
    vendor: [ receive AudioChunk, loop, send Transcript, end ]
}

upstream DeepgramSTT {
    transport: websocket
    protocol: SttDialogue
    role: axon
    resolve: upstream.deepgram.url
    secret: upstream.deepgram.api_key
    auth: header("Authorization", "Token ")
    map: [
        send AudioChunk as binary,
        receive Transcript as json when "type" = "Results",
    ]
    reconnect: { backoff_ms: 500, max_attempts: 5, on_exhausted: fail }
    overflow: drop_oldest
}
"#;
    must_compile("upstream/canonical", src);
}

// NOTE: the §80.f preset-instantiation surface (`upstream X from
// DeepgramSTT@v1 { secret: … }`) gets its own compile gate when the preset
// catalog + desugar expansion land (80.f) — an unexpanded preset reference
// is deliberately NOT a compilable program (the checker demands the full
// structural surface the expansion provides).
