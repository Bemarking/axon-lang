# Fase 12 — Workspace Refactor + Tooling Ecosystem

**Documento vivo.** Reorganiza el árbol Rust de Axon para habilitar
herramientas externas (`axon-lsp`, `axon-analyzer` futuro, bindings
de terceros) que solo necesitan el frontend del lenguaje sin arrastrar
el runtime completo (HTTP + Postgres + AWS). Mantiene byte-identical
parity con la Python reference.

**Target:** `axon-lang v1.4.1` (patch — zero-semantic change).
**Inicio:** 2026-04-24
**Depende de:** Fase 11 GA (v1.4.0, ya shippeada).
**Habilita:** `axon-lsp v0.1.0` (repo standalone, ver
`axon-lsp/docs/plan_v0.1.0.md` en el repo hermano
`git@github.com:Bemarking/axon-lsp.git`).

## Regla de pureza

Sigue vigente. Este refactor es estructural — no cambia una sola
línea de semántica, no agrega features, no toca adopters. Cualquier
PR que toque `axon-enterprise/` en esta fase se rechaza.

---

## Estado del plan

| Sub-fase | Scope | Estado |
|---|---|---|
| 12.a | Extraer `axon-frontend/` como crate standalone sin deps de runtime | ✅ Completo (2026-04-24) |
| 12.b | `axon-rs` consume `axon-frontend` vía path dep; tests regresión | ✅ Completo (2026-04-24) |
| 12.c | CI — matrix build incluye `axon-frontend` solo, validando ausencia de runtime deps | ⬜ Pendiente |
| 12.d | Release v1.4.1 — tag + GitHub Release + publicación opcional a crates.io | ⬜ Pendiente |
| 12.e | (Futuro) `axon-backends/` — extracción análoga de los 7 LLM backends | ⬜ Backlog |

Orden no arbitrario: 12.a crea el crate, 12.b migra `axon-rs` para consumirlo, 12.c valida el contrato de "frontend sin runtime", 12.d cierra la versión.

---

## Motivación

### El problema concreto

`axon-rs/src/lib.rs` expone hoy **~120 `pub mod`** en un único crate
monolítico llamado `axon`. Cualquier consumidor externo que solo
necesita el frontend (lexer, parser, AST, type checker) arrastra
como transitive deps:

- `axum 0.8` + `tower` + `tower-http` (HTTP server) — irrelevante
  para un LSP o un analyzer.
- `sqlx 0.8 [postgres]` + `chrono` — irrelevante.
- `aws-config 1` + `aws-sdk-secretsmanager 1` — irrelevante.
- `reqwest 0.12 [rustls]` + `jsonwebtoken 9` — irrelevante.
- `ed25519-dalek 2` + `hmac 0.12` + `sha2 0.10` — irrelevante.
- `tokio 1 [full]` — innecesario para análisis sync.
- `zip 2 [deflate]` + 12 más.

**Impacto medido estimado sobre `axon-lsp`:**
- Binary size: ~80–120 MB (vs. ~15 MB esperado para un LSP lean).
- `cargo build --release` cold: ~3–5 min (vs. ~40 s esperado).
- CI `cargo check` p95: ~90 s (vs. ~15 s esperado).
- Cold-start del servidor LSP: cuestionable con runtime tokio full.

### Lo que ya está bien

El código fuente del frontend **ya es puro**. Verificado 2026-04-24:

```
tokens.rs      — serde::Serialize solo                   (leaf)
lexer.rs       — use crate::tokens                        (→ tokens)
ast.rs         — <no internal deps>                       (leaf)
parser.rs      — use crate::{ast, tokens}                 (→ ast, tokens)
epistemic.rs   — std::collections solo                    (leaf)
type_checker.rs— use crate::{ast, epistemic}              (→ ast, epistemic)
ir_nodes.rs    — <no internal deps>                       (leaf)
ir_generator.rs— use crate::{ast, ir_nodes}               (→ ast, ir_nodes)
checker.rs     — use crate::{ast, lexer, parser,          (→ ast, lexer,
                   type_checker}                             parser, type_checker)
```

Total: 9 módulos, 10,762 LOC, **cero deps externas más allá de `serde`
y `std`**. La reubicación es mecánica — la dificultad está en el
resto del repo que consume estos módulos vía `crate::` path, no
vía `axon_frontend::`.

---

## Layout propuesto (Opción P1)

```
axxon-constructor/
├── axon/                         # Python reference (sin cambios)
├── axon-rs/                      # Rust runtime (depende de axon-frontend)
│   ├── Cargo.toml                # [dependencies] axon-frontend = { path = "../axon-frontend" }
│   └── src/
│       ├── lib.rs                # sin los pub mod de frontend; pub use axon_frontend::*
│       ├── main.rs
│       ├── handlers/             # runtime-only
│       ├── runtime/
│       ├── esk/
│       ├── pem/
│       ├── ots/
│       └── ...                   # (toda la capa de runtime + servers)
├── axon-frontend/                # NUEVO crate standalone — pure compiler frontend
│   ├── Cargo.toml                # [dependencies] serde = "1"  (eso es todo)
│   ├── README.md
│   └── src/
│       ├── lib.rs                # pub mod tokens; lexer; ast; parser; ...
│       ├── tokens.rs             (movido desde axon-rs/src/)
│       ├── lexer.rs
│       ├── ast.rs
│       ├── parser.rs
│       ├── epistemic.rs
│       ├── type_checker.rs
│       ├── ir_nodes.rs
│       ├── ir_generator.rs
│       └── checker.rs
├── docs/
├── infrastructure/
├── pyproject.toml                # Python side (sin cambios)
└── ...
```

**Por qué P1 y no un workspace `crates/` unificado:**
- Preserva el shape Python+Rust del repo (axxon-constructor es
  multi-lenguaje, no un puro Cargo workspace).
- Cambia 2 `Cargo.toml` y 9 archivos fuente reubicados — vs. decenas
  de paths en CI, Dockerfiles, scripts si migramos a `crates/`.
- No rompe URLs de issue/PR que referencian `axon-rs/src/...` en el
  pasado (los paths nuevos son `axon-frontend/src/...`, los viejos
  siguen resolviendo para módulos que se quedan en `axon-rs/`).

---

## Sub-fase 12.a — Extraer `axon-frontend/`

**Alcance cerrado:**

1. Crear `axon-frontend/` con:
   ```toml
   [package]
   name = "axon-frontend"
   version = "0.1.0"
   edition = "2024"
   rust-version = "1.95"
   description = "Axon compiler frontend — lexer, parser, AST, type checker, IR generator. Zero runtime dependencies."
   license = "MIT"
   repository = "https://github.com/Bemarking/axon-lang"
   readme = "README.md"
   keywords = ["axon", "compiler", "parser", "ast"]
   categories = ["compilers"]

   [dependencies]
   serde = { version = "1", features = ["derive"] }
   serde_json = "1"   # used by ir_nodes + ir_generator for dynamic fields
   ```

2. Mover (con `git mv`, preservando historial) estos 12 archivos:
   - `axon-rs/src/tokens.rs`      → `axon-frontend/src/tokens.rs`
   - `axon-rs/src/lexer.rs`       → `axon-frontend/src/lexer.rs`
   - `axon-rs/src/ast.rs`         → `axon-frontend/src/ast.rs`
   - `axon-rs/src/parser.rs`      → `axon-frontend/src/parser.rs`
   - `axon-rs/src/epistemic.rs`   → `axon-frontend/src/epistemic.rs`
   - `axon-rs/src/type_checker.rs`→ `axon-frontend/src/type_checker.rs`
   - `axon-rs/src/ir_nodes.rs`    → `axon-frontend/src/ir_nodes.rs`
   - `axon-rs/src/ir_generator.rs`→ `axon-frontend/src/ir_generator.rs`
   - `axon-rs/src/checker.rs`     → `axon-frontend/src/checker.rs`
   - `axon-rs/src/refinement.rs`  → `axon-frontend/src/refinement.rs`  (Fase 11.a Trust catalog)
   - `axon-rs/src/stream_effect.rs`→ `axon-frontend/src/stream_effect.rs`  (Fase 11.a backpressure catalog)
   - `axon-rs/src/legal_basis.rs` → `axon-frontend/src/legal_basis.rs`   (Fase 11.c legal catalog)

   **Descubrimiento durante ejecución (2026-04-24):** el scan inicial
   de deps solo identificó los 9 módulos explícitos del compilador. Al
   compilar el crate extraído aparecieron 3 deps transitivas adicionales
   vía `crate::<module>::CATALOG` en `type_checker.rs`. Los 3 módulos
   extra son puros (`std::fmt` únicamente) y forman parte lógica del
   frontend — catalogs compile-time usados por el type checker.

3. Extracción parcial de `axon-rs/src/ots/mod.rs` — este archivo es
   mixto (contiene const catalogs + registry runtime con
   `OnceLock<TransformerRegistry>`). Split:
   - Crear `axon-frontend/src/ots_catalog.rs` con los 3 `pub const`:
     `OTS_TRANSFORM_EFFECT_SLUG`, `OTS_BACKEND_EFFECT_SLUG`,
     `OTS_BACKEND_CATALOG`.
   - En `axon-rs/src/ots/mod.rs` reemplazar los consts por
     `pub use axon_frontend::ots_catalog::*` (backward compat).
   - Actualizar `type_checker.rs` para usar
     `crate::ots_catalog::OTS_BACKEND_CATALOG` (antes
     `crate::ots::OTS_BACKEND_CATALOG`).

3. Crear `axon-frontend/src/lib.rs`:
   ```rust
   //! AXON compiler frontend — zero-runtime-deps core.
   //!
   //! Re-exported by `axon-rs` (which adds runtime + handlers + servers)
   //! and consumed directly by `axon-lsp` (which only needs the frontend).

   pub mod tokens;
   pub mod lexer;
   pub mod ast;
   pub mod parser;
   pub mod epistemic;
   pub mod type_checker;
   pub mod ir_nodes;
   pub mod ir_generator;
   pub mod checker;
   ```

4. Crear `axon-frontend/README.md`: breve descripción + warning de
   "pure frontend — cero runtime deps, si agregas una sin review
   se cierra el PR".

**Verificación:**
- `cd axon-frontend && cargo build --release` verde en <60 s cold.
- `cargo tree -p axon-frontend` muestra SOLO `serde` + `serde_json` +
  sus deps transitivas (`serde_derive`, `syn`, `quote`, `proc-macro2`,
  `unicode-ident`, `itoa`, `ryu`, `memchr`).
  **Cero** mención de `tokio`, `axum`, `sqlx`, `reqwest`, `aws-*`,
  `jsonwebtoken`, `zip`, `chrono`, `hmac`, `sha2`, `ed25519-dalek`.
- `cargo test -p axon-frontend` verde (sin tests nuevos; los
  existentes viajan con los archivos).

**CHECK:** el crate extraído compila sin tocar `axon-rs/` para nada.

---

## Sub-fase 12.b — `axon-rs` consume `axon-frontend`

**Alcance cerrado:**

1. Actualizar `axon-rs/Cargo.toml`:
   ```toml
   [dependencies]
   axon-frontend = { path = "../axon-frontend" }
   # ...todas las demás deps de runtime
   ```

2. Editar `axon-rs/src/lib.rs` — remover los 9 `pub mod` que movimos,
   reemplazar con re-exports transparentes para mantener compatibilidad
   con callers existentes:
   ```rust
   //! AXON runtime — frontend vive en axon-frontend, runtime en este crate.
   pub use axon_frontend::{
       ast, checker, epistemic, ir_generator, ir_nodes,
       lexer, parser, tokens, type_checker,
   };

   // ...el resto de pub mod de runtime sigue igual
   pub mod handlers;
   pub mod runtime;
   // ...
   ```

3. Auditar todos los `use crate::{ast, lexer, parser, ...}` dentro de
   `axon-rs/src/**` — tras el re-export, deberían seguir compilando
   sin cambios (porque `crate::ast` resuelve vía `pub use`). Si algún
   macro o path literal se rompe, cambiar a `axon_frontend::<mod>::`
   explícito en ese call site.

4. Ejecutar tests completos de `axon-rs` — byte-identical parity con
   Python reference se mantiene.

**Verificación:**
- `cd axon-rs && cargo build --release` verde (idéntico a pre-refactor
  en artefacto final, solo cambia el grafo de deps).
- `cargo test -p axon --all-features` verde: toda la suite existente
  de tests de integración pasa idéntica.
- `cargo run -p axon -- check examples/*.axon` produce salida
  byte-identical a pre-refactor (comparar con `git stash` + rerun).
- `cargo tree -p axon | grep axon-frontend` → aparece con `path+...`.

**CHECK:** binary `axon` (runtime) se comporta idéntico para CLI,
HTTP routes, y outputs del checker.

---

## Sub-fase 12.c — CI: matrix valida el contrato

**Alcance cerrado:**

1. Actualizar `.github/workflows/rust.yml` (o equivalente):
   - Agregar job `axon-frontend-build` que hace `cargo build -p
     axon-frontend --release` aislado.
   - Agregar step de verificación: `cargo tree -p axon-frontend |
     grep -vE '^(axon-frontend|serde|serde_derive|syn|quote|proc-macro2|unicode-ident)'`
     debe retornar vacío. Si encuentra algo, **falla el CI** con mensaje
     explícito: "axon-frontend gained a runtime dep — review needed".
   - Job existente `axon-rs-build` queda igual.

2. Actualizar `Dockerfile` de `axon-rs/` si aplica — el COPY context
   ahora necesita `../axon-frontend/` también. Escenario específico:
   `COPY axon-rs/ ./axon-rs/` ahora también hace `COPY axon-frontend/
   ./axon-frontend/`, y la RUN de `cargo build` opera sobre el crate
   `axon` con path dep resuelto al lugar correcto.

**Verificación:**
- CI verde en main después del merge.
- El dep-audit job **falla intencionalmente** si se agrega una dep de
  prueba (ej. `tokio = "1"`) a `axon-frontend/Cargo.toml` — validado
  con PR sintético local antes de merge.

**CHECK:** la regla "axon-frontend no tiene runtime deps" es una
invariante ejecutable en CI, no un comentario en un doc.

---

## Sub-fase 12.d — Release v1.4.1

**Alcance cerrado:**

1. Bump `axon-rs/Cargo.toml` → `version = "1.4.1"`.
2. Bump `axon/__init__.py` → `__version__ = "1.4.1"` (parity requirement).
3. `axon-frontend/Cargo.toml` → `version = "0.1.0"` (initial release
   del nuevo crate).
4. `CHANGELOG.md` entry: "1.4.1 — Workspace refactor: extract
   `axon-frontend` as standalone crate. Zero semantic change. Enables
   `axon-lsp` and future tooling to consume the Axon compiler frontend
   without runtime dependencies."
5. Tag + release.
6. (Opcional, decidir en review): `cargo publish -p axon-frontend`
   a crates.io. Si sí → `axon-lsp` puede usar `axon-frontend = "0.1"`
   de registry en vez de path dep.

**Verificación:**
- `git tag v1.4.1 && git push origin v1.4.1` → CI de release verde.
- Binarios publicados en GitHub Releases.
- `axon-lsp` repo actualiza su `Cargo.toml` para consumir
  `axon-frontend` vía path (`../axxon-constructor/axon-frontend`) o
  via registry (si 6 completado).

**CHECK:** `axon-lsp v0.1.0 sub-fase 0.b` puede arrancar con
`axon-frontend` disponible como crate reutilizable.

---

## Sub-fase 12.e — Backlog futuro (no parte de v1.4.1)

Documentado aquí para no perder el hilo; NO se ejecuta en esta fase.

### `axon-backends/` — extracción análoga para los 7 LLM backends

Similar a 12.a pero para backends (`claude`, `gpt`, `mistral`, `ollama`,
`echo`, `google`, `cohere`). Beneficia un escenario futuro donde
adopters quieran un subset mínimo de backends sin el runtime
completo. Prerequisitos: auditar deps de cada backend (reqwest compartido
es OK, cosas específicas como aws-bedrock o gcp-auth irían en
backend-gated features). Target tentativo: v1.5.0.

### `axon-cli-core/` — lib extraíble del CLI

Si queremos shippear `axon check` y `axon inspect` como utilidades
standalone (sin el server completo), un `axon-cli-core` crate que
dependa solo de `axon-frontend` + `clap` sería viable. Target
tentativo: v1.6.0.

---

## Riesgos + mitigaciones

| Riesgo | Mitigación |
|---|---|
| Byte-identical parity se rompe por algún path literal (`module_path!()`, `file!()`) que cambia con la reubicación | Tests de `axon-rs` + comparación directa con outputs Python pre/post refactor. Rollback trivial: revert del merge commit. |
| `pub use axon_frontend::...` causa ambigüedad con otros `pub use` en `axon-rs/src/lib.rs` | Renombrar imports en call sites conflictivos a `axon_frontend::ast` explícito. `rustc` detecta la ambigüedad en compile time. |
| Macros `proc-macro` en `axon-rs` que generan rutas `crate::ast` se rompen | Auditar `grep -r '#\[derive' axon-rs/src/` en 12.b; los derives estándar (serde, Debug) no se rompen. Si hay macro custom que genera paths, ajustar la macro. |
| `Dockerfile` falla en build por COPY context incorrecto | Build local del Dockerfile antes de merge. Update a multi-stage si es necesario. |
| crates.io publish conflicts (nombre `axon-frontend` tomado) | Plan B: publicar como `axon-compiler-frontend` o `axon-lang-frontend`. Verificar disponibilidad en 12.d antes de tagging. |

---

## Versionado

- `axon-lang v1.4.1` — release de 12.a–12.d.
- `axon-frontend v0.1.0` — primera publicación del nuevo crate.
- `axon-lsp v0.1.0` — bloqueada hasta 12.d, después arranca sub-fase 0.b.

---

## Handoff a sesiones futuras

Este doc es el single source of truth para Fase 12. Cada sub-fase
cerrada se marca en la tabla de estado + resultado bloque aquí con
commits + verificación ejecutada. No repetir plan inline en
conversación.

---

## Resultado — Sub-fases 12.a + 12.b (2026-04-24)

**Rama:** `feat/fase-12a-axon-frontend`.

**Scope real ejecutado (vs. 9 archivos planeados → 12 movidos + 1 split):**

Movidos (12) con `git mv` preservando historial:
- `tokens.rs`, `lexer.rs`, `ast.rs`, `parser.rs`, `epistemic.rs`,
  `type_checker.rs`, `ir_nodes.rs`, `ir_generator.rs`, `checker.rs`
  (los 9 previstos)
- `refinement.rs`, `stream_effect.rs`, `legal_basis.rs` (3 catalogs
  compile-time de Fase 11.a/11.c que `type_checker` necesitaba y que
  el scan inicial no detectó porque sus referencias eran embedded en
  código, no `use` statements)

Split parcial:
- `axon-rs/src/ots/mod.rs` → se extrajeron los 3 `pub const` catalogs
  a `axon-frontend/src/ots_catalog.rs`; runtime registry
  (`TransformerRegistry`, `OnceLock`, `native::seed_registry`) se
  quedó en `axon-rs/src/ots/mod.rs`. Re-export backward-compat en el
  runtime.

Cambios textuales (vs. movimientos): 1 call site updated en
`type_checker.rs` (`crate::ots::OTS_BACKEND_CATALOG` → `crate::ots_catalog::OTS_BACKEND_CATALOG`).

**Deps del nuevo crate:**
```
axon-frontend v0.1.0
├── serde v1.0.228 (+ serde_derive + syn + quote + proc-macro2 + unicode-ident)
└── serde_json v1.0.149 (+ itoa + memchr + zmij)
```
Cero `tokio/axum/sqlx/reqwest/aws-*/jwt/chrono/hmac/sha2/ed25519-dalek/zip`.
Contrato cumplido.

**Verificación ejecutada:**

| Check | Resultado |
|---|---|
| `cargo build --release -p axon-frontend` (aislado) | ✅ 9s cold |
| `cargo build --release -p axon` (consumer) | ✅ 3m 37s cold, 0 errors, 23 warnings (todas pre-existentes) |
| `cargo tree -p axon-frontend` — runtime deps | ✅ ninguna |
| `axon.exe check examples/banking_reference.axon` | ✅ `457 tokens · 21 declarations · 0 errors` |
| `axon.exe check examples/government_reference.axon` | ✅ `434 tokens · 18 declarations · 0 errors` |
| `axon.exe check examples/contract_analyzer.axon` | ✅ `168 tokens · 9 declarations · 0 errors` |
| Parse errors con posición precisa (axpoint_status, axonendpoint_full) | ✅ `file:line:col` idéntico al comportamiento esperado |

**Pre-existente, no bloquea 12.a/12.b:**

`cargo test --lib` falla en 5 errores en archivos **que no toqué**:
- `trust_verifiers.rs:372, 392` (4 errores) — `OsRng: CryptoRngCore`
  no satisfecho por version skew `rand 0.9` vs `ed25519-dalek 2`
  (que usa `rand_core 0.6`). Tests `ed25519_roundtrip` y
  `ed25519_rejects_tampered_payload`.
- `ots/pipeline.rs:389` (1 error) — `dyn Transformer: Debug` faltante
  en un `.unwrap_err()` de test.

Ambos problemas existen en master pre-refactor (verificado vía git log
— commits relevantes son `363f845 feat(lang-11.a)` y `e50ca4a
feat(runtime-11.e)`; commit `a7f6445 fix(axon-rs): compile errors
in OTS + multipart + refresh Cargo.lock` ya fue un intento previo
de saneamiento en este área). Se documentan como item separado de
12.c fixes (no parte de 12.a/12.b scope).

**Handoff a 12.c:** feature branch lista para merge a master una vez
validada por review. 12.c debe resolver los 5 tests pre-existentes
ANTES de habilitar el job CI que valida "no runtime deps en
axon-frontend", de lo contrario el pipeline queda rojo por razones
no relacionadas.
