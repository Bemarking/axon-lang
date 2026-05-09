//! §Fase 25.b — axon-csys build orchestration.
//!
//! Compiles the C23 metal-bound kernels into a static archive
//! (`libaxon_csys.a` on Unix, `axon_csys.lib` on MSVC) that the Rust crate
//! links against. The `cc` crate handles cross-platform compiler dispatch
//! (gcc / clang on Unix, MSVC / clang-cl on Windows); we drive it with
//! C23-first flags and a graceful fallback chain per founder ratification
//! D2 (2026-05-08): C23 floor, C2x fallback for clang ≤17 / gcc ≤13, no
//! C17 path.
//!
//! New kernels (25.c onward) append their `.c` files to the source list
//! near the bottom of `main()`. The flag chain stays the same — C23 +
//! strict diagnostics + cargo's own optimisation level.

use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(
        env::var("CARGO_MANIFEST_DIR")
            .expect("CARGO_MANIFEST_DIR is always set by cargo when invoking build scripts"),
    );
    let c_src = manifest_dir.join("c-src");

    let mut build = cc::Build::new();
    build.include(&c_src);

    // ─── C23-first standard flag chain (D2 ratified 2026-05-08) ────────────
    //
    // `flag_if_supported` silently drops flags the compiler does not
    // recognise. The cc crate appends in order; the LAST recognised flag
    // wins. So writing `-std=c23` then `-std=c2x` means clang 17 takes c2x,
    // clang 18+ takes c23, gcc 13 takes c2x, gcc 14+ takes c23. This is
    // the documented graceful-degrade path.
    if cfg!(target_env = "msvc") {
        // MSVC's "C latest" mode covers what is currently available of
        // C23 in the Microsoft compiler (nullptr, #embed preview, etc.).
        // It does NOT cover labels-as-values or _BitInt — those kernels
        // gate themselves with #ifdef in the C source.
        build.flag_if_supported("/std:clatest");
        // C11 _Atomic on MSVC is gated behind an experimental flag even
        // with /std:clatest. Required by 25.d's pool.c — slab allocator
        // counters use _Atomic uint64_t. Silently ignored by older MSVCs
        // that don't recognise the flag (the build then fails loudly on
        // the #include <stdatomic.h>, which is the right behaviour).
        build.flag_if_supported("/experimental:c11atomics");
    } else {
        build.flag_if_supported("-std=c23");
        build.flag_if_supported("-std=c2x");
    }

    // ─── Diagnostics — strict for kernels ──────────────────────────────────
    //
    // No slop tolerated in the C surface. Warnings are errors so that any
    // implicit conversion / unused-result / signed-comparison warning
    // breaks CI immediately.
    if cfg!(target_env = "msvc") {
        build.flag_if_supported("/W4");
        // /WX makes warnings errors. Match the -Werror posture below.
        build.flag_if_supported("/WX");
    } else {
        build.flag_if_supported("-Wall");
        build.flag_if_supported("-Wextra");
        build.flag_if_supported("-Wpedantic");
        build.flag_if_supported("-Werror");
        // Belt + braces — these are the warnings most likely to mask
        // FFI safety bugs at the C boundary.
        build.flag_if_supported("-Wshadow");
        build.flag_if_supported("-Wcast-align");
        build.flag_if_supported("-Wconversion");
        build.flag_if_supported("-Wstrict-prototypes");
    }

    // ─── Optimisation ──────────────────────────────────────────────────────
    //
    // Cargo respects `OPT_LEVEL` env var that it sets per profile, so we
    // do NOT override `-O3` here — that would defeat `cargo build`
    // (debug profile wants -O0 + debuginfo). `-march=native` is also
    // intentionally NOT added at the global level; baking the build
    // host's instruction set into release tarballs would crash adopter
    // machines lacking AVX-512 / NEON. Per-kernel SIMD opt-in lives in
    // 25.c via `target_feature` cfg gates.

    // ─── Sources ───────────────────────────────────────────────────────────
    //
    // 25.b: build-infra probe.
    // 25.c: G.711 μ-law transcoders + linear PCM16 resampler.
    //       OTS native morphisms — port of axon-rs/src/ots/native/{mulaw,
    //       resample}.rs preserving the categorical structure documented
    //       in docs/ontological_tool_synthesis.md.
    // 25.d: Cache-line-aligned slab allocator with bitmap free-list +
    //       huge-pages opt-in. Port of axon-rs/src/buffer/pool.rs.
    //       Per-tenant accounting stays in the Rust shim (HashMap-of-
    //       Arc<str>) per founder pillar split — C handles slabs;
    //       Rust handles symbolic bookkeeping.
    build.file(c_src.join("probe").join("probe.c"));
    build.file(c_src.join("audio").join("mulaw.c"));
    build.file(c_src.join("audio").join("resample.c"));
    build.file(c_src.join("buffer").join("pool.c"));
    // 25.e: Algebraic effects FSM dispatcher with computed gotos
    //       (gcc/clang) + switch fallback (MSVC). Paper §5 delivery —
    //       "operaciones atómicas de salto en la pila de CPU sin
    //       objetos de control opacos" finally honoured by the
    //       per-opcode label table. Direct port of
    //       axon-rs/src/effects/runtime.rs preserving D2 (one-shot
    //       continuations), D9 (typechecker rejects unhandled effect)
    //       and D10 (typechecker rejects no-discharge / multi-resume)
    //       — the C runtime mirrors the Rust ref in surfacing those
    //       cases as defensive error codes for the unlikely path
    //       where the compiler missed them.
    build.file(c_src.join("effects").join("dispatch.c"));

    build.compile("axon_csys");

    // ─── Math library link (resample.c uses floor / round) ────────────────
    //
    // Modern glibc inlines libm functions into libc.so but musl, BSD, and
    // older glibcs require explicit `-lm`. macOS libSystem covers it; MSVC
    // bundles math into the CRT. Link explicitly on Unix to be portable.
    if !cfg!(target_env = "msvc") && !cfg!(target_os = "macos") {
        println!("cargo:rustc-link-lib=m");
    }

    // ─── Re-build triggers ─────────────────────────────────────────────────
    println!("cargo:rerun-if-changed=c-src");
    println!("cargo:rerun-if-changed=build.rs");
}
