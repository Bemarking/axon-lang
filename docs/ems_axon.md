# Epistemic Module System (EMS) — Research Paper

> **axon-lang v0.23.0** — Separate Compilation for Cognitive Programming Languages  
> March 2026

---

## Abstract

This document presents the **Epistemic Module System (EMS)**, axon-lang's solution to separate compilation and cross-file referencing. Unlike traditional module systems designed for value-level programming, EMS operates on *cognitive compilation units* — files whose exports are personas, anchors, shields, mandates, and flows rather than functions, types, and values.

EMS synthesizes seven state-of-the-art paradigms from programming language theory into a unified design that is both theoretically grounded and practically functional:

1. **OCaml ML** — Signatures, functors, first-class modules
2. **1ML (Rossberg 2015)** — Core/module unification via System Fω
3. **Haskell Backpack** — Mixin linking + separate type-checking
4. **GHC `.hi` / OCaml `.cmi`** — Interface files for incremental compilation
5. **Zig** — `comptime` + lazy evaluation + build dependency graphs
6. **Nix / Bazel** — Content-addressed hermetic builds with early cutoff
7. **Rust** — Crates + traits as behavioral contracts

The novel contribution is **Epistemic Compatibility Checking** — no existing module system validates *epistemic guarantees* across import boundaries. EMS ensures that a `know`-level module cannot silently import `speculate`-level definitions, propagating the epistemic type lattice across the entire project dependency graph.

---

## I. Problem Statement: Why axon-lang Needs a Module System

### 1.1 The Single-File Bottleneck

Prior to EMS, each `.axon` file compiled in complete isolation. The parser correctly recognized `import` statements:

```axon
import axon.security.{NoHallucination, NoBias}
```

The lexer tokenized them, the parser produced `ImportNode` AST nodes, the type checker validated them, and the IR generator lowered them to `IRImport` — but **nothing resolved them**. The `_resolve_run()` method in `ir_generator.py` only searched local symbol tables (`self._personas`, `self._anchors`, etc.), meaning any cross-file reference required duplicate inline stubs:

```axon
// expert_module.axon — the canonical source
persona Expert {
    domain ["medicine", "diagnostics"]
    tone "precise"
    confidence_threshold 0.9
}

anchor NoHallucination {
    require "factual, verifiable claims only"
    on_violation raise
}
```

```axon
// consultation.axon — MUST duplicate everything
// NOTA: Stubs mínimos para satisfacer el IR resolver.
persona Expert {
    domain ["medicine"]
    tone "precise"
}

anchor NoHallucination {
    require "factual claims"
    on_violation raise
}
```

### 1.2 Three Concrete Problems

| Problem | Impact |
|---------|--------|
| **DRY Violation** | Every file needing `Expert` must re-declare it. 10 files = 10 copies. |
| **Silent Divergence** | Stubs desynchronize from canonical definitions. `consultation.axon`'s `Expert` has `domain ["medicine"]` while the original has `["medicine", "diagnostics"]`. |
| **Scaling Barrier** | Multi-agent systems with dozens of `.axon` files are impractical. Each file is an island. |

### 1.3 Why Not a Simple `#include`?

A naive textual inclusion (`#include`-style) would solve DRY but introduce worse problems:

- **Compilation cost**: Including all transitive dependencies means recompiling everything on any change.
- **Name pollution**: All symbols from included files flood the namespace.
- **Circular dependencies**: No protection against `A includes B includes A`.
- **No semantic boundary**: Cannot validate epistemic compatibility.

axon-lang needed a solution worthy of its cognitive domain — not a hack, but a system grounded in programming language theory.

---

## II. Research Foundation: Seven Paradigms Analyzed

### 2.1 OCaml ML Module System — Signatures, Functors, First-Class Modules

**Source**: Xavier Leroy et al., "The OCaml system" (INRIA); Robert Harper & John Mitchell, "On the type structure of Standard ML" (1993).

OCaml's module system is the gold standard for typed modularity. Three key concepts:

**Signatures** (module types): Describe what a module *must* provide without revealing implementation:
```ocaml
module type SECURITY = sig
  val verify : claim -> bool
  val reject_patterns : string list
end
```

**Functors** (parameterized modules): Functions from modules to modules, enabling dependency injection:
```ocaml
module MakeValidator (S : SECURITY) = struct
  let validate claim = S.verify claim
end
```

**First-class modules**: Modules as values, enabling runtime dispatch:
```ocaml
let security_module = (module StrictSecurity : SECURITY)
let validator = MakeValidator((val security_module))
```

**What we take**: The concept of *Cognitive Signatures* — interfaces that declare the epistemic properties a module guarantees (persona domains, anchor constraints, shield capabilities) without exposing prompt text or step logic.

### 2.2 1ML (Rossberg 2015) — Unification via System Fω

**Source**: Andreas Rossberg, "1ML — Core and modules united" (ICFP 2015).

1ML's radical thesis: the distinction between "core language" (expressions, types) and "module language" (signatures, functors) is artificial. By interpreting the entire language through System Fω (the polymorphic lambda calculus with type operators), 1ML eliminates stratification.

In practical terms: a module IS a record, a signature IS a record type, a functor IS a function. No separate "module language" needed.

**What we take**: axon-lang should NOT have a separate "module declaration language." An imported persona IS a persona. An imported anchor IS an anchor. The namespace is unified — `import axon.security.{NoHallucination}` makes `NoHallucination` available as if it were declared locally. No wrappers, no adapters, no module-level indirection.

### 2.3 Haskell Backpack — Mixin Linking + Separate Type-Checking

**Source**: Scott Kilpatrick et al., "Backpack: Retrofitting Haskell with interfaces" (POPL 2014); Edward Z. Yang, "Backpack to work" (PhD thesis, 2017).

Backpack separates compilation into two distinct phases:

1. **Wiring diagram** — determines which package provides which signature, without looking at code.
2. **Type-checking** — validates each component against the wired signatures.

The *mixin linking* mechanism allows multiple packages to "mix in" implementations for the same signature, with diamond dependencies resolved automatically.

**What we take**: Two-phase compilation. Phase 0-1 (Discovery + Interface Generation) produces the wiring diagram — which file provides which symbols. Phase 2-3 (Resolution + Full IR) type-checks against those interfaces. This separation means Phase 0-1 can run in parallel across all files.

### 2.4 GHC `.hi` / OCaml `.cmi` — Interface Files

**Source**: GHC User's Guide §4.7 "Recompilation checking"; OCaml Manual §13 "Separate compilation."

Both compilers emit interface files alongside compiled output:

- **GHC `.hi`**: Contains type signatures, class instances, rules, inlining hints, and an *ABI hash*. If the ABI hash hasn't changed, GHC skips recompilation of downstream modules.
- **OCaml `.cmi`**: Contains the typed signature of a module. The compiler checks `.cmi` files of dependencies, not their source.

GHC's insight: content-based recompilation (`-fforce-recomp` disables it) is dramatically faster than timestamp-based. The ABI hash captures *semantic* changes, ignoring whitespace and comment edits.

**What we take**: `.axi` (AXON Interface) files — JSON-serialized cognitive signatures. Each `.axi` contains:
- Exported persona/anchor/flow/shield/mandate/psyche signatures
- Content hash (SHA-256 of source → Nix-style cache key)
- Interface hash (SHA-256 of the `.axi` content → early cutoff key)
- Epistemic floor (the module-level epistemic guarantee)

### 2.5 Zig — Comptime + Lazy Evaluation + Build DAGs

**Source**: Andrew Kelley, "Zig Language Reference" §29 "Build system."

Zig's compilation model is radically lazy:

- The compiler only analyzes functions that are actually called.
- `@import("module.zig")` creates a dependency edge but doesn't trigger full compilation until a symbol is used.
- `build.zig` is itself Zig code, making the build system a DAG of compilation steps expressed in the same language.

Zig's `comptime` allows arbitrary computation at compile time, including type manipulation, code generation, and validation — all without a separate macro language.

**What we take**: Lazy resolution — the module resolver only scans `import` statements (fast regex, no full parse), builds the dependency DAG, and topologically sorts it. Full compilation happens only for modules whose symbols are actually referenced by `run` statements. If a module is imported but no symbols are used, it's a no-op.

### 2.6 Nix / Bazel — Content-Addressed Hermetic Builds

**Source**: Eelco Dolstra, "The Purely Functional Software Deployment Model" (PhD thesis, 2006); Bazel documentation, "Remote caching" (2024).

Nix's fundamental insight: a build is a *pure function* from inputs to outputs. If the inputs haven't changed (verified by content hash), the output is guaranteed identical. This enables:

- **Content-addressed storage**: Artifacts keyed by `SHA-256(inputs)`, not by name or path.
- **Early cutoff**: If source changes but output is identical (e.g., adding a comment), downstream rebuilds are skipped.
- **Hermetic isolation**: Builds happen in sandboxed environments with no network access.

Bazel extends this with a two-layer cache: **Action Cache** (maps action hash → output references) and **Content-Addressable Storage** (maps content hash → file bytes).

**What we take**: The `CompilationCache` uses the Nix model:
```
cache_key = SHA-256(source_content + imported_interface_hashes)
```
If any dependency's interface changes, we recompile. If a source changes but its `.axi` interface is identical, we apply *early cutoff* and skip recompilation of downstream modules.

### 2.7 Rust — Crates + Traits as Behavioral Contracts

**Source**: The Rust Reference, "Crates and source files"; "The Rust Programming Language" §10 "Traits."

Rust's module system provides:
- **Crates**: The compilation unit. Each crate compiles independently, producing `.rlib` or `.so` files.
- **Traits**: Behavioral contracts that types must implement, analogous to Haskell typeclasses or OCaml module types.
- **Visibility**: Fine-grained `pub`/`pub(crate)` access control.

Rust does NOT have first-class modules or functors. Instead, it uses traits + generics to achieve parameterized behavior — a more constrained but pragmatic approach.

**What we take**: The concept of *cognitive behavioral contracts*. An anchor set (e.g., `{NoHallucination, NoBias, CiteSources}`) functions like a trait — it declares the behavioral guarantees a module provides. A module that exports these anchors is certifying compliance with those guarantees.

---

## III. EMS Architecture: How It Works

### 3.1 Compilation Pipeline (5 Phases)

```
Phase 0: DISCOVERY    ─── ModuleResolver ──────────────── ┐
         Build dependency DAG from import statements       │
         (Zig-inspired: regex scan, no full parse)         │  Can run
                                                           │  in parallel
Phase 1: INTERFACE    ─── InterfaceGenerator ──────────── ┘
         Compile each file to .axi (signatures only)
         Compute epistemic floor for each module

Phase 2: RESOLUTION   ─── EpistemicCompatChecker ──────── ┐
         Validate epistemic compatibility across imports    │  Sequential
                                                           │  (needs Phase 1)
Phase 3: FULL IR      ─── IRGenerator + ModuleRegistry ── ┘
         Generate complete IR with resolved symbols
         Cache result via CompilationCache

Phase 4: LINKING      ─── (future) ────────────────────────
         Merge .axir files into unified IRProgram
```

### 3.2 Phase 0 — Dependency Discovery (`module_resolver.py`)

The `ModuleResolver` builds a DAG of `.axon` file dependencies using a fast regex scanner (`scan_imports`) that extracts import statements without lexing or parsing — inspired by Zig's lazy compilation approach.

```python
# Regex matches: import axon.security.{NoHallucination, NoBias}
_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w]+(?:\.[\w]+)*)(?:\.\{([^}]+)\})?\s*$",
    re.MULTILINE,
)
```

The DAG is topologically sorted using **Kahn's algorithm**:

1. Compute in-degrees (number of dependencies) for each node.
2. Start with nodes having zero dependencies (leaf modules).
3. Process each node, decrementing dependents' in-degrees.
4. If the sorted result doesn't include all nodes → **cycle detected**.

Cycle detection is critical because cognitive cycles create semantic paradoxes — a persona cannot depend on an anchor that depends on that persona's definition.

**Module path resolution**:
```
import axon.security.{NoHallucination}
                 ↓
Search: project_root/axon/security.axon
Then:   stdlib_path/axon/security.axon
```

### 3.3 Phase 1 — Interface Generation (`interface_generator.py`)

The `InterfaceGenerator` extracts the **public surface** of a compiled `IRProgram` into a `CognitiveInterface` — the `.axi` file. This contains only signatures, never implementation details:

| Primitive | What the signature captures | What it hides |
|-----------|---------------------------|--------------|
| **Persona** | name, domain, tone, confidence_threshold | description text |
| **Anchor** | name, constraint_hash, on_violation | require/reject/enforce text |
| **Flow** | name, step_count, output_type | step bodies, prompt text |
| **Shield** | name, scan_categories, on_breach | strategy details, redact rules |
| **Mandate** | name, tolerance, max_steps | PID gains (kp, ki, kd) |
| **Psyche** | name, trait_count | trait values, Big Five scores |

#### Interface Hash (GHC ABI Hash)

Each `.axi` file has two hashes:

1. **`content_hash`** = SHA-256(source file) — changes on ANY edit.
2. **`interface_hash`** = SHA-256(serialized `.axi`) — changes only when the PUBLIC surface changes.

This distinction enables **early cutoff**: if a developer adds a comment to `security.axon`, the `content_hash` changes but the `interface_hash` stays the same. Modules that import from `security.axon` DON'T need recompilation.

### 3.4 Epistemic Floor Computation

Each module's **epistemic floor** is computed from its content:

```
Rules (highest level wins):
  anchors present           → KNOW (4)
  shields present           → BELIEVE (3)
  epistemic block 'know'    → KNOW (4)
  epistemic block 'believe' → BELIEVE (3)
  epistemic block 'doubt'   → DOUBT (2)
  epistemic block 'speculate' → SPECULATE (1)
  none of the above         → UNSPECIFIED (0)
```

The epistemic floor represents the **maximum level of epistemic guarantee** the module can provide. A module with anchors is inherently `KNOW`-level because anchors enforce factual constraints.

### 3.5 Phase 2 — Epistemic Compatibility (`epistemic_compat.py`)

The `EpistemicCompatChecker` validates that every import respects the **Epistemic Compatibility Principle (ECP)**:

$$\forall \text{import}(M_a, M_b): \text{floor}(M_b) \geq \text{floor}(M_a) \lor \text{explicit\_downgrade}(M_a)$$

In plain language: if module A (the importer) has a higher epistemic floor than module B (the imported), this is an epistemic downgrade.

**Compatibility Matrix**:

| Importer ↓ \ Imported → | know | believe | doubt | speculate |
|---|---|---|---|---|
| **know** | ✅ OK | ⚠️ WARNING | ⚠️ WARNING | ❌ ERROR |
| **believe** | ✅ OK | ✅ OK | ⚠️ WARNING | ❌ ERROR |
| **doubt** | ✅ OK | ✅ OK | ✅ OK | ⚠️ WARNING |
| **speculate** | ✅ OK | ✅ OK | ✅ OK | ✅ OK |

**Gap calculation**:
- Gap ≥ 3 → ERROR (severe mismatch, e.g., `know` importing `speculate`)
- Gap ≥ 1 → WARNING (downgrade, e.g., `know` importing `believe`)
- Gap ≤ 0 → OK (same level or upgrade)
- `strict=True` mode escalates all warnings to errors.

**Why this matters**: Without this check, a developer could write a `know`-level medical diagnosis flow that silently imports creative `speculate`-level personas. The diagnosis would execute with speculative reasoning where factual rigor was expected — a silent semantic bug that no traditional module system would catch.

### 3.6 Phase 3 — Cross-Reference Resolution (`ir_generator.py`)

The modified `IRGenerator` accepts an optional `ModuleRegistry`:

```python
# Old behavior (unchanged):
gen = IRGenerator()  # No registry → single-file, no resolution

# New behavior (EMS):
registry = ModuleRegistry(interfaces)
gen = IRGenerator(module_registry=registry)
```

When `_visit_import` encounters an `ImportNode` and the registry is present:

1. Looks up the module's `CognitiveInterface` in the registry.
2. For each imported name, calls `_inject_imported_symbol()`.
3. `_inject_imported_symbol` dispatches by signature type:
   - `PersonaSignature` → creates `IRPersona` stub in `self._personas`
   - `AnchorSignature` → creates `IRAnchor` stub in `self._anchors`
   - `FlowSignature` → creates `IRFlow` stub in `self._flows`
   - `ShieldSignature` → creates `IRShield` stub in `self._shields`
   - `MandateSignature` → creates `IRMandate` stub in `self._mandate_specs`
   - `PsycheSignature` → creates `IRPsycheSpec` stub in `self._psyche_specs`
4. Marks the `IRImport` as `resolved=True` with the interface hash.

Now when `_resolve_run()` searches for personas and anchors, they're in the local symbol tables — placed there by the import resolution, not by duplicate stubs.

### 3.7 Phase 4 — Compilation Cache (`compilation_cache.py`)

The `CompilationCache` implements the Nix/Bazel content-addressed caching model:

```
Cache key = SHA-256(source_content) + SHA-256(dependency_interfaces)
```

**Cache structure on disk**:
```
.axon_cache/
  ├── interfaces/      # .axi interface files
  ├── ir/              # Serialized IRProgram JSON files
  └── manifest.json    # Cache manifest with metadata
```

**Invalidation rules**:
1. Source hash changed → recompile.
2. Any dependency's interface hash changed → recompile.
3. Source AND dependency hashes match → CACHE HIT (skip compilation).
4. Source changed BUT interface hash unchanged → **early cutoff** (downstream modules skip recompilation).

---

## IV. Why It's Functional: Theoretical Guarantees

### 4.1 Soundness (No False Positives in Resolution)

The import resolution is sound because:

- **Signature monotonicity**: A `CognitiveInterface` only contains what a module actually exports. If `NoHallucination` appears in the `.axi`, it was compiled from a valid `anchor` declaration.
- **Backwards compatibility**: When `ModuleRegistry` is `None`, the `IRGenerator` behaves identically to the pre-EMS version. All 151 existing tests pass without modification.
- **Immutable IR**: All `IRNode` subclasses are `@dataclass(frozen=True)`. Once an `IRPersona` is injected by import resolution, it cannot be accidentally mutated.

### 4.2 Completeness (No Missing Symbols)

The topological sorting guarantees that when module A is compiled, all of A's dependencies have already been compiled and their interfaces are available in the `ModuleRegistry`. This prevents "forward reference" errors.

### 4.3 Termination

- **Acyclicity**: Kahn's algorithm detects cycles before compilation begins.
- **Finite DAG**: The dependency graph is bounded by the number of `.axon` files.
- **No fixpoint iteration**: Unlike some module calculi that require iterating to a fixed point, EMS resolves in a single topological pass.

### 4.4 Determinism

- **Content-addressed**: Same inputs always produce same outputs.
- **Sorted dependency hash**: `sorted(interface_hashes)` ensures hash order is deterministic regardless of discovery order.
- **No ambient state**: The `ModuleResolver` takes a `project_root` and produces a topological order — no global mutable state.

---

## V. Test Validation

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestBackwardsCompatibility` | 3 | IRGenerator with/without registry, IRImport defaults |
| `TestTwoFileResolution` | 3 | Persona + anchor import, unresolved fallback |
| `TestCircularImportDetection` | 3 | Import scanning, cycle detection |
| `TestEpistemicCompatibility` | 4 | Same level, upgrade, downgrade, unspecified |
| `TestEpistemicConflict` | 4 | Severe mismatch, strict mode, missing symbol, reporting |
| `TestCompilationCache` | 5 | Hit/miss, source/dependency invalidation, hash determinism |
| `TestInterfaceGeneration` | 3 | Creation, serialization roundtrip, hash determinism |
| `TestEarlyCutoff` | 2 | Cutoff applies/doesn't apply |
| `TestDiamondDependency` | 1 | A→B, A→C, B→D, C→D topological order |
| `TestModuleRegistry` | 6 | Register, resolve, contains, init, epistemic lattice |
| **Total** | **34** | **+ 151 existing = 185 all passing** |

---

## VI. Comparison with Existing Systems

| Feature | OCaml | Haskell | Rust | Zig | **axon-lang EMS** |
|---------|-------|---------|------|-----|------------------|
| Interface files | `.cmi` | `.hi` | — | — | **`.axi`** |
| Content-addressed cache | ✗ | Partial | ✗ | ✗ | **✓ (Nix-style)** |
| Early cutoff | ✗ | ✓ (ABI hash) | ✗ | ✗ | **✓** |
| Lazy discovery | ✗ | ✗ | ✗ | ✓ | **✓** |
| Cycle detection | ✓ | ✓ | ✓ | ✓ | **✓** |
| Epistemic compatibility | ✗ | ✗ | ✗ | ✗ | **✓ (novel)** |
| Zero-breaking-change retrofit | — | ✓ (Backpack) | — | — | **✓** |

---

## VII. File Map

```
axon/compiler/
  ├── module_resolver.py       # Phase 0: DAG discovery + topological sort
  ├── interface_generator.py   # Phase 1: .axi generation + ModuleRegistry
  ├── epistemic_compat.py      # Phase 2: Cross-module epistemic validation
  ├── compilation_cache.py     # Phase 3: Content-addressed IR cache
  ├── ir_generator.py          # Phase 3: Modified — accepts ModuleRegistry
  └── ir_nodes.py              # Modified — IRImport.resolved + interface_hash

tests/
  └── test_module_system.py    # 34 tests covering all EMS components
```

---

## References

1. Leroy, X. (2000). "A modular module system." *Journal of Functional Programming*, 10(3), 269–303.
2. Rossberg, A. (2015). "1ML — Core and modules united." *ACM SIGPLAN Notices*, 50(9), 35–47.
3. Kilpatrick, S., Dreyer, D., Peyton Jones, S., Marlow, S. (2014). "Backpack: Retrofitting Haskell with interfaces." *POPL 2014*.
4. Yang, E. Z. (2017). "Backpack to work: Towards practical mixin linking for Haskell." PhD thesis, Stanford University.
5. Dolstra, E. (2006). "The Purely Functional Software Deployment Model." PhD thesis, Utrecht University.
6. Harper, R., Mitchell, J. C. (1993). "On the type structure of Standard ML." *ACM TOPLAS*, 15(2), 211–252.
7. Kelley, A. (2024). "Zig Language Reference." https://ziglang.org/documentation/
8. The Bazel Authors (2024). "Remote caching." https://bazel.build/remote/caching
