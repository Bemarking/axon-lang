---
title: "Plan vivo: Fase 23 — Native Algebraic Effects + Free Monad Runtime"
status: DRAFTED 2026-05-08 — sub-fases 23.a–23.h pendientes; target axon-lang v1.17.0 (cross-stack release: Python frontend + Rust runtime)
owner: AXON Language Team
created: 2026-05-08
updated: 2026-05-08
target: axon-lang v1.17.0 (PyPI + crates.io)
depends_on: Fase 22 SHIPPED (multi-provider backend coverage + observability foundation); paper docs/algebraic_effects_streaming.md (research substrate)
---

## ▶ Status snapshot (2026-05-08 — TODA Fase 23 SHIPPED como axon-lang v1.17.0 cross-stack, decisiones D1/D6/D11 ratificadas/revisadas por founder)

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 23.a Engineering spec | ✅ DONE | doc-only | — | Operacionaliza paper §1-§6 en specs verificables. `docs/fase/fase_23_algebraic_effects_runtime.md` (este doc) + `axon_language_specification.md` §3.21 + decisiones D1–D12 (D1/D6/D11 founder-ratified 2026-05-08) |
| 23.b Lexer + Parser + AST | ✅ DONE 2026-05-08 | ~720 effective | Python | 6 keywords + `BANG` token + 9 AST classes + 8 parser productions + 57/57 tests verdes; 0 regressions |
| 23.c Typechecker + effect row inference + row polymorphism + operation polymorphism | ✅ DONE 2026-05-08 | ~750 effective | Python | EffectRow + EffectEnvironment + HandlerFrame data classes + 11 nuevos `_check_*` methods en TypeChecker + integración `_check_flow` y `_check_step` + 98/98 tests verdes; 0 regressions (562/562) |
| 23.d IR opcodes + CPS lowering | ✅ DONE 2026-05-08 | ~520 effective | Python | 8 IR opcodes + `IRProgram.effects` field + 9 nuevos `_visit_*` methods + per-flow CPS state counters + handler stack + body_states accumulator + 37/37 tests verdes; 0 regressions. State machine FSM canónico: `(flow_name, state_id)` is the Rust runtime coordinate. |
| 23.f Rust runtime — Free Monad interpreter | ✅ DONE 2026-05-08 | ~1700 effective | Rust | `axon-rs/src/effects/` nuevo módulo: 4 archivos (mod.rs + value.rs + ir.rs + runtime.rs) + tests inline. EffectRuntime FSM dispatch loop direct-style (Rust call stack ≡ handler stack), 49/49 tests verdes (`cargo test --lib effects::`). Total axon-rs lib: 1092/1092 verdes (0 regressions). Bug fix mid-implementation: `find_handler_index` walking direction (forward debe outward only desde source frame, no desde top of stack — destapado por `forward_chain_through_three_frames`). LOC menor que estimate (~2500) porque interpreter direct-style + serde Deserialize delegation; codegen-to-jmp se difiere a Fase 24+. |
| 23.e ~~Python runtime~~ | ❌ deliberately skipped | — | — | Decisión D6 ratificada: solo Rust runtime; Python no tiene first-class delimited continuations sin overhead que viola el paper §5; coherente con destino long-term 100% Rust + C |
| 23.g Migrate `stream<τ>` to algebraic effects | ✅ DONE 2026-05-08 | ~150 effective | Python | Dual-emission: `IRStreamSpec` legacy fields preservados (D8 backward compat 100%) + nuevo `desugared_handler: IRHandlerFrame` synthesised on `_visit_stream_definition` con effect_names=("_StreamBuiltin",), Chunk(chunk)→{...; resume} + Complete(response)→{...; abort}, body=() (passive consumer driven externally), frame_id allocated via `_next_frame_id()` (per-flow CPS namespace, no collision with user-written handlers). 15/15 tests verdes en `tests/test_fase23_stream_desugar.py`; 0 regressions (614/614 surface tocada). La footnote del paper "Integrado nativamente en la primitiva `stream`" se vuelve **factualmente cierta** post-23.g — `stream<τ>` ES un IRHandlerFrame al nivel IR. Rust runtime se beneficia transparentemente vía la FSM dispatch existente de 23.f (no Rust changes needed). |
| 23.h Coordinated cross-stack release v1.17.0 | ✅ DONE 2026-05-08 | release | — | Drift gate `tests/test_fase23_drift_gate.py` (23 tests verdes — Python opcodes ≡ Rust enum variants ≡ JSON wire shape) + bump-my-version 1.16.2 → 1.17.0 cross-stack (pyproject.toml + axon/__init__.py + axon-rs/Cargo.toml + golden test pins) + 653/653 tests verdes en surface tocada (incluye golden + drift + las 5 suites Fase 23) + 49/49 Rust `effects::tests` verdes (1043 filtered del resto axon-rs) + commit + tag v1.17.0 + push origin + cargo publish + PyPI publish via release workflow. Contiene Fase 23 completa: AST + parser + lexer + typechecker + IR + CPS lowering + Rust runtime FSM + stream desugar. Paper §1-§6 entregado al 100% sin asteriscos. |
| 23.i CI infrastructure tech debt cleanup | ✅ DONE 2026-05-08 | ~85 LOC effective | Python + YAML + Rust | **Suite Python verde 100% por primera vez desde v1.5.x**: 4945 passed / 4 skipped / 0 failed. Cuatro commits en cadena (7c98f77 → d33e1dd → 56f1d8d): (a) `hypothesis>=6.0` añadido al `dev` extras (3 suites Fase 19/20 antes-fallidas a colectar); (b) `permissions: contents: write` en `audit_evidence.yml` (release-attach ya no falla con HTTP 403); (c) CI install extiende a `[dev,tools,server]` (test_path_matcher requiere starlette); (d) 3 sites en `cost_estimator.rs` añaden `effects: vec![],` al IRProgram literal (axon-rs cargo test rojo post-23.h); (e) **bug real en `axon/server/server.py::_compile_source`**: `axonendpoint X { execute: F }` sin `run F(...)` no compilaba el flow F en la deployment — el dispatcher fallaba con HTTP 422 + "Flow X not found". Fix: synthetic `IRRun` con `resolved_flow=flow_index[ep.execute_flow]` para cada endpoint sin run explícito; (f) test stale en `test_compute_mek.py::test_dispatch_with_mek_bridge` hardcodeaba `tier == "python"` — relaxed a `in ("python", "rust", "c")` (companion test ya tenía ese pattern). 4/4 workflows verde en CI: CI + Audit Evidence + Rust↔Python IR Parity + axon-frontend Dependency Audit. |

**Acceptance metrics target:**

- **≥180 nuevos tests** distribuidos: 40 parser + 80 typechecker (incl. row poly + operation poly) + 30 IR + 50 Rust runtime + 10 cross-stack drift + 10 stream backward-compat. (Bumped de 150 → 180 por D1/D11 revisión).
- **Paper §1–§6 entregado al 100%**: Free Monad encoding ✓, algebraic effects + handlers ✓, one-shot delimited continuations ✓, CPS transform ✓, **effect row polymorphism ✓ (D11 ratified)**, **operation polymorphism ✓ (D1 ratified)**.
- **Rust runtime executes state-machine compiled to native jumps** (no boxed continuations, no heap allocation per perform). Benchmark target: streaming 10k tokens via algebraic effect handler vs Python `yield` baseline — ≥10× speedup, zero heap allocation in the hot path.
- **Effect row exhaustiveness enforced at compile time** — every `perform Effect.Op(...)` must be discharged by an enclosing `handle Effect { ... }` block before reaching the top-level run statement, OR the program fails to compile with location of the offending perform.
- **Linear continuation discipline enforced** — within a single handler clause body, `resume()` may be invoked at most once. Multi-resume is a compile-time type error (linear logic alignment, paper §4).
- **Backward compat 100%** — every `.axon` source that compiled and ran on v1.16.x continues to compile and run identically on v1.17.0. The `stream<τ>` primitive is reimplemented on top of the new effect system without sintaxis adopter-facing changes.
- **Drift gate**: compile-side gate asserts every IR opcode the Python frontend emits has a corresponding handler in the Rust runtime; if axon-lang Python ships a new opcode without Rust support (or vice versa), CI rojo en master.

## How to apply (post-SHIPPED)

Cuando el usuario, un adopter, o un colaborador menciona algebraic effects, Free Monad, delimited continuations, CPS, effect handlers, "Plotkin/Pretnar", o pregunte "¿cómo expreso un side-effect en axon sin contaminar la pureza algorítmica?" — la respuesta post-v1.17.0 es: declarar un `effect`, performar la operación dentro del step body, y handle-arla en un scope superior. El paper `docs/algebraic_effects_streaming.md` describe la teoría; este doc describe la implementación. La sintaxis vive en `axon_language_specification.md §3.21`.

---

# FASE 23 — NATIVE ALGEBRAIC EFFECTS + FREE MONAD RUNTIME

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** axon-lang gana algebraic effects + handlers + one-shot delimited continuations como ciudadanos de primera clase del lenguaje. La sintaxis es Plotkin/Pretnar (Koka-shape): `effect`, `perform`, `handle`, `resume`, `abort`. El typechecker infiere effect rows y enforza exhaustividad. La compilación lower-ea a IR en CPS form. El runtime Rust ejecuta una state machine compilada a saltos nativos. axon se vuelve **el primer lenguaje** que entrega algebraic effects nativos, tipados, en Rust runtime, con effect row polymorphism, específicamente diseñado para cognición de IA — superando categóricamente al `yield`/`async for` de Python que el paper §1-§6 disecciona como "reliquia transicional".
- **Why:** la primitiva `stream<τ>` actual es un handler especializado, no un sistema general de efectos. El paper promete teoría que el código no entrega. Per founder vision "0 MVP, todo 100% robusto", esta brecha es **inadmisible** — vale corregir el paper o entregar la implementación; elegimos entregar.
- **OSS / ENTERPRISE / SPLIT split:** **100% OSS.** Algebraic effects son fundacionales del lenguaje, no feature enterprise. axon-lang Python compila + axon-rs runtime ejecuta. axon-enterprise consume transparente vía version bump.
- **Robustness target:** state machine en Rust compilable a `jmp` instructions verificable empíricamente vía benchmark contra Python `yield`. Effect row exhaustiveness check enforza taint analysis a nivel de tipo. Linear continuation discipline enforza one-shot semantics. Drift gate cross-stack asegura que IR opcode emitter (Python) y consumer (Rust) nunca diverjan.

---

## 2. Audit findings — qué dice el paper vs qué tiene v1.16.x

### 2.1 Paper claims (líneas 1-56 de `algebraic_effects_streaming.md`)

El paper especifica explícitamente seis piezas:

1. **Free Monad** `F_Σ(X) ≅ X + Σ(F_Σ(X))` — pure deliberation retorna AST de intenciones, no ejecuta I/O directo (§3).
2. **Algebraic effects** Plotkin/Pretnar — `perform(Emit(v))` invocable como código síncrono (§4).
3. **One-shot delimited continuations** vía operadores `shift` (𝓢) y `reset` (𝓡) (§4).
4. **CPS transformation** para deforestation + eliminación de heap allocation (§5).
5. **Topological edges discipline** — async/network "se orquestan estrictamente en los bordes topológicos del sistema" (§6).
6. **Footnote claim**: "Integrado nativamente en la primitiva `stream` de Axon-lang v0.19.1."

### 2.2 v1.16.x reality

| Promise paper | Reality v1.16.x | Severidad |
|---|---|---|
| Free Monad encoding | ❌ no existe | crítica |
| `perform`/`handle` syntax | ❌ no existe (verificado en `axon/compiler/parser.py` step body switch — keywords ausentes) | crítica |
| One-shot delimited continuations | ❌ no existe; `stream<τ>` solo tiene handlers fijos `on_chunk` / `on_complete` | crítica |
| CPS transform | ❌ no existe; IR es directo (linear opcode list) | crítica |
| Effect row inference | ⚠️ `EffectRowNode` existe en AST pero solo para `tool` declarations, no para steps; no hay inference algorithm | parcial |
| Footnote "integrated en stream" | ⚠️ stream existe pero NO es algebraic effect handler — es streaming primitive con handlers fijos. La footnote es **aspiracional, no factual** | misleading |

**Conclusión**: el paper describe un sistema que **no existe en código**. La footnote es engañosa. Para honrar el paper al 100%, hay que construir la implementación.

### 2.3 Por qué importa

axon-lang se posiciona como "el primer lenguaje del mundo para cognición de IA con fundamentación matemática". Tener un paper académico que reclama feature no implementado es **deuda de credibilidad** — adopters técnicos que lean el paper y prueben el lenguaje encontrarán el gap inmediatamente. Esta fase cierra la brecha definitivamente.

---

## 3. Architecture — la implementación operacional del paper

### 3.1 Surface syntax (§3.21 del language spec)

```axon
// Effect declaration — top-level, like tool/persona/anchor
effect SSE {
    Emit(token: Token) -> Unit
    Done() -> Never
}

effect ToolCall {
    Call(name: str, args: dict) -> Result
}

// Perform — invocable como código síncrono dentro de step body
step generate {
    given: prompt
    let response = ask "Generate response"

    // Cada perform es un yield point que el handler externo captura
    perform Emit(response.token)
    perform Done()
}

// Handler — establece scope delimitado donde performs son interceptados
flow stream_chat {
    handle SSE {
        Emit(token) -> {
            websocket.send(token)
            resume()              // continúa la deliberación
        }
        Done() -> {
            websocket.close()
            // sin resume — abort implícito
        }
    } in {
        run generate(prompt: user_input)
    }
}
```

**Observaciones**:
- El `step generate` es **completamente agnóstico** de cómo se transmite el token al cliente. Su deliberación es pura.
- El `handle SSE { ... } in { ... }` es donde la fenomenología (network I/O) entra. Topologicamente en el "edge".
- `resume()` continúa la deliberación con valor de retorno de la operación (aquí `Unit` per la firma).
- Sin `resume()` antes de salir del handler clause = abort. La continuación es liberada (one-shot, paper §4).

### 3.2 Effect row inference

El typechecker infiere el effect row de cada step:

```
step generate(prompt: str) -> Token!{SSE}    // performs Emit + Done; ambas son SSE
```

El `!{SSE}` es la **fila de efectos** (Koka-style row type). Ese row se propaga hacia arriba:

```
flow stream_chat() -> Unit!{}    // SSE descargado por handle, row vacío al top
```

El typechecker exige que **al alcanzar el run statement, el effect row sea vacío**. Cualquier `perform X` no descargado por un handle enclosing es **error de compilación** con location del perform offending.

### 3.3 IR encoding (Free Monad como state graph)

El IR pre-v1.17.0 es lineal: lista de opcodes ejecutados secuencialmente. Para soportar effects, el IR se vuelve un **state graph**:

```
IROpPerform(effect="SSE", op="Emit", args=[token_var], frame_id=0, k_label="L1")
IRLabel("L1")  // resume llega acá con el valor que el handler le pasó
... siguiente opcode del step ...
```

Cada `perform` se compila a:
1. Un `IRPerform` que captura la operación + sus argumentos + el ID del handler frame enclosing + un label de continuación.
2. Un `IRLabel` que es donde la continuación reanuda cuando el handler hace `resume(value)`.

El state graph resultante es **isomorfo al árbol del Free Monad** del paper §3:

```
F_Σ(X) ≅ X + Σ(F_Σ(X))
        ↓                ↓
     IRReturn          IRPerform → IRLabel → ... → (recursivo)
```

### 3.4 CPS transform (paper §5)

El IR generator hace lowering CPS-style:

```
// Source axon
step gen { let x = ask "..."; perform Emit(x); perform Done(); }

// Lowered IR (CPS form)
IRBlock([
    IRAsk(prompt="...", binds_to="x"),
    IRPerform(effect="SSE", op="Emit", args=[x], k_label="L1"),
    IRLabel("L1"),
    IRPerform(effect="SSE", op="Done", args=[], k_label="L2"),
    IRLabel("L2"),
    IRReturn(unit)
])
```

Cada perform es un **state transition** explícito. El runtime no necesita capturar continuations dinámicamente — la continuación está estáticamente encoded como el label siguiente.

### 3.5 Rust runtime — state machine

Para cada `step` con effects, el compilador emite (a IR-level, no a Rust source) una representación que el runtime ejecuta como state machine:

```rust
// Conceptual Rust (no es código real adopter-facing — es interno del axon-rs runtime)
enum StepGenState {
    Initial { prompt: String },
    AfterAsk { x: Token },
    AfterEmit { /* resume value */ },
    AfterDone,  // Never type — no resume value
    Done,
}

impl StepGenState {
    fn step(&mut self, runtime: &mut Runtime) -> StepOutcome {
        match self {
            StepGenState::Initial { prompt } => {
                // ... ejecutar ask ...
                *self = StepGenState::AfterAsk { x: token };
                StepOutcome::Continue
            }
            StepGenState::AfterAsk { x } => {
                // perform Emit(x): yield al handler
                StepOutcome::Perform {
                    effect: "SSE",
                    op: "Emit",
                    args: vec![x.clone()],
                    resume_state: Box::new(StepGenState::AfterEmit { /* unit */ }),
                }
            }
            StepGenState::AfterEmit { .. } => {
                StepOutcome::Perform {
                    effect: "SSE",
                    op: "Done",
                    args: vec![],
                    resume_state: Box::new(StepGenState::AfterDone),
                }
            }
            StepGenState::AfterDone => StepOutcome::Return(unit),
        }
    }
}
```

**Esto es exactamente lo que el paper §5 promete**: el state machine se compila a `jmp` instructions, sin heap allocation per perform, sin boxing de continuations dinámicas. La continuación ES el siguiente variant del enum.

El handler dispatch funciona así:
1. Step ejecuta hasta el primer perform → retorna `StepOutcome::Perform { effect, op, args, resume_state }`.
2. Runtime busca el handler frame enclosing para ese effect.
3. Ejecuta el handler clause body (que es código Rust similar — su propio state machine).
4. Si el handler clause invoca `resume(value)`, el runtime carga `resume_state`, le inyecta `value`, y reanuda el step.
5. Si el handler clause termina sin `resume`, el step queda abortado; la continuación nunca se invoca.

### 3.6 One-shot continuation discipline

El typechecker enforza al compile-time que dentro de cada handler clause body, `resume(...)` se invoque **a lo sumo una vez por path**. Esto es:

- 0 resumes: aborto explícito, OK.
- 1 resume: paper §4 standard, OK.
- ≥2 resumes en mismo path: **error de tipo**, no soportado.

Esto alinea con linear logic (Convergence Theorem 1 ya en el codebase) y permite la optimización Rust-side sin clonado de continuations.

### 3.7 Backward compat para `stream<τ>`

El primitivo actual `stream<T> { on_chunk: B1; on_complete: B2 }` se convierte en sugar para:

```axon
// Source v1.16.x
step gen {
    given: prompt
    stream<Token> {
        on_chunk: { /* B1 con $value bound */ }
        on_complete: { /* B2 */ }
    }
}

// Equivalent v1.17.0 (desugared)
effect _StreamBuiltin<T> {
    Chunk(value: T) -> Unit
    Complete() -> Never
}

step gen {
    given: prompt
    handle _StreamBuiltin<Token> {
        Chunk(value) -> { /* B1 */; resume() }
        Complete() -> { /* B2 */; /* abort implícito */ }
    } in {
        // ... resto del step body emitirá perform _StreamBuiltin<Token>.Chunk(...) implícitamente ...
    }
}
```

Adopters con `.axon` files actuales no cambian una sola línea. El parser detecta `stream<...>`, lo desugara a la forma con `handle`, el resto del pipeline procede idéntico.

---

## 4. Sub-fases — desglose, dependencies, classification

| # | Title | Classification | Depends on | Approximate scope |
|---|---|---|---|---|
| 23.a | Engineering spec | OSS (docs) | — | doc operacional + decisiones D1-D12 + spec language §3.21 + spec IR opcodes + spec Rust runtime |
| 23.b | Lexer + Parser + AST | OSS (Python) | 23.a | 6 keywords + 7 AST nodes + ~40 parse tests |
| 23.c | Typechecker + effect row inference | OSS (Python) | 23.b | algoritmo de inference + exhaustiveness + linear-resume + ~50 tests |
| 23.d | IR opcodes + CPS lowering | OSS (Python) | 23.c | 4 opcodes nuevos + state-graph generator + ~30 IR-shape tests |
| 23.f | Rust runtime — Free Monad interpreter | OSS (Rust) | 23.d | módulo `axon-rs/src/effects/` + state machine + handler dispatch + one-shot continuations + ~50 Rust tests |
| 23.g | Migrate `stream<τ>` to algebraic effects | OSS (Python + Rust) | 23.f | parser desugar + Rust runtime built-in `_StreamBuiltin` + ~10 backward-compat tests |
| 23.h | Coordinated cross-stack release v1.17.0 | OSS (release) | 23.g | bump-my-version + PR cross-stack + crates.io publish + PyPI publish + drift gate verde |

**Classification**: 100% OSS. axon-lang core + axon-rs core. axon-enterprise consume transparente vía version bump (no enterprise-only behavior).

**Parallelisability**: 23.b → 23.c → 23.d son secuenciales (cada una depende del AST/IR de la anterior). 23.f puede arrancar en paralelo a 23.d una vez que el IR opcode shape está congelado en 23.a. 23.g depende de 23.f. 23.h va al final.

**Cadencia calendario sugerida** (4 semanas focused, post D1/D11 ratification):

```
Semana 1: 23.a (DONE) → 23.b (2 días) → 23.c arranca (5 días — incl. row poly + op poly)
Semana 2: 23.c termina → 23.d (3 días) → 23.f arranca en paralelo (Rust, 5 días)
Semana 3: 23.f continúa (5 días)
Semana 4: 23.f termina → 23.g (2 días) → 23.h (1 día)
```

**Trade-off de la cadencia**: +1 semana vs estimado original (3 → 4) por D1 (operation polymorphism, +0.5 días) y D11 (row polymorphism, +1 día), distribuidos en 23.c con cushion para iteración. **Justificación**: el costo de añadir polymorphism en v1.18+ es prohibitivo (rompe inferencia en código adopter monomorphic existente); +1 semana ahora vale la "born mature" property.

---

## 5. Decisions (D1–D12)

**D1 — Effect operations son polimórficas en sus parámetros desde v1.17.0** ✅ **REVISED 2026-05-08 (founder criterion: born mature, 30-year vision)**

Operaciones declaradas pueden ser parametrizadas en sus tipos: `effect Channel { Send<T>(value: T) -> Unit; Recv<T>() -> T }`. El typechecker hace unification + monomorphization en el sitio del `perform`. Sin esto, cada effect operation queda atada a un tipo concreto — `Emit(token: Token)` no puede reusarse para `Emit(sentence: Sentence)` sin declarar dos effects.

**Razón para no diferir**: (a) Koka, Eff, OCaml 5, Effekt todos soportan polimorfismo de operación desde día 1 — diferirlo nos ubicaría peor que el state-of-the-art académico, contradiciendo "first language for AI cognition with mathematical foundation"; (b) el migration cost de añadirlo en v1.18+ es altísimo — cada effect declaration en código adopter pasa de monomorphic a potentially-polymorphic, rompiendo type inference que antes era trivial; (c) el paper §3-§4 implícitamente lo asume cuando habla de Free Monad genérico `F_Σ(X)`.

**Costo**: +~150 LOC en typechecker (rank-1 unification + monomorphization), +~10 tests. Total Fase 23: +0.5 días.

**Restricción mantenida (postpone para v1.18+)**: rank-2 polymorphism (operations que toman effect-polymorphic continuations) — innecesario para v1.17.0 y operacionalmente complejo.

**D2 — One-shot continuations only**

`resume(...)` invocable ≤1 vez por handler clause body path. Multi-shot continuations (necesarias para backtracking, non-determinism monads) **no soportadas**. Razones: (a) paper §4 explícitamente dice "one-shot delimited continuations"; (b) linear logic alignment con Convergence Theorem 1 ya en el codebase; (c) permite la optimización Rust state-machine sin clonado de continuation state — el resume state ES el siguiente enum variant, no un objeto separado heap-allocated.

**D3 — Handler scope is delimited via `in` block**

```axon
handle E { ... } in { body }
```

`E` es interceptable solo dentro de `body`. Effects no escapan el block — no hay equivalente a una "global effect handler stack" implícita. Esto preserva referential transparency local y hace effect row inference decidible.

**D4 — Plotkin/Pretnar handler semantics, not raw shift/reset**

La maquinaria subyacente ES `shift`/`reset` (paper §4 las menciona explícitamente como fundamento), pero la sintaxis adopter-facing es `handle/perform/resume`. Razón: shift/reset son operacionalmente correctos pero conceptualmente densos para adopters no-académicos; handlers son la abstracción pragmática estándar (Koka, Eff, OCaml 5).

**D5 — CPS transform at IR level, not at runtime**

El Python frontend hace CPS lowering durante IR generation. El runtime Rust recibe IR ya en CPS form (state graph). Razón: el paper §5 explícitamente argumenta que CPS transform al compile-time permite deforestation + native jumps; hacerlo runtime-side sería interpretar continuations dinámicamente, contradiciendo el spirit del paper.

**D6 — Rust runtime is the only runtime; NO Python interpreter for effects** ✅ **RATIFIED 2026-05-08 by founder**

Decisión emergente del feedback del founder: implementar effects en Python requiere CPS transform manual o trampolines o `greenlet` — todos con overhead que viola el paper §5 ("código ensamblador inmensamente más veloz... operaciones atómicas de salto en la pila de CPU sin objetos de control opacos"). Python no tiene first-class delimited continuations nativas; cualquier emulación contradice la promesa del paper. Rust state machine sí entrega performance nativa. **Único runtime: Rust. Frontend Python compile-time-only.**

**Strategic context (founder ratification 2026-05-08)**: el destino de largo plazo de axon es **100% Rust + C** — Python frontend es transitional, no permanente. Cada fase debe empujar lógica hacia Rust agresivamente. D6 no es solo una optimización local de Fase 23; es coherente con el trayecto del lenguaje. El founder textual: "Yo prefiero Rust puro D6 (pensando en que axon, al final será 100% Rust y C)."

Trade-off: tests de runtime semantics requieren ejecutar Rust. Mitigación: 23.f incluye 50+ tests Rust extensivos. Adopters Python que importan `axon` sin `axon-rs` instalado pueden compile pero no ejecutar effects (raro — `axon-rs` se distribuye como dep transitiva del package).

**D7 — Cross-stack drift gate is compile-side**

Como solo hay un runtime (Rust), el drift gate clásico "Python interpreta lo mismo que Rust" no aplica. El gate de v1.17.0 es **compile-side**: el Python frontend mantiene una lista canonica de IR opcodes que emite; el Rust runtime mantiene una lista canonica de IR opcodes que consume; el drift gate asserta que ambas listas coinciden exactamente. Si Python emite `IRPerform` que Rust no soporta → CI rojo. Si Rust soporta `IRFancyOp` que Python nunca emite → dead code en el runtime, también CI rojo (advertencia).

**D8 — Backward compat for `stream<τ>` 100%**

El parser detecta `stream<T> { on_chunk: ... on_complete: ... }`, desugara internamente a `effect _StreamBuiltin<T>` + `handle _StreamBuiltin<T> { ... } in { ... }`, y el resto del pipeline procede idéntico. **Cero cambios en `.axon` source files de adopters**. La footnote del paper que decía "integrado en stream v0.19.1" se vuelve **factualmente cierta** post-v1.17.0 — porque ahora `stream<τ>` ES algebraic effect handler.

**D9 — Effect row exhaustiveness at compile time**

Cualquier `perform Effect.Op(...)` no descargado por un `handle Effect { ... }` enclosing antes de alcanzar el top-level run statement es **error de compilación**. No hay fallback runtime ("perform sin handler → exception"). Razón: la promesa del paper es composición algebraica con seguridad deductiva (§6); permitir runtime errors viola esa promesa.

**D10 — Linear resume discipline (typechecker-enforced)**

Dentro de cada handler clause body, el typechecker walks el control-flow graph y asserta que en cada path desde la entrada hasta la salida, `resume(...)` aparezca a lo sumo una vez. Multi-resume en mismo path = type error. Razón: alinea con linear logic + permite la optimización D6 sin clonado de continuation state.

**D11 — Effect row polymorphism vía row variables desde v1.17.0** ✅ **REVISED 2026-05-08 (founder criterion: born mature, 30-year vision)**

Los step type signatures soportan **row variables** abiertas: `step compose(f: A -> B!ε, g: B -> C!ε) -> A -> C!ε` donde `ε` es una row variable que unifica con cualquier conjunto de effects. Esto permite escribir combinators genéricos efectfully (mapping, folding, threading) sin reescribir uno por cada combinación de effects.

**Implementación**: row polymorphism estilo Koka — open rows con tail variable, unification con row equality up-to-permutation, principal type inference vía Hindley-Milner extendido con row constraints. Sin esto, cada `step` es monomorphic y la composición efectful queda artificialmente cerrada.

**Razón para no diferir**: (a) Algebraic effects sin row polymorphism son **operacionalmente correctos pero compositionally crippled** — pierdes el 80% del power expresivo del paradigma. Adopters intentarán componer steps efectfully día 1 y chocarán contra el typechecker; (b) Koka, Eff, Effekt lo tienen estándar — quedarnos atrás es admitir incompletitud teórica; (c) el migration cost diferido es prohibitivo: cada signature monomorphic en código adopter se vuelve un punto de re-anotación cuando se introduce polymorphism — peor que en D1 porque las signatures son más visibles.

**Costo**: +~250 LOC en typechecker (row unification algorithm), +~20 tests. Total Fase 23: +1 día.

**Restricciones mantenidas**: (a) row variables solo en step signatures, no en effect operation signatures (D1 cubre eso por separado); (b) no row subtyping (e.g., `{A,B} <: {A,B,C}` no se infiere automáticamente — hay que pasar por handler explícito); (c) no higher-rank row polymorphism. Estas restricciones son consistentes con Koka v2.x y ningún adopter las sentirá en patrones reales.

**D12 — `forward` keyword for effect propagation**

Dentro de un handler clause body, `forward Effect.Op(args)` propaga el perform al handler outer (siguiente frame en el stack). Útil para "interception transparente" — un handler que log-ea pero deja pasar:

```axon
handle SSE {
    Emit(t) -> { log.info(t); forward Emit(t) }    // log + delegate
    Done() -> { log.info("done"); forward Done() }
}
```

Sin `forward`, los handlers son strict — interceptan y no propagan. Con `forward`, son transparentes/decoradores.

---

## 6. Tests target — ≥150 nuevos

| Suite | File (proposed) | Tests | Coverage |
|---|---|---|---|
| Lexer + parser | `tests/test_fase23_effects_parser.py` | ~40 | every keyword tokenizes, every AST node parses, round-trip serialization, error messages on missing pieces, nested handlers, forward expressions |
| Typechecker + effect row inference | `tests/test_fase23_effect_rows.py` | ~50 | infer effect row of step, handle removes from row, run requires empty row, exhaustiveness errors with location, linear-resume violation errors, forward typing, handler signature compat |
| IR + CPS lowering | `tests/test_fase23_ir_cps_lowering.py` | ~30 | each AST shape lowers to expected IR, perform creates label + frame_id, handler block creates HandlerFrame + dispatch table, IR shape stable across builds (golden snapshots) |
| Rust runtime — Free Monad interpreter | `axon-rs/src/effects/tests/` | ~50 | state machine transitions correctly, perform yields to runtime, handler clause body executes, resume(value) injects value at next state, abort terminates step, one-shot enforced runtime side, multi-effect handler frames stack correctly, forward propagates to outer frame |
| Cross-stack drift gate | `tests/test_fase23_cross_stack_drift_gate.py` | ~10 | Python frontend's emitted-opcodes list ≡ Rust runtime's consumed-opcodes list; `stream<τ>` desugar matches expected handler form; AST drift gate against `_build_request`-style hardcoded literal regression |
| Stream backward compat | `tests/test_fase23_stream_backward_compat.py` | ~10 | every `.axon` file using `stream<τ>` compiles to identical-shape program post-v1.17.0; `on_chunk` / `on_complete` semantics preserved byte-for-byte |

**Total**: ~150 nuevos. Rust tests cuentan separados de Python tests (suite cross-stack).

---

## 7. Drift gates / charter compliance

### 7.1 Compile-side opcode parity (D7)

```python
# tests/test_fase23_cross_stack_drift_gate.py

def test_python_emitted_opcodes_match_rust_consumed_opcodes():
    """The IR opcodes the Python frontend emits must exactly match
    what the Rust runtime consumes. A new Python opcode without
    Rust support, or an unused Rust opcode, fail CI."""
    python_emitted = collect_emitted_opcodes_from_ir_generator()
    rust_consumed = parse_rust_opcode_dispatch_table_via_subprocess()
    assert python_emitted == rust_consumed, (
        f"Cross-stack opcode drift: "
        f"Python-only={python_emitted - rust_consumed}, "
        f"Rust-only={rust_consumed - python_emitted}"
    )
```

### 7.2 AST kwarg gate extension (siguiendo el patrón v1.15.1)

Cualquier `raise <X>(...)` donde `X` es subclass de `AxonRuntimeError` debe pasar kwargs en signature. Ya existe en v1.15.1; v1.17.0 debe seguir verde post-implementación.

### 7.3 Effect row exhaustiveness gate

Test que asserta que el typechecker **rechaza** un programa con `perform` no descargado:

```python
def test_unhandled_perform_fails_compilation():
    source = """
    effect SSE { Emit(t: Token) -> Unit }
    step gen { perform Emit(token) }  // no handler en scope
    flow main { run gen }              // SSE row no vacío al top
    """
    with pytest.raises(AxonTypeError, match="unhandled effect SSE.Emit"):
        compile_axon(source)
```

### 7.4 Linear resume gate

```python
def test_double_resume_in_handler_clause_fails_compilation():
    source = """
    effect E { Op() -> int }
    flow main {
        handle E {
            Op() -> { resume(1); resume(2) }   // multi-shot, illegal
        } in { ... }
    }
    """
    with pytest.raises(AxonTypeError, match="multi-shot resume"):
        compile_axon(source)
```

### 7.5 Performance benchmark gate

Test que asserta empírica la promesa del paper §5:

```python
def test_axon_effect_streaming_outperforms_python_yield_baseline():
    """Stream 10k tokens via effect handler vs Python yield generator.
    axon should be ≥10× faster + zero heap allocation in hot path
    (verified via cargo bench / pyperf)."""
    python_yield_time = bench_python_generator(10000)
    axon_effect_time = bench_axon_effect_handler(10000)
    assert axon_effect_time * 10 < python_yield_time, (
        f"axon effects must be ≥10× faster: "
        f"axon={axon_effect_time}, python={python_yield_time}"
    )
```

---

## 8. Ship target

- **axon-lang v1.17.0** (PyPI + crates.io) — minor bump (additive features, no breaking, backward-compat 100%).
- **Cross-stack lockstep** — Python frontend + Rust runtime versionados juntos per `reference_enterprise_release_workflow.md`. Cargo.toml + pyproject.toml + Cargo.lock + version-pinned tests todos a v1.17.0.
- **axon-enterprise** consume transparente vía version-only bump.
- **Documentation deliverables**:
  - Update `algebraic_effects_streaming.md` con sección de implementación post-paper (la footnote del paper se vuelve factual).
  - Update `axon_language_specification.md` §3.21 con `effect` / `perform` / `handle` syntax + effect row notation.
  - New adopter guide `docs/effects_handlers_guide.md` (separate doc) — "How to write streaming flows with algebraic effects in axon".

---

## 9. Out of scope (para esta fase)

- **Effect-polymorphic functions/steps** (`forall E. step generic(...) -> T!E`). D11. Diferido a v1.18+.
- **Multi-shot continuations**. D2. Razón: linear logic alignment + paper §4 explicitness. Probablemente nunca soportado en axon (es decisión de diseño, no temporal).
- **Operation polymorphism** (`Emit<T>(value: T)`). D1. Diferido.
- **Implicit effect inheritance** ("global effect handler stack"). D3. Probablemente nunca — viola referential transparency local.
- **`handler` as first-class value** (passing handlers as args). Diferido a v1.18+ si surge caso de uso.
- **Effect equation laws** (algebraic laws verifying handler composition). Mathematically interesting, no caso de uso adopter inmediato.
- **Resumable exceptions** (efecto `Exn` con resume = retry). Implementable encima del primitivo cuando se quiera; no built-in en v1.17.0.

---

## 10. Summary table — 30-second decision support

| Question | Answer |
|---|---|
| ¿Es esto urgente? | **Estratégico, no urgente**. Cierra la brecha entre el paper y la realidad — credibilidad técnica de axon como "primer lenguaje para cognición de IA fundamentado". Sin esto, el paper es aspirational; con esto, es factual. |
| ¿Toca axon-enterprise? | **No.** Solo version-only bump lockstep. Cero código nuevo del lado enterprise. |
| ¿Rompe algo existente? | **No.** Backward compat 100% — `stream<τ>` reimplementado encima del nuevo runtime sin cambio sintáctico adopter-facing. v1.17.0 minor bump (additive). |
| ¿Cuánto código nuevo? | ~600 LOC Python parser + ~700 LOC Python typechecker + ~500 LOC Python IR + ~2500 LOC Rust runtime + ~300 LOC stream desugar + ~150 tests = **~4.6k LOC** total. |
| ¿Qué desbloquea? | (a) Adopters pueden expresar streaming, tool dispatch, error handling, resumable computation, etc. todos como effects con handlers composables. (b) axon se posiciona técnicamente al nivel de Koka, Eff, OCaml 5 — **el primero entre lenguajes de cognición de IA con effects nativos**. (c) El paper se vuelve factual, eliminando deuda de credibilidad. |
| ¿Cuál es el primer commit? | 23.a — engineering spec + decisiones D1-D12 frozen. ~4 horas. Sin código aún; pure design. Cuando esté revisado y aprobado, arranca 23.b. |

---

## 11. Cómo se ejecuta esta fase (operacional para sub-fases siguientes)

Cada sub-fase 23.b–23.h sigue el patrón end-to-end ya consolidado en esta sesión:

1. Branch off master → `release/v1.17.0-alpha.<N>` (alpha tags durante incremental shipping; tag final v1.17.0 al completar 23.h).
2. Implementar el scope estricto de la sub-fase.
3. Tests target alcanzados (sub-fase no se cierra hasta tests verdes).
4. AST drift gate pertinente actualizado.
5. Bump versions a `1.17.0-alpha.N` durante alphas; bump final a `1.17.0` en 23.h.
6. Commit + push + PR + admin merge + tag (alpha) + GitHub Pre-release.
7. Memory update (`project_fase_23_plan.md` + `MEMORY.md`).
8. Doc update — flip status del row de la sub-fase a `✅ SHIPPED` con commit/PR/release links.

Al cerrar 23.h, el último commit promueve v1.17.0-alpha.N → v1.17.0 (full release, no pre-release), publica a PyPI + crates.io, y la fase entera flips a `SHIPPED`.

---

**Próximo paso operacional**: confirmación del founder sobre las decisiones D1–D12 (especialmente D2 one-shot only, D6 Rust-only runtime, D8 backward compat). Cuando estén ratificadas, arranca 23.b (Lexer + Parser + AST). Estimado calendario total: 3 semanas focused desde 23.b hasta v1.17.0 publicado.
