# Backlog de Ejecución — Fase E

Este archivo lista las sesiones planeadas y ejecutadas para la Fase E (Integración y Producción) del programa AXON.

## Objetivo de Fase

Conectar la plataforma runtime (Fase D: 185 rutas, 579 tests, 47K+ líneas) con sistemas reales — backends LLM, protocolo MCP, y endurecimiento para producción. La Fase D entregó la infraestructura completa; la Fase E la hace operativa con proveedores reales.

## Estado heredado de Fase D

| Métrica | Valor |
|---------|-------|
| Módulos fuente | 61 archivos `.rs` |
| Líneas fuente | 47,239 |
| Tests de integración | 576 |
| Rutas API | 181 (al cierre D147) |
| Structs públicos (server) | 129 |
| Dominios API | 21 |

## Backlog Inicial

1. Backend registry — gestión de backends LLM a nivel servidor con API keys y health probing.
2. Backend key resolution — conectar el registry al path de ejecución real.
3. Backend call metrics — métricas por proveedor (calls, errors, latencia).
4. Backend fallback chain — failover automático entre proveedores.
5. MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
6. Backend rate limiting — throttling por proveedor respetando límites.

## Sesiones

### Sesión E1: Backend Registry — configuración server-managed de backends LLM y health probing

**Objetivo de sesión:**
Implementar un registro de backends LLM a nivel servidor que permita gestionar API keys en runtime (sin depender exclusivamente de variables de entorno), verificar disponibilidad de proveedores, y exponer el estado de cada backend vía API.

**Alcance cerrado:**
- Implementar `BackendRegistryEntry` struct:
  - **Campos:** name, api_key (`#[serde(skip_serializing)]` — nunca se filtra a JSON), enabled, status (unknown/healthy/degraded/unreachable/no_key), last_check_at, last_check_latency_ms, total_calls, total_errors.
  - `#[serde(default)]` en todos los campos opcionales para backward compatibility.
- Cuatro endpoints nuevos:
  - `GET /v1/backends` — lista los 7 backends soportados (anthropic, openai, gemini, kimi, glm, openrouter, ollama) mergeados con el registry. Muestra `key_source`: "server" (key en registry), "env" (key en env var), "none" (sin key).
  - `PUT /v1/backends/{name}` — registrar/actualizar backend con API key y enabled flag. Valida que el nombre sea un backend soportado. Audit-logged.
  - `DELETE /v1/backends/{name}` — eliminar del registry (revierte a env-only). Audit-logged.
  - `POST /v1/backends/{name}/check` — health probe via llamada LLM mínima (5 tokens max). Actualiza status y latencia en registry. Ejecuta fuera del lock (CPU/network bound).
- Función `resolve_backend_key(state, backend)`:
  - Prioridad: server registry key → env var → error.
  - Si backend está disabled en registry → error inmediato.
- Campo `backend_registry: HashMap<String, BackendRegistryEntry>` en `ServerState`.
- No entra: wiring al path de ejecución (E2), métricas por llamada (E3), fallback chain (E4).

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - **Structs:** `BackendRegistryEntry` (8 campos, api_key skip_serializing).
  - **Helpers:** `default_backend_status()`, `resolve_backend_key()`.
  - **Handlers:** `backends_list_handler`, `backends_put_handler`, `backends_delete_handler`, `backends_check_handler`.
  - **ServerState:** +1 campo `backend_registry`.
  - **Routes:** 181→185 (+4 backend routes).
  - **Doc comment:** actualizado con `/v1/backends`.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (579 total):
  - `backend_registry_entry_serde` — serialización/deserialización, api_key no aparece en JSON, defaults correctos.
  - `backend_resolve_key_priority` — disabled rechaza, enabled+key retorna key.
  - `backend_supported_list_complete` — los 7 backends presentes, todos lowercase.

**Verificación:**
- `cargo test`: 579 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E2:**
- **A:** Backend key resolution in server_execute — wire resolve_backend_key into execution path.
- **B:** MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
- **C:** Backend call metrics — track per-backend call count, error rate, avg latency in registry.
- **D:** Backend fallback chain — if primary backend fails, try secondary (e.g., anthropic → openai).
- **E:** Backend rate limiting — per-backend request throttling to respect provider limits.

### Sesión E2: Backend Key Resolution — wire registry keys into execution path

**Objetivo de sesión:**
Conectar `resolve_backend_key()` al path completo de ejecución: `server_execute` → `execute_server_flow` → `execute_real`, de modo que las API keys registradas a nivel servidor (E1) se usen automáticamente al ejecutar flujos, sin depender exclusivamente de variables de entorno.

**Alcance cerrado:**
- Añadir parámetro `api_key_override: Option<&str>` a tres funciones:
  - `server_execute()` en `axon_server.rs` — acepta key override, la propaga al runner.
  - `execute_server_flow()` en `runner.rs` — acepta key override, la propaga a `execute_real`.
  - `execute_real()` en `runner.rs` — si `Some(key)`, usa directamente; si `None`, cae a `backend::get_api_key()` (env var).
- Handler primario `execute_handler` (`POST /v1/execute`):
  - Resuelve key vía `resolve_backend_key(&s, &payload.backend)` dentro del lock scope donde obtiene source/source_file.
  - Pasa `resolved_key.as_deref()` a `server_execute`.
  - Si el registry tiene key → la usa. Si no → fallback a env var. Si disabled → error.
- 16 call sites restantes de `server_execute`: actualizados con `None` (backward-compatible, usan env var). Sesiones futuras pueden upgradarlos individualmente.
- CLI path (`run_run`) mantiene `None` (siempre usa env var).
- No entra: actualización de los 16 handlers secundarios para resolver desde registry (sesiones futuras), métricas por llamada (E3).

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `server_execute()`: +1 parámetro `api_key_override: Option<&str>`.
  - `execute_handler`: resuelve key desde registry antes de llamar.
  - 16 call sites restantes: actualizados con `, None`.
- `axon-rs/src/runner.rs`:
  - `execute_server_flow()`: +1 parámetro `api_key_override: Option<&str>`, lo propaga.
  - `execute_real()`: +1 parámetro `api_key_override: Option<&str>`, resuelve key condicionalmente.
  - CLI call site (`run_run`): `None`.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (582 total):
  - `execute_server_flow_accepts_api_key_override` — verifica que la firma acepta `None` y `Some`.
  - `resolve_backend_key_function_exported` — verifica que la función es accesible públicamente.
  - `backend_key_override_none_vs_some_semantics` — verifica semántica de resolución.

**Verificación:**
- `cargo test`: 582 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E3:**
- **A:** Backend call metrics — track per-backend call count, error rate, avg latency in registry after each execution.
- **B:** MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
- **C:** Backend fallback chain — if primary backend fails, try secondary (e.g., anthropic → openai).
- **D:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **E:** Wire remaining 16 handlers to resolve keys from backend registry.

### Sesión E3: Backend Call Metrics — per-backend usage tracking after each execution

**Objetivo de sesión:**
Rastrear métricas de uso real por proveedor LLM: llamadas totales, errores, tokens consumidos, latencia acumulada, y timestamp de última llamada. Exponer métricas detalladas por backend vía nuevo endpoint.

**Alcance cerrado:**
- Extender `BackendRegistryEntry` con 4 campos nuevos:
  - `total_tokens_input: u64` — tokens de entrada acumulados.
  - `total_tokens_output: u64` — tokens de salida acumulados.
  - `total_latency_ms: u64` — latencia acumulada (dividir por `total_calls` para promedio).
  - `last_call_at: u64` — timestamp Unix de última ejecución.
  - Todos con `#[serde(default)]` para backward compatibility.
- Función `record_backend_metrics(state, backend, success, tokens_in, tokens_out, latency_ms)`:
  - Crea o actualiza entry en registry.
  - Incrementa total_calls, tokens, latency. Si !success → incrementa total_errors.
  - Actualiza last_call_at.
- Wired into `execute_handler` (`POST /v1/execute`): después de audit log, dentro del lock scope.
- Nuevo endpoint `GET /v1/backends/{name}/metrics`:
  - Computa avg_latency_ms, error_rate, total_tokens en tiempo real.
  - Si no hay entry en registry → retorna zeros. Routes: 185→186.
- No entra: wiring en los 16 handlers secundarios (sesiones futuras), dashboard aggregation.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendRegistryEntry`: +4 campos.
  - `record_backend_metrics()`: nueva función helper.
  - `execute_handler`: llamada a `record_backend_metrics` post-ejecución.
  - `backends_metrics_handler`: nuevo handler con computación de avg/error_rate.
  - 3 `or_insert_with` constructors: actualizados con nuevos campos.
  - +1 ruta.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (585 total):
  - `backend_registry_new_metric_fields_serde` — serialización de nuevos campos, defaults.
  - `backend_metrics_avg_latency_and_error_rate` — computación correcta de promedios, edge case zero.
  - `backend_record_metrics_accumulation` — simulación de acumulación tras 3 llamadas.

**Verificación:**
- `cargo test`: 585 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E4:**
- **A:** MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
- **B:** Backend fallback chain — if primary backend fails, try secondary (e.g., anthropic → openai).
- **C:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **D:** Wire remaining 16 handlers to resolve keys and record metrics from backend registry.
- **E:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.

### Sesión E4: Backend Fallback Chain — automatic failover between LLM providers

**Objetivo de sesión:**
Implementar failover automático entre proveedores LLM: si el backend primario falla durante ejecución, intentar cada backend de la cadena de fallback en orden hasta que uno tenga éxito.

**Alcance cerrado:**
- Extender `BackendRegistryEntry` con `fallback_chain: Vec<String>` (`#[serde(default)]`).
- Dos endpoints de configuración:
  - `GET /v1/backends/{name}/fallback` — ver cadena de fallback configurada.
  - `PUT /v1/backends/{name}/fallback` — configurar cadena. Validación: no auto-referencia, todos deben ser backends soportados. Audit-logged.
- Función `execute_with_fallback(state, source, source_file, flow_name, primary, primary_key)`:
  - Intenta ejecución con backend primario.
  - Si falla y hay `fallback_chain` configurada: intenta cada fallback en orden, resolviendo key de cada uno vía `resolve_backend_key`.
  - Retorna `(Result, actual_backend_used)` — el caller sabe qué backend tuvo éxito.
  - Si todos fallan: retorna error original del primario.
- Wired into `execute_handler`: usa `execute_with_fallback` en lugar de `server_execute` directo. Actualiza `exec_result.backend` con el backend real usado.
- Routes: 186→187.
- No entra: wiring en otros handlers (sesiones futuras), retry con mismo backend, circuit breaker.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendRegistryEntry`: +1 campo `fallback_chain: Vec<String>`.
  - `backends_fallback_get_handler`, `backends_fallback_put_handler`: 2 handlers nuevos.
  - `execute_with_fallback()`: función de failover con resolución de keys por fallback.
  - `execute_handler`: usa `execute_with_fallback`.
  - Todos los constructors de `BackendRegistryEntry`: actualizados con `fallback_chain: Vec::new()`.
  - +1 ruta.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (588 total):
  - `backend_fallback_chain_field_serde` — serialización, deserialización, defaults.
  - `backend_fallback_chain_validation` — auto-referencia rechazada, backends desconocidos rechazados.
  - `backend_fallback_execution_logic` — simulación de failover: primario falla → fallback exitoso.

**Verificación:**
- `cargo test`: 588 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E5:**
- **A:** MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
- **B:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **C:** Wire remaining 16 handlers to resolve keys, record metrics, and use fallback.
- **D:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **E:** Backend circuit breaker — auto-disable backends after N consecutive failures, auto-recover after cooldown.

### Sesión E5: Backend Circuit Breaker — auto-disable after consecutive failures, auto-recover after cooldown

**Objetivo de sesión:**
Implementar patrón circuit breaker por backend LLM: tras N fallas consecutivas, abrir el circuito (rechazar llamadas) durante un período de cooldown. Tras cooldown, permitir una llamada de prueba (half-open). Si tiene éxito, cerrar circuito. Si falla, re-abrir.

**Alcance cerrado:**
- Extender `BackendRegistryEntry` con 4 campos:
  - `consecutive_failures: u32` — contador de fallas consecutivas (reset en éxito).
  - `circuit_open_until: u64` — timestamp Unix hasta cuando circuito está abierto (0=cerrado).
  - `circuit_breaker_threshold: u32` — fallas antes de abrir (default 5, 0=deshabilitado).
  - `circuit_breaker_cooldown_secs: u64` — duración del cooldown (default 60s).
- En `record_backend_metrics()`:
  - Falla: incrementa `consecutive_failures`. Si >= threshold → abre circuito (`circuit_open_until = now + cooldown`), status → "circuit_open".
  - Éxito: reset `consecutive_failures = 0`. Si circuito estaba abierto y cooldown expiró → cierra y status → "healthy".
- En `resolve_backend_key()`:
  - Si `circuit_open_until > 0` y `now < circuit_open_until` → error con mensaje informativo (failures, tiempo restante).
  - Si cooldown expiró → permite pasar (half-open state).
- No entra: configuración dinámica de threshold/cooldown vía endpoint (sesiones futuras), alert on circuit open.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendRegistryEntry`: +4 campos CB.
  - `default_cb_threshold()`, `default_cb_cooldown()`: helpers de defaults.
  - `record_backend_metrics()`: lógica de apertura/cierre de circuito.
  - `resolve_backend_key()`: check de circuito abierto con half-open.
  - Todos los constructors: actualizados.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (591 total):
  - `circuit_breaker_fields_serde` — serialización, defaults (threshold=5, cooldown=60).
  - `circuit_breaker_open_close_logic` — apertura tras threshold, half-open tras cooldown, reset en éxito.
  - `circuit_breaker_disabled_when_threshold_zero` — 100 fallas no abren circuito si threshold=0.

**Verificación:**
- `cargo test`: 591 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E6:**
- **A:** MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP).
- **B:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **C:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **D:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **E:** Backend status dashboard — aggregate view of all backends with circuit state, error rates, and recommendations.

### Sesión E6: MCP Exposition — exponer flujos AXON como herramientas MCP ($\mathcal{E}$MCP)

**Objetivo de sesión:**
Implementar el lado servidor del protocolo MCP: AxonServer expone cada flujo desplegado como una herramienta MCP invocable por clientes MCP externos (Claude Desktop, IDEs, otros agentes).

**Alcance cerrado:**
- `POST /v1/mcp` — endpoint JSON-RPC 2.0 implementando protocolo MCP servidor:
  - `initialize` → retorna `protocolVersion: "2024-11-05"`, capabilities (tools), serverInfo.
  - `tools/list` → cada flujo desplegado → tool MCP con nombre `axon_{flow}`, descripción, inputSchema (backend + input).
  - `tools/call` → recibe `name` y `arguments`, strip prefijo `axon_`, ejecuta vía `server_execute` con key resolution desde backend registry, retorna resultado MCP con `content[{type:"text", text:...}]`, `isError`, y metadatos `_axon` (flow, backend, latency, tokens, epistemic_taint, effects).
  - Método desconocido → JSON-RPC error -32601.
- `GET /v1/mcp/tools` — endpoint de conveniencia (no JSON-RPC) que lista herramientas expuestas.
- `McpExposedTool` struct (name, description, input_schema).
- Metadatos epistémicos: `epistemic_taint: "speculate"`, `effects: ["io", "epistemic:speculate"]` — toda data MCP nace como especulativa.
- Backend metrics registrados tras cada `tools/call`.
- Routes: 187→189.
- No entra: MCP streaming (SSE transport), resources exposition, prompts exposition.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `McpExposedTool` struct.
  - `mcp_handler`: JSON-RPC 2.0 dispatch (initialize/tools-list/tools-call).
  - `mcp_tools_list_handler`: convenience list endpoint.
  - +2 rutas, doc comment actualizado.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (594 total):
  - `mcp_exposed_tool_struct_serializes` — struct serializa correctamente.
  - `mcp_jsonrpc_protocol_shapes` — validate init/list/call/error response shapes.
  - `mcp_tool_name_prefix_convention` — `axon_` prefix y strip logic.

**Verificación:**
- `cargo test`: 594 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E7:**
- **A:** MCP streaming transport — SSE-based MCP transport for real-time tool output.
- **B:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **C:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **D:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **E:** MCP resources exposition — expose AXON traces, configs, and metrics as MCP resources.

### Sesión E7: ℰMCP Formal Compliance — alineación con principios matemáticos CSP y ΛD

**Objetivo de sesión:**
Corregir la exposición MCP (E6) para cumplir con el contrato formal de AXON: tools como CSP (§5.3), ΛD epistemic envelopes en respuestas, blame calculus (Findler-Felleisen CT-2/CT-3), y effect rows computadas — no hardcodeadas.

**Diagnóstico previo (5 brechas identificadas):**
1. ~~`inputSchema` genérico sin constraints~~ → CSP schema con `_axon_csp.constraints` (anchors del flow)
2. ~~`epistemic_taint: "speculate"` hardcodeado~~ → `EpistemicEnvelope::derived()` con certainty computada
3. ~~Sin blame en errores~~ → Blame::Caller (CT-2) / Server / Network en cada error path
4. ~~Effect rows hardcodeadas~~ → computadas desde backend (stub vs real → con/sin network)
5. ~~Sin ΛD en respuesta~~ → `epistemic_envelope` completo con ψ = ⟨T, V, E⟩

**Alcance cerrado:**
- **ΛD Epistemic Envelope en `tools/call`:**
  - `EpistemicEnvelope::derived()` con certainty calculada:
    - c=0.85 (speculate): éxito sin anchor breaches
    - c=0.5 (doubt): éxito con anchor breaches
    - c=0.1 (near ⊥): ejecución fallida
  - Theorem 5.1 enforced: derived never carries c=1.0 (clamped to 0.99)
  - Ontology: `mcp:tool:{flow_name}`
  - Provenance: `emcp:axon_server:{flow}:{backend}`
- **Blame calculus (Findler-Felleisen):**
  - Caller (CT-2): flow no desplegado, parámetros inválidos
  - Server (CT-3): error de compilación/ejecución
  - Network: timeout, connection refused, backend error
  - `_axon_blame` en error responses, `"blame": "none"` en success
- **CSP Schema en `tools/list`:**
  - `extract_flow_anchors()`: compila source, extrae nombres de anchors del IR
  - `_axon_csp.constraints`: anchors que acotan el espacio de output
  - `_axon_csp.effect_row`: `<io, epistemic:speculate>`
  - `_axon_csp.output_taint`: `Uncertainty` (todo dato MCP nace untrusted)
- **Effect rows computadas:**
  - `["io"]` para stub, `["io", "network"]` para backends reales
  - Efecto epistémico mapeado desde certainty: speculate/doubt/uncertain
- **Lattice position:** `⊥ ⊑ doubt ⊑ speculate` en cada respuesta

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `extract_flow_anchors()`: helper que compila source y extrae anchors.
  - `mcp_handler tools/list`: CSP schema con `_axon_csp`, anchors, effect_row.
  - `mcp_handler tools/call success`: ΛD envelope computada, effect rows, lattice, blame=none.
  - `mcp_handler tools/call error`: blame assignment, envelope con c=0.0 y δ=failed.
  - `mcp_handler error (flow not found)`: `_axon_blame` con CT-2.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (597 total):
  - `emcp_epistemic_envelope_in_mcp_response` — ΛD envelope con certainty levels, Theorem 5.1.
  - `emcp_blame_calculus_findler_felleisen` — blame assignment para cada tipo de error.
  - `emcp_csp_effect_row_and_lattice` — effect rows computadas, lattice mapping, CSP constraints.

**Verificación:**
- `cargo test`: 597 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

**Alineación formal verificada:**
| Principio | Sección | Implementación |
|-----------|---------|----------------|
| CSP (§5.3) | Tools como CSP | `_axon_csp.constraints` = anchors del flow |
| Lattice epistémico (§5.1) | ΛD en response | `EpistemicEnvelope::derived()` con certainty |
| Blame calculus (CT-2/CT-3) | Error attribution | Caller/Server/Network en cada error path |
| Effect rows | Algebraic effects | Computadas desde backend + certainty |
| Theorem 5.1 | Epistemic degradation | `derived()` clamps c ≤ 0.99 |

---

**Handoff E8:**
- **A:** MCP streaming transport — SSE-based MCP transport for real-time tool output.
- **B:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **C:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **D:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **E:** MCP resources exposition — expose AXON traces, configs, and metrics as MCP resources.

### Sesión E8: MCP Streaming Transport — algebraic effects streaming via ℰMCP

**Objetivo de sesión:**
Conectar el streaming algebraico (D112-D114, StreamEmitter) con la exposición MCP, permitiendo que clientes MCP reciban tokens progresivos vía SSE con metadatos epistémicos en cada chunk.

**Alcance cerrado:**
- `POST /v1/mcp/stream` — streaming variant de `tools/call`:
  - Acepta `name` (con prefijo `axon_`) y `arguments` (backend, input).
  - Ejecuta flow, crea StreamEmitter (handler algebraico h: F_Σ(B) → M_IO(B)).
  - Emite tokens con word-boundary chunking (~3 palabras por token).
  - Publica al EventBus para consumo SSE en `/v1/events/stream?topic=flow.stream.{id}`.
  - Respuesta incluye:
    - `stream.topic`, `stream.consume_url`, `stream.token_count`, `stream.protocol: "SSE"`.
    - `stream.coinductive_type: "Stream(τ) = νX. (StreamChunk × EpistemicState × X)"`.
    - `algebraic_effect.handler: "StreamEmitter: h: F_Σ(B) → M_IO(B)"`.
    - ΛD envelope completa (E7), blame, lattice, effect_row computadas.
  - Backend metrics registrados post-ejecución.
  - Blame calculus en errores (CT-2/CT-3).
- Routes: 189→190.
- No entra: SSE transport nativo MCP (requiere cambio de protocolo base), bidirectional streaming.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `mcp_stream_handler`: nuevo handler con StreamEmitter + ΛD + blame.
  - +1 ruta `/v1/mcp/stream`.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (600 total):
  - `mcp_stream_response_shape` — valida stream metadata, algebraic effect handler notation, ΛD.
  - `stream_token_coinductive_type` — StreamToken con epistemic_state/effect_row, PIX skip_serializing.
  - `stream_emitter_algebraic_handler` — emit_chunks + finalize → token count correcto.

**Verificación:**
- `cargo test`: 600 passed, 0 failed. **✓ All green. ✓ Milestone: 600 tests.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E9:**
- **A:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **B:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **C:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **D:** MCP resources exposition — expose AXON traces, configs, and metrics as MCP resources.
- **E:** MCP prompts exposition — expose AXON personas/contexts as MCP prompts.

### Sesión E9: MCP Resources Exposition — traces, métricas y backends como MCP resources

**Objetivo de sesión:**
Implementar el segundo pilar del protocolo MCP: resources. Exponer estado del servidor (traces, métricas, backends, flows) como recursos MCP navegables por clientes externos.

**Alcance cerrado:**
- `resources/list` en `mcp_handler` — retorna descriptores de recursos disponibles:
  - `axon://traces/recent` — últimas 20 traces con ΛD metadata.
  - `axon://metrics` — snapshot de métricas del servidor.
  - `axon://backends` — estado del backend registry (status, circuit breaker, fallback).
  - `axon://flows` — flujos desplegados con versiones.
  - `axon://traces/{id}` — traces individuales (últimas 10 listadas dinámicamente).
  - Cada recurso: `uri` (esquema `axon://`), `name`, `description`, `mimeType`.
- `resources/read` en `mcp_handler` — routing por URI:
  - `axon://traces/recent` → 20 traces con `_epistemic` (certainty basada en status).
  - `axon://metrics` → requests, errors, deploys, flows, traces, backends, alerts.
  - `axon://backends` → registry entries con circuit breaker state y fallback chains.
  - `axon://flows` → list_flows con versiones.
  - `axon://traces/{id}` → trace individual con ΛD raw (c=1.0, δ=raw — dato observado directamente).
  - URI desconocido → JSON-RPC error -32602.
  - Response: `contents[{uri, mimeType, text}]` per MCP spec.
- `initialize` actualizado: capabilities ahora incluyen `resources: {subscribe: false, listChanged: false}`.
- Epistemic distinction: traces son `raw` (c=1.0, observadas), traces/recent summary es `derived` (c=0.85/0.3 según status).

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `mcp_handler`: +2 métodos (`resources/list`, `resources/read`).
  - `initialize`: capabilities updated con `resources`.
  - URI router con 5 resource types + individual traces.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (603 total):
  - `mcp_resources_list_response_shape` — 4 base resources, `axon://` scheme, required fields.
  - `mcp_resources_read_response_shape` — contents array, mimeType, ΛD raw en traces.
  - `mcp_resource_uri_routing` — routing correcto para 7 URIs incluyendo error.

**Verificación:**
- `cargo test`: 603 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff E10:**
- **A:** MCP prompts exposition — expose AXON personas/contexts as MCP prompts.
- **B:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **C:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **D:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **E:** Phase E comprehensive closeout — feature inventory, API surface audit, MCP compliance review.

### Sesión E10: MCP Prompts Exposition + 47 Cognitive Primitives Inventory

**Objetivo de sesión:**
Implementar el tercer y último pilar del protocolo MCP: prompts. Exponer personas y contexts de AXON como prompts MCP invocables. Codificar las 47 primitivas cognitivas de AXON como inventario formal accesible vía MCP.

**Alcance cerrado:**
- `prompts/list` en `mcp_handler`:
  - Cada persona de cada flow desplegado → MCP prompt con nombre `flow:persona`.
  - Arguments: `input` (required), `backend` (optional).
  - `_axon_persona`: domain, tone, confidence_threshold.
  - `_axon_primitives`: inventario completo de las 47 primitivas categorizadas:
    - **Declarations (20):** persona, context, flow, anchor, tool, memory, type, agent, shield, pix, psyche, corpus, dataspace, ots, mandate, compute, daemon, axonstore, axonendpoint, lambda.
    - **Epistemic (4):** know, believe, speculate, doubt.
    - **Execution (14):** step, reason, validate, refine, weave, probe, use, remember, recall, par, hibernate, deliberate, consensus, forge.
    - **Navigation (9):** stream, navigate, drill, trail, corroborate, focus, associate, aggregate, explore.
- `prompts/get` en `mcp_handler`:
  - Parsea nombre `flow:persona`, extrae IR persona + context.
  - Construye system prompt: nombre, dominio, tono, confidence, contexto.
  - Retorna MCP messages array con el prompt construido + input del usuario.
  - ΛD envelope (c=0.95, más alta que tools porque persona es pre-definida).
  - Blame CT-2 si flow o persona no existen.
- `extract_personas()`, `extract_contexts()`: helpers que compilan source y extraen IR.
- `AXON_COGNITIVE_PRIMITIVES`: constante `pub` con las 47 primitivas.
- `initialize` actualizado: capabilities ahora incluye `prompts: {listChanged: false}`.

**Las 47 primitivas cognitivas:**
```
Declarations (20): persona context flow anchor tool memory type agent shield pix
                    psyche corpus dataspace ots mandate compute daemon axonstore
                    axonendpoint lambda
Epistemic (4):     know believe speculate doubt
Execution (14):    step reason validate refine weave probe use remember recall
                    par hibernate deliberate consensus forge
Navigation (9):    stream navigate drill trail corroborate focus associate
                    aggregate explore
```

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `extract_personas()`, `extract_contexts()`: 2 helpers nuevos.
  - `AXON_COGNITIVE_PRIMITIVES`: constante pub con 47 entries.
  - `mcp_handler`: +2 métodos (`prompts/list`, `prompts/get`).
  - `initialize`: capabilities updated con `prompts`.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (606 total):
  - `axon_47_cognitive_primitives_inventory` — verifica 47 exactas, 4 categorías, unicidad, completitud.
  - `mcp_prompts_list_response_shape` — formato flow:persona, arguments, _axon_persona.
  - `mcp_prompts_get_builds_messages` — messages array, system prompt, ΛD c=0.95, primitives_used=47.

**Verificación:**
- `cargo test`: 606 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

**MCP Protocol Coverage Complete:**

| Pilar MCP | Sesión | Métodos |
|-----------|--------|---------|
| Tools | E6+E7 | `tools/list`, `tools/call` (con ΛD, blame, CSP) |
| Resources | E9 | `resources/list`, `resources/read` (5 URI types) |
| Prompts | E10 | `prompts/list`, `prompts/get` (personas→prompts) |
| Streaming | E8 | `POST /v1/mcp/stream` (StreamEmitter, coinductive) |

---

**Handoff E11:**
- **A:** Backend rate limiting — per-backend request throttling to respect provider limits.
- **B:** Wire remaining 16 handlers to resolve keys, record metrics, use fallback and circuit breaker.
- **C:** Backend cost tracking — integrate per-backend cost computation using CostPricing into registry.
- **D:** Phase E comprehensive closeout — feature inventory, API surface audit, MCP compliance review.
- **E:** MCP notifications — implement notifications/initialized and progress reporting.

### Sesión E11: Phase E Comprehensive Closeout — feature inventory, API surface audit, MCP compliance review

**Alcance:** Full Phase E exit review. Audited 189 routes + 7 MCP JSON-RPC methods, 131 public structs, 61 source modules (48,668 lines), 606 integration tests (19,812 lines). Two major deliverables: (1) Backend Management Stack — registry, key resolution, metrics, fallback chain, circuit breaker; (2) ℰMCP Protocol — complete MCP server with tools, resources, prompts, streaming, all with ΛD epistemic envelopes, blame calculus CT-2/CT-3, CSP constraints, and computed effect rows. 47 cognitive primitives codified and exposed via MCP. Created `docs/phase_e_exit_review.md`.
**Evidencia:** 606 tests pass. Release build limpio. Exit review document complete.
**CHECK: 5/5**

---

## Phase E: COMPLETE

**Sessions:** E1–E11 (11 sessions)
**Final test count:** 606
**Final source:** 48,668 lines across 61 modules
**Exit review:** `docs/phase_e_exit_review.md`

**Phase F candidates:**
1. Production hardening — TLS, connection pooling, horizontal scaling
2. Client SDKs — TypeScript/Python MCP clients for ℰMCP
3. Language evolution — new AXON primitives, pattern matching, modules
4. Real-world testing — end-to-end with live Anthropic/OpenAI backends
5. AxonStore persistence — durable execution state across restarts
