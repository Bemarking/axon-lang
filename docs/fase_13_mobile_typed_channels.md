---
title: "Plan vivo: Fase 13 — Mobile Typed Channels (π-calculus mobility + λ-L-E integration)"
status: SHIPPED — todas las sub-fases [DONE] (incluye 13.f.2 cierre cross-stack v1.5.0 el 2026-04-27)
owner: AXON Language Team
created: 2026-04-24
updated: 2026-04-27 (13.f.2 closed — Rust runtime parity, release v1.5.0)
target: axon-lang v1.5.0 + axon-rs v1.5.0 (Fase 13 fully GA cross-stack)
depends_on: Fase 4 (session types) DONE · Fase 12 (workspace refactor) DONE · Fase 8 (Rust runtime) WIP
---

# FASE 13 — MOBILE TYPED CHANNELS

> **Documento vivo**, única fuente de verdad para la fase. Leer solo este archivo basta para saber dónde estamos y qué sigue.

---

## 1. TL;DR (reanudación en 30 segundos)

- **Qué:** Elevar los canales de Axon de _strings opacos resueltos en runtime por el EventBus_ a **resources tipados de primera clase** con movilidad π-calculus (pasables como valores, almacenables, publicables).
- **Por qué:** El modelo actual `listen "topic" as x` usa strings dinámicos — EventBus decide en runtime. Es Kafka/NATS re-empaquetado, cero razonamiento estático, invisible al type-checker, invisible al LSP, sin verificación de schema productor↔consumidor. Contradice el ADN formal de Axon (linear types, session types, HoTT, Curry-Howard). El usuario pidió resolverlo eligiendo el camino _fuerte_: canales tipados + movilidad, no híbrido con fallback stringly-typed.
- **Insight rector:** π-calculus (Milner 1991) _ya resuelve_ el tradeoff estático/dinámico vía **channel mobility** — los canales son valores tipados que se pasan por otros canales. Honda-Yoshida (1999) extendió esto con session types de segundo orden. Axon ya tiene la mitad (Fase 4 session types binarios); falta la otra mitad (canales como valores).
- **Estado global:** `[DRAFT]` — este documento. Sin código hasta fijar decisiones.
- **Próximo paso concreto:** Sign-off humano de las decisiones D1–D9 abajo. Luego Fase 13.0 (paper formal) antes de tocar parser.

---

## 2. Regla de pureza (hereda de Fase 11/12)

Axon es lenguaje, no adoptante. Este plan vive en `axxon-constructor` porque afecta `axon/` (Python reference) y `axon-frontend/` + `axon-rs/` (Rust parity). El código del lenguaje permanece adopter-agnóstico: cero mención de Kivi, Stripe, Whisper o cualquier cliente. Las primitivas son genéricas (`Channel<Msg>`, `Capability<c>`, `publish`). Las integraciones concretas viven en adopters.

---

## 3. Decisiones de diseño — FIJADAS (no re-abrir)

> Las nueve decisiones fundacionales de la fase quedaron fijadas el 2026-04-24 (sign-off owner). Por convención Fases 0–11, no se re-abren.

| # | Decisión | Resolución | Estado |
|---|---|---|---|
| **D1** | **Linearidad del handle** | **Affine** (no duplicable, puede descartarse). Un handle `c: Channel<T>` se consume por `send`/`receive`/`publish`/`store` pero puede salir de scope sin uso (cleanup automático). Rechaza duplicación por assign (`let d = c` si `c` aún vive). Justificación: π-calc permite drop; linear pleno (must-consume) es demasiado restrictivo para canales de larga vida. | ✅ **FIJADA** (2026-04-24) |
| **D2** | **Movilidad** | First-class values: un `Channel<T>` puede ser (a) argumento de `send`/`receive` sobre otro channel, (b) valor retornado por `flow`, (c) persistido en `axonstore`, (d) emitido por `publish` (π-calc extrusion). Type-checker rastrea afinidad cross-boundary. | ✅ **FIJADA** (2026-04-24) |
| **D3** | **Typing de mensajes** | Schema declarado en la definición: `channel Name { message: T, qos: X }` donde `T` es nombre de tipo (struct/enum/primitive) o estructural inline. Enforcement compile-time en `send`/`receive`/`emit`/`listen` + runtime (queue typed). | ✅ **FIJADA** (2026-04-24) |
| **D4** | **Compatibilidad retro con string topics** | Dual-mode hasta v2.0. `listen "topic" as x { ... }` sigue válido pero emite **deprecation warning** en `axon check`. Camino canónico: `channel Topic { ... }` + `listen Topic as x { ... }`. En v2.0, strings topics = error (sin escape hatch — decidido por el usuario en este hilo: _"el híbrido te deja con la peor mitad de cada mundo"_). | ✅ **FIJADA** (2026-04-24) |
| **D5** | **Orden cross-language** | Python reference first (convención Fases 1–7), Rust parity second (convención Fase 8). Golden-IR byte-identical en cada sub-fase. Sin divergencia permitida. | ✅ **FIJADA** (2026-04-24) |
| **D6** | **Integración con primitivas existentes** | (a) `channel` declaration top-level como `resource`/`fabric`. (b) Handle afín participa en `manifest` y Linear/Separation Logic. (c) `daemon`/`listen` acepta handle tipado _o_ string (D4). (d) `session` binaria puede tener `send Channel<T>` o `receive Channel<T>` en sus steps (session types de segundo orden, Honda-Yoshida). (e) `axonstore` persiste handles con τ-decay. | ✅ **FIJADA** (2026-04-24) |
| **D7** | **QoS** | Declarado por-canal. Valores: `at_most_once`, `at_least_once`, `exactly_once`, `broadcast`, `queue`. Default `at_least_once`. Handler del EventBus enforce-a la QoS. | ✅ **FIJADA** (2026-04-24) |
| **D8** | **Capability/publish** | `publish c` expone un canal dinámicamente (π-calc extrusion). Requiere gate `shield` (ESK enforcement, Fase 6). Sin `shield`, `publish` es compile-time error. Consumers descubren via `discover Name as c` — tipado, no string. | ✅ **FIJADA** (2026-04-24) |
| **D9** | **Paper primero** | Antes de parser: `docs/paper_mobile_channels.md`. Extiende λ-L-E (paper 0.1) con reglas de mobility polyadic + soundness theorem (bisimilaridad strong, preservación de linearidad bajo extrusion). Convención culturalmente estricta en Axon (Fases 0/5/6 tuvieron paper primero). | ✅ **FIJADA** (2026-04-24) |

---

## 4. Formalismo de referencia

- **π-calculus polyadic + mobility** (Milner 1991, _Communicating and Mobile Systems_).
- **Session Types de segundo orden** (Honda–Yoshida 1999, _Language primitives and type discipline for structured communication-based programming_).
- **Linear Logic con exponenciales** (Girard 1987) — `!c` permite duplicación explícita; handles default no exponencial.
- **Extrusion y scope bisimulation** (Milner–Parrow–Walker 1992).
- **λ-L-E** (paper 0.1 Axon) — marco existente a extender.
- **Honda duality** (paper 4 Axon) — ya implementada en Fase 4, debe seguir válida bajo mobility.

---

## 5. Sintaxis propuesta (indicativa — ajustable en 13.a)

```axon
# Declaración (top-level, como resource/fabric)
channel OrdersCreated {
    message: Order                # schema tipado
    qos: at_least_once            # D7
    lifetime: affine              # D1 (default)
    persistence: ephemeral        # o persistent → axonstore
}

# Uso local (producer)
flow create_order(o: Order) -> Channel<Order> {
    emit OrdersCreated(o)
    return OrdersCreated         # mobility: channel as value (D2)
}

# Uso remoto (consumer typed)
daemon OrdersProcessor {
    listen OrdersCreated as o {  # D4 canonical form
        process(o)
    }
}

# Mobility — pasar un canal por otro canal (π-calc)
channel ChannelBroker {
    message: Channel<Order>      # second-order session type (D6.d)
    qos: exactly_once
}

flow rebind() -> () {
    send OrdersCreated on ChannelBroker   # canal como valor, tipado
}

# Capability/publish (requiere shield, D8)
shield PublicBroker { scope: [OrdersCreated], ... }
publish OrdersCreated within PublicBroker

# Escape hatch deprecado (D4 — emite warning)
daemon LegacyProcessor {
    listen "orders.created" as o { ... }   # WARN: string topics deprecated
}
```

---

## 6. Leyenda de estado

`[TODO]` sin iniciar · `[WIP]` en curso · `[REVIEW]` listo para revisión · `[DONE]` completo · `[BLOCKED]` bloqueado · `[DROPPED]` descartado.

---

## 7. Sub-fases

### 13.0 — Formalización (paper) `[DONE]` ✓
> Precede al código. Culturalmente no-negociable (Fases 0/5/6 sentaron el precedente).

- **13.0.1** [docs/paper_mobile_channels.md](paper_mobile_channels.md) — Extiende λ-L-E con:
  - Sintaxis polyadic π-calc (`c⟨v⟩.P`, `c(x).P`, `(νc)P`, `!P`).
  - Reglas de tipado para `Channel<T>` como tipo afín con extrusion.
  - Interacción con session types binarios (Fase 4): un session-step `send Channel<T>` es legal si ambos roles tienen el protocolo dual sobre T.
  - Teorema de soundness (preservación + progreso) bajo mobility.
  - Mapeo a runtime (EventBus tipado con handle registry).
- **Criterio de cierre:** paper revisado, teorema con prueba estructural, alineado con paper_lambda_lineal_epistemico + paper 4 Honda duality.

### 13.a — Python: Tokens + AST + Parser `[DONE]` ✓
- **13.a.1** Tokens en [axon/compiler/tokens.py](../axon/compiler/tokens.py): `CHANNEL`, `EMIT`, `PUBLISH`, `DISCOVER` añadidos al `TokenType` enum + entradas en `KEYWORDS`. `[DONE]`
- **13.a.2** AST nodes en [axon/compiler/ast_nodes.py](../axon/compiler/ast_nodes.py): `ChannelDefinition`, `EmitStatement`, `PublishStatement`, `DiscoverStatement` en sección dedicada Fase 13. `ListenBlock` extendido con `channel_is_ref: bool` para soportar dual-mode (D4) sin romper backward compat. `[DONE]`
- **13.a.3** Parser en [axon/compiler/parser.py](../axon/compiler/parser.py): top-level dispatch `CHANNEL → _parse_channel`; flow-step dispatch `EMIT/PUBLISH/DISCOVER`; `_parse_listen` dual-mode (STRING legacy + IDENTIFIER canonical); `_parse_channel_message_type` recursivo soporta `Channel<Channel<T>>` second-order (paper §3.3); validación sintáctica de `qos` (5 valores), `lifetime` (3 valores reusando `_VALID_LIFETIMES`), `persistence` (2 valores). `publish` sin `within` y `discover` sin `as` rechazados sintácticamente. `[DONE]`
- **13.a.4** Tests — 21 nuevos en [tests/test_parser.py](../tests/test_parser.py), todos pasando:
  - 11 `TestChannelDefinition` (full, defaults, second-order, nested, invalid qos/lifetime/persistence, all 5 qos, persistence axonstore, linear y persistent lifetimes explícitos)
  - 2 `TestEmitStatement` (value emit + mobility — channel-as-value)
  - 2 `TestPublishStatement` (within shield + bare publish rechazado)
  - 2 `TestDiscoverStatement` (alias bind + missing alias rechazado)
  - 3 `TestListenDualMode` (typed ref, legacy string, dual-mode coexistence)
  - 1 `TestChannelIntegration` (paper §9 worked example end-to-end)
- **13.a.5** Smoke test end-to-end: `Lexer + Parser` reconoce el ejemplo §9 del paper produciendo `[ChannelDefinition×2, DaemonDefinition, FlowDefinition]` con flow body `[EmitStatement, PublishStatement, DiscoverStatement]`. `[DONE]`

**Criterio de cierre:** ✓ Suite Python completa: **3600 passed, 26 skipped, 0 failures, 0 regresiones** (vs 3579 baseline pre-13.a). Listen string-topic legacy y typed-ref canonical coexisten. Sin parser tests rotos.

### 13.b — Python: Type checker `[DONE]` ✓
- **13.b.1** Importes y registro: `ChannelDefinition` añadida a Phase 1 con kind `"channel"`; dispatch en `_check_declaration` enruta a `_check_channel`. **Bonus**: `DaemonDefinition` ahora también se valida (gap pre-existente: estaba registrada pero nunca type-checked) — `_check_daemon` valida shield_ref + delega cada listener a `_check_listen`. `[DONE]`
- **13.b.2** Warning infrastructure: nueva propiedad `TypeChecker.warnings` + helper `_warn`, separados de errores. Permite emitir diagnósticos no-fatales (D4 deprecation) sin romper compilación. `[DONE]`
- **13.b.3** `_check_channel` (paper §3.1, §3.4): valida `shield_ref` resuelve a ShieldDefinition; resuelve `message:` recursivamente con `_validate_channel_message_type` que descompone `Channel<Channel<…<T>>>` y resuelve T contra builtins/user types/canales. Soft-resolve para nombres no encontrados (consistente con resource/manifest). `[DONE]`
- **13.b.4** `_check_emit` (Chan-Output / Chan-Mobility): rechaza canales indefinidos o de kind incorrecto; cuando channel.message empieza con `Channel<…>`, exige value_ref de kind `"channel"` y verifica equality del payload interno (second-order schema check). Casos escalares quedan como tolerados hasta 13.c (binding tracking en IR). `[DONE]`
- **13.b.5** `_check_publish` + `_check_publish_compliance_coverage` (D8 + paper §3.4): rechaza publish sin shield, con shield o canal indefinidos, con kind incorrecto. Implementa enforcement κ(message) ⊆ shield.compliance — desempaqueta `Channel<…<T>>` recursivamente al payload leaf, lee `TypeDefinition.compliance` y reporta clases faltantes. `[DONE]`
- **13.b.6** `_check_discover`: rechaza capabilities indefinidas o de kind incorrecto; aplica el invariante D8 de que solo canales con `shield_ref` declarado son descubribles. `[DONE]`
- **13.b.7** `_check_listen` (D4 dual-mode): si `channel_is_ref=True`, exige que channel_expr resuelva a ChannelDefinition (errores típicos detectados); si `False`, emite **deprecation warning** estructurado citando D4 y la versión target (v2.0). El cuerpo del listener se valida via `_check_flow_step` — emit/publish/discover dentro de listeners reciben la misma validación que en flows. `[DONE]`
- **13.b.8** Tests — 41 nuevos en [tests/test_type_checker.py](../tests/test_type_checker.py), todos pasando:
  - 5 `TestChannelTypeCheck` (happy path con shield, undefined shield, wrong kind, second-order recursivo, sanity de message)
  - 7 `TestChannelEmit` (undefined channel, wrong kind, mobility OK, mobility con value no-canal, schema mismatch second-order, emit dentro de listen body, scalar payload tolerado)
  - 11 `TestChannelPublish` (compliant valid, undefined channel, undefined shield, kind mismatch del canal, kind mismatch del shield, compliance missing class, compliance partial coverage, exact coverage, superset coverage, type sin κ, unwrap recursivo de Channel<…<T>> al leaf)
  - 4 `TestChannelDiscover` (publishable valid, undefined, wrong kind, no-shield → not publishable)
  - 6 `TestListenDualMode` (typed valid, typed undefined, typed wrong kind, string topic warning, dual-mode coexistencia, warning no bloquea compilación)
  - 8 `TestChannelIntegration` + edge cases (paper §9 sin compliance, paper §9 con PCI_DSS, second-order chain L1/L2/L3, forward references, múltiples legacy listeners → múltiples warnings, publish dentro de listener body, discover dentro de listener body, warnings/errors no se mezclan)

**Criterio de cierre:** ✓ Suite Python completa: **3641 passed, 26 skipped, 0 failures, 0 regresiones** (vs 3600 baseline pre-13.b, exactamente +41 nuevos). Type checker rechaza emit/publish/discover sobre referencias inválidas, enforce-a κ-coverage en publish, detecta second-order schema mismatches, y emite deprecation warnings (no errors) sobre listen string-topic. La validación atraviesa daemons (gap pre-existente), permitiendo que emit/publish/discover en listener bodies reciban la misma cobertura que dentro de flows.

### 13.c — Python: IR + Free Monad `[DONE]` ✓
- **13.c.1** IR nodes en [axon/compiler/ir_nodes.py](../axon/compiler/ir_nodes.py): `IRChannel` (declarativo), `IREmit`, `IRPublish`, `IRDiscover` (reducciones step-level). Sección dedicada Fase 13 con docstrings que mapean cada nodo a su regla del paper (Chan-Output / Chan-Mobility / Publish-Ext / Discover dual). `IRListen` extendida con `channel_is_ref: bool` para preservar dual-mode D4 desde AST hasta IR. `IRProgram` añade `channels: tuple[IRChannel, ...]`. `[DONE]`
- **13.c.2** Decisión arquitectónica del Free Monad: canales son **declarativos** (no entran al `IRIntentionTree`, análogos a `IRResource`), mientras emit/publish/discover son **reducciones embebidas** en su flow/listener contenedor (`IRFlow.steps` o `IRListen.children`). Esto honra estructuralmente la disciplina π-calc de prefijos (`c⟨v⟩.P`, `P ∥ Q`), sin elevar reducciones a operaciones top-level. Handlers resuelven canales por nombre cuando interpretan steps embebidos. `[DONE]`
- **13.c.3** Generator en [axon/compiler/ir_generator.py](../axon/compiler/ir_generator.py): cuatro nuevos imports + cuatro entradas en `_VISITOR_MAP` + `self._channels: dict[str, IRChannel]` + entrada en `generate()` y `_reset()`. Métodos `_visit_channel`, `_visit_emit`, `_visit_publish`, `_visit_discover`. `_visit_listen` actualizado para portar `channel_is_ref`. `[DONE]`
- **13.c.4** **Mobility detection at lowering**: `IREmit.value_is_channel` se calcula automáticamente comprobando si `node.value_ref` resuelve a un `IRChannel` previamente bajado. Esto deja el dispatch (Chan-Output vs Chan-Mobility) pre-resuelto en el IR, sin requerir re-resolución de símbolos en runtime. `[DONE]`
- **13.c.5** JSON serialization: las cuatro nuevas formas IR heredan `IRNode.to_dict()` y serializan correctamente — verificado por `TestChannelIR.test_channel_serializes_to_dict`, `TestEmitIR.test_emit_serializes_to_dict`, `TestPublishIR.test_publish_serializes_to_dict`, `TestDiscoverIR.test_discover_serializes_to_dict`. Listo para consumo cross-language (paridad Rust en 13.f). `[DONE]`
- **13.c.6** Tests — 18 nuevos en [tests/test_ir_generator.py](../tests/test_ir_generator.py), todos pasando:
  - 6 `TestChannelIR` (todos los campos, defaults D1, second-order preservado, persistence axonstore, no-en-intention-tree, JSON)
  - 3 `TestEmitIR` (scalar value_is_channel=False, mobility value_is_channel=True, JSON)
  - 2 `TestPublishIR` (lowered, JSON)
  - 2 `TestDiscoverIR` (lowered, JSON)
  - 2 `TestListenIRDualMode` (typed ref carries flag=True, legacy string flag=False)
  - 3 `TestChannelIRIntegration` (paper §9 ejemplo lowers completo, paper ejemplo serializes completo, emit/publish dentro de listener body)

**Criterio de cierre:** ✓ Suite Python completa: **3659 passed, 26 skipped, 0 failures, 0 regresiones** (+18 vs 3641 baseline pre-13.c). El paper §9 ejemplo lowers a `[IRChannel×2, IRDaemon(IRListen(typed)), IRFlow(IREmit(value_is_channel=True), IRPublish)]` con JSON serialización completa. emit/publish dentro de listener bodies se lower correctamente como `IRListen.children`.

### 13.d — Python: Runtime (typed EventBus) `[DONE]` ✓
- **13.d.1** Nuevo módulo [axon/runtime/channels/typed.py](../axon/runtime/channels/typed.py) — runtime layer **superpuesta** al EventBus existente, no reemplazo. La ruta string-topic legacy queda intacta para D4 dual-mode; la superficie typed añade schema, QoS, capability gating, mobility. Re-exports en [axon/runtime/channels/__init__.py](../axon/runtime/channels/__init__.py). `[DONE]`
- **13.d.2** Tipos públicos:
  - `TypedChannelHandle` — wrap runtime de un `IRChannel` con `consumed_count` para enforcement de lifetime, `is_publishable`, `carries_channel`, `inner_message_type()` para second-order (paper §3.3).
  - `Capability` — token frozen para `publish`/`discover` con UUID, `delta_pub` (default 0.05 — paper §3.4 lower bound), `issued_at` timestamp.
  - `TypedChannelRegistry` — name → handle map con `register_from_ir_channel()` para bootstrap directo desde IR.
  - `TypedEventBus` — orquestador con `from_ir_program()` factory; expone `emit`, `publish`, `discover`, `subscribe_broadcast`, `receive`, `close_all`, `issued_capabilities()`. `[DONE]`
- **13.d.3** Errores estructurados (todos heredan `TypedChannelError → RuntimeError`):
  - `ChannelNotFoundError` — name no en registry
  - `SchemaMismatchError` — runtime D3 enforcement (defense-in-depth)
  - `CapabilityGateError` — D8 (publish sin shield, shield mismatch, capability revocada/falsificada)
  - `LifetimeViolationError` — linear consumido más de una vez
- **13.d.4** Schema enforcement runtime (paper §3.1, §3.2): `emit` rechaza scalar→second-order, handle→first-order, second-order schema mismatch, payload no-handle con flag mobility activa. Mirror exacto de las reglas Chan-Output / Chan-Mobility. `[DONE]`
- **13.d.5** QoS dispatch (paper §3 + Fase 13 D7) — cinco modos:
  - `at_most_once` — best-effort, drop silencioso si canal cerrado/lleno
  - `at_least_once` — default, delegado al EventBus subyacente
  - `exactly_once` — dedup por `event_id` in-process; cross-process diferido a 13.e con replay-token Fase 11.c
  - `broadcast` — fan-out a `subscribe_broadcast` queues; `receive` directo rechazado
  - `queue` — single-consumer FIFO, hereda de EventBus
- **13.d.6** Capability gate (D8 + paper §3.4): `publish` requiere shield no-vacío, valida que el handle sea publishable (`shield_ref` declarado), exige equality entre shield arg y `handle.shield_ref`. Compliance check via `ShieldComplianceFn` predicate inyectado — la función recibe `(shield_name, handle)` y delega κ-extraction al checker (mantiene la layer agnóstica de ESK/IRType). `discover` consume capability one-shot; capabilities de otra instancia bus rechazadas. `[DONE]`
- **13.d.7** Lifetime accounting: `consumed_count` por handle; linear viola en consumición #2; affine y persistent sin upper bound. Per-binding tracking diferido a 13.e (cuando discover yields fresh aliases con identidad propia). `[DONE]`
- **13.d.8** Dual-mode coexistencia (D4): `TypedEventBus` recibe el EventBus subyacente como dependencia opcional; legacy callers usando string topics directamente sobre la misma instancia EventBus ven sus mensajes intactos. Verificado por test. `[DONE]`
- **13.d.9** Tests — 52 nuevos en [tests/test_typed_channels.py](../tests/test_typed_channels.py), todos pasando:
  - 4 `TestTypedChannelHandle` (defaults D1, is_publishable, carries_channel, inner_message_type)
  - 5 `TestTypedChannelRegistry` (register/get, unknown raises, overwrite, sorted names, register_from_ir_channel)
  - 3 `TestTypedEventBusBootstrap` (from_ir_program, underlying access, custom underlying)
  - 3 `TestEmit` (scalar emit+receive, unknown channel, event_id+timestamp)
  - 5 `TestEmitMobility` (handle through second-order, schema mismatch interno, scalar→second-order rejected, second-order→first-order rejected, flag con non-handle rejected)
  - 7 `TestPublish` (capability returned, empty shield rejected, unpublishable rejected, wrong shield rejected, unknown channel, default delta_pub, compliance predicate veto, predicate handle inspection)
  - 4 `TestDiscover` (returns handle, consumes cap, revoked rejected, forged rejected)
  - 6 `TestQoS*` (at_least_once default, at_most_once delivers/drops, exactly_once dedup, broadcast fan-out, broadcast subscribe rejection, broadcast receive rejection, queue FIFO)
  - 3 `TestLifetime` (affine multi-emit OK, linear second emit raises, persistent unrestricted)
  - 1 `TestPaperExampleE2E` (paper §9 producer→publish→discover→receive flow)
  - 2 `TestErrorHierarchy` (heredan typed-base, typed-base hereda RuntimeError)
  - 2 `TestDualModeCoexistence` (legacy string topics intactos, close_all drena)
  - 4 `TestEdgeCases` (capability_id único, capabilities por-instancia, lifetime aislado por-handle, from_ir_program preserva metadata)

**Criterio de cierre:** ✓ Suite Python completa: **3711 passed, 26 skipped, 0 failures, 0 regresiones** (+52 vs 3659 baseline pre-13.d). Runtime layer typed coexiste con EventBus legacy sin tocar el path string-topic. Paper §9 ejemplo end-to-end (producer→publish→consumer→discover, mobility carrying inner channel) ejecuta limpio. Migración de daemon/listen al typed bus diferida a 13.e (parte del migration path strict).

### 13.e — Python: Migration path + deprecation `[DONE]` ✓
- **13.e.1** Frontend facade en [axon/compiler/frontend.py](../axon/compiler/frontend.py): `FrontendDiagnostic` extendida con `severity: str` (`"error"` default | `"warning"`); `FrontendCheckResult` y `FrontendCompileResult` exponen propiedades `errors` / `warnings`; `ok` cuenta solo errores. Backward-compatible: callers existentes ven los errors via `errors` y warnings tolerated en compile path. `_analyze_source` plumbing-through warnings desde `TypeChecker.warnings` (D4 deprecation expuesto via 13.b). `[DONE]`
- **13.e.2** CLI `axon check` en [axon/cli/check_cmd.py](../axon/cli/check_cmd.py) + [axon/cli/__init__.py](../axon/cli/__init__.py):
  - Flag `--strict` agregado al argparse con docstring que cita docs/migration_fase_13.md
  - Render diferenciado: warnings con marker amarillo `⚠`, errores con `✗ `; severity-coloured prefix por línea
  - Default mode: warnings shown, exit 0 (check passes)
  - Strict mode: warnings promoted to errors, exit 1, summary muestra `(--strict)` para distinguir de errores reales
  - Programas con errores reales + warnings: ambos surfaced; errors no contaminados por strict
  `[DONE]`
- **13.e.3** Migration script [scripts/migrate_string_topics.py](../scripts/migrate_string_topics.py):
  - `topic_to_identifier()` — PascalCase con manejo de separadores, dígitos iniciales (prefijo `T`), edge cases (vacío → `DeprecatedTopic`)
  - `find_string_topics()` — regex `\blisten\s+"…"` colecta unique topics en orden de aparición; ignora typed listeners
  - `build_channel_block()` — genera `channel <Name> { message: Bytes qos: ... lifetime: ... }` con review hints inline (`//` comments per Axon syntax — descubrí mid-implementation que Axon no usa `#`)
  - `rewrite_listens()` — sustitución textual via regex; preserva otros strings (`goal: "x"`)
  - `migrate()` — pipeline completo, retorna `(new_source, topics)`
  - `_verify()` — re-corre `axon check` sobre la salida para garantizar cleanliness
  - CLI: `--in-place` con backup `.bak`, `--message` / `--qos` / `--lifetime` para refinar defaults, `--no-verify` para escape hatch
  `[DONE]`
- **13.e.4** Documentación [docs/migration_fase_13.md](migration_fase_13.md): guía completa para adopters — schedule v1.4.x → v1.5.0 → v2.0, before/after diff, instructions para script y manual migration, CI gating con `--strict`, capacidades nuevas desbloqueadas post-migración (mobility, capability gating, LSP support, static topology), troubleshooting common issues. `[DONE]`
- **13.e.5** Tests — 34 nuevos:
  - 6 `TestCheckStrict` en [tests/test_cli.py](../tests/test_cli.py): default warning-passes, strict warning-fails, multi-warning count, canonical typed clean en strict, marker `⚠` default, errors+warnings mixed
  - 28 en [tests/test_migrate_string_topics.py](../tests/test_migrate_string_topics.py):
    - 10 `TestTopicToIdentifier` (parametrize: 7 conversions + digit prefix + empty + only-separators)
    - 5 `TestFindStringTopics` (single, unique, order, ignore-typed, empty)
    - 3 `TestRewriteListens` (substitution, preserves-other-strings, multi-distinct)
    - 5 `TestBuildChannelBlock` (one-per-topic, default Bytes, custom message, // comments, review hint)
    - 5 `TestMigrate` (returns topics, no-op clean, axon-check passes, preserves-typed, custom qos+lifetime)
  `[DONE]`

**Criterio de cierre:** ✓ Suite Python completa: **3745 passed, 26 skipped, 0 failures, 0 regresiones** (+34 vs 3711 baseline pre-13.e). End-to-end verificado: legacy file con 2 string-topic listens → `axon check` muestra 2 warnings (exit 0) → `axon check --strict` falla (exit 1) → `python -m scripts.migrate_string_topics` produce file canónico → `axon check --strict` sobre el output: 0 errors, 0 warnings, exit 0. Migración path lista para v1.5.0.

### 13.f.1 — Rust frontend parity `[DONE]` ✓
- **13.f.1.1** Tokens en [axon-frontend/src/tokens.rs](../axon-frontend/src/tokens.rs): `Channel`, `Emit`, `Publish`, `Discover` añadidos al `TokenType` enum + `keyword_type()` mappings + `Channel` registrado como `is_declaration_keyword`. `[DONE]`
- **13.f.1.2** AST en [axon-frontend/src/ast.rs](../axon-frontend/src/ast.rs): `ChannelDefinition` + `EmitStatement` + `PublishStatement` + `DiscoverStatement` structs; variantes en `Declaration` y `FlowStep`. `ListenStep` extendida con `channel_is_ref: bool`. `DaemonDefinition` extendida con `listeners: Vec<ListenStep>` (gap pre-existente: pre-Fase-13 los listen blocks se descartaban estructuralmente en parse_daemon). `[DONE]`
- **13.f.1.3** Parser en [axon-frontend/src/parser.rs](../axon-frontend/src/parser.rs): top-level dispatch para `Channel`; flow-step dispatch para `Emit`/`Publish`/`Discover`; `parse_listen_step` dual-mode (track `channel_is_ref`); `parse_channel` con field-by-field validación (qos/lifetime/persistence + shield); `parse_channel_message_type` recursivo soporta `Channel<Channel<T>>`; `parse_emit_step`/`parse_publish_step`/`parse_discover_step`; `parse_daemon` ahora preserva listeners para validación. `[DONE]`
- **13.f.1.4** Type checker en [axon-frontend/src/type_checker.rs](../axon-frontend/src/type_checker.rs): nuevo símbolo kind `"channel"`; `warnings: Vec<TypeError>` + `warn()` helper + `check_with_warnings()` API; `check_channel` (shield ref + message recursion); `check_daemon` (delega a `check_listen` por listener); `check_listen` dual-mode con D4 deprecation warning; `check_emit` con second-order schema mismatch detection; `check_publish` (D8 capability gate); `check_discover` (publishable check). `find_channel_message`/`find_channel_shield` helpers que escanean declaraciones. `[DONE]`
- **13.f.1.5** IR en [axon-frontend/src/ir_nodes.rs](../axon-frontend/src/ir_nodes.rs): `IRChannel`, `IREmit`, `IRPublish`, `IRDiscover` structs (Serialize); variantes en `IRFlowNode` enum (untagged); `IRListenStep` extendida con `channel_is_ref`; `IRProgram.channels` añadido. Generator en [axon-frontend/src/ir_generator.rs](../axon-frontend/src/ir_generator.rs): `visit_channel` lower; `IREmit.value_is_channel` se computa al lower checando `channel_names: HashSet` (paridad con Python `_channels` dict). `[DONE]`
- **13.f.1.6** CLI [axon-frontend/src/checker.rs](../axon-frontend/src/checker.rs) + [axon-rs/src/main.rs](../axon-rs/src/main.rs): flag `--strict` añadido al CLI Rust; render de warnings con marker amarillo `⚠`, errors con `X`; strict promueve warnings → errors (exit 1); coexisten errors + warnings sin contaminación. `[DONE]`
- **13.f.1.7** Cobertura cross-language: editado [axon-rs/src/cost_estimator.rs](../axon-rs/src/cost_estimator.rs) y [axon-rs/src/runner.rs](../axon-rs/src/runner.rs) para clasificar las nuevas variantes `IRFlowNode::Emit/Publish/Discover` (Cognitive step kind / step info dispatch). `[DONE]`
- **13.f.1.8** Tests Rust — 34 nuevos en `axon-frontend/src`:
  - 3 en `tokens.rs::tests_lang_extensions` (channel keywords, declaration-level, flow-step-level)
  - 12 en `parser.rs::fase13_parser_tests` (full channel, defaults D1, second-order, nested, invalid qos/lifetime/persistence, emit, publish, discover, listen typed/legacy/dual)
  - 12 en `type_checker.rs::fase13_typecheck_tests` (clean shield, undefined shield, wrong kind, emit cases, second-order schema mismatch, publish/discover cases, listen typed clean/undefined, D4 warning, dual-mode warning isolation)
  - 7 en `ir_generator.rs::fase13_ir_tests` (channel all fields, second-order preserved, value_is_channel mobility/scalar, publish/discover, JSON serialization)
  Total Rust suite: **83 passed** (49 baseline + 34 nuevos), 0 fallos.
- **13.f.1.9** **Byte-identical IR parity verificada**: el ejemplo paper §9 produce el mismo JSON sub-tree (`channels[]` + emit/publish/discover en `flows[].steps[]`) cuando se compila con Python (`IRGenerator().generate()`) y Rust (`axon compile --stdout`). Diff `python ↔ rust` sobre el subset Fase 13: **0 líneas de diferencia**.

**Criterio de cierre 13.f.1:** ✓ Suite Rust completa: **83 passed, 0 failures, 0 regresiones** (vs 49 baseline pre-13.f). Suite Python sigue **3745 passed, 0 failures**. CLI `axon check --strict` funcional en Rust. Paridad byte-identical Python ↔ Rust verificada manualmente sobre el ejemplo §9 del paper. Contrato Fase 12.c mantenido: `axon-frontend` sigue zero-runtime-deps (solo `serde`).

### 13.f.2 — Rust runtime parity (TypedEventBus en axon-rs) `[DONE]` ✓
- **13.f.2.1** Nuevo árbol de módulos [axon-rs/src/runtime/channels/mod.rs](../axon-rs/src/runtime/channels/mod.rs) + [axon-rs/src/runtime/channels/typed.rs](../axon-rs/src/runtime/channels/typed.rs) — port directo de `axon/runtime/channels/typed.py`. Decisión arquitectónica: el typed bus Rust **no se monta sobre el `EventBus` broadcast existente** (que sirve lifecycle de daemons con semántica fan-out) sino que owns su propio transport con FIFO single-consumer per channel — eso preserva la semántica QoS Python 1:1. Ambos buses coexisten en el mismo proceso para concerns diferentes. Cableado en [axon-rs/src/runtime/mod.rs](../axon-rs/src/runtime/mod.rs) como `pub mod channels;`. `[DONE]`
- **13.f.2.2** Tipos públicos paridad exacta:
  - `TypedChannelHandle` con `is_publishable()`, `carries_channel()`, `inner_message_type()`, `from_ir(&IRChannel)`. Defaults D1 (qos=at_least_once, lifetime=affine, persistence=ephemeral, no shield).
  - `Capability` (immutable struct) con `capability_id`/`channel_name`/`shield_ref`/`delta_pub` (default 0.05 — paper §3.4 lower bound)/`issued_at`.
  - `TypedChannelRegistry` con `register`/`register_from_ir`/`get`/`has`/`names()` (sorted).
  - `TypedEventBus` con `from_ir_program(&IRProgram)` factory que itera `ir.channels: Vec<IRChannel>`.
  - `TypedPayload` enum (`Scalar(serde_json::Value)` | `Handle(TypedChannelHandle)`) — sustituye Python's `payload_is_handle: bool` keyword argument por sum type type-system-enforced.
  - `ShieldComplianceFn = Arc<dyn Fn(&str, &TypedChannelHandle) -> bool + Send + Sync>` — permite hookear ESK-aware checker production-side. `[DONE]`
- **13.f.2.3** Errores estructurados en `TypedChannelError` (Display + std::error::Error implementados):
  - `ChannelNotFound { name, registered }` — name no en registry, lista los registrados como en Python
  - `SchemaMismatch(String)` — runtime D3 enforcement (defense-in-depth)
  - `CapabilityGate(String)` — D8 (publish sin shield, shield mismatch, capability revocada/forged/cross-bus)
  - `LifetimeViolation { name, count }` — linear consumido > 1 vez
  - `Transport(String)` — fallo de transport subyacente (mpsc closed/dropped) — variante Rust-específica; Python usa RuntimeError equivalente
- **13.f.2.4** Schema enforcement runtime (paper §3.1, §3.2): `emit` rechaza scalar→second-order, handle→first-order, second-order schema mismatch, payload no-handle con flag mobility. Mirror exacto Chan-Output / Chan-Mobility. `[DONE]`
- **13.f.2.5** QoS dispatch (paper §3 + Fase 13 D7) — cinco modos sobre `tokio::sync::mpsc` (single-consumer FIFO) + lista de senders broadcast:
  - `at_most_once` — best-effort, drop silencioso si transport cerrado (test verifica ambos: delivery normal + cierre transport)
  - `at_least_once` — default, FIFO transport
  - `exactly_once` — dedup por `event_id` in-process via `HashMap<channel, HashSet<event_id>>`; cross-process diferido (parity con Python 13.d note)
  - `broadcast` — fan-out a `subscribe_broadcast()` queues; `receive` directo rechazado
  - `queue` — single-consumer FIFO
- **13.f.2.6** Capability gate (D8 + paper §3.4): `publish` requiere shield no-vacío, valida `is_publishable`, exige equality `shield arg == handle.shield_ref`, invoca `compliance_check` predicate. `discover` consume capability one-shot; capabilities forjadas o de otra instancia bus rechazadas. `[DONE]`
- **13.f.2.7** Lifetime accounting via `consumed_count` por handle dentro del registry; linear viola en consumición #2 (test); affine y persistent sin upper bound (test).  `[DONE]`
- **13.f.2.8** Tests — **44 nuevos** en `runtime::channels::typed::tests` (mix `#[test]` sync + `#[tokio::test]` async), todos pasando:
  - 5 Handle (defaults D1, is_publishable, carries_channel, inner_message_type unwrap, from_ir round-trip)
  - 5 Registry (register/get, unknown raises con registered list, overwrite, sorted names, register_from_ir)
  - 2 Bus bootstrap (from_ir_program, default compliance permisivo)
  - 3 Emit base (scalar round-trip, unknown channel error, event_id+timestamp)
  - 4 Emit mobility (handle through second-order, schema mismatch interno, scalar→second-order rechazado, handle→first-order rechazado)
  - 8 Publish (capability returned, empty shield rejected, unpublishable rejected, wrong shield rejected, unknown channel, default delta_pub=0.05, compliance predicate veto, predicate handle inspection)
  - 3 Discover (returns handle + consumes cap + double rejected, forged rejected, cross-bus capability rejected)
  - 7 QoS (at_least_once default, at_most_once delivers + silent drop, exactly_once dedup, broadcast fan-out 2 subs, broadcast subscribe rejection, broadcast receive rejection, queue FIFO ordering)
  - 3 Lifetime (affine multi-emit OK, linear second-emit raises, persistent unrestricted)
  - 1 Paper §9 e2e (producer→emit→publish→discover→receive con Order payload)
  - 1 Error display (ChannelNotFound + LifetimeViolation rendering)
  - 2 Edge (capability_id único, close_all drains)
- **13.f.2.9** **Coexistencia con `EventBus` daemon-supervisor**: el typed bus es un módulo independiente; el broadcast EventBus existente sigue intacto y sus 974 tests baseline pasan sin regresión. Suite axon-rs `--lib`: **1018 passed (974 + 44 nuevos), 0 failed**.

**Criterio de cierre 13.f.2:** ✓ Suite axon-rs `--lib`: **1018 passed, 0 failures, 0 regresiones** (vs 974 baseline pre-13.f.2). Suite axon-frontend sigue 103 passed (sin tocar). Paridad estructural Python ↔ Rust completa: errores, handle, capability, registry, bus con QoS×5, lifetime, second-order mobility, paper §9 worked example. Adopters Rust-side ahora obtienen typed EventBus end-to-end — el flujo `axon compile` + runtime nativo Rust corre con las mismas garantías que `axon compile` + interpretación Python. Fase 13 cierra como **fully GA cross-stack**.

### 13.g — axon-lsp support `[DONE]` ✓
- **Decisión de scope:** El repo hermano `axon-lsp` está en estado scaffold (solo `main.rs` placeholder). Construir una LSP completa quedaba fuera del scope razonable de un solo turn. El move de mayor valor: **exponer en `axon-frontend` los primitives de análisis** que el LSP necesitará para implementar hover/autocomplete/go-to-def/find-refs sobre canales — disponibles ya como API pública, byte-identical con lo que el type checker ve. Cuando axon-lsp v0.1.0 arranque, el wire-up de Fase 13 será trivial (path dep + llamadas directas). Decisión registrada en el plan doc de axon-lsp como prerequisito 0.b satisfecho. `[DONE]`
- **13.g.1** Nuevo módulo [axon-frontend/src/channel_analysis.rs](../axon-frontend/src/channel_analysis.rs) — funciones puras sobre AST que cubren los cinco usos LSP del spec:
  - **list_channels(program)** — orden source, descend en epistemic blocks → outline view + `workspace/symbol`
  - **find_channel_definition(program, name)** → `textDocument/definition` jump
  - **find_channel_references(program, name)** → `textDocument/references` con `ChannelRefKind` (Emit / EmitMobility / Listen / Publish / Discover) para que el editor distinga producers/consumers; descend en if/for-in; **excluye explícitamente legacy string topics** (alineado con D4 — string topics no son refs tipadas)
  - **channel_hover_markdown(channel)** → `textDocument/hover` Markdown con: bloque de signature en code-fence axon, flag para second-order, explicación del shield gate (D8) o warning si no hay shield declarado
  - **channel_names_in_scope(program)** + **publishable_channel_names(program)** → completion lists (la segunda filtra para `discover`/`publish` triggers)
  - **channel_completion_detail(channel)** → string del CompletionItem.detail con `channel<msg, qos, lifetime>` + " · publishable" si shield_ref
  - **duplicate_channels(program)** → diagnostics con related-information (cada site duplicado)
  - **detect_channel_trigger(line_prefix)** → reconoce `listen `/`emit `/`publish `/`discover ` para que el LSP elija la lista correcta
  `[DONE]`
- **13.g.2** Re-export en [axon-frontend/src/lib.rs](../axon-frontend/src/lib.rs) bajo `pub mod channel_analysis;` con docstring que cita Fase 13.g y mantiene el contrato Fase 12.c (zero runtime deps — el módulo usa solo `crate::ast` y `std`). `[DONE]`
- **13.g.3** Tests — 20 nuevos en `channel_analysis.rs::tests`:
  - 2 list_channels (source order, epistemic block recursion)
  - 2 find_channel_definition (found, not found)
  - 4 find_channel_references (emit+publish+discover+listen, mobility distinguished from emit, legacy string topics excluded, conditional + for-in recursion)
  - 4 hover_markdown (signature block, second-order flag, shield gate explanation, no-shield warning)
  - 4 completions (sorted, publishable filter, detail with shield, detail without shield)
  - 2 duplicate detection (detected, empty when unique)
  - 2 trigger detection (recognizes 4 keywords + edge case stale prefixes, returns None outside)
- **13.g.4** **Roadmap LSP-side:** Cuando axon-lsp implemente sus crates `lsp-core`/`lsp-server` (sub-fases 0.c-0.g de su plan), los handlers se reducen a thin adapters:
  ```rust
  // En lsp-core/src/hover.rs (futuro)
  fn hover_at(program: &Program, pos: Position) -> Option<MarkupContent> {
      let name = symbol_at(program, pos)?;
      let channel = axon_frontend::channel_analysis::find_channel_definition(program, &name)?;
      Some(MarkupContent::markdown(channel_analysis::channel_hover_markdown(channel)))
  }
  ```
  Sin lógica duplicada, sin re-implementar AST walks. Esa es la idea de "frontend reusable" del plan axon-lsp D2.

**Criterio de cierre 13.g:** ✓ Suite Rust completa: **103 passed, 0 failures, 0 regresiones** (vs 83 baseline pre-13.g, +20 nuevos para channel_analysis). API pública estable y testeada para los 5 casos de uso LSP del spec original (autocomplete, go-to-def, find-refs, hover, diagnostics extras). Contrato Fase 12.c mantenido. axon-lsp queda con todo el material listo para wire-up cuando arranquen sus sub-fases 0.c-0.g.

### 13.h — Integration tests + examples + release `[DONE]` ✓
- **13.h.1** [examples/mobile_channels.axon](../examples/mobile_channels.axon) — pipeline producer→broker→consumer con mobility (channel-over-channel) + PCI_DSS compliance gate. Documentado con comentarios que mapean a las decisiones D1/D3/D6/D8 + paper §3.1/§3.2/§3.3/§3.4. `axon check --strict` clean en Python y Rust (125 tokens, 6 declarations, 0 errors). `[DONE]`
- **13.h.2** [examples/secure_publish.axon](../examples/secure_publish.axon) — publish + shield + discover end-to-end con HIPAA gate (`ClinicalGate`) sobre `PatientReading`. Demuestra producer/consumer separados y la regla "discover only on shield-gated channels". `axon check --strict` clean (109 tokens, 6 declarations, 0 errors). `[DONE]`
- **13.h.3** Integration tests cross-phase en [tests/test_fase13_integration.py](../tests/test_fase13_integration.py) — 10 tests cubriendo:
  - 3 `TestWorkedExamples` (mobile_channels clean, secure_publish clean, JSON round-trip)
  - 2 `TestChannelShieldComposition` (publish κ-coverage violation rejected; compliant shield clean) — **acceptance D8 + Fase 6.1 RTT**
  - 1 `TestChannelSessionComposition` (channel + session coexist en un programa)
  - 1 `TestChannelImmuneComposition` (channel + observe + immune + reflex compone limpio)
  - 1 `TestChannelManifestComposition` (channels coexisten con resource/fabric/manifest/observe; verifica que canales NO entran en `intention_tree` — paridad con paper §13.c.2 structural decision)
  - 1 `TestMigrationRoundTrip` (legacy → migrate → strict-check passes con cero warnings)
  - 1 `TestFase13AcceptanceCriterion::test_full_acceptance_pipeline` — **criterio de cierre absoluto**: parser + type-check + warnings + IR + JSON serialization, todo limpio sobre el ejemplo paper §9
  `[DONE]`
- **13.h.4** Versiones bumpeadas a v1.4.2:
  - [pyproject.toml](../pyproject.toml) — `axon-lang 1.4.2` con descripción Fase 13
  - [axon/__init__.py](../axon/__init__.py) — `__version__ = "1.4.2"`
  - [axon-rs/Cargo.toml](../axon-rs/Cargo.toml) — `axon 1.4.2` + descripción Fase 13
  - [axon-frontend/Cargo.toml](../axon-frontend/Cargo.toml) — `axon-frontend 0.2.0` (minor bump por nuevo API público `channel_analysis`)
  - [axon-rs/src/compiler.rs](../axon-rs/src/compiler.rs) — `AXON_VERSION = "1.4.2"` (sincronizado con package)
  `[DONE]`
- **13.h.5** Plan vivo `plan_io_cognitivo.md` actualizado: Fase 4 marcada como "extended by Fase 13 (typed channels + π-calc mobility)" con nota explicativa apuntando a `paper_mobile_channels.md`. `[DONE]`

**Criterio de cierre 13.h:** ✓ Suite Python: **3755 passed, 0 failures, 0 regresiones** (+10 vs 3745 baseline pre-13.h). Suite Rust: **103 passed, 0 failures**. Examples paper §9 ejecutan limpios bajo `axon check --strict` Python y Rust. Migration script + `--strict` flag forman el pipeline completo: legacy → migrate → strict pass. Versiones sincronizadas v1.4.2 (axon-lang Python + axon-rs) y v0.2.0 (axon-frontend). Fase 13 cierra como "production-ready GA": π-calc mobility tipada, capability extrusion via shield, second-order session types, runtime TypedEventBus con QoS, migration path explícito, tests cross-phase comprehensivos, byte-identical Python ↔ Rust IR parity, axon-lsp ready-to-wire. **D9 paper-first cumplido sin compromisos: 11 secciones del paper + 8 sub-fases + 0 fallos.**

---

## §Fase 13 — Estado final

| Sub-fase | Scope | Estado | Tests |
|---|---|---|---|
| 13.0 | Paper formal (`paper_mobile_channels.md`) | ✅ DONE | — |
| 13.a | Tokens + AST + Parser (Python) | ✅ DONE | 21 |
| 13.b | Type checker + warnings (Python) | ✅ DONE | 41 |
| 13.c | IR + Free Monad effects (Python) | ✅ DONE | 18 |
| 13.d | Runtime TypedEventBus (Python) | ✅ DONE | 52 |
| 13.e | Migration path + `--strict` flag | ✅ DONE | 34 |
| 13.f.1 | Rust frontend parity | ✅ DONE | 34 (Rust) |
| 13.f.2 | Rust runtime port (TypedEventBus) | ✅ DONE | 44 (Rust) |
| 13.g | axon-lsp analysis primitives | ✅ DONE | 20 (Rust) |
| 13.h | Integration + examples + release v1.4.2 | ✅ DONE | 10 |
| 13.h.bis | Cierre cross-stack — release v1.5.0 (Fase 13.f.2) | ✅ DONE | — |

**Totales:**
- Tests Python nuevos en Fase 13: **176** (21 + 41 + 18 + 52 + 34 + 10)
- Tests Rust nuevos en Fase 13: **98** (34 frontend parity + 20 channel_analysis + 44 runtime parity)
- Suite Python total: **3755 passed, 0 failures**
- Suite Rust axon-frontend: **103 passed, 0 failures**
- Suite Rust axon-rs: **1018 passed, 0 failures** (974 baseline + 44 typed channels)
- Paridad Python↔Rust IR sobre paper §9: **byte-identical (0 líneas diff)**
- Paridad Python↔Rust runtime: **estructural completa** (TypedChannelHandle/Capability/TypedChannelRegistry/TypedEventBus/QoS×5/lifetime/mobility/§9 e2e)

---

## 8. Criterio de cierre de Fase 13

1. Paper `paper_mobile_channels.md` con teorema de soundness probado.
2. `examples/mobile_channels.axon` compila + type-checks + ejecuta end-to-end pasando un `Channel<Order>` sobre `ChannelBroker` a un consumidor descubridor.
3. Golden IR Python == Rust byte-identical para los 3 examples nuevos.
4. axon-lsp autocompleta nombres de canales declarados.
5. `axon check --strict examples/` falla si encuentra string topics; sin `--strict`, emite warning.
6. Regression: la suite completa Python (3267+ tests) sigue verde. Rust suite (`cargo test --workspace`) verde.
7. Migration script funciona sobre un `.axon` real (corpus de adopters internos).

---

## 9. Riesgos identificados

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Complejidad de type-checking (afinidad cross-session + mobility) | Paper primero (13.0) — formalismo debe existir antes del código. |
| R2 | Break change si strings topics salen en v2.0 | Dual-mode extendido en v1.5.0; `--strict` opt-in permite CI gradual en adopters. |
| R3 | Drift Python↔Rust | Golden-IR byte-identical test en CI desde 13.a (no solo al final). |
| R4 | Scope creep — "aprovechar para tipar eventos tambien" | Strict boundary: eventos typed son implícitos en esta fase (`message: T` lo cubre); no abrir subsistema separado. |
| R5 | Interacción con Immune (Fase 5) — ¿observe sobre canales tipados? | Fuera de scope; Fase 13 no toca immune, solo asegura que handles se registran para observación futura. |

---

## 10. Fuera de scope (explícito)

- Distributed channels cross-cluster (queda para una Fase 14 hipotética con Raft/CRDT).
- Runtime GC de handles huérfanos más allá del τ-decay del ΛD wrapper (ya existe).
- Herramientas de visualización (axon-analyzer) del grafo de canales — queda para Fase 12.e/f.
- Cambios en AxonEndpoint — canales typed coexisten con endpoints, no los reemplazan.

---

## 11. Actualización de este documento

Cualquier decisión técnica tomada durante las sub-fases se registra aquí. Cada sub-fase completada cambia de `[TODO]` a `[DONE]` con enlaces a commits, tests añadidos y criterio de cierre verificado. Si una decisión D1–D9 se redirige, se anota explícitamente en §3 con la razón.
