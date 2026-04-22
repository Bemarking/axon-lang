# OTS Binary Pipeline Synthesis

§λ-L-E Fase 11.e. Ontological Tool Synthesis extended from API
discovery to **binary stream transformation**. Given a source
`BufferKind` and a sink `BufferKind`, OTS auto-discovers a typed
transformer chain, picks the cheapest path (native-first), and
executes it — caching warm pipelines between requests.

Concretely: a flow that ingests μ-law 8 kHz audio but calls a
Whisper-class transcriber expecting PCM16 16 kHz declares neither
transcoder nor resampler. OTS wires `mulaw8 → pcm16 → pcm16_16k`
automatically.

## The Transformer trait

```rust
pub trait Transformer: Send + Sync {
    fn source_kind(&self) -> BufferKind;
    fn sink_kind(&self) -> BufferKind;
    fn backend(&self) -> TransformerBackend;  // Native | Subprocess
    fn cost_hint(&self) -> u32 { 1 }
    fn transform(&self, input: &ZeroCopyBuffer) -> Result<ZeroCopyBuffer, OtsError>;
}
```

The registry is a directed multi-graph: nodes are `BufferKind`s,
edges are transformers. Dijkstra finds the cheapest path; the
runtime executes it step by step, verifying kind invariants
between steps (catches registry drift between path-find and
execute).

## Built-in transformers

Seeded into `axon::ots::global_registry()` at startup:

| Source → Sink | Backend | Cost |
|---|---|---|
| `mulaw8 → pcm16` | Native (ITU-T G.711) | 1 |
| `pcm16 → mulaw8` | Native (ITU-T G.711) | 1 |
| `pcm16_8k → pcm16_16k` | Native (linear resample) | 1 |
| `pcm16_16k → pcm16_8k` | Native (linear resample) | 1 |
| `pcm16_16k → pcm16_48k` | Native (linear resample) | 1 |
| `pcm16_48k → pcm16_16k` | Native (linear resample) | 1 |

Adopters extend the catalogue by implementing `Transformer` and
calling `registry.install(...)` at startup. The §Fase 11.d
decision stands: **no runtime hot-loading** — a transformer
appearing mid-flight hurts auditability.

## Kind-tag convention

`pcm16_<rate>k` encodes both byte layout AND sample rate. This
lets OTS resolve both transcoding (layout change) and resampling
(rate change) as independent edges in the same graph. A flow
declaring `Bytes[mulaw8]` → `Bytes[pcm16_16k]` gets the path

```
mulaw8 → pcm16 → pcm16_16k  (if 8 kHz is the implicit μ-law rate)
```

provided the adopter has registered the compose step `pcm16 →
pcm16_8k` (they usually do; adopters with μ-law know the rate).

## ffmpeg fallback

When no native path covers a requested transformation, adopters
register an `FfmpegTransformer` wrapping a concrete
`FfmpegPipeline`:

```rust
use std::sync::Arc;
use axon::ots::subprocess::{FfmpegPool, FfmpegPipeline, FfmpegTransformer};

let pool = Arc::new(FfmpegPool::default());
pool.register(FfmpegPipeline::new(
    BufferKind::new("mp3"),
    BufferKind::new("wav"),
    vec![
        "-f".into(), "mp3".into(),
        "-i".into(), "pipe:0".into(),
        "-f".into(), "wav".into(),
        "pipe:1".into(),
    ],
));
registry.install(Arc::new(FfmpegTransformer {
    pipeline: pool.registered("mp3", "wav").unwrap(),
    pool: Arc::clone(&pool),
    cost_hint: 10,  // bias Dijkstra toward native when both exist
}));
```

The pool keeps the pipeline warm for 60s between invocations
(configurable via `FfmpegPoolConfig`). ffmpeg availability is
detected once at startup (`is_ffmpeg_available()`); absent
binary is a non-fatal warning — flows needing ffmpeg fail at
pipeline synthesis time with `OtsError::NoPath` instead of
crashing the runtime.

## Type-checker integration

Two effect families feed the checker:

- `ots:transform:<from>:<to>` — declares a tool performs the
  conversion. Open taxonomy for the kinds (same as
  `BufferKind`'s open registry in 11.b).
- `ots:backend:<native|ffmpeg>` — declares the backend. **Closed**
  catalogue; new backends require a compiler patch.

```axon
tool decode_phi_audio {
  provider: local
  timeout:  30s
  effects:  <sensitive:phi, legal:HIPAA.164_502,
             ots:transform:mulaw8:pcm16, ots:backend:native>
}
```

Compile-time diagnostics (selected):

```
error: Effect 'ots:transform' in tool 'x' requires '<from>:<to>'
       qualifier (e.g. 'ots:transform:mulaw8:pcm16').
```

```
error: Unknown OTS backend 'gstreamer' in tool 'x'.
       Valid: native, ffmpeg.
```

### HIPAA + ffmpeg is rejected

Because ffmpeg runs as a subprocess, ePHI crossing that boundary
is a disclosure the HIPAA Business Associate Agreement typically
doesn't cover. The checker rejects the combination:

```axon
tool transcribe_phi {
  effects: <sensitive:phi, legal:HIPAA.164_502,
            ots:transform:pcm16:mp3, ots:backend:ffmpeg>
}
```

```
error: Tool 'transcribe_phi' combines HIPAA legal basis
       (HIPAA.164_502) with 'ots:backend:ffmpeg'. ePHI MUST NOT
       cross the process boundary to a subprocess outside the
       auditable runtime. Use 'ots:backend:native' or register
       a native transformer that covers the required pipeline.
```

GDPR / CCPA / SOX / GLBA / PCI-DSS are NOT blocked from using
ffmpeg — those adopters accept the subprocess risk at the ops
level. Only HIPAA is explicitly regulated on the data-path
boundary.

## Composition with earlier Fase 11

- **11.a `Stream<T>`** — transformers are pure `fn buf → buf`
  adapters so the stream's backpressure policy passes through
  unmodified.
- **11.b `ZeroCopyBuffer` + `BufferKind`** — OTS is the consumer
  of the kind taxonomy. Native transcoders allocate via the
  pool; the μ-law ↔ PCM16 byte-width change triggers a fresh
  buffer but every intermediate keeps its tenant tag.
- **11.c `LegalBasis`** — drives the HIPAA+ffmpeg rejection rule.
- **11.d `CognitiveState`** — pipelines run inside stateful flows;
  they're `Send + Sync` so snapshots after a transform capture
  consistent state.

## What 11.e does NOT include (deferred)

- **Long-running ffmpeg workers.** The current pool caches the
  pipeline descriptor but spawns per-call. A pipe-in / pipe-out
  worker that stays alive between calls cuts spawn cost for
  high-rate audio — deferred to a future revision because the
  back-pressure semantics are delicate.
- **Custom transformer hot-loading.** Adopters register at
  startup; runtime registration would require a registry
  snapshot mechanism for auditability that isn't worth the
  complexity today.
- **Polyphase FIR resample.** The linear resampler is telephony-
  grade (the μ-law use case). Studio-quality rate conversion
  ships as an adopter-registered transformer.
- **Unit-based kinds beyond rate.** Bit depth, channel count,
  colour space etc. all extend the kind taxonomy — 11.e ships
  with rate-tagged PCM16 only.

## Where to look in the code

- Rust registry + Dijkstra: [`axon-rs/src/ots/pipeline.rs`](../axon-rs/src/ots/pipeline.rs)
- Rust native transcoders: [`axon-rs/src/ots/native/mulaw.rs`](../axon-rs/src/ots/native/mulaw.rs), [`resample.rs`](../axon-rs/src/ots/native/resample.rs)
- Rust ffmpeg wrapper: [`axon-rs/src/ots/subprocess/ffmpeg.rs`](../axon-rs/src/ots/subprocess/ffmpeg.rs)
- Python mirror: [`axon/runtime/ots/`](../axon/runtime/ots/)
- Type-checker rules: `axon-rs::type_checker` ots + HIPAA+ffmpeg blocks
- Rust integration tests: [`axon-rs/tests/fase_11e_ots_pipelines.rs`](../axon-rs/tests/fase_11e_ots_pipelines.rs)
- Python unit tests: [`tests/test_fase_11e_ots.py`](../tests/test_fase_11e_ots.py)
