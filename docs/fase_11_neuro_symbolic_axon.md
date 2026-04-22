# Fase 11 — Axon Neuro-Symbolic Micro-OS

**Documento vivo.** Evoluciona Axon del "intérprete de grafos de LLM"
al Micro-Sistema Operativo Neuro-Simbólico: formaliza red (HTTP/WS),
criptografía (HMAC, OAuth2), flujos continuos (audio PCM/μ-law), y
replay determinista con base legal tipada **como primitivas del
lenguaje**, garantizadas en tiempo de compilación por `checker.rs`.

**Target:** `axon-lang v1.2.0` + `axon-enterprise v1.2.0`
**Inicio:** 2026-04-22
**Depende de:** Fase 10 GA (`axon-enterprise v1.1.0`) — específicamente
10.g (audit hash chain), 10.l (compliance tooling) y 10.i (observability).

## Regla de pureza

Axon es lenguaje, no adoptante. Este plan vive en `axxon-constructor`
porque describe la evolución del lenguaje **y** su integración con
Enterprise. El código en `axon-lang` permanece adopter-agnóstico:
**cero mención** de Whisper, Stripe, Kivi, o cualquier cliente
específico. Las primitivas son genéricas (`Stream<Bytes>`, `LegalBasis`,
`ReplayToken`); las integraciones concretas viven en los adopters.

---

## Estado del plan

| Sub-fase | Scope | Estado |
|---|---|---|
| 11.a | Temporal Algebraic Effects + Trust Types (`Stream<T>`, `Trusted<T>`) | ✅ Completo |
| 11.b | Zero-Copy Multimodal Buffers (audio/video/file ingest sin cruzar FFI) | ✅ Completo |
| 11.c | Deterministic Replay + Legal-Basis Typed Effects (`ReplayToken` + `LegalBasis<>`) | ✅ Completo |
| 11.d | Stateful PEM sobre WebSocket (continuidad cognitiva cross-reconnect) | ✅ Completo |
| 11.e | OTS Binary Pipeline Synthesis (auto-descubrir transcoders tipados) | ✅ Completo |
| 11.f | Integration Testing + Security Audit (regresión cross-phase, threat model) | ✅ Completo |

Orden NO es arbitrario: 11.a habilita refinement types que 11.c y 11.d
usan; 11.b es prerequisito para 11.e (OTS opera sobre buffers zero-copy);
11.f sella la fase.

---

## Arquitectura objetivo

```
┌───────────────────────────────────────────────────────────────────┐
│                       Axon Source (.axon)                         │
│                                                                   │
│   stream: Stream<Bytes[pcm16, 16kHz]>    <-- Temporal Effect      │
│   @legal_basis(GDPR.Art6.B)              <-- Compile-time guard   │
│   @backpressure(DegradeQuality)          <-- Effect handler       │
│   flow transcribe(input: Trusted<AudioFrame>) -> ... { ... }      │
└───────────────────────────────┬───────────────────────────────────┘
                                ▼
        ┌───────────────────────────────────────────────┐
        │        axon-lang compiler (checker.rs)        │
        │  Refinement types  +  LegalBasis enforcement  │
        │  Stream<T> effect tracking  +  ReplayToken    │
        │  derivation at every effect site              │
        └───────────────────────────────┬───────────────┘
                                        ▼
        ┌───────────────────────────────────────────────┐
        │             axon-lang runtime                 │
        │                                               │
        │   ZeroCopyBuffer pool (Arc<[u8]> + slab)      │
        │   Stream<T> with backpressure policies        │
        │   PEM CognitiveState snapshot/restore         │
        │   OTS binary pipeline registry                │
        │   ReplayToken emission on every effect        │
        └───────────┬───────────────────────────┬───────┘
                    │                           │
           ┌────────▼─────────┐         ┌───────▼────────┐
           │  axon-rs (Rust)  │         │  PyO3 bindings │
           │  HTTP/WS drivers │         │  buffer protoc │
           │  HMAC/JWT/OAuth2 │         │  symbolic ptrs │
           │  verifiers       │         │  only          │
           └────────┬─────────┘         └───────┬────────┘
                    │                           │
                    └──────────┬────────────────┘
                               ▼
        ┌───────────────────────────────────────────────┐
        │         axon-enterprise v1.2.0                │
        │                                               │
        │  replay_tokens table (hash-chained to 10.g)   │
        │  cognitive_states table (envelope-encrypted)  │
        │  LegalBasis catalogue (compile-time + seed)   │
        │  Replay audit events                          │
        └───────────────────────────────────────────────┘
```

---

## 11.a — Temporal Algebraic Effects + Trust Types

**Estado:** ✅ Completo — **Depende de:** Fase 10 GA; no depende de otras 11.x

**Commits:**
- `363f845` feat(lang-11.a): closed Trust Catalogue + Stream<T> primitives
- `aa6f7a2` feat(compiler-11.a): refinement + stream checker + parity tests
- `<docs-commit>` docs(fase-11.a): STREAM_EFFECTS.md + TRUST_TYPES.md + living doc

**Entregado:**

- **Rust primitives (axon-rs)**:
  - `src/refinement.rs` — `TrustProof` enum (Hmac, JwtSig, OAuthCodeExchange, Ed25519) + `Trusted`/`Untrusted` type constructor recognition + refinement annotation parser. Catálogo CERRADO.
  - `src/stream_effect.rs` — `BackpressurePolicy` enum (DropOldest, DegradeQuality, PauseUpstream, Fail) + `Stream` type constructor + backpressure annotation parser. Sin política default — falla cerrado en compilación.
  - `src/trust_verifiers.rs` — impls runtime: HMAC-SHA256 (constant-time via `hmac::Mac::verify_slice`), Ed25519 (`verify_strict`), JWT delegando a 10.e, OAuth2 PKCE S256 via `reqwest`. Return uniforme: `VerifiedPayload`.
  - `src/stream_runtime.rs` — `Stream<T>` async channel con dispatch por política + `StreamMetrics` (counter per policy hit).
- **Python reference (axon/)**:
  - `runtime/trust.py` — mirror del catálogo + verifiers Python. `Trusted`/`Untrusted` como wrappers; `assert_trusted` para defensa en FFI boundaries.
  - `runtime/stream_primitive.py` — mirror de `Stream<T>` + 4 policies. Constructor enforcea "DegradeQuality requires degrader".
  - `compiler/refinement_check.py` — mirror de la pass del checker Rust.
- **Compiler extension (type_checker.rs)**:
  - `VALID_EFFECTS` gained `"stream"` + `"trust"`.
  - Tool-level: `stream` sin qualifier o con qualifier desconocido → error apuntando al catálogo completo. Idem para `trust`.
  - Flow-level: `Stream<T>` en signature requiere alcance a un tool con `stream:<policy>`; `Untrusted<T>` en parámetros requiere alcance a un tool con `trust:<proof>`. Walk recursivo por `If` (then_body/else_body) y `ForIn` (body).
- **Tests**:
  - `axon-rs/tests/fase_11a_refinement_and_stream.rs` — 13 integration tests (sintaxis Axon real validada contra examples/).
  - `tests/test_fase_11a_trust.py`, `test_fase_11a_stream.py`, `test_fase_11a_refinement_check.py` — 45 unit tests Python, todos pasando (2 skipped sin `cryptography` dep).
- **Docs**:
  - `docs/STREAM_EFFECTS.md` — operator guide + catálogo + runtime contract + metrics.
  - `docs/TRUST_TYPES.md` — operator guide + "trust IS NOT safety" disclaimer + error catalog.

**Decisiones cerradas:**

- **Syntax via composite effect string** (`stream:drop_oldest`, `trust:hmac`), no atributos `@backpressure(...)` — aprovecha el mecanismo `name:qualifier` que ya existía en el parser. Evita extender lexer/parser para esta sub-fase; la semántica es equivalente y el diagnóstico del checker igual de preciso.
- **Conservative flow-level reachability check** en vez de full taint-tracking dataflow — la aproximación captura el caso load-bearing "autor olvidó verificador" sin requerir pre-pass de dataflow. Propagación total queda como follow-up explícito cuando el AST gane nodos de atributo.
- **Catálogos cerrados con seed determinístico en Rust + Python**, mismo ordering de slugs. Parity test asegura que ambos catálogos son idénticos; agregar un verificador/política requiere parche sincronizado en ambos lados + security review.
- **Trust y Stream son ortogonales.** Un `Stream<Trusted<AudioFrame>>` es válido (y deseable); el checker propaga ambas constrains independientemente.
- **Ed25519 usa `verify_strict`**, no `verify()`. La distinción no es opcional — `verify()` acepta low-order points que permiten múltiples firmas válidas para el mismo mensaje.

**Open questions (none blocking — future 11.a follow-ups):**

- Refinement TypeExpr en AST vs composite effect string — cuando el AST gane annotation nodes, migrar a syntax más visible como `param: Trusted<T> via hmac` sin romper la semántica actual.
- Dataflow taint propagation sobre step outputs — hoy el checker ve la signature; falta propagar hasta que cada `.output` binding conozca su refinement status.
- Parity test `tests/parity/test_fase_11a_catalogue_parity.py` — listado en el plan, pero no implementado en este sub-fase; se agregará cuando haya más cambios cross-catalogue para amortizar el harness.

**Objetivo.** Extender el sistema de efectos de Axon con:

1. `Stream<T>` — efecto algebraico temporal de primera clase, con
   *backpressure semántica* expresada como handler obligatorio. No hay
   `Stream<T>` sin política de contrapresión declarada.
2. `Untrusted<T>` / `Trusted<T>` — refinement types que el checker
   propaga. Un `Untrusted<T>` solo se convierte en `Trusted<T>` vía un
   verificador registrado en el catálogo cerrado del compilador. Olvidar
   verificar = error de compilación.

### Archivos nuevos (axon-lang)

- `axon/compiler/refinement.rs` — algoritmo de propagación de refinement
  types; tabla `Refinement<T, Proof>` con `Proof ∈ {Hmac, JwtSig,
  OAuthCodeExchange, Ed25519}` (catálogo cerrado en 11.a).
- `axon/compiler/effects/stream.rs` — tipo efecto `Stream<T>` + inference
  de handler de backpressure requerido.
- `axon/compiler/checker.rs` — extensión: cualquier efecto que consuma
  `Untrusted<T>` debe probar que el payload fue refinado a `Trusted<T>`
  por un verificador del catálogo.
- `axon/runtime/effects/stream.rs` — implementación runtime: `Stream<T>`
  con 4 políticas (`DropOldest`, `DegradeQuality<fn>`, `PauseUpstream`,
  `Fail`) + observabilidad (métricas por política).
- `axon/runtime/effects/trust.rs` — runtime de los verificadores del
  catálogo; cada uno devuelve `Result<Trusted<T>, TrustError>`.
- `axon-rs/src/crypto/hmac.rs` — HMAC-SHA256 constant-time.
- `axon-rs/src/crypto/jwt.rs` — re-export del verifier ya existente en
  10.e, tipado como `Proof::JwtSig`.
- `axon-rs/src/crypto/oauth.rs` — PKCE S256 code exchange tipado como
  `Proof::OAuthCodeExchange`.

### Decisiones clave (propuestas — cerrar en kickoff)

- **Refinement representación:** newtype a nivel compilador, compilado
  fuera (zero-cost). No hay tag runtime — la garantía vive en el tipo.
- **Backpressure policy OBLIGATORIA:** ningún `Stream<T>` sin handler
  explícito; el default implícito (`Fail`) se rechaza para forzar
  decisión consciente en cada flujo.
- **Catálogo cerrado de verificadores en 11.a:** HMAC-SHA256, JWT
  signature (RS256/384/512), OAuth2 PKCE S256, Ed25519. Agregar nuevos
  requiere PR al compilador — impide que un dev escriba su propio
  `verify_hmac` con comparación no-constant-time.
- **Sintaxis propuesta:** `untrusted via hmac(key=env.HMAC_KEY)` como
  handler inline; equivale a `refine<Hmac>(payload, key)` del checker.

### Open questions

- [ ] ¿`Stream<T>` es un **effect** o un **type constructor con effect
      annotation**? Propongo **type constructor** para que se componga
      con refinement: `Stream<Trusted<AudioFrame>>` es el tipo que un
      flow de transcripción consume.
- [ ] ¿Backpressure policy puede delegarse a otra función? (ej:
      `DegradeQuality(fn resample)`) → sí, pero `fn` debe ser pura (sin
      efectos) para que el runtime pueda ejecutarla en el critical path.
- [ ] ¿Cómo expresar "verificador encadenado" (ej. valida HMAC primero,
      luego valida timestamp dentro del payload)? Propongo tuple:
      `Trusted<(HmacValid, FreshTimestamp)>`.

### Criterios de completitud

- [ ] Checker rechaza un programa que consume `Untrusted<T>` sin refinar.
- [ ] Checker rechaza un `Stream<T>` sin `@backpressure(...)` anotación.
- [ ] Runtime ejecuta los 4 handlers de backpressure bajo carga
      sintética (verificable con métricas Prometheus por política).
- [ ] HMAC verifier pasa test de constant-time (basada en timing
      differential < 5% entre mensajes de igual longitud).
- [ ] Tests: propiedad (hypothesis) — ningún camino del programa
      resuelve a `Trusted<T>` sin pasar por un verificador del catálogo.

---

## 11.b — Zero-Copy Multimodal Buffers

**Estado:** ✅ Completo — **Depende de:** 11.a (composable con `Stream<T>` + `Trusted<T>`)

**Commits:**
- `57844c9` feat(runtime-11.b): zero-copy multimodal buffers + ingest paths
- `c49bbee` test+docs(fase-11.b): buffers + ingest + `BUFFER_PROTOCOL.md`

**Entregado:**

- **Rust primitives (axon-rs):**
  - `src/buffer/mod.rs` — `ZeroCopyBuffer` (Arc<[u8]> + range + kind + tenant tag), `BufferMut` in-flight builder con freeze al closing boundary.
  - `src/buffer/kind.rs` — `BufferKind` registry INTERNO ABIERTO (no closed como 11.a); 14 seeded kinds (raw, pcm16, mulaw8, wav, mp3, opus, jpeg, png, webp, mp4, webm, pdf, json, csv); adopters registran domain-specific kinds at runtime.
  - `src/buffer/pool.rs` — Slab allocator: 4 KiB / 64 KiB / 1 MiB / 10 MiB + oversize direct path. Per-tenant soft-limit accounting + `soft_limit_exceeded_total` counter. Free-list cap 64 slabs/class.
  - `src/ingest/multipart.rs` — RFC 7578 subset streaming parser; feed(chunk) → Vec<MultipartEvent>. Content-Type → kind mapping; nested multipart rejected; configurable header/part size limits.
  - `src/ingest/ws_binary.rs` — WebSocket fragment stitcher; opcode 0x2 + 0x0 + FIN; orphan continuation + message-too-large diagnostics.
- **Python reference (axon/runtime/ffi/):**
  - `buffer.py` — `ZeroCopyBuffer` con `bytes` carrier + memoryview views (read-only); PEP 3118 `__buffer__` expuesto para NumPy/PyTorch/Pillow zero-copy; `BufferMut`; `BufferPool` con misma taxonomía de size classes + per-tenant accounting.
  - `symbolic_ptr.py` — `SymbolicPtr[T]` genérico; clone O(1); `weakref.finalize` decrementa refcount on drop. Fast-path para fan-out de consumers.
- **Tests:**
  - Rust integration: `axon-rs/tests/fase_11b_buffers_and_ingest.rs` — multipart E2E, WS fragmentation stitch, pool reuse bajo steady-state, oversize bypass, custom kinds, slice-of-slice, BufferMut.freeze con tenant.
  - Python: `tests/test_fase_11b_buffer.py` + `test_fase_11b_symbolic_ptr.py` — 30 tests pasando (interning, slice semantics, readonly memoryview, PEP 3118 exposure, freeze-once, pool classes, tenant soft-limit, refcount + weakref drop).
- **Docs:**
  - `docs/BUFFER_PROTOCOL.md` — operator guide con composition example `Stream<Trusted<Bytes[pcm16]>>` combinando 11.a + 11.b.

**Decisiones cerradas:**

- **BufferKind es OPEN registry** (vs closed de 11.a trust + backpressure). Los kinds son metadata de contenido, no un security boundary — registrar custom kinds no requiere security review.
- **Pool global-per-proceso con soft-limit per-tenant tracked**, no pool per-tenant. Una sola región de memoria; tenant accounting vive en metrics. Evita fragmentation por pool-per-tenant bajo adopters con 1000s de tenants.
- **SymbolicPtr[T] copiable** (via clone()) para permitir fan-out; alternativa move-only prevenía cross-consumer sharing que es el caso load-bearing.
- **memoryview readonly** enforced (PEP 3118 flag) — C extension que intenta mutar a través de la vista falla fast. Adopter que necesita mutar llama `as_bytes()` explícito para obtener copia owned.
- **PyO3 binding físico diferido a 11.b.1.** Python side usa `bytes` carrier + memoryview hoy; semantics de zero-copy aplican via memoryview, pero Rust-allocated storage aún no cruza FFI. Interfaz no cambia cuando lande; carrier sí.
- **Fase 11.b no define compile-time kind constraints** (`Bytes[pcm16] → Bytes[wav]`). El auto-wiring tipado va en 11.e (OTS Binary Pipeline Synthesis).

**Open questions deferred:**

- [ ] PyO3 wrapper around `axon::buffer::ZeroCopyBuffer` exposing Arc<[u8]> via Python buffer protocol — requiere maturin build en el release pipeline.
- [ ] Lockfree free list para el pool (hoy usa Mutex / threading.RLock). Performance follow-up; correctness ya está en su sitio.
- [ ] Buffer composition sin copy — concatenar two `ZeroCopyBuffer`s via reference en vez de memcpy. Útil pero out of scope para 11.b.

**Objetivo.** Bytes que entran por red (HTTP multipart, WS binary,
stdin file upload) aterrizan directamente en región de memoria Rust. La
capa Python manipula punteros simbólicos; los bytes NO cruzan FFI hasta
el consumer final (transcriptor, compressor, sink de archivo). Elimina
el cuello de botella FFI en audio/video en tiempo real.

### Archivos nuevos (axon-lang)

- `axon-rs/src/buffer/mod.rs` — `ZeroCopyBuffer` backed by `Arc<[u8]>`.
  Soporta slicing sin copia, refcount decide liberación.
- `axon-rs/src/buffer/pool.rs` — slab allocator en clases de tamaño
  (4KB, 64KB, 1MB, 10MB); recicla buffers entre requests para reducir
  fragmentación en workloads de audio continuo.
- `axon-rs/src/ingest/multipart.rs` — parser multipart que stream-ea
  cada field directamente a un `ZeroCopyBuffer`.
- `axon-rs/src/ingest/ws_binary.rs` — acumulador de frames binarios WS
  que deja el payload completo en un único buffer contiguo.
- `axon/runtime/ffi/buffer.py` — binding PyO3 via buffer protocol
  (`__buffer__`). Tipo Axon: `Bytes[kind]` donde `kind ∈ {raw, pcm16,
  mulaw8, jpeg, png, mp3, opus, pdf, ...}`.
- `axon/runtime/ffi/symbolic_ptr.py` — `SymbolicPtr[T]` — handle Python
  que referencia un `ZeroCopyBuffer` Rust sin materializar bytes.

### Decisiones clave (propuestas)

- **Ownership:** `Arc<[u8]>` para buffers consumidos (multi-reader
  seguro); `BytesMut` para buffers en acumulación. Transición one-way:
  `BytesMut::freeze() -> Arc<[u8]>` al cerrar ingest.
- **Pool:** slab por clase de tamaño; oversized buffers (> 10MB) van a
  allocation directa + warning en métricas (`axon_buffer_oversize_total`).
- **FFI:** buffer protocol (PEP 3118) — ya soportado por NumPy, PyTorch,
  Pillow. Zero-copy con torch.Tensor o np.ndarray sin serialización.
- **Vida del buffer:** atado al scope del flow; al salir del scope sin
  referencias activas, Arc refcount → 0 → memoria vuelve al pool.

### Open questions

- [ ] ¿`SymbolicPtr<T>` es copiable (implies Arc clone cheap) o move
      (ownership strict)? Propongo **copiable** para permitir fan-out
      del mismo buffer a múltiples consumers.
- [ ] ¿El pool es global-por-proceso o per-tenant? Global es más simple;
      per-tenant previene que un tenant con audio largo agote memoria
      afectando otros. Propongo **global con soft-limit per-tenant**
      tracked por métrica, degradación graceful cuando se excede.
- [ ] ¿Cómo se handle un buffer que un consumer Python mutó (ej.
      downsampling in-place)? Propongo **prohibir mutación**: si consumer
      necesita modificar, explicit copy. Enforce via buffer protocol
      `readonly=True` flag.

### Criterios de completitud

- [ ] Benchmark: ingest de 1GB audio μ-law a 8kHz → transcoder → sink
      mantiene throughput > 50MB/s con memoria RSS < 20MB adicional
      (zero-copy path validado).
- [ ] Test: `SymbolicPtr` pasa a NumPy + PyTorch sin copia (verificable
      comparando `id()` del buffer subyacente).
- [ ] Métricas: `axon_buffer_pool_hits_total`, `axon_buffer_pool_misses_total`,
      `axon_buffer_oversize_total`, `axon_buffer_live_bytes` por clase
      de tamaño.
- [ ] No regresión en Fase 10 — compilación y suite de tests de
      enterprise siguen verdes.

---

## 11.c — Deterministic Replay + Legal-Basis Typed Effects

**Estado:** ✅ Completo — **Depende de:** 11.a (refinement types),
10.g (audit hash chain), 10.l (compliance module).

**Commits (axon-lang):**
- `2b933a1` feat(lang-11.c): legal-basis closed catalog + ReplayToken primitives
- `b4e5bec` test+docs(fase-11.c): replay + legal-basis suite + `REPLAY_AND_LEGAL_BASIS.md`
- `f6f6208` feat(compiler-11.c): extend type_checker with sensitive + legal enforcement

**Commits (axon-enterprise):**
- `0db9b4f` feat(fase-11.c): replay module + migración 011_replay_tokens
- `903ad77` test(fase-11.c): ReplayService integration suite

**Entregado:**

- **Catálogo cerrado en Rust** (`axon-rs/src/legal_basis.rs`): 21 variantes — GDPR Art 6 (Consent, Contract, LegalObligation, VitalInterests, PublicTask, LegitimateInterests), GDPR Art 9 (ExplicitConsent, Employment, VitalInterests, NotForProfit, PublicData, LegalClaims, SubstantialPublicInterest, HealthcareProvision, PublicHealth, ArchivingResearch), CCPA.1798_100, SOX.404, HIPAA.164_502, GLBA.501b, PCI_DSS.v4_Req3. `LEGAL_BASIS_CATALOG` const slice paridad con `axon/compiler/legal_basis.py`.
- **ReplayToken primitives** (`axon-rs/src/replay_token/`): `token.rs` (canonical struct + SHA-256 hash derivation con separador `\x1e` compartido con 10.g), `log.rs` (ReplayLog async trait + InMemoryReplayLog), `executor.rs` (ReplayExecutor + EffectInvoker trait + ReplayMatch/ReplayMismatch outcomes).
- **Python mirror** (`axon/runtime/replay/`): byte-idéntica implementación de canonical hashing, ReplayTokenBuilder, InMemoryReplayLog, ReplayExecutor. Mismo wire format; tokens minted en cualquier lenguaje re-hashean igual.
- **Compiler extension** (`axon-rs/src/type_checker.rs`): `VALID_EFFECTS` gana `sensitive` + `legal`. Tool-level enforcement: `sensitive` requiere qualifier de categoría (abierta); `legal` requiere qualifier del catálogo CERRADO; un tool con `sensitive:<c>` sin `legal:<basis>` en el MISMO tool → error. Catálogo completo listado en el mensaje de error.
- **Enterprise persistence** (`axon_enterprise/replay/`): `ReplayTokenRecord` ORM (tenant-scoped + RLS + append-only triggers SQLSTATE 42501), `ReplayService` con `record()` que persiste + emite `replay:token_emitted` audit event en la misma transacción + verifica canonical hash integrity, `record_divergence`/`record_replay` para seguimiento forense. Alembic migration 011 crea tabla + cinco indexes + triggers + RLS policies.
- **Audit events nuevos**: `replay:token_emitted`, `replay:replayed`, `replay:divergence_detected`, `replay:legal_basis_missing`.
- **Tests**: 10 Rust integration tests + 33 Python unit tests (todos pasando) + 7 enterprise integration tests (cubren persistencia + audit anchoring + tamper detection + tenant scoping + ordenamiento cronológico + append-only trigger enforcement).
- **Docs** (`docs/REPLAY_AND_LEGAL_BASIS.md`): operator guide con tabla completa del catálogo, contrato compile-time, protocolo de re-ejecución, sección "why this is the regulated-vertical unlock" con mapping concreto SOX/HIPAA/GDPR auditor-question → machine-checkable answer.

**Decisiones cerradas:**

- **Catálogo cerrado con security review**: agregar una base requiere parche al compilador + firma del legal team en el PR. Extension no es un hot-path para adopters; evita diluting del catálogo con interpretaciones creativas.
- **Sintaxis via composite effect strings**: `sensitive:<category>, legal:<basis>` en vez de atributos dedicados — aprovecha el parser existente como 11.a. Open taxonomy para categorías (adopter-defined vertical domains), closed catalog para bases (regulatory boundary).
- **Error directo de compilación**, sin warning/transition period: precedente seteado por 11.a con `Untrusted<T>` sin refinar. Warnings son shortcuts que la regla de zero-shortcuts del proyecto rechaza.
- **Coherence enforcement at same-tool boundary**: un tool con `sensitive:<c>` MUST carry `legal:<b>` él mismo, no "en algún lugar del flow". Matches GDPR Art 6 "each processing activity has a lawful basis".
- **Canonical-JSON + RS `\x1e` separator compartido con 10.g**: ReplayTokens se anclan al audit chain sin traducción; cualquier helper que el chain verifier use ya funciona para replay.
- **Append-only trigger mirrors audit_events posture**: SQLSTATE 42501 en UPDATE/DELETE/TRUNCATE. Tampering de un replay token requiere subir a DBA-role + el chain verifier detecta divergencias a la siguiente verificación.

**Objetivo original (para referencia).** Cada efecto (`call_tool`,
`llm_infer`, `db_read`, `http_post`, `ws_send`) emite un `ReplayToken<
Effect, Inputs, Ts>` hash-encadenado al audit chain de Enterprise.
Efectos marcados `@sensitive(jurisdiction=...)` requieren un parámetro
compile-time `LegalBasis<>`; si falta, el programa **no compila**.
Cualquier flow puede re-ejecutarse desde un ReplayToken y producir
output bit-idéntico (modulo no-determinismo LLM, capturado en el token
vía temperature + seed).

Este es el diferenciador para Banca Corporativa, Fintech, LegalTech y
MedicalTech: el regulador reproduce cualquier decisión, y el compilador
garantiza que ningún efecto regulado se ejecutó sin base legal.

### Archivos nuevos (axon-lang)

- `axon/compiler/legal_basis.rs` — enum cerrado:
  `LegalBasis ∈ {GDPR::Art6(A|B|C|D|E|F), GDPR::Art9(A|B|...),
  CCPA::§1798_100, SOX::§404, HIPAA::§164_502, GLBA::§501B, PCI_DSS::v4_3}`.
  Extensión requiere PR + legal review.
- `axon/compiler/sensitive_effects.rs` — detecta atributos
  `@sensitive(jurisdiction=...)` en la firma del efecto + exige el
  parámetro `LegalBasis<variant>` en cada call-site.
- `axon/compiler/replay_derive.rs` — deriva automáticamente
  `ReplayToken` emission en cada effect call durante la fase de codegen.
- `axon/runtime/replay/token.rs` — `ReplayToken`:
  `{effect_name, inputs_hash (canonical JSON SHA-256), outputs_hash,
  model_version, temperature, seed, timestamp, nonce}`.
- `axon/runtime/replay/log.rs` — trait `ReplayLog` con impls:
  `LocalSqliteLog` (dev), `EnterpriseAuditLog` (prod — apuntada a 10.g).
- `axon/runtime/replay/executor.rs` — `replay_from(token) -> Output`
  que re-ejecuta un flow validando cada effect hit contra el token
  registrado; divergence emite `replay:divergence_detected`.

### Archivos nuevos (axon-enterprise)

- `axon_enterprise/replay/__init__.py` — exports del módulo.
- `axon_enterprise/replay/models.py` — ORM `ReplayTokenRecord`
  (tenant-scoped + RLS):
  `{token_id, tenant_id, flow_id, effect, inputs_hash_hex,
  outputs_hash_hex, model_version, legal_basis, created_at,
  audit_event_id (FK a audit_events)}`.
- `axon_enterprise/replay/service.py` — `ReplayService.record(token)`
  + `replay(token_id) -> Output`. Usa `AuditService` de 10.g para
  anclar cada emisión al hash chain.
- `axon_enterprise/replay/legal_basis.py` — espejo Python del
  catálogo Rust, seedeado por migración 011.
- `alembic/versions/20260501_0000_011_replay_tokens.py` — crea
  `axon_control.replay_tokens` + índices por `(tenant_id, flow_id,
  created_at)` + FK a `audit_events`.
- `axon_enterprise/audit/events.py` — nuevos tipos:
  `replay:token_emitted`, `replay:replayed`, `replay:divergence_detected`,
  `replay:legal_basis_missing` (este último es compile-time; pero se
  emite en tests CI cuando un atacante intenta bypass).

### Decisiones clave (propuestas)

- **LegalBasis catalogue CERRADO.** Extensión = PR al compilador + legal
  review firmado. Starts: GDPR, CCPA, SOX, HIPAA, GLBA, PCI-DSS.
- **ReplayToken hash incluye `model_version`.** Cambio de modelo → nuevo
  token; replay con modelo distinto requiere `@force_replay(new_model)`
  que emite `replay:model_forced` en audit chain.
- **No-determinismo LLM:** el token captura `temperature`, `top_p`,
  `seed`, `top_k`. Providers que no soportan seeded sampling se marcan
  `@non_replayable` en el tool descriptor; compilador rechaza su uso en
  un contexto `@sensitive`.
- **Canonical JSON para `inputs_hash`:** usar el mismo canonicalizador
  que 10.g audit chain (Record Separator `\x1e`) — input idéntico
  produce hash idéntico Python↔Rust.
- **Legal-basis inference:** si el llamante hereda de un scope que ya
  declaró la base legal (`with legal_basis(GDPR.Art6.B): ...`), los
  efectos sensibles dentro no la repiten. Reduce ruido sintáctico sin
  debilitar la garantía.

### Open questions

- [ ] ¿El `ReplayLog` local en dev debe espejar el schema de enterprise
      o ser simpler? Propongo simpler (SQLite + schema mínimo) pero con
      migración 1-a-1 automática al primer push a enterprise.
- [ ] ¿Qué tan profundo replay-ear? Un flow que llama a 100 tools →
      replay-ea los 100 o solo el output final? Propongo **replay
      inductivo**: cada effect hit valida contra su token; el primer
      divergence marca el flow como "no-replayable from here" y emite
      el evento de auditoría con el punto exacto.
- [ ] ¿Replay sobre datos que YA fueron erasured (10.l)? Si los inputs
      del token incluían PII que se borró, el replay no encontrará la
      fuente. Propongo **token carga el hash del input, no el input**;
      replay con PII borrada emite `replay:input_unavailable` y deja el
      token como evidencia de que se intentó.

### Criterios de completitud

- [ ] Programa sin `LegalBasis<>` en efecto `@sensitive` → error de
      compilación con mensaje accionable.
- [ ] Replay de un flow con LLM fijo (seed + temperature) produce
      bytes-idénticos output vs ejecución original.
- [ ] Replay con modelo cambiado sin `@force_replay` rechaza con
      mensaje explícito + emite `replay:model_mismatch`.
- [ ] Hash chain de enterprise se mantiene consistente después de 1M
      ReplayTokens emitidos (verificado con `verify_chain`).
- [ ] Integración con migración 011 — schema desplegable desde cero y
      contra una instalación 10.l existente sin romper tokens previos.

---

## 11.d — Stateful PEM sobre WebSocket

**Estado:** ✅ Completo — **Depende de:** 11.a (`Stream<T>` framing),
10.b (envelope encryption), 10.g (audit chain), 10.l (residency + SAR + erasure), 11.c (ReplayToken flow_id correlation).

**Commits (axon-lang):**
- `7e9e421` feat(lang-11.d): stateful PEM — CognitiveState + ContinuityToken + backend
- `86d23e2` test+docs(fase-11.d): PEM suite + `STATEFUL_PEM.md`

**Commits (axon-enterprise):**
- `5033569` feat(fase-11.d): cognitive_states module + migración 012
- `79607d2` feat(fase-11.d): integrate cognitive_states with 10.l SAR + erasure + tests

**Entregado:**

- **Rust primitives (axon-rs/src/pem/):**
  - `state.rs` — `CognitiveState` + `FixedPoint` Q32.32 quantización (precisión ≈ 2.3e-10, error representable menor que rounding del propio float). Density matrix bit-identical across N reconnects — test `density_matrix_bit_identical_after_three_reconnects` lo verifica.
  - `continuity_token.rs` — `ContinuityTokenSigner` con HMAC-SHA256 + `subtle::ConstantTimeEq`. Rechaza forged (wrong key), expired, tampered session_id. Base64url wire format.
  - `backend.rs` — `PersistenceBackend` async trait + `InMemoryBackend` impl con `PersistenceError::{NotFound, Expired, Backend}`.
- **Python mirror (axon/runtime/pem/):** byte-idéntico wire format + `hmac.compare_digest` constant-time; misma API Rust→Python para cross-language interop.
- **axon-enterprise (`axon_enterprise/cognitive_states/`):**
  - `models.py` — `CognitiveStateSnapshot` ORM tenant-scoped + RLS, `state_ciphertext` LargeBinary + metadata indexable sin descifrar.
  - `service.py` — persist/restore/evict con envelope encryption (AAD bindings a `(tenant_id, session_id, flow_id, subject_user_id)`); cross-row ciphertext swap falla AEAD tag ANTES de producir plaintext. Todos los boundary crossings emiten audit events.
  - `worker.py` — `CognitiveStateEvictionWorker` siguiendo el patrón del ComplianceWorker de 10.l.
- **Alembic migration 012_cognitive_states.py** — tabla + 5 B-tree indexes + RLS policies. NO append-only trigger porque snapshots SON mutables (rewrite in-place en cada persist; DELETE en eviction).
- **Integración con 10.l compliance:**
  - `SarExporter._collect_tables` incluye `cognitive_states.jsonl` (metadata only; payload `[redacted]`).
  - `ErasureService.anonymize` DELETE-a cada snapshot del subject (cryptoshred para KMS envelope; row-delete para local).
- **Nuevos audit events**: `pem:state_persisted`, `pem:state_restored`, `pem:state_evicted`, `pem:reconnect_denied`.
- **Tests**: 10 Rust integration + 21 Python unit (todos pasando) + 10 enterprise integration (incluye ciphertext_bound_to_row_aad que valida AEAD row-binding).
- **Docs**: `docs/STATEFUL_PEM.md` con Q32.32 rationale, continuity token handshake, composition con 10.b/10.g/10.l + 11.a/11.b/11.c.

**Decisiones cerradas:**

- **Q32.32 fixed-point** para floats del density_matrix en vez de IEEE-754 serialización. Precisión ≈ 2.3e-10 es suficiente para belief states; la estabilidad bit-wise across reconnects es no negociable.
- **JSON key-sorted canónico** como wire format (no MessagePack). Consistente con 10.g + 11.c canonicaliser. MessagePack queda como optimización futura si profiling justifica.
- **AAD de envelope bindea `(tenant_id, session_id, flow_id, subject_user_id)`**. Cross-row ciphertext swap falla AEAD tag ANTES de producir plaintext — el test `ciphertext_bound_to_row_aad` lo asegura.
- **Snapshots SON mutables** (no append-only como audit/replay). TTL requires DELETE; append-only trigger lo bloquearía. El audit chain captura persist/restore/evict events así el lifecycle queda en el chain sin que la tabla lo sea.
- **ContinuityToken HMAC-signed** (no JWT). Matiz: necesitamos algo short-lived + no requiere parseo de claims — HMAC binario sobre 3 campos es más simple y rotable independiente del JWT signing key de 10.e.
- **Eviction worker vs Postgres TTL** — worker dedicado porque queremos el cryptoshred operation visible en el audit chain (pem:state_evicted emitido por cada DELETE), no un background cleanup silencioso.
- **SAR incluye metadata only**, no ciphertext. El recipiente del SAR no tiene la envelope key; entregar ciphertext sin camino de descifrado es distracción, no disclosure.

**Objetivo.** El motor PEM (Psychological Epistemic Modeling) persiste
su estado cognitivo (density matrix, belief state, short-term memory)
a través de desconexiones del WebSocket. Reconexión retoma el hilo
exacto sin reiniciar. Acopla el lifecycle del WebSocket al lifecycle
del estado cognitivo de un agente.

### Archivos nuevos (axon-lang)

- `axon/runtime/pem/state.rs` — `CognitiveState` serializable via
  canonical MessagePack (floats → fixed-point para prevenir drift entre
  reconnect-es).
- `axon/runtime/transport/ws.rs` — hooks `on_disconnect` + `on_reconnect`
  con política configurable por flow: `@reconnect_window(minutes=N)`.
- `axon/runtime/persistence/backend.rs` — trait `PersistenceBackend`
  con impls `InMemoryBackend` (test), `RedisBackend`, `PostgresBackend`.
- `axon/runtime/pem/continuity_token.rs` — token de reconexión emitido
  al cliente al primer `on_disconnect`; cliente lo presenta en
  `on_reconnect` para probar continuidad de identidad.

### Archivos nuevos (axon-enterprise)

- `axon_enterprise/cognitive_states/__init__.py` — módulo.
- `axon_enterprise/cognitive_states/models.py` — ORM
  `CognitiveStateSnapshot` tenant-scoped + RLS, state encryptado via
  envelope (10.b) porque puede contener PII del usuario.
- `axon_enterprise/cognitive_states/service.py` — `persist` + `restore`
  + `evict_expired` (worker-driven).
- `alembic/versions/20260515_0000_012_cognitive_states.py` — tabla +
  TTL index.
- `axon_enterprise/compliance/residency.py` — extensión: el middleware
  de residencia de 10.l también chequea que el `CognitiveState` se
  rehidrata desde el mismo region slug que lo snapshot-eó.

### Decisiones clave (propuestas)

- **Reconnect window:** default 15 min, anotable por flow con
  `@reconnect_window(minutes=N)`. Más allá → estado se evictea; reconnect
  tarde aterriza en un nuevo estado "fresh start" con log del estado
  previo para debug humano.
- **Auth on reconnect:** cliente presenta session JWT del handshake
  original + continuity_token. Si JWT revocado (10.e `jti` blacklist)
  → estado se preserva para auditoría, NO se entrega al cliente.
- **Serialización canónica de floats:** fixed-point Q32.32; previene
  drift por float-IEEE round-trip en Redis/Postgres.
- **Eviction:** worker dedicado (siguiendo el patrón del
  `ComplianceWorker` de 10.l) poll-ea estados expirados y los borra
  vía envelope-key rotation (cryptoshred).

### Open questions

- [ ] ¿El CognitiveState incluye inputs del usuario literales? Si sí,
      se vuelve PII y right-to-erasure de 10.l debe incluir esta tabla.
      Propongo **sí, incluye** + la tabla está en el `SarExporter` de
      10.l + el `ErasureService` la borra.
- [ ] ¿Persistir el density matrix completo o un hash + regenerar?
      Persist completo = más memoria; hash = pierde precisión en
      reconnect. Propongo **persistir completo** hasta que mediciones
      reales justifiquen compresión.
- [ ] ¿La migración 012 va en axon-enterprise o en un nuevo módulo
      separado? Propongo **axon-enterprise** — reusa RLS, envelope,
      compliance ya existentes.

### Criterios de completitud

- [ ] Test integración: cliente abre WS → envía 10 frames de audio →
      desconecta → reconecta → continua exactamente donde quedó (verifica
      density matrix idéntica a pre-disconnect).
- [ ] Reconnect con JWT revocado NO entrega el estado al cliente pero
      lo deja visible al Admin API para debug.
- [ ] Estado expira después de `@reconnect_window` configurado — test
      con window=60s valida que a los 65s el estado está cryptoshreded.
- [ ] `SarExporter` de 10.l incluye `cognitive_states.jsonl` cuando
      el subject tiene estados activos.

---

## 11.e — OTS Binary Pipeline Synthesis

**Estado:** ✅ Completo — **Depende de:** 11.a (`Bytes[kind]`),
11.b (zero-copy buffers), 11.c (LegalBasis para HIPAA+ffmpeg gate).

**Commits (axon-lang):**
- `e50ca4a` feat(runtime-11.e): OTS binary pipeline synthesis
- `91fb237` feat+test+docs(fase-11.e): checker ots rules + HIPAA reject + suite + docs

**Entregado:**

- **Rust primitives (axon-rs/src/ots/):**
  - `pipeline.rs` — `Transformer` trait (source_kind, sink_kind, backend, cost_hint, transform), `TransformerRegistry` con Dijkstra path search sobre el directed kind graph, `Pipeline` ejecutable con per-step kind invariant checks, `TransformerBackend {Native | Subprocess}`, `OtsError {NoPath, TransformFailed, KindMismatch}`.
  - `native/mulaw.rs` — μ-law ↔ PCM16 per ITU-T G.711, pure arithmetic (stored-vs-logical byte convention documentada; stored 0x80 → +32124 es correcto).
  - `native/resample.rs` — linear resampler para PCM16 con kind tags `pcm16_<rate>k`; ladder 8k↔16k↔48k seeded.
  - `subprocess/ffmpeg.rs` — `is_ffmpeg_available()` probe one-time, `FfmpegPool` TTL-bounded warm cache (60s default), `FfmpegTransformer` genérico. Absence de ffmpeg non-fatal; flows que la necesitan fallan en pipeline synthesis con `NoPath`, no crashean.
  - `mod.rs` — `global_registry()` seeded; `OTS_BACKEND_CATALOG = ["native", "ffmpeg"]` cerrado.
- **Python mirror (axon/runtime/ots/):** misma Dijkstra registry + native mulaw + native resample + misma byte output en reference vectors (paridad garantizada).
- **Compiler extension:**
  - `ots:transform:<from>:<to>` qualifier — open taxonomy para kinds, validation de no-empty from + to.
  - `ots:backend:<native|ffmpeg>` qualifier — closed catalogue.
  - **HIPAA+ffmpeg rejection rule** — un tool con `legal:HIPAA.*` + `ots:backend:ffmpeg` falla compilación. Mismo posture cerrado que las reglas de 11.a/11.c. GDPR+ffmpeg explicitamente permitido (no infantilizar a adopters no-healthcare).
- **Tests:** 11 Rust integration tests (incluye HIPAA-blocked + GDPR-ok + qualifier validation + end-to-end execute) + 20 Python unit tests (todos pasando; G.711 reference vectors alineados con stored-vs-logical byte convention).
- **Docs:** `docs/OTS_BINARY_PIPELINES.md` con Transformer API, built-in table, kind-tag convention, ffmpeg wrapper usage, checker rules, composition con 11.a/11.b/11.c/11.d.

**Decisiones cerradas:**

- Registry **at startup only** (no hot-load) — un transformer apareciendo mid-flight rompe auditability.
- ffmpeg absence **non-fatal** — falla en pipeline synthesis con `NoPath`, no en process startup. Adopters con paths nativos funcionan sin ffmpeg instalado.
- Pool con TTL 60s — primer call paga el spawn, subsequent calls within TTL reusan. Spawn-per-call hoy; pipe-in worker es follow-up.
- Kind convention `pcm16_<rate>k` encodes byte-layout + rate en un solo tag — permite componer transcode + resample como edges independientes del graph.
- **HIPAA rule targeted, no blanket** — GDPR / CCPA / SOX / GLBA / PCI-DSS NO bloquean ffmpeg. Solo HIPAA dada su especificidad sobre el boundary entre BAA-covered y no-covered systems.
- μ-law decoder sigue G.711 stored-vs-logical convention (stored byte es el logical byte con todos los bits invertidos). Reference vectors documentados inline en el test para prevenir regresiones por confusión.

**Objetivo.** Ontological Tool Synthesis (OTS) extiende de descubrir
APIs a descubrir transformaciones de streams binarios. Cuando un flow
declara un consumer que requiere `Bytes[kind=pcm16, rate=16000]` pero
el producer emite `Bytes[kind=mulaw, rate=8000]`, el compilador +
runtime descubren y encadenan un transcoder automáticamente — tipado,
zero-copy donde sea posible, cacheado entre requests.

### Archivos nuevos (axon-lang)

- `axon/runtime/ots/pipeline.rs` — registry de transformaciones
  conocidas: `(Bytes[A], Bytes[B]) -> fn`. Inferencia de shortest-path
  entre dos kinds usando Dijkstra sobre el grafo de transformaciones.
- `axon/runtime/ots/native/mulaw.rs` — transcoder Rust-nativo μ-law↔PCM.
- `axon/runtime/ots/native/resample.rs` — resample lineal (8k→16k,
  16k→48k) sin dependencias externas.
- `axon/runtime/ots/subprocess/ffmpeg.rs` — wrapper que spawns ffmpeg
  como subprocess cuando no hay transcoder nativo; sandbox via resource
  limits del SO.
- `axon/compiler/pipeline_derive.rs` — el checker detecta mismatch de
  `Bytes[kind_a] → Bytes[kind_b]` y emite un wire-up implícito si
  existe path; error si no.

### Decisiones clave (propuestas)

- **ffmpeg disponibilidad:** detectado al startup; ausencia emite
  `ots:capability_degraded` warning pero no es fatal si los transcoders
  nativos cubren el pipeline requerido.
- **Native-first policy:** el runtime prefiere nativo sobre subprocess
  cuando ambos existen (latencia + footprint predictable).
- **Cache:** pipelines idénticos (misma source/sink kind + misma
  config) reusan instancia warm — reduce overhead de spawning en
  audio streams continuos.
- **Sandbox ffmpeg:** subprocess bajo usuario dedicado + ulimits; en
  Kubernetes, container separado con `readOnlyRootFilesystem`. Detalles
  operacionales en 11.f security audit.
- **Tipado:** `auto_pipeline` es un efecto, no una síntesis puramente
  compile-time, porque el path óptimo puede cambiar según availability.
  El checker verifica que AL MENOS UN path existe; el runtime escoge
  concreto.

### Open questions

- [ ] ¿Permitir a usuarios registrar transformaciones custom? Si sí,
      corren el riesgo de "mi transcoder que perdió precisión". Propongo
      **sí, pero via trait Rust** — no scripts arbitrarios. Custom
      transformers viven en crates separados + se registran al startup.
- [ ] ¿Qué hacer si múltiples paths equivalentes existen? (ej: nativo
      rápido pero lossy, ffmpeg lento pero lossless). Propongo anotación
      `@prefer(Quality | Speed | Balance)` en el consumer; default
      `Balance`.
- [ ] ¿ffmpeg como subprocess es aceptable en contextos regulated
      (HIPAA)? Data cruza el boundary de proceso. Propongo
      **documentar como incompatible con `LegalBasis<HIPAA>`** hasta
      que quede todo-nativo; el checker rechaza el combo.

### Criterios de completitud

- [ ] Flow con mismatch μ-law 8kHz → PCM 16kHz compila y corre sin
      que el autor del flow escriba una sola línea de transcoding.
- [ ] Benchmark: pipeline nativo μ-law → PCM sostiene 10× real-time
      para audio 16kHz mono en un core.
- [ ] ffmpeg fallback probado contra H.264 → imagenes JPEG frames
      (codec que no está nativamente en 11.e).
- [ ] OTS emite `ots:pipeline_synthesised` audit event con source kind,
      sink kind, path descubierto, native_or_subprocess.

---

## 11.f — Integration Testing + Security Audit

**Estado:** ✅ Completo — **Depende de:** 11.a–11.e completos.

**Commits (axon-lang):**
- `f370eeb` test(fase-11.f): cross-phase integration + adversarial security suite
- `240a7e8` docs+load(fase-11.f): k6 SLO gates + threat model + GA audit

**Entregado:**

- **Cross-phase integration tests (Rust + Python)**:
  - `axon-rs/tests/fase_11f_cross_phase_integration.rs` — end-to-end pipeline combinando HMAC verify (11.a) + ZeroCopyBuffer con tenant tag (11.b) + OTS mulaw8→pcm16 (11.e) + Stream con drop_oldest (11.a) + ReplayToken (11.c) + CognitiveState Q32.32 (11.d) + ContinuityToken reconnect (11.d). Compose is load-bearing.
  - `tests/test_fase_11f_cross_phase.py` — 14 tests Python pasando; mismo composition surface.
- **Adversarial security tests**:
  - `axon-rs/tests/fase_11f_security_adversarial.rs` — 14 tests, uno por cada threat en el threat model (T-11-01 replay poisoning, T-11-02 legal-basis bypass, T-11-03 HIPAA boundary breach, T-11-04 continuity-token phishing, T-11-05 buffer isolation bleed, T-11-06 trust-catalogue drift, T-11-07 backpressure erasure).
- **k6 load suites** (`tests/load_fase_11/`):
  - `k6_ws_audio_stream.js` — WebSocket audio p95 < 300ms / p99 < 500ms RTT.
  - `k6_replay_emission.js` — ReplayToken emission p99 < 2ms.
  - `k6_ots_synthesis.js` — cold p99 < 10ms / cached p99 < 0.1ms.
  - `k6_pem_snapshot.js` — persist + restore p99 < 50ms para estados ≤ 64 KiB.
- **Docs nuevos**:
  - `docs/THREAT_MODEL_FASE_11.md` — STRIDE completo (Spoofing / Tampering / Repudiation / Info Disclosure / DoS / EoP) + **5 AI/ML-specific threats**: T-ML-01 Model-swap replay, T-ML-02 Prompt injection mid-replay, T-ML-03 Buffer exhaustion via SymbolicPtr, T-ML-04 Continuity-token phishing, T-ML-05 HIPAA boundary breach. Cada threat con mitigation + residual risk + test que la defiende.
  - `docs/SECURITY_AUDIT_v1_2_0.md` — GA sign-off gate: gates automatizados (cargo test, pytest, clippy, ruff, mypy, cargo audit, pip-audit, 4 k6 scripts), invariantes de código por sub-fase, controles operacionales, non-automatable review items, **external pentest PRE-GA obligatorio**, SLO thresholds enforced, known deviations, release command.

**Decisiones cerradas:**

- **Pentest externo PRE-GA para v1.2.0** (NO diferido como v1.1.0) — el attack surface nuevo (FFI buffers, ffmpeg subprocess, WebSocket stateful, LLM replay, LegalBasis typed effects) justifica auditoría externa antes del marketing.
- **Cross-phase regression harness**: tests Rust + Python compuestos por sub-fase se ejecutan en el mismo `cargo test --all` + `pytest tests/` workflow. No runner dedicado — reusamos lo que ya hay.
- **Threat model STRIDE + 5 AI/ML-specific** — cada uno con test específico. Model-swap replay resuelto via `model_version` en canonical hash; prompt injection resuelto via canonical-JSON end-to-end hash; buffer exhaustion via Arc refcount + pool free-list cap; continuity-token phishing via HMAC constant-time + TTL + key rotation; HIPAA boundary via compile-time rejection.
- **SLO thresholds específicos** (en k6): WebSocket audio end-to-end p99 < 500ms; ReplayToken emission < 2ms; OTS synthesis cold < 10ms / cached < 0.1ms; PEM snapshot+restore < 50ms. Relaxación = breaking-change release note.
- **Known deviations documentadas**: Q32.32 precisión ≈ 2.3e-10, Dijkstra cold path O(V log V), ffmpeg spawn-per-call sin pipe-in worker. Todas accepted con justificación.

### Archivos nuevos (axon-lang + axon-enterprise)

- `tests/integration/fase_11/test_full_pipeline.py` — flow realista
  (audio WS → transcoder OTS → LLM → ReplayToken → respuesta WS) con
  reconnect a mitad del stream.
- `tests/security/fase_11/test_replay_poisoning.py` — atacante intenta
  inyectar ReplayTokens falsos; verificación via audit chain los detecta.
- `tests/security/fase_11/test_legal_basis_bypass.py` — variaciones del
  compilador que intentan esquivar `@sensitive`; todas fallan.
- `tests/security/fase_11/test_buffer_isolation.py` — tenant A no puede
  alcanzar buffers emitidos por tenant B vía SymbolicPtr.
- `tests/security/fase_11/test_ws_reconnect_auth.py` — reconnect con
  JWT revocado, JWT de otro tenant, continuity_token forjado.
- `tests/security/fase_11/test_ffmpeg_sandbox.py` — fuzz inputs al
  subprocess ffmpeg; verificar que no crashea ni escapa.
- `docs/THREAT_MODEL.md` — extensión con sección Fase 11 (STRIDE sobre
  las 5 sub-fases).
- `docs/SECURITY_AUDIT.md` — extensión con gates de Fase 11.
- `tests/load/k6_audio_stream.js` — stress test: 100 WebSocket audio
  streams concurrentes a 16kHz, p99 latency < 500ms end-to-end.

### Decisiones clave (propuestas)

- **Pentest externo es pre-requisito para tag v1.2.0.** Fase 10 permitió
  pentest diferido a v1.1.1; Fase 11 introduce ataque surface nuevo
  (FFI, subprocess, WebSocket stateful) que justifica pentest previo.
- **SLO thresholds adicionales:**
  - WebSocket audio frame p99 end-to-end < 500ms
  - Zero-copy buffer overhead < 1% (memcpy-free path verificado)
  - ReplayToken emission adds < 2ms a cualquier effect
  - OTS pipeline synthesis < 10ms at cold, < 0.1ms at cached
  - CognitiveState snapshot + restore < 50ms para estado de hasta 64KB
- **Threat model:** STRIDE + categorías nuevas específicas de AI/MLS:
  *model swap attack* (replay con modelo distinto), *prompt injection
  via Trusted<>* (payload validado por HMAC pero con contenido
  malicioso — Trusted no significa safe), *buffer exhaustion DoS*.

### Criterios de completitud

- [ ] Todos los gates automatizados verdes (unit, integration, security,
      hypothesis, load, lint, pip-audit).
- [ ] Pentest externo completado con report sin findings críticos.
- [ ] Cross-phase interop tests verdes (flow que usa las 5 primitivas
      de 11.a–11.e simultáneamente).
- [ ] `THREAT_MODEL.md` y `SECURITY_AUDIT.md` extendidos + firmados por
      engineering lead.
- [ ] Tag `v1.2.0` disparado en ambos repos (axon-lang y axon-enterprise)
      con release notes consolidadas.

---

## Log de decisiones transversales

Decisiones cerradas al arrancar el plan (2026-04-22) — revisables pero
cada cambio requiere entrada en este log con justificación.

- **Target conjunto v1.2.0 en ambos repos.** Las primitivas de lenguaje
  (`axon-lang`) y la persistencia de replay/cognitive state
  (`axon-enterprise`) co-evolucionan; no tiene sentido disociar releases.
- **Regla de pureza activa.** Axon-lang sigue adopter-agnostic. Ninguna
  mención de Whisper, Stripe, Kivi, o clientes específicos en código o
  docstrings de axon-lang. Este plan vive en axxon-constructor porque
  coordina ambos.
- **Zero shortcuts.** Ninguna sub-fase marca "completado" con
  `@TODO`/`# por ahora` sin su contraparte production-ready. Regla de
  memoria del usuario.
- **Dual remote strategy.** Commits a axon-lang van a `origin` (público)
  + `enterprise` (privado) vía `push-smart.sh`. Commits a
  axon-enterprise solo a `origin` (privado).
- **LegalBasis es un catálogo CERRADO.** Extender requiere PR al
  compilador + legal review firmado en el doc de decisiones del PR.
- **Canonical JSON shared.** Replay hash + audit chain hash usan el
  mismo canonicalizador (Record Separator `\x1e`). Cambio requiere
  migración explícita.
- **Pentest externo pre-GA para v1.2.0** (a diferencia de v1.1.0 donde
  se difirió). El attack surface nuevo de Fase 11 (FFI, subprocess, WS
  stateful) lo justifica.

---

## Sesión actual — estado vivo

**Última actualización:** 2026-04-22

**Próxima sesión — pickup point:** **Fase 11 COMPLETA.** GA `v1.2.0` en
ambos repos (axon-lang + axon-enterprise) listo para tag una vez el
checklist de `docs/SECURITY_AUDIT_v1_2_0.md` esté verde — incluye el
pentest externo PRE-GA obligatorio.

**Decisiones cerradas en esta sesión (11.f):**
- **Pentest externo PRE-GA** para v1.2.0 (NO diferido como v1.1.0). El attack surface nuevo (FFI buffers, ffmpeg subprocess, WebSocket stateful, LLM replay, LegalBasis typed effects) justifica auditoría externa antes de marketing.
- Cross-phase regression usa `cargo test --all` + `pytest tests/` existentes (no runner dedicado). Más commits, menos infra.
- Threat model = STRIDE + **5 AI/ML-specific threats** (T-ML-01..T-ML-05). Cada uno con mitigation + residual risk + test que la defiende.
- SLO thresholds in k6: WS audio p99 < 500ms, ReplayToken emission p99 < 2ms, OTS synth cold p99 < 10ms / cached < 0.1ms, PEM snapshot+restore p99 < 50ms. Relaxation requires breaking-change release note.
- Known deviations aceptadas: Q32.32 precisión ≈ 2.3e-10, Dijkstra cold path O(V log V), ffmpeg spawn-per-call. Todas con justification documented.

**Cierre del plan Fase 11 — Neuro-Symbolic Micro-OS:**
- [x] 11.a Temporal Algebraic Effects + Trust Types
- [x] 11.b Zero-Copy Multimodal Buffers
- [x] 11.c Deterministic Replay + Legal-Basis Typed Effects
- [x] 11.d Stateful PEM over WebSocket
- [x] 11.e OTS Binary Pipeline Synthesis
- [x] 11.f Integration Testing + Security Audit

**Sesión abierta en:**
- Plan vivo: `axxon-constructor:docs/fase_11_neuro_symbolic_axon.md`
- Commits axon-lang pushed a `origin`: `363f845`, `aa6f7a2`, `495bc34` (11.a); `57844c9`, `c49bbee`, `95df120` (11.b); `2b933a1`, `b4e5bec`, `f6f6208`, `b9d1926` (11.c); `7e9e421`, `86d23e2`, `afc2172` (11.d); `e50ca4a`, `91fb237`, `87cddeb` (11.e); `f370eeb`, `240a7e8` (11.f).
- Commits axon-enterprise pushed a `origin`: `0db9b4f`, `903ad77` (11.c); `5033569`, `79607d2` (11.d).
- Tag `v1.2.0` pendiente de sign-off por engineering lead + external pentest per `docs/SECURITY_AUDIT_v1_2_0.md`.

---

## Routing Git para este plan

### axon-lang (primitivas, compiler, runtime, axon-rs)

Commits en `axon-lang`, pusheados a ambos remotes:

```bash
cd axon-lang/
git push origin master && git push enterprise master
```

Prefijos de commit:
- `feat(lang-11.a): ...` — primitivas del lenguaje (effects, types)
- `feat(runtime-11.b): ...` — runtime (zero-copy, OTS)
- `feat(compiler-11.c): ...` — extensión del checker

### axon-enterprise (replay service, cognitive states, LegalBasis seed)

Commits en `axon-enterprise`, solo a origin:

```bash
cd axon-enterprise/
git push origin master
git tag v1.2.0-alpha.X && git push origin v1.2.0-alpha.X   # alpha per sub-fase
git tag v1.2.0 && git push origin v1.2.0                   # GA al terminar 11.f
```

Prefijo: `feat(fase-11.X): ...` donde X es la sub-fase. Tag `v1.2.0*`
dispara el release workflow (Fase 10 ya lo tiene wired) → ECR.

### Coordinación cross-repo

Cuando un commit en axon-lang requiere un cambio corresponding en
axon-enterprise (típico en 11.c: nueva primitiva ReplayToken → migración
011 con nuevo schema), ambos commits van en el mismo PR/sesión con
mensaje que referencia al hermano. Release notes consolidadas en el tag
v1.2.0 listan commits de ambos repos.
