---
title: "Plan vivo: Fase 25 — Silicon + Cognition (sesión 1) — Pure C migration of metal-bound kernels"
status: DRAFTED 2026-05-08 — investigación completada; sub-fases 25.a–25.k pendientes; target axon-lang v1.19.0 cross-stack
owner: AXON Language Team
created: 2026-05-08
updated: 2026-05-08
target: axon-lang v1.19.0 (PyPI + crates.io) + nuevo crate `axon-csys` (C build artefacts) shipped via cargo
depends_on: Fase 24 SHIPPED (native Rust backends v1.18.0); Fase 23 SHIPPED (algebraic effects runtime v1.17.0); existing FFI bridge in `axon/runtime/{ffi_bridge,native_compiler,rust_transpiler}.py`
session_series: Silicon + Cognition (1ª de varias sesiones planeadas — éstas progresivamente convierten axon en sistema nervioso sintético: alto-nivel cognitivo orquestando pensamientos vía Python/Rust + bajo-nivel hablando directamente con el metal vía C23)
---

## ▶ Status snapshot (2026-05-08 — DRAFTED)

Investigación profunda terminada (ver §1). Plan operacional: §3 en adelante. Espera ratificación founder sobre decisiones D1–D12 antes de arrancar 25.b.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 25.a Engineering spec | ✅ SHIPPED 2026-05-08 | doc-only | — | Doc redactado ✓ + memoria `project_fase_25_plan.md` ✓ + memoria `project_axon_four_pillars.md` ✓ + MEMORY.md actualizado ✓ + D1–D12 ratificadas (D11 reasignada a Fase 26 explícitamente) |
| 25.b C build infrastructure (axon-csys crate + cc-rs + C23 detection + cross-OS CI) | ✅ SHIPPED 2026-05-08 | ~470 | Rust + C + build.rs | crate `axon-csys` 0.1.0 ✓ (`Cargo.toml`, `build.rs`, `src/{lib,probe}.rs`, `c-src/probe/probe.c`, `tests/probe.rs`); cc-rs 1.2 dispatch (gcc/clang `-std=c23` con fallback `-std=c2x`, MSVC `/std:clatest`); strict warnings (`-Wall -Wextra -Wpedantic -Werror -Wshadow -Wcast-align -Wconversion -Wstrict-prototypes` / `/W4 /WX`); 12 tests verdes Windows MSVC (probe ABI version + C standard realisation + 7 feature flags + cache-line alignment 64B + struct round-trip + thread safety); CI matrix `ubuntu-latest`+`macos-latest`+`windows-latest` añadido a `.github/workflows/ci.yml` con cargo build/test/fmt/clippy + D12 lint guard. cbindgen diferido a 25.c — el probe surface es trivial (5 funcs); cuando aparezca la primera kernel API extensible (slab allocator) se introduce. |
| 25.c OTS native transformers → C (μ-law + resample) | ✅ SHIPPED 2026-05-08 | ~810 (C + Rust + tests) | C + Rust shim | Port de `axon-rs/src/ots/native/{mulaw,resample}.rs` a `axon-csys/c-src/audio/{mulaw.c,resample.c,audio.h}` + Rust shim `src/audio.rs` (safe wrappers `mulaw_decode`, `mulaw_encode`, `resample_linear_pcm16`, `resample_linear_pcm16_output_len` + `ResampleError`). **35 tests verdes**: G.711 Annex A reference vectors, exhaustive 256-byte decode drift gate (byte-identical vs Rust ref), encode drift gate (stride-7 sweep over i16 domain), saturation at MULAW_CLIP, signed-zero coset collapse documentado como property correcta, round-trip quantisation bounds, sign symmetry, resample identity/empty/up/down/triple-ratio length contracts, constant-signal preservation, linear-ramp interpolation correctness, FP drift gate ≤1 LSB sobre 8k→16k, 16k→48k, 48k→16k, OTS pipeline composition (μ-law decode → resample → μ-law encode end-to-end), 100KB stress, concurrent reentrancy. Total cross-stack tests = 47 (12 probe + 35 audio). SIMD activation diferida a 25.j (benchmarks) — scalar baseline es la verdad canónica que SIMD debe respetar. cbindgen aún diferido — header `audio.h` hand-written + comentado para auditabilidad lado-a-lado del shim Rust. |
| 25.d Buffer pool slab allocator → C | ✅ SHIPPED 2026-05-08 | ~1320 (C + Rust + tests) | C + Rust shim | Port del slab allocator de `axon-rs/src/buffer/pool.rs` a `axon-csys/c-src/buffer/{pool.c, pool.h}` + Rust shim `src/buffer.rs` (`BufferPool`, `Slab<'pool>` con RAII Drop, `PoolClass`, `BufferPoolSnapshot`). C kernel: `_Alignas(64)` cache-line + bitmap free-list 64-bit con `__builtin_ctzll` (gcc/clang) y `_BitScanForward64` (MSVC) + huge-pages opt-in (Linux `mmap MAP_HUGETLB`, Windows `VirtualAlloc MEM_LARGE_PAGES`, ambos con graceful fallback a `posix_memalign` / `_aligned_malloc`) + C11 `_Atomic` counters (MSVC requiere `/experimental:c11atomics` añadido al build) + per-class SRWLOCK (Win) / pthread_mutex (Unix) thread safety. Tenant accounting (`HashMap<Arc<str>, TenantAccount>`) vive en Rust shim — pillar split: C metal, Rust symbolic. **43 tests verdes Windows MSVC** (90 cross-suite total: 12 probe + 35 audio + 43 buffer): class mapping en cada boundary, capacity table, slug, cache-line alignment Small/Medium/Large/Oversize, slot reuse después de release (bitmap demuestra mismo address), pool hit/miss counters, oversize bypass, live_bytes tracking, concurrent slot distinctness (8 threads via barrier), bitmap-full overflow → direct-alloc + cleanup, slab as_slice/as_mut_slice round-trip, tenant live_bytes, soft-limit-exceeded counter increments per overflow call (no blocking), per-tenant override aplicable antes y después de allocs, saturating release at zero, snapshot huge-page counters (active vs fallback sum = num Large/Huge attempts), 50× pool churn no-leak smoke. _Static_assert clava la invariante SLOTS_PER_CLASS == 64. |
| 25.e Effects FSM dispatch → C (computed gotos) | ✅ SHIPPED 2026-05-08 | ~1880 (C + Rust + tests) | C + Rust shim | Port del dispatcher de `axon-rs/src/effects/runtime.rs` a `axon-csys/c-src/effects/{dispatch.h,dispatch.c}` + Rust shim `src/effects.rs` (`WireBuilder`/`BuiltWire`/`Dispatcher`/`Value`/`Opcode`/`Instruction`/`Clause`/`Frame`/`EffectDecl`/`TraceEvent`/`DispatchResult`/`DispatchError`). **Paper §5 entregado**: computed gotos (`goto *labels[op]`) en gcc/clang con `switch` fallback MSVC (D5); explicit exec stack + handler stack (no recursión C); CPS state machine equivalent al recursive Rust ref. Pillar split honrado: C = inner dispatch loop con AxonCsysValue tagged union (Unit/Bool/Int/Float/String/Symbol borrowed slices, zero-alloc en hot path) + globals como flat linear-probing array (max 128) + per-clause parameter binding con save/restore vía param_saves[] en exec frame; Rust = type-safe builder con split top-level/body pool (clave para layout correcto), index resolution de effect/operation/clause names a u32, conversión bidireccional Value↔RawValue. Mathematical preservation: D2 one-shot continuations (cada clause discharges exactamente once vía resume/abort/forward), D9/D10 typechecker invariants surfaceadas como defensive errors (UnhandledEffect/UnknownOperation/NoDischarge/ForwardWithoutOuterHandler/ControlOpcodeOutsideClauseBody/StackOverflow), forward semantics correctas (búsqueda outward desde source frame, bypassing source AND nested frames). **33 nuevos tests verdes (123 cross-suite total)**: build-infra parity (computed-goto vs switch detection), empty/passthrough/handler-with-empty-body degenerate cases, single perform→handle→resume con Int/Bool/Unit/Float/String values, abort propagation a handle frame boundary, defensive errors (perform-without-handler, perform-unknown-op, no-discharge, resume-outside-clause, forward-outside-clause), múltiples performs sequencing, trace events (4-event sequence con EnterFrame/Perform/Resume/ExitFrame, capacity=0 disables, capacity=1 silently drops excess), Symbol resolution against pre-bound globals (passes-through unbound), clause parameter binding (Symbol("x") in resume body → resolves to bound Int(42)), forward propagation a outer handler con resume value travels back, forward-without-outer error, Display impl readability, dispatcher reentrant (50 iterations × 2 wires) + thread-safe (8 threads × 200 ops), opcode u8 stability, Value round-trip Int/Float/Bool. cbindgen aún diferido — header hand-written + comentado. Limites runtime: max 256 exec stack, 64 handler stack, 128 globals, 8 clause params (StackOverflow defensive surface). MSVC quirks: `_BitScanForward64` intrinsic + `/experimental:c11atomics` (carryover de 25.d) + `/W4 /WX` warnings handled; `__assume(0)` portable unreachable hint. Layout fix crítico: `WireBuilder` necesita split entre `body_instructions` + `top_level_instructions` para que el dispatcher walk-only-the-top-level — body_offset/count se shift past top_level_count en `BuiltWire::new()`. List/Map values diferidos a 25.e.2 (heap-managed; flows que los usen se quedan en Rust dispatcher path). Benchmark ≥10× target diferido a 25.j (criterion suite). |
| 25.f C transpiler for compute blocks (adopter-facing) | ✅ SHIPPED 2026-05-08 | ~430 (Python + tests) | Python | Nueva clase `CTranspiler` paralelo a `RustTranspiler` en `axon/runtime/c_transpiler.py` con paridad estructural completa: mismo operator whitelist `{+, -, *, /}`, mismo source hash SHA-256, mismas patterns `_LET_RE`/`_RETURN_RE`, mismos helpers `_tokenize_expr`/`_is_numeric`/`_sanitize`, misma `transpile()` API → returna `CTranspileResult` (mirror de `TranspileResult`). `NativeCompiler` refactorizado para delegar Tier-2 al nuevo `CTranspiler` instance — el inline `_transpile_to_c` legacy fue eliminado (regression test asserts `not hasattr(nc, "_transpile_to_c")`). Pure C divergencias deliberadas vs Rust: integer literals get `.0` suffix (no `_f64`), empty params get `void`, export macro platform-specific (`__declspec(dllexport)` on Windows, `__attribute__((visibility("default")))` elsewhere). **Mathematical-purity boundary** (per founder ratification 2026-05-08): el C transpiler explícitamente NO emite código que toque PIX navigation primitives (navigate/drill/trail), MDN memory ops (recall/record/μ-update operator), ni algebraic effects (perform/handle/resume/abort/forward). El boundary se enforces grammatically — el DSL solo admite let/return sobre arithmetic + known identifiers; PIX/MDN/effects keywords (13 forbidden ops tested) son rechazados como "Unknown identifier". Documentado en module docstring + INLINE en cada `.c` source generado ("Boundary: no PIX / MDN / effects"). **61 nuevos tests verdes en `tests/test_fase25_c_transpiler.py`**: TestCTranspilerCorrectness (15 — function signature, export macro per-platform, void params, let bindings, integer-literal `.0` suffix preserva FP semantics, source hash determinism, fn_name independence from logic hash, parens preservation), TestCTranspilerValidation (9 — empty/missing-return/unsupported-statement/unknown-ident/disallowed-op/function-call/preprocessor-directive rejection, identifier sanitisation), TestDriftGateRustVsC (12 — parametrised over 9 valid + 8 invalid DSL inputs asserting both transpilers agree on accept/reject; operator whitelist identity check; fn_name prefix identity check; sanitisation identity), TestNativeCompilerDelegation (3 — instance check + legacy method removal regression), TestPurityBoundary (14 — parametrised over 13 PIX/MDN/effects keywords asserting all rejected as unknown identifiers + 1 happy path). **Cross-suite Python = 5038 passed, 0 failed** (full suite verde, 0 regresiones). Tests legacy de `test_native_compute.py` actualizados para usar `nc._c_transpiler.transpile(logic, fn_name, params).c_source` en lugar de `nc._transpile_to_c(logic, fn_name, params)` (arity preservada — el prefijo `axon_compute_` ahora se aplica internamente por CTranspiler). |
| 25.g BPE table embedding via `#embed` | ⏳ pending | ~400 | C + Rust shim | `axon-csys/c-src/tokens/bpe.c` con `#embed "<merges_table>.bin"`; reemplaza tiktoken-rs dep para `cl100k_base` + `o200k_base`; SIMD UTF-8 byte boundary detection; ~20 tests |
| 25.h PEM continuity_token → C (FIPS-friendly crypto) | ⏳ pending | ~500 | C + Rust shim | Port de `axon-rs/src/pem/continuity_token.rs` a C23 con BoringSSL/OpenSSL FIPS-validated SHA256 + HMAC + constant-time compare; audit posture upgrade; ~25 tests |
| 25.i Cross-platform CI matrix (Linux/macOS/Windows × clang/gcc/msvc) | ⏳ pending | CI config | YAML | Extender `.github/workflows/ci.yml` con C23 build matrix; libc compat smoke tests; pinear toolchain versions per OS |
| 25.j Cross-stack drift gate (Rust ↔ C parity) + benchmarks | ⏳ pending | ~600 | Rust + Python | `axon-csys/tests/drift_gate.rs` verifica que C funcs producen byte-identical output a Rust reference impls; benchmarks `cargo bench` con `criterion` para μ-law/resample/buffer-pool/FSM-dispatch — ≥10× target documented |
| 25.k Coordinated cross-stack release v1.19.0 | ⏳ pending | release | — | bump-my-version 1.18.0 → 1.19.0 + tag + push + cargo publish (axon-csys + axon-rs) + PyPI publish + GitHub Release + drift gate verde |

---

# 1. Investigation Summary — kernel candidates por C-brillance

> **Methodology**: surveyed 75k LOC Rust + 17k LOC Python; identified hot-path / latency-critical / memory-control / SIMD-amenable / bit-level / WCET-bound candidates; classified per "where C uniquely wins" vs Rust's existing strengths.

## 1.1 Top-tier candidates (C wins decisively)

### Tier 1A — `axon-rs/src/effects/runtime.rs` (FSM dispatch) → C23 computed gotos
**~590 LOC Rust direct-style interpreter.** Per Fase 23 paper substrate, the unfulfilled promise was *"código ensamblador inmensamente más veloz... operaciones atómicas de salto en la pila de CPU sin objetos de control opacos"* (paper §5). The current Rust impl is a tree-walking interpreter — correct, but it does NOT deliver the native-jump promise.

**Why C uniquely wins here**:
- **Computed gotos** (`goto *labels[op_id]`) are the canonical tool for FSM dispatch since Forth. GCC + clang both support the labels-as-values extension; it became standard practice (Python's CPython interpreter, Lua VM, V8 baseline interpreter all use it). Rust does NOT have computed gotos and likely never will (`unsafe` orthogonality concern).
- **Branch prediction**: with computed gotos the CPU branch predictor sees a per-opcode dispatch site and learns the specific transition probabilities; with Rust's `match`-based dispatch the predictor sees one mega-switch and bottoms out at ~50% prediction accuracy.
- Measured improvement on similar interpreter ports (CPython, Wren, Lua): **3–10× throughput gain** moving from `switch` to computed gotos.

**Hot-path impact**: every algebraic effect operation routes through this dispatcher. Adopters using `stream<τ>` (now desugared to `_StreamBuiltin` handler) hit it for every chunk. At 10k chunks/flow this is the single largest perf lever in the stack.

**FFI clean**: ✅ — the dispatcher takes `&[Instruction]` + a value stack + a handler stack. All inputs serialize trivially via packed structs over FFI. The 8 IR opcodes from Fase 23.d become a packed `enum` with `_BitInt(8)` tags.

**Risk**: HIGH if mishandled (FSM dispatch is correctness-critical). MITIGATED by: byte-identical drift gate (Rust ref impl + C impl must produce same observable trace given same IR), comprehensive Fase 23.f test pack (49 tests) re-applied to the C path.

---

### Tier 1B — `axon-rs/src/buffer/{kind,mod,pool}.rs` (ZeroCopyBuffer + slab allocator) → C23
**~1024 LOC Rust slab allocator with 4 size classes (4K / 64K / 1M / 10M) + per-tenant byte budgets.**

**Why C uniquely wins here**:
- **Cache-line alignment**: `alignas(64)` (C23) gives precise control. Rust has `#[repr(align(64))]` but it's per-struct, not per-allocation. C lets us align entire slab regions to L1d cache lines (64 B on x86-64, 128 B on M-series Apple Silicon).
- **Huge-pages**: `mmap(..., MAP_HUGETLB)` on Linux + `VirtualAlloc(..., MEM_LARGE_PAGES)` on Windows give 2 MiB / 1 GiB pages. TLB miss rate on multimodal workloads (10k+ chunks/sec) drops by ~80%. Rust has no idiomatic crate for this.
- **NUMA awareness**: `numa_alloc_onnode()` (Linux libnuma) lets us pin slab pools to the NUMA node executing the consumer. Critical on dual-socket servers (typical SaaS deploy).
- **`__builtin_ctzll`**: bitmap free-list with O(1) slot picks via count-trailing-zeros intrinsic. Rust has `u64::trailing_zeros()` but our bitmap-walking would still go through Rust's bounds-checking unless we drop into `unsafe` — at which point we've lost Rust's safety advantage anyway.
- **Slab allocators are the canonical C territory**: jemalloc, tcmalloc, mimalloc — all the production-grade allocators are C/C++. There's a reason for this.

**Hot-path impact**: every multimodal chunk (audio frame, image tile, video keyframe) goes through here. Telephony-grade workloads at 10k frames/sec hit this hundreds of thousands of times per second.

**FFI clean**: ✅ — `ZeroCopyBuffer` is already `Arc<[u8]>` + a tag. The `Arc` becomes a refcounted handle in C with `atomic_fetch_add`/`atomic_fetch_sub`. The byte buffer pointer + length tuple is a clean FFI return.

**Risk**: MEDIUM — refcount semantics across FFI boundary need careful design (Rust must not double-free, C must not leak). MITIGATED by: smart-handle wrapper in Rust that holds the C handle + Drops via the C `release` symbol; valgrind + miri runs in CI.

---

### Tier 1C — `axon-rs/src/ots/native/{mulaw,resample}.rs` (signal processing) → C23 + SIMD
**~400 LOC Rust pure-arithmetic transcoders (G.711 μ-law ↔ PCM16 + linear PCM resampler).**

**Why C uniquely wins here**:
- **SIMD intrinsics native**: `<immintrin.h>` (AVX-512 / AVX2 / SSE2) + `<arm_neon.h>` give direct access to vector instructions. Rust has `std::arch::x86_64::*` and `std::arch::aarch64::*` but they require `unsafe` blocks + `#[target_feature]` annotations + manual feature detection. C just compiles `-mavx2` and uses the intrinsics directly.
- **`#embed` for codec lookup tables**: when adding G.722 / G.726 / G.729 codecs (telephony staples), C23's `#embed "tables/g722_qmf.bin"` bakes the tables at compile time. Rust would require `include_bytes!` + a build script to generate the binary — workable but more friction.
- **Predictable WCET**: telephony-grade audio targets ≤20 ms jitter at 8 kHz frame rate. C lets you write code that compiles to a known instruction count per frame; Rust's `unwrap_or_default` patterns + iterator chains compile predictably *most* of the time but defeat WCET reasoning when the pattern compiler picks unexpected codegen paths.
- **`[[unsequenced]]` / `[[reproducible]]` (C23 attributes)**: tell the compiler the function has no observable state mutations across calls → enables loop hoisting + auto-vectorization that Rust's `#[inline]` only partially conveys.

**Hot-path impact**: μ-law transcoding runs once per audio frame per stream. At 1000 concurrent calls × 50 frames/sec = 50k transcodes/sec. Linear resample: same volume.

**FFI clean**: ✅ — already abstracted behind the `Transformer` trait in OTS. Signature is `(input: &[u8], from_kind, to_kind) -> Vec<u8>`. C version exposes `(in_ptr, in_len, out_ptr, out_capacity) -> out_len`. Rust shim handles allocation + slicing.

**Risk**: LOW — pure arithmetic, no shared state. Reference test vectors (G.711 Annex A) are public + immutable.

---

### Tier 1D — Adopter-facing C transpiler for `compute` blocks
**Existing infra**: `axon/runtime/{ffi_bridge,native_compiler,rust_transpiler}.py` already implements DSL → Rust → cdylib → ctypes. Adding a parallel `CTranspiler` opens C as a target backend.

**Why C uniquely wins here**:
- **Compile latency**: `tcc` (TinyC, ~100 KB binary) compiles a 50-line C file in ~5 ms. `rustc` for the same artifact: ~500 ms. For interactive REPL hot-reload of compute blocks, this is the difference between "fluid" and "annoying".
- **Binary size**: a transpiled C `.so` for `let result = a + b; return result` is ~8 KB. The Rust equivalent: ~120 KB (Rust runtime overhead). At scale (1000s of compute blocks per axon program), this matters.
- **Embedded targets**: future axon deployments to microcontrollers (ARM Cortex-M, RISC-V MCUs) need C — there's no `rustc` for `thumbv6m` MCUs that lacks an allocator. Adopters in IoT / edge inference will need C.
- **Adopter familiarity**: more developers know C than Rust. Adopters writing custom compute blocks should not be forced into Rust syntax (that's effectively a Rust-tutorial barrier).

**Hot-path impact**: per-compute-block — typically called many times per flow step. Hot reload during dev experience massively benefits from sub-10ms compile latency.

**FFI clean**: ✅ — same FFI bridge as Rust transpiler. New `CTranspiler` outputs `axon_compute_<name>(double, double, ...) -> double` — same C ABI symbol shape.

**Risk**: LOW — opt-in per compute block (`backend: c` annotation), default stays `rust`. Adopters who want Rust keep Rust; C is the new option.

---

## 1.2 Mid-tier candidates (C wins exist, less compelling)

### Tier 2A — BPE tokenizer (currently `tiktoken-rs`)
~existing dep. Hot path on every LLM call (`Backend::count_tokens`).

**Why C wins**: `#embed "merges_cl100k.bin"` bakes the BPE merges table at compile time (currently downloaded from OpenAI at build time). SIMD UTF-8 boundary detection (simdjson techniques) for 3–8× tokenization speedup on long inputs. Smaller dep tree (drop tiktoken-rs's pulls).

**Why moderate, not top**: tiktoken-rs is fast already (~200 MB/s on a single thread). The win is predominantly *dep hygiene + binary size + #embed offline-buildability*, not a ~10× perf jump.

**Risk**: LOW. Reference vectors come from the OpenAI tiktoken Python package + are exhaustively tested.

### Tier 2B — Audit Evidence ZIP packaging
`axon-rs/src/esk/audit_engine/evidence_packager.rs` (~547 LOC). Deterministic ZIP for SOC2/ISO27001/CC-EAL4+ audit trails.

**Why C wins**: minimal STORE-only ZIP encoder is ~300 LOC C. Full byte-level control aligns with the audit-trail standards (which were drafted assuming C/C++ implementations). The current Rust `zip` crate works but pulls deflate compression that we don't need (we're STORE-only for determinism).

**Why moderate**: existing impl works + passes audit. C version is "polish on already-working", not a critical fix.

### Tier 2C — Trace store (high-volume writes)
`axon-rs/src/trace_store.rs` (~1245 LOC). Every span event writes here.

**Why C wins**: mmap-backed append-only log + SIMD JSON encoding (simdjson techniques in reverse). Reduces per-event latency from ~5 µs (current) to ~500 ns.

**Why moderate, not top**: tightly coupled with tokio + axum + serde. Refactoring the FFI boundary is non-trivial. Better as a Fase 26+ candidate after the lighter wins are shipped.

---

## 1.3 No-go candidates (Rust wins, C is wrong tool)

These were considered + rejected. Documenting so future revisions don't re-litigate:

| Module | Reason C does not fit |
|---|---|
| `axon-rs/src/backends/*` (7 LLM backends) | ~99% of latency is network round-trip to LLM provider. Saving 10-50 µs via C HTTP is irrelevant vs 1-30 s LLM call. Async tokio runtime bound. |
| `axon-frontend/src/{lexer,parser,type_checker,ir_generator}.rs` | String + tree manipulation. Rust pattern matching + lifetimes are perfect fit. C would be a regression. |
| `axon-rs/src/axon_server.rs` (24k LOC HTTP server) | Async runtime bound (tokio + axum). Re-writing in C means losing tokio + sqlx — net loss. |
| `axon/compiler/*.py` (Python frontend) | Symbolic + cold path (compile-time only). No hot-path C win. Per long-term destiny memory: Python frontend will eventually port to Rust, not C. |
| `axon-rs/src/pem/state.rs` (PEM stateful WS) | Async websocket handling — tokio bound. |
| Algebraic effects typechecker (Python) | Compile-time symbolic work. Python's flexibility wins; C would force premature commitment to types. |

---

## 1.4 Strategic frame — "Silicon + Cognition" series

This is the **first** of multiple sessions in the "Silicon + Cognition" series. Future sessions will likely tackle:

- **Fase 26**: GPU acceleration (CUDA / ROCm / Metal kernels for batched LLM token transforms, audio resampling at scale, vector ops). Reordenado 2026-05-08 desde Fase 27: founder priorizó GPU como la siguiente conversación con el metal después de los CPU kernels de Fase 25.
- **Fase 27**: kernel-level integration (eBPF probes, io_uring async, DPDK fast networking)
- **Fase 28**: embedded targets (axon-c-mcu — minimal axon runtime for ARM Cortex-M / RISC-V)
- **Fase 29**: SIMD lane unification (portable SIMD across x86 / ARM / WASM via `<arm_neon.h>` + `<immintrin.h>` + WASM SIMD128 abstraction)

Fase 25 establishes the **C build infrastructure + first 5 kernel ports**. Subsequent sessions build on this foundation. The pattern post-Fase-25 is: every new "metal-bound" kernel goes to C; every new "cognitive" kernel stays Python or Rust.

The naming captures the duality: **silicon** (the metal, the predictable, the deterministic, the fast) on one hand; **cognition** (the LLM-bound, the flexible, the symbolic) on the other. axon becomes a **synthetic nervous system** that orchestrates both layers natively, with C handling the reflexes and Rust/Python handling the deliberate thought.

---

# 2. TL;DR (resume in 30 seconds)

- **What**: introduce C23 as a third stack layer alongside Python (frontend / cognition) + Rust (runtime / glue). Five hot-path kernels migrate to C in Fase 25 v1: effects FSM dispatch (computed gotos), buffer pool slab allocator (huge-pages + cache-aligned), OTS audio transcoders + resampler (SIMD intrinsics), BPE tokenizer (#embed table baking), PEM continuity token (FIPS-friendly crypto). Plus one adopter-facing surface: C transpiler for `compute` blocks (parallel to existing Rust transpiler).
- **Why**: founder vision "axon será 100% Rust + C" + paper §5 "operaciones atómicas de salto" promise unfulfilled by tree-walker + SIMD + huge-pages + audit-posture wins are concretely reachable. Rust is excellent at correctness + ownership; C is canonical for memory layout control + bit-twiddle + hardware intrinsics. Both win when used where they brille.
- **OSS / ENTERPRISE / SPLIT**: 100% OSS. C kernels are foundational performance plumbing, not enterprise differentiation.
- **Robustness target**: byte-identical output across Rust ref impls and C ports (drift gate per kernel); ≥10× speedup vs current Rust where the metric applies (FSM dispatch, audio transcoders); 0 valgrind / miri / address-sanitizer warnings at CI; cross-platform support (Linux gcc + clang, macOS clang + Apple-clang, Windows MSVC + clang-cl).

---

# 3. Architecture — operational design

## 3.1 Crate layout

```
axon-csys/                         # NEW — C build artefacts + Rust extern shims
├── Cargo.toml                     # rustc package, cc-rs in build-dependencies
├── build.rs                       # cc::Build::new().std("c23").file(...)
├── c-src/                         # C23 sources (named .c, never .h.in)
│   ├── effects/dispatch.c         # FSM dispatch with computed gotos
│   ├── effects/dispatch.h         # public header (also generated by cbindgen?)
│   ├── buffer/pool.c              # slab allocator + bitmap free-list
│   ├── buffer/pool.h
│   ├── audio/mulaw.c              # G.711 transcoder (SIMD)
│   ├── audio/resample.c           # linear PCM resampler (SIMD)
│   ├── audio/audio.h
│   ├── tokens/bpe.c               # BPE tokenizer + #embed merges table
│   ├── tokens/merges_cl100k.bin   # binary BPE merge table (embedded via #embed)
│   ├── tokens/merges_o200k.bin
│   ├── tokens/bpe.h
│   └── crypto/continuity.c        # HMAC-SHA256 + base64 + constant-time compare
├── src/                           # Rust shim layer
│   ├── lib.rs                     # extern "C" blocks + safe Rust wrappers
│   ├── effects.rs
│   ├── buffer.rs
│   ├── audio.rs
│   ├── tokens.rs
│   └── crypto.rs
└── tests/
    ├── drift_gate.rs              # Rust ref impl ≡ C port (byte-identical)
    └── soundness.rs               # miri-friendly portion
```

`axon-rs` adds `axon-csys = { path = "../axon-csys" }` as a dep + replaces selected internal kernels with calls into `axon_csys::*`.

## 3.2 Build system

`axon-csys/build.rs` (Rust-side build orchestration):

```rust
fn main() {
    let mut build = cc::Build::new();
    build
        .files(&[
            "c-src/effects/dispatch.c",
            "c-src/buffer/pool.c",
            "c-src/audio/mulaw.c",
            "c-src/audio/resample.c",
            "c-src/tokens/bpe.c",
            "c-src/crypto/continuity.c",
        ])
        .include("c-src")
        // C23 with graceful fallback to C2x for clang ≤17 / gcc ≤13.
        .flag_if_supported("-std=c23")
        .flag_if_supported("-std=c2x")
        // Aggressive but standards-safe optimisation.
        .flag_if_supported("-O3")
        .flag_if_supported("-march=native")    // dev builds; CI overrides
        // Strict warnings — these are kernels, no slop tolerated.
        .flag_if_supported("-Wall")
        .flag_if_supported("-Wextra")
        .flag_if_supported("-Wpedantic")
        .flag_if_supported("-Werror")
        .compile("axon_csys");
    // ...
}
```

Cross-platform compiler dispatch:
- **Linux**: gcc (default, system) + clang (fallback via `cc::Build::compiler("clang")`)
- **macOS**: Apple clang (default) + LLVM clang (homebrew, optional)
- **Windows**: MSVC (default via cc-rs auto-detect) + clang-cl (CI matrix)

C23 detection: `cc::Build::flag_if_supported("-std=c23")` falls back to `-std=c2x` if compiler is older. MSVC uses `/std:clatest`. If neither available → build fails with clear error.

## 3.3 FFI surface conventions

Every C kernel exposes a Rust shim that:
1. Owns the C handle as an opaque `*mut <Type>`
2. Implements `Drop` to call the C `release` symbol
3. Provides safe Rust API on top — adopters never see `unsafe`
4. Compile-time guards prevent accidental double-free (Rust ownership)

Example (buffer pool):
```rust
// axon-csys/src/buffer.rs
use std::os::raw::c_void;

extern "C" {
    fn axon_csys_pool_create(class_count: u32) -> *mut c_void;
    fn axon_csys_pool_destroy(pool: *mut c_void);
    fn axon_csys_pool_alloc(pool: *mut c_void, size: usize) -> *mut u8;
    fn axon_csys_pool_release(pool: *mut c_void, ptr: *mut u8, size: usize);
}

pub struct BufferPool {
    handle: *mut c_void,
}

impl BufferPool {
    pub fn new() -> Self {
        Self { handle: unsafe { axon_csys_pool_create(4) } }
    }
}

impl Drop for BufferPool {
    fn drop(&mut self) {
        unsafe { axon_csys_pool_destroy(self.handle) };
    }
}

unsafe impl Send for BufferPool {}
unsafe impl Sync for BufferPool {}
// ...
```

## 3.4 C23 features deliberately exploited

| Feature | Where used | Why |
|---|---|---|
| `[[nodiscard]]` | every fallible C function | Prevents callers ignoring error returns |
| `[[deprecated("…")]]` | API evolution markers | Cleaner deprecation path than `#warning` |
| `_BitInt(N)` | effects opcode tags (`_BitInt(8)`), packed FSM state | Known-width integers, dense layout |
| `#embed` | BPE merge tables, future codec LUTs | Compile-time binary embedding, no build script gymnastics |
| `nullptr` | universal null constant | Clearer than `NULL` macro |
| `auto` (limited C23 form) | type inference for verbose decls | Reduce boilerplate without losing safety |
| `typeof_unqual` | generic-style macros | Cleaner generic inline functions |
| `[[unsequenced]]` / `[[reproducible]]` | pure-function attributes on transcoders | Enables aggressive auto-vectorisation |
| `alignas(64)` | cache-line alignment of slab regions | Eliminates false sharing |
| Improved enum semantics (declared underlying type) | FSM opcodes | Wire-stable enum layout |

---

# 4. Sub-fases & schedule

| Sub-phase | Description | Stack | Depends on | Deliverable |
|---|---|---|---|---|
| 25.a | Engineering spec (this doc + memory) | — | Fase 24 SHIPPED | spec ratified |
| 25.b | C build infrastructure: `axon-csys` crate + `build.rs` + `cbindgen` + cross-platform dispatch | Rust + C + build.rs | 25.a | crate scaffold + 1 hello-world C kernel + cross-OS CI pass + ~10 build tests |
| 25.c | OTS native transformers → C (mulaw + resample) | C + Rust shim | 25.b | `c-src/audio/{mulaw,resample}.{c,h}` + Rust drop-in replacement + drift gate + benchmark + ~30 tests |
| 25.d | Buffer pool slab allocator → C (cache-aligned + huge-pages opt-in) | C + Rust shim | 25.b | `c-src/buffer/pool.{c,h}` + tenant-aware budget enforcement + valgrind-clean + ~40 tests |
| 25.e | Effects FSM dispatch → C (computed gotos) | C + Rust shim | 25.b, Fase 23.f stable | `c-src/effects/dispatch.{c,h}` + benchmark ≥10× vs tree-walker + drift gate against Rust ref impl + ~50 tests |
| 25.f | C transpiler for compute blocks | Python | 25.b | `axon/runtime/c_transpiler.py` parallel a `RustTranspiler` + adopter-facing `backend: c` annotation + tcc fast-compile for hot-reload + ~25 tests |
| 25.g | BPE tokenizer with `#embed` merges table | C + Rust shim | 25.b | `c-src/tokens/bpe.{c,h}` + embedded merges_cl100k.bin + merges_o200k.bin + replaces tiktoken-rs dep + ~20 tests |
| 25.h | PEM continuity_token → C (FIPS-friendly) | C + Rust shim | 25.b | `c-src/crypto/continuity.{c,h}` + FIPS-validated SHA256 + HMAC + audit posture upgrade + ~25 tests |
| 25.i | Cross-platform CI matrix | YAML | 25.b–h all green | extended `.github/workflows/ci.yml` with C23 build matrix Linux/macOS/Windows × clang/gcc/msvc + libc compat smoke + valgrind + miri + asan |
| 25.j | Cross-stack drift gate (Rust ↔ C parity) + benchmarks | Rust + Python | 25.c–h ports done | `axon-csys/tests/drift_gate.rs` byte-identical assertions + criterion benchmarks documented in plan vivo with measured speedups |
| 25.k | Coordinated cross-stack release v1.19.0 | release | 25.j | bump 1.18.0 → 1.19.0 + tag + push + cargo publish (axon-csys + axon-rs) + PyPI publish + GitHub Release + drift gate verde |

**Classification**: 100% OSS.

**Parallelisability**: 25.b is hard prerequisite. After it lands, 25.c (audio) / 25.d (buffer pool) / 25.e (FSM) / 25.f (C transpiler) / 25.g (BPE) / 25.h (crypto) are all independent and can ship in parallel PRs. 25.i (CI matrix) needs at least one C kernel in main first to exercise the matrix.

**Cadence calendar suggested** (5–7 días focused):

```
Día 1: 25.a + 25.b (build infra + first hello-world cross-OS pass)
Día 2: 25.c audio (mulaw + resample) — first real production kernel
Día 3: 25.d buffer pool — C territory canonical
Día 4: 25.e effects FSM — paper §5 delivery
Día 5: 25.f C transpiler + 25.g BPE + 25.h crypto (parallelisable)
Día 6: 25.i CI matrix + 25.j drift gate + benchmarks
Día 7: 25.k release v1.19.0
```

---

# 5. Decisions (D1–D12) — pending founder ratification

**D1 — `axon-csys` as separate crate, not `axon-rs/c-src/`**

Pros: clean dep boundary; adopters who don't need C kernels can skip the C compiler dep; cross-stack publishing easier (axon-csys gets its own crates.io versioning); build cache hits cleaner. Cons: one more crate to version + publish. **Recommendation**: separate crate.

**D2 — C23, fallback to C2x, no support for ≤C17**

Pros: `#embed` + `_BitInt(N)` + `[[unsequenced]]` are C23-only and we want them. C2x is the same standard pre-ratification name; clang ≥17 + gcc ≥13 + MSVC's `/std:clatest` cover it. Cons: locks out adopters on RHEL 7-era toolchains. Mitigation: graceful build error with clear "upgrade to clang 17+ / gcc 13+" message. **Recommendation**: C23 with C2x fallback; NO C17 path.

**D3 — `cc-rs` not `cmake` for build orchestration**

Pros: `cc-rs` is the de facto Rust ecosystem standard for C deps (used by `ring`, `openssl-sys`, `sodiumoxide`, etc); zero adopter setup; build script integrates into `cargo build` natively. Cons: `cmake` is more capable for complex builds. Mitigation: our C surface is small (~6 files); `cc-rs` is sufficient. **Recommendation**: `cc-rs`.

**D4 — `cbindgen` for header generation, NOT hand-written headers**

Pros: single source of truth (Rust extern blocks); refactors propagate; reduces drift bugs. Cons: cbindgen is not perfect (some macro edge cases). **Recommendation**: cbindgen primary, hand-written .h fallback only when cbindgen produces wrong output.

**D5 — Computed gotos for FSM dispatch (Tier 1A) — REQUIRES gcc/clang, breaks MSVC**

Pros: 3–10× speedup, paper §5 delivery. Cons: MSVC does not support labels-as-values. Mitigation: `#ifdef _MSC_VER` fallback to `switch`-based dispatch on Windows (correctness-equivalent, perf-degraded). **Recommendation**: computed gotos as primary path; switch fallback for MSVC + portable target gates; document the perf delta in benchmarks.

**D6 — Drift gate is byte-identical, not "approximately equal"**

Pros: zero ambiguity in CI; regressions surface immediately. Cons: forces deterministic codegen (no `f64::sqrt` floating-point divergence between libc impls). Mitigation: limit C ports to integer arithmetic + bit ops + standards-pinned crypto; floating-point ports (resample) gate the drift on epsilon-bounded equality, not byte-identical. **Recommendation**: byte-identical for integer kernels; epsilon ≤ 1 LSB for floating-point.

**D7 — No GPL-licensed deps in C kernels (axon-csys is MIT)**

Pros: license matches axon-lang; adopters don't get pulled into GPL contagion. Cons: rules out GNU readline (no impact — we don't use it), GPL parts of glibc extensions (we use vanilla POSIX). Mitigation: pin to libnuma's MIT-licensed parts, BoringSSL (Apache-2) for FIPS crypto path. **Recommendation**: MIT/Apache/BSD only.

**D8 — Existing `RustTranspiler` stays, `CTranspiler` is parallel option (NOT replacement)**

Pros: zero adopter break (`backend: rust` keeps working); C is opt-in via `backend: c`. Cons: two transpilers to maintain. Mitigation: shared parser surface in Python (logic_source → AST) + per-backend code emitter. **Recommendation**: parallel paths, opt-in C.

**D9 — Cross-stack release v1.19.0 includes `axon-csys` 0.1.0 first publish**

Pros: clean version cohort; adopters can pin `axon-csys = "=0.1.0"`. Cons: extra publish step. Mitigation: include in coordinated-release.yml workflow alongside axon-rs + axon-frontend bumps. **Recommendation**: yes, axon-csys ships in v1.19.0 cohort.

**D10 — Benchmark threshold: ≥10× FSM dispatch, ≥3× audio transcoders**

Pros: forcing function for "real wins, not nominal" — if the C port doesn't hit the threshold the C version doesn't ship. Cons: adds discipline burden. Mitigation: criterion benchmarks integrated into CI; PR can't merge if benchmark regresses below threshold. **Recommendation**: yes, document targets per kernel.

**D11 — No GPU / accelerator kernels in Fase 25 (deferred to Fase 26 — RATIFIED 2026-05-08)**

Pros: keep scope manageable; CUDA / Metal / ROCm have their own toolchain complexity that warrants a dedicated session. Cons: leaves perf on the table. Mitigation: structure axon-csys C kernels so GPU offload becomes a future addition (C functions take pointer + length, GPU layer can wrap them). **Founder ratification (2026-05-08)**: GPU/accelerator NO se difiere a "fases posteriores" vagas — se asigna explícitamente a **Fase 26** ("Silicon + Cognition" sesión 2). Esto adelanta el roadmap Silicon: lo que el draft inicial proyectaba como Fase 27 se sube a Fase 26 (GPU es el siguiente metal a hablar después de los kernels CPU de Fase 25). Las otras fronteras (eBPF/io_uring/DPDK, embedded MCU, SIMD lanes) se reordenan en consecuencia y serán secuenciadas en sesiones 3+.

**D12 — `axon-csys` is a foundational component; never bypass via direct `cc::Build` calls in `axon-rs/build.rs`**

Pros: single discipline location for C build; enforces architecture cleanliness. Cons: any axon-rs dev who wants to add a C file must touch axon-csys. Mitigation: this IS the desired effect — C kernels live in axon-csys, period. **Recommendation**: enforce via CI lint (forbidden patterns: `cc::Build::new()` outside `axon-csys/build.rs`).

---

# 6. Tests target — ≥225 nuevos

| Suite | Path | Tests | Coverage |
|---|---|---|---|
| C build infra | `axon-csys/tests/build.rs` + per-OS CI | ~10 | Compiles on Linux/macOS/Windows × clang/gcc/msvc; C23 detected; `flag_if_supported` graceful degrade |
| OTS audio (mulaw + resample) | `axon-csys/tests/audio.rs` | ~30 | G.711 Annex A reference vectors, resampler ratio correctness, SIMD-vs-scalar drift gate, valgrind-clean |
| Buffer pool | `axon-csys/tests/buffer.rs` | ~40 | size class dispatch, tenant byte budgets, alignment guarantees, refcount FFI safety, miri-clean |
| Effects FSM | `axon-csys/tests/effects.rs` | ~50 | Re-applies Fase 23.f Rust test pack against C dispatcher, computed gotos correctness, MSVC switch-fallback parity, benchmark ≥10× |
| C transpiler | `tests/test_fase25_c_transpiler.py` | ~25 | DSL → C source correctness, tcc fast-compile, ctypes load + invoke parity vs RustTranspiler |
| BPE tokens | `axon-csys/tests/tokens.rs` | ~20 | Cross-validates against tiktoken Python reference, #embed table integrity, UTF-8 boundary edge cases |
| PEM crypto | `axon-csys/tests/crypto.rs` | ~25 | NIST CAVS HMAC-SHA256 vectors, base64 round-trip, constant-time compare timing variance bounded |
| Cross-stack drift gate | `axon-csys/tests/drift_gate.rs` | ~20 | Byte-identical (integer kernels) + epsilon-bounded (FP kernels) vs Rust ref impls |
| Cross-stack benchmarks | `axon-csys/benches/*.rs` (criterion) | ~10 (benches, not test count) | FSM dispatch / mulaw / resample / buffer pool / BPE — measured speedups documented |

**Total**: ~220 nuevos + 10 benchmarks. Cross-platform CI matrix multiplies coverage by 6 (3 OS × 2 compilers).

---

# 7. Out of scope (Fase 26+)

- GPU acceleration (CUDA / ROCm / Metal kernels) → Fase 26 (founder ratified 2026-05-08, reordenado desde Fase 27)
- eBPF probes for production telemetry (kernel-level) → Fase 27
- DPDK fast networking for AxonServer high-throughput ingress → Fase 27
- Embedded targets (axon-c-mcu for ARM Cortex-M / RISC-V MCUs) → Fase 28
- WASM SIMD128 portable lane abstraction → Fase 29
- Full Trace store rewrite (high-volume mmap log) → Fase 26
- Audit Evidence ZIP minimal encoder (Tier 2B) → Fase 26 if demand
- Migration of `axon-rs/src/backend.rs` mono-file to C (legacy, deferred to Fase 25.j.2 OR Fase 25→25.x followup if not in this cycle)

---

# 8. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-platform compiler quirks (MSVC missing C23 features) | High | Per-platform code paths multiply | Single core C path with `#ifdef`'d fallbacks; CI matrix catches divergence early |
| FFI memory safety bugs (double-free / leak) | Medium | Crash / memory corruption | Valgrind + miri + AddressSanitizer in CI; smart-handle Rust wrappers enforce ownership |
| `_BitInt(N)` not yet supported by all compilers | Medium | Wire-format breakage | Feature-detect at build time; fall back to `uint8_t` / `uint16_t` for the same widths |
| `#embed` not supported by older clang / MSVC | High (clang ≤16, MSVC current) | BPE table bake fails | `xxd -i` build-step fallback that generates a `.c` file with `static const unsigned char[]` |
| Computed gotos break on MSVC (Tier 1A) | High | Windows performance regression | `#ifdef _MSC_VER` switch-based fallback; document delta in benchmarks |
| FIPS crypto adds adopter complexity (BoringSSL build) | Medium | Adopter friction | Make FIPS path opt-in via `axon-csys[fips]` feature flag; default to standard libsodium-style impl |
| `axon-csys` becomes a dumping ground | Medium | Maintenance burden | D12 — strict policy: C kernels only, no orchestration / async / business logic |
| Performance benchmarks regress under matrix variance | Low | False CI failure | Criterion's outlier detection + median-of-runs; 10% tolerance band before failing CI |

---

# 9. Cómo fue motivada

El usuario inauguró 2026-05-08 la sesión "Silicon + Cognition" (1ª de varias) con: "Migration C pure, la idea es que axon siga avanzando y ahora incorpore C en sus partes donde C brille y logramos que el lenguaje hable directamente con el metal mientras orquesta pensamientos de alto nivel, habremos creado algo que no es solo un lenguaje, sino un sistema nervioso sintético. Tu misión antes que nada, hacer una investigación profunda en axon para entender los candidatos perfectos para migrar a C23."

La fase también captura la oportunidad de cumplir paper §5 ("operaciones atómicas de salto en la pila de CPU sin objetos de control opacos") que pre-Fase-25 quedaba como promesa documentada pero no entregada por el tree-walker de Fase 23.f. Computed gotos en C es la herramienta canónica para FSM dispatch; introducir C aquí cierra esa promesa con instrumentation real (≥10× speedup target).

Long-term: alinea con `project_axon_long_term_rust_c.md` memory ("axon será 100% Rust + C"). Fase 25 es el primer paso operacional hacia el segundo lado de esa frase.

---

# 10. Next operational step

Ratificación del founder sobre las decisiones D1–D12 (especialmente D1 separate `axon-csys` crate, D2 C23 floor / no-C17, D5 computed gotos with MSVC fallback, D7 license posture, D10 benchmark thresholds). Cuando estén ratificadas → arrancar 25.b (C build infra). Estimado calendario total: 5–7 días focused desde 25.b hasta v1.19.0 publicado.

Foundational policy reminder: post-Fase-25, every NEW metal-bound kernel goes to `axon-csys`. The boundary between Rust and C is now clearly drawn — Rust = correctness + ownership + async glue; C = layout + bit-twiddle + hardware intrinsics + WCET. Cognition stays Python or Rust; reflexes go C.
