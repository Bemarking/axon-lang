//! §Fase 27.b — axon-csys-enterprise build orchestration.
//!
//! Compiles the C23 metal-bound enterprise kernels into a static
//! archive (`libaxon_csys_enterprise.a` on Unix, `axon_csys_enterprise.lib`
//! on MSVC) that the Rust crate links against. Mirrors the OSS
//! `axon-csys/build.rs` (Fase 25.b) on the C-build side; adds the
//! FIPS feature-flag dispatch on the link side per D3 ratification
//! (BoringSSL-FIPS OR OpenSSL-FIPS, mutually exclusive).
//!
//! Default (no feature) is the no-fips passthrough: only the probe
//! C source compiles + links; the Rust shim re-exports OSS axon-csys
//! verbatim. This keeps the crate buildable on adopters' unlicensed
//! deployments — no surprise build failures.
//!
//! New kernels (27.c onward) append their `.c` files to the source
//! list near the bottom of `main()`. The flag chain stays the same
//! — C23 + strict diagnostics + cargo's own optimisation level.

use std::env;
use std::path::PathBuf;

fn main() {
    // ─── Mutual-exclusivity guard for FIPS feature flags (D3) ─────────────
    //
    // Both BoringSSL-FIPS and OpenSSL-FIPS are NIST-CAVS-validated crypto
    // libraries with overlapping symbol surfaces (e.g. `EVP_DigestInit_ex`
    // exists in both). Linking both at once produces undefined-symbol
    // collisions at the linker stage, OR worse, a successful link that
    // routes calls non-deterministically to one or the other.
    //
    // Fail loudly at build time so the adopter picks one explicitly.
    let fips_boringssl = env::var("CARGO_FEATURE_FIPS_BORINGSSL").is_ok();
    let fips_openssl = env::var("CARGO_FEATURE_FIPS_OPENSSL").is_ok();
    if fips_boringssl && fips_openssl {
        panic!(
            "axon-csys-enterprise: features `fips-boringssl` and `fips-openssl` \
             are mutually exclusive (per D3 ratified 2026-05-09). Pick one."
        );
    }

    let manifest_dir = PathBuf::from(
        env::var("CARGO_MANIFEST_DIR")
            .expect("CARGO_MANIFEST_DIR is always set by cargo when invoking build scripts"),
    );
    let c_src = manifest_dir.join("c-src");

    let mut build = cc::Build::new();
    build.include(&c_src);

    // ─── Propagate cargo features to C-side `#ifdef` blocks ──────────────
    //
    // probe.c (and future kernels) use `#ifdef
    // AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL` etc to gate per-feature
    // code. Cargo only sets the corresponding `CARGO_FEATURE_*` env
    // var; we forward those into the C compile as `-D...=1` defines.
    if fips_boringssl {
        build.define("AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL", "1");
    }
    if fips_openssl {
        build.define("AXON_CSYS_ENTERPRISE_FIPS_OPENSSL", "1");
    }
    if env::var("CARGO_FEATURE_PUBLIC_ANCHOR").is_ok() {
        build.define("AXON_CSYS_ENTERPRISE_PUBLIC_ANCHOR", "1");
    }
    if env::var("CARGO_FEATURE_PHI_SCRUBBER_C").is_ok() {
        build.define("AXON_CSYS_ENTERPRISE_PHI_SCRUBBER_C", "1");
    }

    // ─── C23-first standard flag chain (inherits OSS Fase 25.b D2) ────────
    //
    // Same `flag_if_supported` chain the OSS crate uses: `-std=c23` then
    // `-std=c2x` so clang ≤17 / gcc ≤13 take c2x and clang ≥18 / gcc ≥14
    // take c23. MSVC uses `/std:clatest`. The C standard floor is
    // documented as C23 with C2x fallback per OSS D2; no C17 path.
    if cfg!(target_env = "msvc") {
        build.flag_if_supported("/std:clatest");
        // C11 _Atomic on MSVC is gated behind an experimental flag even
        // with `/std:clatest`. Reserved here for future kernels (audit
        // log mmap will need it); harmless for the probe.
        build.flag_if_supported("/experimental:c11atomics");
    } else {
        build.flag_if_supported("-std=c23");
        build.flag_if_supported("-std=c2x");
    }

    // ─── Diagnostics — strict for kernels (mirrors OSS) ───────────────────
    if cfg!(target_env = "msvc") {
        build.flag_if_supported("/W4");
        build.flag_if_supported("/WX");
    } else {
        build.flag_if_supported("-Wall");
        build.flag_if_supported("-Wextra");
        build.flag_if_supported("-Wpedantic");
        build.flag_if_supported("-Werror");
        build.flag_if_supported("-Wshadow");
        build.flag_if_supported("-Wcast-align");
        build.flag_if_supported("-Wconversion");
        build.flag_if_supported("-Wstrict-prototypes");
    }

    // ─── Feature-test macros (inherits OSS Fase 25.k patch fix) ───────────
    //
    // glibc gates `posix_memalign` + similar declarations behind
    // `_POSIX_C_SOURCE >= 200112L`. macOS exposes them unconditionally;
    // MSVC uses `_aligned_malloc` instead. Define on Linux/BSD only.
    if !cfg!(target_env = "msvc") && !cfg!(target_os = "macos") {
        build.define("_POSIX_C_SOURCE", "200809L");
    }

    // ─── Sources ──────────────────────────────────────────────────────────
    //
    // 27.b: build-infra probe.
    // 27.c: c-src/crypto/fips_glue.c  (BoringSSL/OpenSSL-FIPS bridge) — gated.
    // 27.d: c-src/audit/log.c         (tamper-evident mmap audit log).
    // Subsequent sub-fases append their .c files:
    //   27.e: c-src/tokens/*.c          (vertical BPE registration helpers)
    //   27.f: c-src/audit/evidence.c    (byte-deterministic ZIP encoder)
    //   27.g: c-src/shield/phi_scrub.c  (SIMD PHI scrubber, optional)
    build.file(c_src.join("probe").join("probe.c"));
    build.file(c_src.join("audit").join("log.c"));
    build.file(c_src.join("shield").join("phi_scrub.c"));

    // ─── 27.c — FIPS glue source (conditionally compiled) ─────────────────
    //
    // The glue file `c-src/crypto/fips_glue.c` includes <openssl/evp.h>
    // unconditionally. Adopters running the no-fips passthrough do NOT
    // have OpenSSL/BoringSSL headers in their toolchain — including
    // those headers in the no-fips build would force every adopter to
    // install a crypto lib for no reason. The build script therefore
    // adds the source ONLY when one of the FIPS features is active.
    //
    // The OS-side prebuilt include + lib paths come from environment
    // variables AXON_BORINGSSL_FIPS_PREBUILT / AXON_OPENSSL_FIPS_PREBUILT,
    // mirroring the convention OpenSSL's own build scripts use
    // (`OPENSSL_DIR` + the `openssl-sys` crate).
    if fips_boringssl || fips_openssl {
        let fips_glue = c_src.join("crypto").join("fips_glue.c");
        build.file(&fips_glue);

        let (env_var, prebuilt) = if fips_boringssl {
            (
                "AXON_BORINGSSL_FIPS_PREBUILT",
                env::var("AXON_BORINGSSL_FIPS_PREBUILT"),
            )
        } else {
            (
                "AXON_OPENSSL_FIPS_PREBUILT",
                env::var("AXON_OPENSSL_FIPS_PREBUILT"),
            )
        };

        let prebuilt = prebuilt.unwrap_or_else(|_| {
            panic!(
                "axon-csys-enterprise: feature `{feature}` requires \
                 `{env_var}` to point at a prebuilt {lib} root containing \
                 `include/` + `lib/`. Per D3 ratified 2026-05-09: adopters \
                 supply their own NIST-CAVS-validated build (BoringSSL-FIPS \
                 / OpenSSL-FIPS Provider). The fips-{lib_short} feature is \
                 a LINK-TIME contract; the source-code path is built but the \
                 final binary cannot link without `{env_var}` set.",
                feature = if fips_boringssl {
                    "fips-boringssl"
                } else {
                    "fips-openssl"
                },
                env_var = env_var,
                lib = if fips_boringssl {
                    "BoringSSL-FIPS"
                } else {
                    "OpenSSL-FIPS Provider"
                },
                lib_short = if fips_boringssl {
                    "boringssl"
                } else {
                    "openssl"
                },
            )
        });
        let prebuilt = PathBuf::from(prebuilt);
        let include_dir = prebuilt.join("include");
        let lib_dir = prebuilt.join("lib");

        if !include_dir.is_dir() {
            panic!(
                "axon-csys-enterprise: {} = {} but `{}` is not a directory. \
                 Expected layout: <root>/include + <root>/lib.",
                env_var,
                prebuilt.display(),
                include_dir.display(),
            );
        }
        if !lib_dir.is_dir() {
            panic!(
                "axon-csys-enterprise: {} = {} but `{}` is not a directory. \
                 Expected layout: <root>/include + <root>/lib.",
                env_var,
                prebuilt.display(),
                lib_dir.display(),
            );
        }

        // Header search path: the FIPS lib's include root. Lib search
        // path: emitted to rustc as `cargo:rustc-link-search`.
        build.include(&include_dir);
        println!("cargo:rustc-link-search=native={}", lib_dir.display());

        if fips_boringssl {
            // BoringSSL ships a single static archive `libcrypto.a`
            // that bundles both the crypto + the FIPS module.
            println!("cargo:rustc-link-lib=static=crypto");
        } else {
            // OpenSSL-FIPS Provider exposes `libcrypto` for the EVP
            // surface; `libssl` is required if any caller pulls TLS
            // helpers (none in this kernel, but link defensively so
            // future kernels can use them).
            println!("cargo:rustc-link-lib=static=crypto");
            println!("cargo:rustc-link-lib=static=ssl");
        }

        // Linker-side platform deps: BoringSSL / OpenSSL link against
        // libdl + libpthread on Unix; on Windows the equivalents are
        // bundled in the CRT. Emitting these unconditionally on Unix
        // matches what `openssl-sys` does and avoids a confusing
        // "undefined reference to dlopen" message at adopter link
        // time.
        if !cfg!(target_env = "msvc") {
            println!("cargo:rustc-link-lib=dylib=dl");
            println!("cargo:rustc-link-lib=dylib=pthread");
        }
    }

    build.compile("axon_csys_enterprise");

    // ─── FIPS-validated crypto link cfg flags ─────────────────────────────
    //
    // The link-search + link-lib emissions for the FIPS prebuilt happen
    // up in the `if fips_boringssl || fips_openssl { ... }` source-block
    // above (alongside the conditional fips_glue.c compilation). Here
    // we only emit the rustc-cfg flags so downstream Rust code can
    // `cfg!(axon_csys_enterprise_fips_*)` over the active path
    // independently of feature-flag dispatch.
    if fips_boringssl {
        println!("cargo:rustc-cfg=axon_csys_enterprise_fips_boringssl");
    }
    if fips_openssl {
        println!("cargo:rustc-cfg=axon_csys_enterprise_fips_openssl");
    }

    // ─── Math library link (resample / future hash kernels use libm) ──────
    //
    // Modern glibc inlines libm functions into libc.so but musl, BSD, and
    // older glibcs require explicit `-lm`. macOS libSystem covers it; MSVC
    // bundles math into the CRT. Reserved for future kernels; harmless to
    // emit unconditionally.
    if !cfg!(target_env = "msvc") && !cfg!(target_os = "macos") {
        println!("cargo:rustc-link-lib=m");
    }

    // ─── pthread link for the audit log mutex (POSIX only) ────────────────
    //
    // 27.d's audit log uses pthread_mutex_t for the writer's append
    // serialization on POSIX. Modern glibc bundles pthread into libc.so
    // (since glibc 2.34) but musl, BSD, and older glibcs require explicit
    // `-lpthread`. macOS libSystem covers it. MSVC uses CRITICAL_SECTION
    // (no link required). Linking unconditionally on non-MSVC + non-macOS
    // is harmless and matches the convention OSS axon-csys' future
    // pthread-using kernels will adopt.
    if !cfg!(target_env = "msvc") && !cfg!(target_os = "macos") {
        println!("cargo:rustc-link-lib=pthread");
    }

    // ─── Re-build triggers ────────────────────────────────────────────────
    println!("cargo:rerun-if-changed=c-src");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=AXON_BORINGSSL_FIPS_PREBUILT");
    println!("cargo:rerun-if-env-changed=AXON_OPENSSL_FIPS_PREBUILT");

    // ─── Declare custom rustc cfgs (silence unexpected_cfgs lint) ─────────
    //
    // Rust 1.80+ warns on `cfg!(...)` checks against names not declared
    // in Cargo.toml `[lints]` or via `cargo:rustc-check-cfg`. The two
    // axon-csys-enterprise-specific cfgs activate behind the matching
    // feature flag — declare them so `unexpected_cfgs` doesn't yell.
    println!("cargo:rustc-check-cfg=cfg(axon_csys_enterprise_fips_boringssl)");
    println!("cargo:rustc-check-cfg=cfg(axon_csys_enterprise_fips_openssl)");
}
