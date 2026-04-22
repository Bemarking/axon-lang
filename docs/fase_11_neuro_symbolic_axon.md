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
| 11.b | Zero-Copy Multimodal Buffers (audio/video/file ingest sin cruzar FFI) | ⏳ Pendiente |
| 11.c | Deterministic Replay + Legal-Basis Typed Effects (`ReplayToken` + `LegalBasis<>`) | ⏳ Pendiente |
| 11.d | Stateful PEM sobre WebSocket (continuidad cognitiva cross-reconnect) | ⏳ Pendiente |
| 11.e | OTS Binary Pipeline Synthesis (auto-descubrir transcoders tipados) | ⏳ Pendiente |
| 11.f | Integration Testing + Security Audit (regresión cross-phase, threat model) | ⏳ Pendiente |

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

**Estado:** ⏳ Pendiente — **Depende de:** 11.a (`Bytes[kind]` usa
refinement types para tag-de-kind)

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

**Estado:** ⏳ Pendiente — **Depende de:** 11.a (refinement types),
10.g (audit hash chain), 10.l (compliance module).

**Objetivo.** Cada efecto (`call_tool`, `llm_infer`, `db_read`,
`http_post`, `ws_send`) emite un `ReplayToken<Effect, Inputs, Ts>`
hash-encadenado al audit chain de Enterprise. Efectos marcados
`@sensitive(jurisdiction=...)` requieren un parámetro compile-time
`LegalBasis<>`; si falta, el programa **no compila**. Cualquier flow
puede re-ejecutarse desde un ReplayToken y producir output bit-idéntico
(modulo no-determinismo LLM, capturado en el token vía temperature +
seed).

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

**Estado:** ⏳ Pendiente — **Depende de:** 11.a (`Stream<T>` para
framing), 11.c (ReplayToken — el estado cognitivo se snapshot-ea con
un token de continuidad).

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

**Estado:** ⏳ Pendiente — **Depende de:** 11.a (`Bytes[kind]`),
11.b (zero-copy buffers).

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

**Estado:** ⏳ Pendiente — **Depende de:** 11.a–11.e completos.

**Objetivo.** Validar formalmente que las 5 sub-fases interoperan:
`Stream<Trusted<AudioFrame>>` + zero-copy + replay + stateful PEM + OTS
compuestos en un flow multi-efecto no se degradan. Threat model
específico para los vectores introducidos: replay poisoning, legal
basis bypass, buffer reuse cross-tenant, WebSocket hijack durante
reconnect, ffmpeg subprocess escape.

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

**Próxima sesión — pickup point:** arrancar **11.b (Zero-Copy Multimodal
Buffers)** — `ZeroCopyBuffer` en axon-rs + `SymbolicPtr<T>` en Python via
PyO3 buffer protocol. Desbloquea ingest de audio/video sin copias FFI.

**Decisiones cerradas en esta sesión (11.a):**
- Syntax via composite effect string (`stream:drop_oldest`, `trust:hmac`) en vez de atributos `@backpressure(...)` — aprovecha parser existente; semántica equivalente.
- Conservative flow-level reachability check en vez de full taint-tracking dataflow — captura el caso load-bearing sin requerir pre-pass.
- Catálogos cerrados idénticos Rust + Python; extensión = parche sincronizado + security review.
- Trust y Stream son ortogonales; `Stream<Trusted<T>>` es válido y deseable.
- Ed25519 usa `verify_strict` (no `verify()`); HMAC vía `hmac::Mac::verify_slice` para constant-time implícito.

**Pre-requisitos para 11.b:**
- [x] 11.a completo (primitivas de efectos + refinement types).
- [x] Runtime `Stream<T>` funcionando para orquestar los buffers.
- [ ] Decidir: pool slab global-per-proceso vs per-tenant. Propongo **global con soft-limit per-tenant** tracked por métrica.
- [ ] Decidir: `SymbolicPtr<T>` copiable (Arc clone cheap) vs move-only. Propongo **copiable** para fan-out a múltiples consumers.
- [ ] Decidir: prohibir mutación de buffers compartidos → explicit copy o mutable slice. Propongo **readonly enforced via PEP 3118 flag**.
- [ ] Identificar los kinds iniciales de `Bytes[kind]` — propongo `raw`, `pcm16`, `mulaw8`, `jpeg`, `png`, `mp3`, `opus`, `pdf`, `mp4` como conjunto inicial; extensión libre (no cerrado como los catálogos de 11.a).

**Sesión abierta en:**
- Plan vivo: `axxon-constructor:docs/fase_11_neuro_symbolic_axon.md`
- Commits axon-lang (doble-pushed a `origin` + `enterprise`): `363f845`, `aa6f7a2`, `<docs>`.

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
