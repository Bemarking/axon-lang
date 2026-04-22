# Zero-Copy Multimodal Buffers

§λ-L-E Fase 11.b. Bytes entering the runtime from a network socket,
file handle or FFI boundary land directly in a Rust-owned region of
memory. The Python orchestration layer manipulates `SymbolicPtr<T>`
handles — never the raw bytes — until the final consumer (an audio
transcoder, an image classifier, a file sink) asks for a slice.

The contract: **passing multimodal data across the FFI costs an
`Arc` refcount bump**, not a `memcpy`.

## Building blocks

| Piece | Rust (`axon-rs/src/buffer/`) | Python (`axon/runtime/ffi/buffer.py`) |
|---|---|---|
| Content-kind tag | `BufferKind` (interned slug, open registry) | `BufferKind` + `BufferKindRegistry` |
| Immutable view | `ZeroCopyBuffer` (`Arc<[u8]>` + range) | `ZeroCopyBuffer` (bytes + range) |
| In-flight builder | `BufferMut` (append-only `Vec<u8>`) | `BufferMut` (append-only `bytearray`) |
| Slab allocator | `BufferPool` + `PoolClass` | `BufferPool` + `PoolClass` |
| Shared handle | `Arc<ZeroCopyBuffer>` implicit via clone | `SymbolicPtr[T]` |

Plus ingest deposit paths:

| Piece | Module |
|---|---|
| `multipart/form-data` streaming | `axon-rs/src/ingest/multipart.rs` |
| WebSocket binary fragment stitching | `axon-rs/src/ingest/ws_binary.rs` |

## Core semantics

**Cheap clone.** Every `ZeroCopyBuffer.clone()` is O(1) — the Rust side
is an `Arc` strong-count bump; the Python side shares the `bytes`
carrier (immutable, already refcount-safe).

**Slicing returns a view.** `buf.slice(start, end)` allocates nothing
and the returned buffer shares the carrier. Recording
`buf.sharers()` (Rust) / `ptr.refcount` (Python) reveals the live
view count for observability.

**Kind tag is part of the type.** `ZeroCopyBuffer` carries a
`BufferKind` slug (`pcm16`, `jpeg`, `mp4`, `raw`, …). Unlike the
closed catalogues of Fase 11.a, the kind registry is **open**:
adopters register domain-specific kinds at startup and the tag
flows through the flow type system.

**Tenant tag is part of the buffer.** Every buffer can be tagged
with the owning tenant's slug so pool accounting stays accurate
under multi-tenant load. `.with_tenant("alpha")` is the constructor-
style chain; the tag propagates across `clone`, `slice`, `retag`.

## Seeded kinds

Both sides seed the registry with the same list so a flow that
says `Stream<Bytes[jpeg]>` compiles against the Rust checker and
runs in Python without any adopter setup:

```
raw, pcm16, mulaw8, wav, mp3, opus, jpeg, png, webp,
mp4, webm, pdf, json, csv
```

Custom kinds register via `BufferKind::new("siemens_dicom")` (Rust)
or `BufferKind("siemens_dicom")` (Python). First call registers;
subsequent calls return the interned slug.

## Pool allocation

Four pooled size classes plus an oversize direct-allocation path:

| Class | Capacity |
|---|---|
| `small` | ≤ 4 KiB |
| `medium` | 4 KiB+..64 KiB |
| `large` | 64 KiB+..1 MiB |
| `huge` | 1 MiB+..10 MiB |
| `oversize` | > 10 MiB (direct alloc, not pooled) |

Each class keeps up to 64 free slabs. Exceeding that cap drops
slabs back to the allocator (bounded free-list growth).

Per-tenant **soft limit** — configured via
`pool.set_tenant_soft_limit(tenant_id, soft_limit_bytes)`.
Exceeding the limit does NOT block (the pool is global per process,
not per tenant) but increments a `soft_limit_exceeded_total`
counter per tenant so operators can see which tenant is sustaining
high multimodal throughput.

Metrics surfaced by `pool.snapshot()`:

- `pool_hits{class}` / `pool_misses{class}`
- `oversize_allocations_total`
- `live_bytes` (across all tenants)
- `tenant_live_bytes{tenant_id}` / `tenant_soft_limit_exceeded_total{tenant_id}`

Adopters wire these to Prometheus with whatever tenant tagging
their observability stack expects.

## Ingest paths

### `multipart/form-data`

```rust
use axon::ingest::multipart::{
    parse_boundary_from_content_type, MultipartEvent,
    MultipartLimits, MultipartParser,
};

let boundary = parse_boundary_from_content_type(&content_type)
    .expect("missing boundary");
let mut parser = MultipartParser::new(boundary, MultipartLimits::default());
for chunk in request_body.stream() {
    for event in parser.feed(&chunk)? {
        match event {
            MultipartEvent::PartStart { field_name, kind, .. } => { ... }
            MultipartEvent::PartEnd { field_name, payload } => {
                // payload: ZeroCopyBuffer
            }
            MultipartEvent::Complete => break,
        }
    }
}
```

Streaming guarantees: every part's payload appends into its own
`BufferMut` without materialising the whole request body in RAM.
The parser tolerates boundary splits across chunks.

Limits (configurable via `MultipartLimits`):

- `max_header_bytes` — default 16 KiB
- `max_part_bytes` — default 32 MiB per field

### WebSocket binary frames

```rust
use axon::ingest::ws_binary::{
    WsBinaryAccumulator, WsBinaryLimits,
};

let mut acc = WsBinaryAccumulator::new(
    BufferKind::pcm16(),
    WsBinaryLimits::default(),
)
.with_tenant(tenant_id);

while let Some(frame) = ws.next_frame().await {
    if let Some(buffer) = acc.feed(
        frame.opcode, frame.is_final, &frame.payload
    )? {
        // `buffer` is a ZeroCopyBuffer over the stitched message.
        downstream.send(buffer).await;
    }
}
```

The accumulator is frame-shape-agnostic — the transport parses the
WS frame header; we get the already-unmasked payload + `is_final`
flag. Fragmented frames stitch into a single contiguous buffer;
FIN triggers freeze.

## Crossing the FFI boundary

Python's [PEP 3118](https://peps.python.org/pep-3118/) buffer
protocol is the standard interop surface. `ZeroCopyBuffer` exposes
`__buffer__` (Python 3.12+) returning a read-only `memoryview`
over the visible slice. Consumers — NumPy, PyTorch, Pillow, OpenCV —
accept the memoryview without copying:

```python
import numpy as np

buf = zero_copy_buffer_from_microphone()   # ZeroCopyBuffer(pcm16)
audio = np.frombuffer(buf.as_memoryview(), dtype=np.int16)
# `audio.data` shares bytes with `buf._carrier`. No copy.
```

When the Rust extension ships (PyO3 binding, follow-up in 11.b.1),
the `memoryview` will be sourced from the `Arc<[u8]>` directly —
same interface, different carrier.

## Fan-out with `SymbolicPtr`

```python
from axon.runtime.ffi import SymbolicPtr

buf = ZeroCopyBuffer(mic_chunk, "pcm16")
origin = SymbolicPtr(buf)

# Feed two parallel consumers without copying.
transcriber = origin.clone()
metrics_tap = origin.clone()

await asyncio.gather(
    whisper_client.transcribe(transcriber),
    audio_level_monitor(metrics_tap),
)
```

`origin.refcount` tracks live clones. `is_unique` is True iff no
one else holds a handle — useful for hand-off optimisations where
the sole holder can safely mutate via `to_bytes()` without disturbing
other consumers.

## Compile-time integration with Fase 11.a

Today `Stream<T>` and `Trusted<T>` from 11.a don't special-case
`ZeroCopyBuffer`; they treat it as any other `T`. That composition
is already the interesting case:

```axon
tool ingest_audio {
  provider: local
  timeout:  30s
  effects:  <stream:drop_oldest>
}

tool verify_signed_chunk {
  provider: local
  timeout:  5s
  effects:  <trust:ed25519>
}

flow LiveTranscribe(audio: Stream<Trusted<Bytes[pcm16]>>) {
  step Ingest {
    given: audio
    ask:   "accumulate"
    apply: ingest_audio
  }
  step Analyze {
    given: Ingest.output
    ask:   "summarise"
  }
}
```

- `Stream<T>` forces a backpressure handler (from 11.a)
- `Trusted<T>` forces an Ed25519 verifier (from 11.a)
- `Bytes[pcm16]` tags the content kind (from 11.b)

None of this requires a copy: the raw signed chunks land in a
`ZeroCopyBuffer`, the verifier operates on `.as_slice()`, and the
transcriber receives a `SymbolicPtr<ZeroCopyBuffer>` it can hand
directly to a Whisper-compatible consumer.

## What 11.b does NOT include (deferred)

- **PyO3 binding** for Rust-owned buffers in Python. The Python
  implementation today wraps `bytes` carriers; zero-copy semantics
  hold via `memoryview`, but Rust-allocated storage doesn't yet
  cross the FFI. Lands in 11.b.1 once the PyO3 build is wired into
  the release pipeline.
- **Lock-free free lists.** The pool uses `Mutex` / `threading.RLock`.
  A lockfree slab allocator is a performance follow-up; correctness
  is in place.
- **Buffer diff / patch.** Composing `ZeroCopyBuffer`s by reference
  (e.g. a 10 MiB audio buffer plus a 1 KiB metadata prefix without
  concatenating) is useful but out of scope here.
- **Compile-time kind constraints.** `Bytes[pcm16]` → `Bytes[wav]`
  auto-wiring lands in 11.e (OTS Binary Pipeline Synthesis).

## Where to look in the code

- Rust buffer: [`axon-rs/src/buffer/mod.rs`](../axon-rs/src/buffer/mod.rs), [`kind.rs`](../axon-rs/src/buffer/kind.rs), [`pool.rs`](../axon-rs/src/buffer/pool.rs)
- Rust ingest: [`axon-rs/src/ingest/multipart.rs`](../axon-rs/src/ingest/multipart.rs), [`ws_binary.rs`](../axon-rs/src/ingest/ws_binary.rs)
- Python buffer: [`axon/runtime/ffi/buffer.py`](../axon/runtime/ffi/buffer.py)
- Python SymbolicPtr: [`axon/runtime/ffi/symbolic_ptr.py`](../axon/runtime/ffi/symbolic_ptr.py)
- Rust integration tests: [`axon-rs/tests/fase_11b_buffers_and_ingest.rs`](../axon-rs/tests/fase_11b_buffers_and_ingest.rs)
- Python unit tests: [`tests/test_fase_11b_buffer.py`](../tests/test_fase_11b_buffer.py), [`test_fase_11b_symbolic_ptr.py`](../tests/test_fase_11b_symbolic_ptr.py)
