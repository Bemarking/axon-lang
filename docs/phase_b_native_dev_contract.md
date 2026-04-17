# Fase B - Contrato Operativo de `native-dev`

## Objetivo

Definir con precision que significa el selector `native-dev` en `Fase B`, que garantiza hoy, que no garantiza y como debe evolucionar hacia una implementacion nativa real.

Este documento evita dos errores operativos:

- vender `native-dev` como si ya fuera un core nativo terminado
- tratar `native-dev` como si fuera equivalente a `python`

## Estado Actual

El selector `native-dev` existe en el registro de implementaciones del frontend y puede activarse via bootstrap igual que `python` o `native`.

Implementacion actual:

- clase: `NativeDevelopmentFrontendImplementation`
- modulo: `axon/compiler/frontend.py`
- seleccion: `axon/compiler/frontend_bootstrap.py`

Semantica actual:

- `native-dev` delega en `PythonFrontendImplementation` fuera de un subconjunto nativo explicito y acotado
- `native-dev` preserva el contrato observable congelado de `check` y `compile`
- `native-dev` ya contiene pequenas sustituciones nativas delimitadas para algunos fallos locales de `run(...)` y para un primer camino minimo de exito con `flow Name() {}` seguido de `run Name()`, incluyendo extensiones locales resueltas como `output_to`, `effort`, `on_failure` simple, `on_failure: raise X`, `on_failure: retry(...)` parametrizado de longitud variable, formas positivas prefijadas exactas con `persona`, `context` y `anchor`, formas positivas multi-prefijo exactas con `persona` + `context`, `persona` + `anchor` y `context` + `anchor`, la primera forma positiva exacta con tres prefijos compartidos: `persona` + `context` + `anchor`, y sus extensiones exactas actualmente abiertas con `output_to`, `effort`, `on_failure` simple, `on_failure: raise X`, `on_failure: retry(...)` parametrizado, `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [AnchorName]`; despues de B70, el ladder local exacto de modificadores sobre este programa se considera cerrado hasta que aparezca evidencia nueva de mayor valor, despues de B73 el frente estructural ya no es solo recomendado sino implementado en su primer corte, despues de B75 ese matcher estructural ya cubre tambien los modifiers no referenciales `output_to`, `effort`, `on_failure` simple, `on_failure: raise X` y `on_failure: retry(...)` parametrizado, despues de B77 ese mismo matcher ya cubre tambien las referencias singulares `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [AnchorName]`, despues de B78 ya permite `persona` y `context` como singletons mas uno o mas bloques `anchor` con nombres unicos en orden alterno para resolver `run Name() constrained_by [A, B, ...]`, despues de B79 ya preserva tambien repeticiones en `run Name() constrained_by [A, A, B, ...]`, despues de B80 ya detecta localmente duplicados estructurales de `anchor` por nombre con el mismo diagnostico canonico de Python, despues de B81 extiende ese mismo path local a duplicados estructurales limpios de `persona` y `context`, despues de B82 ya acumula tambien combinaciones limpias de esos duplicate declarations en el mismo orden observable que Python, despues de B83 ya reproduce tambien la mezcla no limpia acotada donde un `context` duplicado añade el diagnostico canonico de `Unknown memory scope ...`, despues de B84 extiende ese mismo orden local para acumular `Unknown memory scope ...` tambien cuando el primer `context` estructural soportado ya es invalido, despues de B85 cubre tambien el mismo diagnostico en programas estructurales soportados sin duplicate declarations, incluyendo los casos que ademas terminan en `Undefined flow ...`, despues de B86 generaliza ese mismo frente de validacion local para cubrir tambien `Unknown tone ...` sobre `persona`, acumulando `persona/context` en orden de fuente y rechazando valores invalidos tambien desde los success matchers, y despues de B87 cierra la brecha restante para que el path de duplicate declarations de `persona` acumule tambien `Unknown tone ...` igual que Python; despues de B88, este frente estructural no limpio queda operativamente cerrado con el grammar actual porque los siguientes candidatos ya exigirian ampliar el parser local mas alla de `tone`, `memory` y `require`; despues de B89, el primer crecimiento acotado de ese grammar ya entra por `context.depth`, incluyendo exito local y diagnosticos de `Unknown depth ...` con el mismo orden observable que Python; despues de B90, ese crecimiento estructural compartido tambien cubre `anchor.enforce` para los paths locales de exito y duplicate declarations; despues de B91, el mismo grammar compartido ya cubre tambien `persona/context.cite_sources` para exito y duplicate declarations sin validaciones nuevas; despues de B92, ese mismo grammar compartido ya cubre tambien `persona/context.language` para exito y duplicate declarations sin validaciones nuevas; despues de B93, ese mismo grammar compartido ya cubre tambien `persona/anchor.description` para exito y duplicate declarations sin validaciones nuevas; despues de B94, ese mismo grammar compartido ya cubre tambien `anchor.unknown_response` para exito y duplicate declarations sin validaciones nuevas; despues de B95, ese mismo grammar compartido ya cubre tambien `context.max_tokens` para exito, validacion y duplicate declarations con diagnostico local de positividad; despues de B96, ese mismo grammar compartido ya cubre tambien `context.temperature` para exito, validacion y duplicate declarations con diagnostico local de rango; despues de B97, ese mismo grammar compartido ya cubre tambien `persona.confidence_threshold` para exito, validacion y duplicate declarations con diagnostico local de rango; despues de B98, ese mismo grammar compartido ya cubre tambien `anchor.confidence_floor` para exito, validacion y duplicate declarations con diagnostico local de rango; despues de B99, ese mismo grammar compartido ya cubre tambien el subconjunto ident-like de un solo token de `anchor.on_violation` para exito, validacion y duplicate declarations; despues de B100, ese mismo grammar compartido ya cubre tambien la forma parser-side acotada `anchor.on_violation: raise ErrorName`; despues de B101, ese mismo grammar compartido ya cubre tambien la forma parser-side acotada `anchor.on_violation: fallback("...")`; despues de B102, ese mismo grammar compartido ya cubre tambien `anchor.reject` para listas bracketed de uno o mas valores identifier-like; despues de B103, ese mismo grammar compartido ya cubre tambien `persona.refuse_if` para listas bracketed de uno o mas valores identifier-like; despues de B104, ese mismo grammar compartido ya cubre tambien `persona.domain` para listas bracketed de uno o mas strings; despues de B105, ese mismo frente estructural compartido ya abre tambien el kind `memory` en su corte minimo mediante `memory.store` para exito, validacion de `Unknown store type ...`, undefined-flow y duplicate declarations; despues de B106, ese mismo frente estructural compartido ya cubre tambien `memory.backend` para exito, undefined-flow y duplicate declarations; despues de B107, ese mismo frente estructural compartido ya cubre tambien `memory.retrieval` para exito, validacion de `Unknown retrieval strategy ...`, undefined-flow y duplicate declarations; despues de B108, ese mismo frente estructural compartido ya cubre tambien `memory.decay` para exito, undefined-flow y duplicate declarations, aceptando tanto valores `DURATION` como identifier-like; despues de B109, ese mismo frente estructural compartido ya abre tambien `tool.provider` para exito y duplicate declarations, sin introducir validacion local nueva; despues de B110, ese mismo frente estructural compartido ya abre tambien `tool.runtime` para exito y duplicate declarations, sin introducir validacion local nueva; despues de B111, ese mismo frente estructural compartido ya abre tambien `tool.sandbox` para exito y duplicate declarations, sin introducir validacion local nueva; despues de B112, ese mismo frente estructural compartido ya abre tambien `tool.timeout` para exito y duplicate declarations, sin introducir validacion local nueva; despues de B113, ese mismo frente estructural compartido ya abre tambien `tool.max_results` para exito, validacion y duplicate declarations con diagnostico local de positividad; despues de B114, ese mismo frente estructural compartido ya abre tambien el subconjunto ident-like de un solo token de `tool.filter` para exito y duplicate declarations, manteniendo fuera la forma parser-side `filter(...)`; despues de B115, ese mismo frente estructural compartido ya abre tambien la forma parser-side acotada `tool.filter(...)` para exito y duplicate declarations, compactando `filter_expr` con la misma salida observable que Python; despues de B116, ese mismo frente estructural compartido ya abre tambien `tool.effects` para exito, validacion y duplicate declarations, reproduciendo localmente `Unknown effect ...` y `Unknown epistemic level ...`; despues de B117, ese mismo frente estructural compartido ya abre tambien el corte minimo real de `intent` mediante `intent.ask` para exito y duplicate declarations, preservando el mismo IR observable que Python al no materializar intents top-level en `IRProgram`; despues de B118, ese mismo frente estructural compartido ya abre tambien la forma parser-side acotada `intent.given + ask` en cualquier orden para exito y duplicate declarations, manteniendo fuera `intent.output` y `intent.confidence_floor`; despues de B119, ese mismo frente estructural compartido ya abre tambien la forma parser-side acotada `intent.ask + confidence_floor` en cualquier orden para exito, validacion de rango, undefined-flow y duplicate declarations, manteniendo fuera `intent.output`

- despues de B120, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName }` en cualquier orden para exito, validacion, undefined-flow y duplicate declarations, materializando `endpoints` en el `IRProgram` local mientras `body`, `output`, `shield`, `retries` y `timeout` siguen delegados

- despues de B121, `native-dev` ya abre tambien la forma parser-side acotada `intent { ask: "..." output: TypeExpr }` en cualquier orden para exito, undefined-flow y duplicate declarations, con parseo local acotado de `type_expr` para `IDENTIFIER`, `IDENTIFIER<IDENTIFIER>` y sufijo opcional `?`; `given + ask + output`, `ask + output + confidence_floor` y shapes mas ricos siguen delegados, y `lambda` pasa a ser el marco de comparacion del siguiente frente sin reemplazar todavia la representacion interna de `intent.output`, precisamente para preservar el caracter epistemico, cognitivo y semantico de AXON

- despues de B122, `native-dev` ya abre tambien la forma parser-side acotada `intent { ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden para exito, validacion de rango, undefined-flow y duplicate declarations, combinando localmente la salida tipada y el control epistemico ya abiertos en B119 y B121 sin materializar intents top-level en `IRProgram`; `intent { given + ask + output }`, `axonendpoint.output` y `axonendpoint.shield` siguen delegados como la siguiente comparacion honesta de frontera

- despues de B123, `native-dev` ya abre tambien la forma parser-side acotada `intent { given: Type ask: "..." output: TypeExpr }` en cualquier orden para exito, undefined-flow y duplicate declarations, combinando localmente el contexto cognitivo de `given` con la salida tipada ya abierta en B121 sin introducir validacion nueva ni materializar intents top-level en `IRProgram`; `intent { given + ask + output + confidence_floor }`, `axonendpoint.output` y `axonendpoint.shield` siguen delegados como la siguiente comparacion honesta de frontera

- despues de B124, `native-dev` ya abre tambien la forma parser-side acotada `intent { given: Type ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden para exito, validacion de rango, undefined-flow y duplicate declarations, combinando localmente el contexto cognitivo de `given`, la salida tipada y el control epistemico ya abiertos en B118, B121 y B119 sin materializar intents top-level en `IRProgram`; `axonendpoint.output` y `axonendpoint.shield` quedan ahora como la siguiente comparacion honesta de frontera

- despues de B125, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName }` en cualquier orden para exito, undefined-flow y duplicate declarations, materializando localmente `output_type` en `IREndpoint` y en el JSON compilado sin introducir validacion nueva porque `output_type` sigue siendo referencia soft en Python para este kind; `axonendpoint.shield` queda como la siguiente comparacion honesta de frontera operativa externa

- despues de B126, `native-dev` ya abre tambien la declaracion top-level minima `shield Name { }` y la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName }` en cualquier orden para exito, undefined-flow, undefined-shield, kind-mismatch y duplicate declarations, materializando localmente `shields` en `IRProgram` y `shield_ref` en `IREndpoint`; la siguiente comparacion honesta de frontera operativa externa pasa a ser componer `output + shield` o justificar un corte alternativo mas pequeno como `body`

- despues de B127, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName body: TypeName }` en cualquier orden para exito, undefined-flow y duplicate declarations, materializando localmente `body_type` en `IREndpoint` y en el JSON compilado sin introducir validacion nueva adicional porque `body_type` ya existia en AST, IR y lowering y su chequeo Python para este kind sigue siendo una referencia de tipo blanda; la siguiente comparacion honesta de frontera operativa externa pasa a ser `axonendpoint { ... output + shield }` o un corte realmente menor dentro de `retries` o `timeout`

- despues de B128, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName shield: ShieldName }` en cualquier orden para exito, undefined-flow, undefined-shield, kind-mismatch y duplicate declarations, materializando localmente `output_type` y `shield_ref` en `IREndpoint` y en el JSON compilado sin introducir validaciones conjuntas nuevas entre ambos fields; la siguiente comparacion honesta de frontera operativa externa pasa a ser decidir el corte realmente menor entre `axonendpoint.retries` y `axonendpoint.timeout`

- despues de B129, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName timeout: TimeoutValue }` en cualquier orden para exito, undefined-flow y duplicate declarations, materializando localmente `timeout` en `IREndpoint` y en el JSON compilado y aceptando valores `DURATION` e identifier-like sin introducir validacion endpoint nueva; la siguiente comparacion honesta de frontera operativa externa pasa a ser abrir `axonendpoint.retries` con su validacion numerica local `>= 0`

- despues de B130, `native-dev` ya abre tambien la forma parser-side acotada `axonendpoint { method: X path: "/..." execute: FlowName retries: N }` en cualquier orden para exito, validacion `retries >= 0`, undefined-flow y duplicate declarations, materializando localmente `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python; la siguiente comparacion honesta de frontera operativa externa pasa a ser decidir si conviene componer `axonendpoint { ... retries + timeout }` o cerrar temporalmente la linea endpoint

## Para Que Sirve `native-dev`

`native-dev` sirve para abrir una ruta de desarrollo nativa sin romper:

- el bootstrap de producto
- la CLI actual
- los golden tests de compatibilidad
- la distincion entre selector estable y selector experimental

Valor operativo hoy:

- ejercita la seleccion de implementacion distinta de `python`
- permite validar que el resto del sistema no asume una unica implementacion fija
- permite introducir sustituciones graduales detras del mismo selector sin tocar adaptadores CLI ni entrypoints

## Garantias de `native-dev`

Mientras `native-dev` siga en su estado actual, garantiza:

- compatibilidad con el contrato de diagnosticos e IR fijado en `docs/phase_b_frontend_contract.md`
- compatibilidad con los golden tests del frontend
- misma semantica observable que `python` para `check` y `compile`
- seleccion explicita via bootstrap y variable de entorno `AXON_FRONTEND_IMPLEMENTATION`
- diferenciacion operativa frente a `native`, que sigue siendo un placeholder duro

En terminos practicos, hoy esto implica:

- `axon check` con `AXON_FRONTEND_IMPLEMENTATION=native-dev` debe seguir devolviendo los mismos codigos de salida y el mismo shape logico de diagnostico que `python`
- `axon compile` con `AXON_FRONTEND_IMPLEMENTATION=native-dev` debe seguir devolviendo el mismo shape minimo de IR y `_meta` que `python`
- cuando `native-dev` cubre un subconjunto de forma nativa, ese subconjunto debe seguir siendo indistinguible de `python` en salida observable para CLI y golden tests

## No Garantias de `native-dev`

`native-dev` no garantiza hoy:

- ejecucion nativa real
- performance distinta de `python`
- independencia estructural respecto del pipeline Python
- cobertura de runtime o backends de ejecucion
- evidencia de que lexer, parser, type checker o IR generator completos ya fueron portados

Conclusion operativa:

- `native-dev` no es una implementacion nativa funcional
- `native-dev` es una ruta de sustitucion controlada con pequeños cortes nativos verificables

## Diferencia Entre Selectores

### `python`

Significa:

- implementacion por defecto
- ruta estable actual
- referencia canonica del comportamiento del frontend

### `native-dev`

Significa:

- ruta de desarrollo para futura implementacion nativa
- hoy delega en Python
- puede empezar a reemplazar piezas internas de forma incremental sin cambiar bootstrap ni CLI

### `native`

Significa:

- placeholder de una implementacion nativa todavia inexistente
- seleccionarlo produce error controlado
- se usa para representar explicitamente que la via nativa real aun no esta entregada

## Regla de Honestidad Tecnica

Mientras `native-dev` delegue en Python, no se debe afirmar que AXON ya tiene frontend nativo.

Incluso despues de B73, esto sigue siendo cierto: existe un camino nativo de exito pequeno y todavia acotado, no un reemplazo nativo general del frontend.

La formulacion correcta es:

- AXON ya tiene costura operativa para un frontend nativo
- AXON ya tiene selector de desarrollo para esa ruta
- AXON todavia no tiene reemplazo nativo real del frontend

La formulacion incorrecta es:

- `native-dev` ya es el compilador nativo
- `native-dev` prueba independencia de Python

## Condiciones para Promover `native-dev`

`native-dev` solo puede dejar de ser una ruta de delegacion y empezar a representar avance nativo real si cumple al menos una de estas condiciones con evidencia:

1. El lexer deja de delegar en Python y preserva golden tests de diagnosticos.
2. El parser deja de delegar en Python y preserva golden tests de diagnosticos.
3. El type checker deja de delegar en Python para un subconjunto explicito y preserva compatibilidad observable.
4. La generacion de IR deja de delegar en Python para un subconjunto explicito y preserva el contrato minimo.

Regla adicional:

- cada sustitucion debe ser trazable, delimitada y verificable por pruebas de compatibilidad

## Transicion Recomendada

Secuencia recomendada a partir de este punto:

1. Mantener `python` como default de producto.
2. Mantener `native` como placeholder duro.
3. Usar `native-dev` como unica ruta donde pueden entrar reemplazos graduales.
4. Sustituir primero una capacidad concreta y verificable detras de `native-dev`.
5. Ejecutar golden tests de B3 y pruebas de fachada/CLI en cada avance.

## Primer Corte Recomendado

El primer reemplazo real recomendado detras de `native-dev` no es runtime ni FFI.

El primer reemplazo recomendado es uno de estos dos:

- lexer para un subconjunto controlado del lenguaje
- parser para fixtures canonicos de `check` y `compile`

Razon:

- son los puntos mas faciles de aislar
- impactan directamente el contrato de diagnosticos
- permiten medir progreso real del frontend nativo sin mezclar runtime o backends

## Decision de B11

`native-dev` queda formalmente definido como:

- selector de desarrollo
- compatible con el contrato congelado del frontend
- no equivalente a una implementacion nativa real
- punto obligatorio de entrada para sustituciones graduales antes de promover un frontend nativo efectivo

## Handoff

Adenda de frontera reciente:

- B131 abrio `axonendpoint.retries + timeout` porque, una vez abiertos ambos knobs por separado, su composicion era el siguiente corte endpoint de menor costo incremental y mayor continuidad operativa; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName retries: N timeout: TimeoutValue }` en cualquier orden para exito, validacion local `retries must be >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B131 quedo cerrada con `3 passed` en fachada, `2 passed` en CLI y `431 passed` en el trio canonico, sin ensanchar todavia composiciones con `body`, `output` o `shield`.
- B132 abrio `axonendpoint.body + output` porque, una vez abiertos ambos fields suaves por separado, su composicion era el siguiente corte endpoint de menor costo semantico y mayor continuidad sobre el payload observable; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType }` en cualquier orden para exito, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B132 quedo cerrada con `3 passed` en fachada, `2 passed` en CLI y `436 passed` en el trio canonico, sin ensanchar todavia composiciones con `shield`, `retries` o `timeout`.
- B133 abrio `axonendpoint.body + shield` porque, una vez abiertos el field suave de payload y la referencia dura de politica por separado, su composicion era el siguiente corte endpoint de menor costo semantico que aun agregaba valor observable; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName }` en cualquier orden para exito, acumulacion con `undefined flow`, diagnostico `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B133 quedo cerrada con `5 passed` en fachada, `2 passed` en CLI y `443 passed` en el trio canonico, sin ensanchar todavia composiciones con `output`, `retries` o `timeout`.
- B134 abrio `axonendpoint.output + timeout` porque, una vez abiertos el field suave de respuesta y el knob operativo por separado, su composicion era el siguiente corte endpoint de menor costo semantico sin validacion dura nueva; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B134 quedo cerrada con `3 passed` en fachada, `2 passed` en CLI y `448 passed` en el trio canonico, sin ensanchar todavia composiciones con `body`, `shield` o `retries`.
- B135 abrio `axonendpoint.body + timeout` porque, una vez abiertos el field suave de request y el knob operativo por separado, su composicion era el siguiente corte endpoint de menor costo semantico sin validacion dura nueva; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B135 quedo cerrada con `3 passed` en fachada, `2 passed` en CLI y `453 passed` en el trio canonico, sin ensanchar todavia composiciones con `output`, `shield` o `retries`.
- B136 abrio `axonendpoint.output + retries` porque, una vez abiertos el field suave de respuesta y el knob operativo de reintentos por separado, su composicion era el siguiente corte endpoint de menor costo semantico que aun reutilizaba una validacion local ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B136 quedo cerrada con `4 passed` en fachada, `2 passed` en CLI y `459 passed` en el trio canonico, sin ensanchar todavia composiciones con `body`, `shield` o `timeout`.
- B137 abrio `axonendpoint.body + retries` porque, una vez abiertos el field suave de request y el knob operativo de reintentos por separado, su composicion era el siguiente corte endpoint de menor costo semantico que aun reutilizaba una validacion local ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B137 quedo cerrada con `4 passed` en fachada, `2 passed` en CLI y `465 passed` en el trio canonico, sin ensanchar todavia composiciones con `output`, `shield` o `timeout`.
- B138 abrio `axonendpoint.shield + timeout` porque, una vez abiertos la referencia de politica y el knob operativo por separado, su composicion era el siguiente corte endpoint de menor costo semantico sin validacion dura nueva; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B138 quedo cerrada con `5 passed` en fachada, `2 passed` en CLI y `472 passed` en el trio canonico, sin ensanchar todavia composiciones con `body`, `output` o `retries`.
- B139 abrio `axonendpoint.shield + retries` porque, una vez abiertos la referencia de politica y el knob operativo de reintentos por separado, su composicion era el ultimo corte endpoint binario de menor costo semantico que aun reutilizaba una validacion local ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName retries: N }` en cualquier orden para exito, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield`, validacion local `retries >= 0` y duplicate declarations, materializando ambos fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B139 quedo cerrada con `6 passed` en fachada, `2 passed` en CLI y `480 passed` en el trio canonico, cerrando la malla binaria del endpoint sin ensanchar todavia composiciones ternarias.
- B140 abrio `axonendpoint.body + output + timeout` porque, una vez cerrada la malla binaria, era la primera composicion ternaria de menor costo semantico: combina solo fields suaves ya abiertos y evita todavia referencia de politica o validacion dura; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B140 quedo cerrada con `3 passed` en fachada, `2 passed` en CLI y `485 passed` en el trio canonico, abriendo el primer ternario del endpoint sin ensanchar todavia ternarios con `shield` o `retries`.
- B141 abrio `axonendpoint.body + output + retries` porque, una vez abierto el primer triangulo suave, el siguiente ternario de menor costo seguia siendo el mismo par de payload mas la validacion local `retries >= 0` ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType retries: N }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B141 quedo cerrada con `4 passed` en fachada, `2 passed` en CLI y `491 passed` en el trio canonico, manteniendo fuera todavia los ternarios que mezclan `shield` con el par de payload.
- B142 abrio `axonendpoint.body + output + shield` porque, una vez agotadas las variantes del par de payload con `timeout` y `retries`, el siguiente ternario de menor costo seguia siendo el mismo par mas la referencia de politica ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType shield: ShieldName }` en cualquier orden para exito, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B142 quedo cerrada con `5 passed` en fachada, `2 passed` en CLI y `498 passed` en el trio canonico, cerrando la variante normativa del triangulo de payload sin abrir todavia un cuarto field operativo.
- B143 abrio `axonendpoint.body + shield + timeout` porque, una vez abierta la composicion con politica `body + shield`, el siguiente ternario de menor costo seguia siendo agregar solo el knob operativo suave `timeout`; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B143 quedo cerrada con `5 passed` en fachada, `2 passed` en CLI y `505 passed` en el trio canonico, cerrando la variante suave de la composicion `body + shield` sin abrir todavia la variante con validacion dura.
- B144 abrio `axonendpoint.body + shield + retries` porque, una vez cerrada la variante suave `body + shield + timeout`, el siguiente ternario de menor costo sobre la misma composicion con politica seguia siendo agregar la validacion dura `retries >= 0` ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName retries: N }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B144 quedo cerrada con `6 passed` en fachada, `2 passed` en CLI y `513 passed` en el trio canonico, cerrando la pareja suave/dura sobre la composicion `body + shield` antes de saltar a otra variante ternaria con politica.
- B145 abrio `axonendpoint.output + shield + timeout` porque, una vez abierta la composicion normativa `output + shield`, el siguiente ternario de menor costo seguia siendo agregar solo el knob operativo suave `timeout`; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName timeout: TimeoutValue }` en cualquier orden para exito, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B145 quedo cerrada con `5 passed` en fachada, `2 passed` en CLI y `520 passed` en el trio canonico, cerrando la variante suave de la composicion `output + shield` antes de abrir su contraparte con validacion dura.

- Antes de abrir B146 se endurecio la arquitectura parser-side de `axonendpoint`: las combinaciones soportadas actuales se consolidaron en un parser estructural unico con mapeo central `field -> atributo IR` y un registro declarativo de field-sets admitidos, eliminando el riesgo de olvidar otra helper o su registro manual en `extended_parsers`.
- La validacion observable de ese hardening quedo cerrada con `135 passed, 376 deselected in 58.03s` en el subset axonendpoint de fachada + CLI y `520 passed in 221.04s` en el trio canonico, sin cambiar el contrato observable ni abrir todavia la variante `output + shield + retries`.

- B146 abrio `axonendpoint.output + shield + retries` porque, una vez cerrada la variante suave `output + shield + timeout`, el siguiente ternario de menor costo sobre la misma composicion normativa seguia siendo agregar la validacion dura `retries >= 0` ya absorbida; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName retries: N }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow`, `undefined shield`, kind mismatch `not a shield` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B146 quedo cerrada con `4 passed` en el foco directo de B146, `142 passed, 376 deselected in 62.84s` en el subset axonendpoint de fachada + CLI y `527 passed in 229.03s` en el trio canonico, confirmando que la extension entro reutilizando el registro central de field-sets soportados y sin regresiones observables.

- B147 abrio `axonendpoint.output + retries + timeout` porque, entre los ternarios restantes sobre la pareja operativa ya abierta, seguia siendo el corte mas honesto para completar primero la rama de respuesta antes de ensanchar la superficie de request con `body`; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N timeout: TimeoutValue }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B147 quedo cerrada con `5 passed` en el foco directo de B147, `147 passed, 376 deselected in 63.88s` en el subset axonendpoint de fachada + CLI y `532 passed in 226.16s` en el trio canonico, confirmando que la extension entro reutilizando el registro central de field-sets soportados y sin regresiones observables.

- B148 abrio `axonendpoint.body + retries + timeout` porque, una vez cerrada en B147 la variante de respuesta sobre la pareja operativa ya abierta, quedaba como ultimo ternario pendiente y era mas honesto cerrar tambien la rama de request antes de pausar la linea endpoint; `native-dev` cubre ahora exactamente `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N timeout: TimeoutValue }` en cualquier orden para exito, validacion local `retries >= 0`, acumulacion con `undefined flow` y duplicate declarations, materializando los tres fields en `IREndpoint` y en el JSON compilado.
- La validacion observable de B148 quedo cerrada con `5 passed` en el foco directo de B148, `152 passed, 385 deselected in 73.56s` en el subset axonendpoint de fachada + CLI + golden, y `537 passed in 249.84s` en el trio canonico, confirmando que la extension entro reutilizando el registro central de field-sets soportados y sin regresiones observables.

- B149 reviso formalmente el gate de salida de `Fase B` y concluyo que la fase no debe cerrarse todavia: el frente endpoint queda pausado despues de B148, pero `native-dev` sigue siendo una ruta de delegacion parcial y el criterio formal de salida sigue exigiendo `lexer`, `parser`, `type checker` y `axon check` / `axon compile` sobre core nativo.
- La recomendacion operativa tras B149 es abrir B150 como primer frente nativo explicito de `type`, empezando por `type RiskScore(0.0..1.0)` y por tipos estructurados con campos opcionales como `mitigation: Opinion?`, porque ese subset ya esta congelado como fixture estable, pertenece al core directo del frontend y ataca delegacion parser/type-checker real en vez de seguir ampliando `axonendpoint`.

- B150 abrio el primer frente nativo explicito de `type`: `native-dev` cubre ahora programas compuestos solo por declaraciones `type` dentro del subset acotado `type RiskScore(0.0..1.0)` y tipos estructurados con fields simples y opcionales como `type Risk { score: RiskScore, mitigation: Opinion? }`, sin delegar a Python en `check` ni en `compile`; el IR local preserva `types`, `range_min`, `range_max`, `fields`, `type_name`, `generic_param` y `optional` con el mismo shape observable ya congelado.
- La validacion observable de B150 quedo cerrada con `6 passed, 524 deselected in 8.08s` en el foco directo de B150 y `539 passed in 280.83s` en el trio canonico frontend, confirmando que el recorte de delegacion entra sin romper el contrato observable.

- B151 abrio el primer frente mixto `type + flow/run`: `native-dev` cubre ahora archivos acotados que combinan uno o mas `type` del subset B150 con el success path minimo ya existente de `flow/run`, incluyendo modifiers de `run` ya soportados como `output_to`, sin delegar entero a Python en `check` ni en `compile`; el IR local preserva `types`, `flows`, `runs` y el mismo shape observable ya congelado para ambos frentes.
- La validacion observable de B151 quedo cerrada con `4 passed, 530 deselected in 7.78s` en el foco directo de B151 y `543 passed in 283.18s` en el trio canonico frontend, confirmando que la composicion entra sin romper el contrato observable.

- B152 abrio el primer frente mixto prefijado `type + persona/context/anchor + flow/run`: `native-dev` cubre ahora archivos acotados que combinan uno o mas `type` del subset B150 con los success paths prefijados ya existentes para `persona/context/anchor`, incluyendo ordenes estructurales ya admitidos y modifiers de `run` ya soportados como `output_to`, sin delegar entero a Python en `check` ni en `compile`; el IR local preserva `types`, `personas`, `contexts`, `anchors`, `flows`, `runs` y el mismo shape observable ya congelado para ambos frentes.
- La validacion observable de B152 quedo cerrada con `3 passed, 535 deselected in 14.34s` en el foco directo de B152 y `547 passed in 314.49s` en el trio canonico frontend, confirmando que la composicion prefijada entra sin romper el contrato observable.

- B153 abrio el primer frente mixto negativo/estructural con prefijo `type`: `native-dev` cubre ahora archivos acotados que combinan uno o mas `type` del subset B150 con los matchers estructurales locales ya abiertos de validacion y duplicate declarations, preservando tambien la acumulacion observable de `Undefined flow ...` cuando el resto del archivo ya cae dentro de esa frontera local, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B153 quedo cerrada con `4 passed, 538 deselected in 2.21s` en el foco directo de B153 y `551 passed in 249.89s` en el trio canonico frontend, confirmando que la composicion negativa/estructural con prefijo `type` entra sin romper el contrato observable.

- B154 cerro el hueco mixto negativo mas pequeno sin prefijos estructurales: `native-dev` cubre ahora archivos acotados que combinan uno o mas `type` del subset B150 con el subset aislado de `run` que ya producia localmente `Undefined flow ...`, incluyendo argumentos y modifiers ya abiertos en ese mismo path, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B154 quedo cerrada con `3 passed, 542 deselected in 4.92s` en el foco directo de B154 y `554 passed in 258.96s` en el trio canonico frontend, confirmando que la composicion `type + run` negativa entra sin romper el contrato observable.

- B155 cerro el siguiente hueco mixto limpio sobre el prefixed run subset: `native-dev` cubre ahora archivos acotados que combinan uno o mas `type` del subset B150 con prefixes limpios `persona/context/anchor` ya abiertos y con el prefixed run subset que ya producia localmente `Undefined flow ...`, incluyendo referencias prefijadas como `as`, `within`, `constrained_by` y modifiers ya soportados en ese mismo path, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B155 quedo cerrada con `3 passed, 545 deselected in 3.24s` en el foco directo de B155 y `557 passed in 248.40s` en el trio canonico frontend, confirmando que la composicion limpia `type + persona/context/anchor + run` negativa entra sin romper el contrato observable.

- B156 cerro el hueco local mas pequeno que quedaba dentro del propio prefijo `type`: `native-dev` cubre ahora duplicate declarations de `type` sobre programas type-only y sobre composiciones mixtas ya abiertas localmente, preservando el diagnostico canonico `Duplicate declaration: 'Name' already defined as type (first defined at line X)` y acumulando despues los diagnosticos locales ya portados cuando corresponden, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B156 quedo cerrada con `3 passed, 548 deselected in 10.97s` en el foco directo de B156 y `560 passed in 311.56s` en el trio canonico frontend, confirmando que el cierre local del duplicate `type` entra sin romper el contrato observable.

- B157 abrio el primer corte parser-side acotado de `type ... where ...` sobre programas type-only: `native-dev` cubre ahora declaraciones `type` del subset B150 con `where` opcional, preservando localmente `where_expression` en el IR compilado junto con `range_min`, `range_max` y `fields` cuando existen, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B157 quedo cerrada con `4 passed, 551 deselected in 20.38s` en el foco directo de B157 y `564 passed in 328.22s` en el trio canonico frontend, confirmando que el primer `where` parser-side entra sin romper el contrato observable ni abrir todavia composiciones mixtas.

- B158 compuso ese primer `type ... where ...` con el success path minimo ya abierto de `flow/run`: `native-dev` cubre ahora el primer conjunto acotado de programas mixtos `type ... where ... + flow/run`, preservando localmente `where_expression` junto con `flows`, `runs`, `range_min`, `range_max` y modifiers ya abiertos como `output_to`, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B158 quedo cerrada con `7 passed, 551 deselected in 4.23s` en el foco directo de B158 y `567 passed in 423.44s` en el trio canonico frontend, confirmando que la primera composicion mixta positiva con `where` entra sin romper el contrato observable ni abrir todavia prefijos estructurales o paths negativos.

- B159 llevo ese mismo `type ... where ...` al success path prefijado ya abierto de `persona/context/anchor + flow/run`: `native-dev` cubre ahora el primer conjunto acotado de programas prefijados `type ... where ... + persona/context/anchor + flow/run`, preservando localmente `where_expression` junto con `personas`, `contexts`, `anchors`, `flows`, `runs` y modifiers ya abiertos como `output_to`, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B159 quedo cerrada con `3 passed, 558 deselected in 1.74s` en el foco directo de B159 y `570 passed in 345.16s` en el trio canonico frontend, confirmando que la primera composicion positiva prefijada con `where` entra sin romper el contrato observable ni abrir todavia paths negativos o duplicate declarations mixtos.

- B160 llevo ese mismo `type ... where ...` a los paths estructurales negativos y de duplicate declarations ya abiertos localmente: `native-dev` cubre ahora el primer conjunto acotado de programas estructurales con `type ... where ...` que reproducen localmente `Unknown memory scope ...`, `Undefined flow ...` y `Duplicate declaration ...` con el mismo orden observable que Python, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B160 quedo cerrada con `6 passed, 559 deselected in 9.40s` en el foco directo de B160 y `574 passed in 404.22s` en el trio canonico frontend, confirmando que el `where` estructural negativo entra sin romper el contrato observable ni abrir todavia otros negativos mixtos.

- B161 llevo ese mismo `type ... where ...` al subset aislado ya abierto de `run Missing()`: `native-dev` cubre ahora el primer conjunto acotado de programas `type ... where ... + run Missing()` del subset aislado, preservando localmente el diagnostico canonico `Undefined flow 'Missing' in run statement` con los mismos conteos observables que Python, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B161 quedo cerrada con `4 passed, 564 deselected in 12.62s` en el foco directo de B161 y `577 passed in 438.83s` en el trio canonico frontend, confirmando que el `where` aislado negativo entra sin romper el contrato observable ni abrir todavia el clean prefixed run o duplicate `type` con `where`.

- B162 llevo ese mismo `type ... where ...` al clean prefixed run ya abierto localmente: `native-dev` cubre ahora el primer conjunto acotado de programas `type ... where ...` sobre el clean prefixed run, preservando localmente el diagnostico canonico `Undefined flow 'Missing' in run statement` con los mismos conteos observables que Python para las formas ya abiertas `as` y `constrained_by`, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B162 quedo cerrada con `4 passed, 567 deselected in 11.39s` en el foco directo de B162 y `580 passed in 430.97s` en el trio canonico frontend, confirmando que el `where` sobre clean prefixed run entra sin romper el contrato observable ni abrir todavia duplicate `type` con `where`.

- B163 cerro el hueco local que quedaba dentro del propio prefijo `type` cuando el subset ya usa `where`: `native-dev` cubre ahora duplicate declarations de `type` con `where` tanto en type-only como en las composiciones mixtas ya abiertas localmente, preservando el diagnostico canonico `Duplicate declaration: 'Name' already defined as type (first defined at line X)` y acumulando despues los diagnosticos locales ya portados cuando corresponden, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B163 quedo cerrada con `3 passed` en el foco directo de B163 y `580 passed in 426.78s` en el trio canonico frontend, confirmando que el cierre local del duplicate `type` con `where` entra sin romper el contrato observable ni abrir todavia semantica rica adicional.

- B164 llevo al frente `type` el primer hueco real de type checker que quedaba dentro del subset local ya abierto: `native-dev` cubre ahora `Invalid range constraint ...` cuando un `type` local usa `min >= max`, tanto en type-only como en las composiciones mixtas ya abiertas, preservando el mismo orden observable cuando ese diagnostico convive con duplicate declarations, `Unknown memory scope ...` y `Undefined flow ...`, sin delegar entero a Python en `check` ni en `compile`.
- La validacion observable de B164 quedo cerrada con `10 passed` en el foco directo de B164 y `583 passed in 366.49s` en el trio canonico frontend, confirmando que el endurecimiento del prefijo `type` entra sin romper el contrato observable ni abrir todavia type compatibility epistemica.

- B165 cerro la frontera `type` como corte pequeno: `check_type_compatible` y `check_uncertainty_propagation` son codigo muerto en el pipeline de produccion — `TypeChecker.check()` nunca las invoca, ningun `_check_*` visitor las referencia, y solo se ejercitan en tests unitarios aislados. Con la frontera `type` agotada, B165 abrio una nueva frontera de declaracion: `import SomeModule` (3 tokens, 1 declaracion) ahora se maneja localmente sin delegacion a Python, produciendo `IRImport(module_path=("SomeModule",))` en el IR compilado.
- La validacion observable de B165 quedo cerrada con `3 passed in 6.09s` en el foco directo de B165 y `586 passed in 359.29s` en el trio canonico frontend, confirmando que el primer corte de `import` entra sin romper el contrato observable.

- B166 extendio la frontera `import` abierta por B165: `native-dev` ahora maneja localmente importaciones con path punteado (`import a.b`, `import a.b.c`, `import a.b.c.d`) via un loop `IMPORT IDENTIFIER (DOT IDENTIFIER)*` que produce `IRImport(module_path=("a", "b", "c"))` identico al IR de Python, sin delegacion.
- La validacion observable de B166 quedo cerrada con `6 passed in 7.82s` en el foco directo de B166 y `589 passed in 351.12s` en el trio canonico frontend, confirmando que la extension dotted import entra sin romper el contrato observable.

- B167 completo la frontera `import` standalone: `native-dev` ahora maneja localmente importaciones nombradas (`import a { X }`, `import a { X, Y }`, `import a.b { X, Y }`, `import a.b.c { X, Y, Z }`) via consumo opcional de `LBRACE IDENTIFIER (COMMA IDENTIFIER)* RBRACE` despues del path punteado, produciendo `IRImport(module_path=..., names=...)` identico al IR de Python, sin delegacion.
- La validacion observable de B167 quedo cerrada con `7 passed in 7.70s` en el foco directo de B167 y `592 passed in 339.34s` en el trio canonico frontend, confirmando que la extension de named imports entra sin romper el contrato observable.

- B168 abrio la primera composicion `import + flow/run`: se extrajo `_parse_native_single_import` y `_parse_native_import_prefix` como prefix parsers reutilizables, se creo `_match_native_import_flow_run_program` que compone el prefix import con `_match_native_non_type_success_program` y fusiona via `_merge_import_prefix_into_program`, y se inserto en la cadena de dispatch entre type-only e import-only. Cuatro variantes (simple, dotted, named, structural prefix) ahora son LOCAL sin delegacion.
- La validacion observable de B168 quedo cerrada con `6 passed in 3.78s` en el foco directo de B168 y `595 passed in 310.49s` en el trio canonico frontend, confirmando que la composicion import+flow/run entra sin romper el contrato observable.

- B169 generalizo `_match_native_import_program` de single-import a loop multi-import via `_parse_native_single_import` con terminal check, cubriendo programas de N imports standalone (simples, dotted, named, mixtos) sin delegacion.
- La validacion observable de B169 quedo cerrada con `7 passed in 7.39s` en el foco directo de B169 y `598 passed in 306.34s` en el trio canonico frontend, confirmando que multi-import standalone entra sin romper el contrato observable.

- B170 abrio la composicion `type + import + flow/run`: se extendio `_match_native_type_flow_run_program` para intentar `_match_native_import_flow_run_program` sobre los remaining tokens tras el type prefix antes de caer al fallback `_match_native_non_type_success_program`. Tres variantes (type+import+flow/run, type+multi_import+flow/run, multi_type+import+flow/run) ahora son LOCAL sin delegacion.
- La validacion observable de B170 quedo cerrada con `3 passed in 5.62s` en el foco directo de B170 y `601 passed in 336.74s` en el trio canonico frontend, confirmando que la composicion type+import+flow/run entra sin romper el contrato observable.

- B171 cerro la composicion inversa `import + type + flow/run`: se extendio `_match_native_import_flow_run_program` para intentar `_match_native_type_flow_run_program` sobre los remaining tokens tras el import prefix antes de caer al fallback `_match_native_non_type_success_program`. Cuatro variantes (import+type+flow/run, multi_import+type+flow/run, import+multi_type+flow/run, import+type+import+flow/run) ahora son LOCAL sin delegacion.
- La validacion observable de B171 quedo cerrada con `3 passed in 10.52s` en el foco directo de B171 y `604 passed in 309.41s` en el trio canonico frontend, confirmando que la composicion import+type+flow/run entra sin romper el contrato observable.

La frontera de composicion cross-prefix con flow/run queda cerrada en ambas direcciones (type+import y import+type).

- B172 abrio la composicion standalone `type + import` (sin flow/run): se refactorizo `_match_native_type_program` para usar `_parse_native_type_prefix` y luego intentar `_match_native_import_program` sobre los remaining tokens. Cinco variantes (type+import_simple, type+import_dotted, type+import_named, multi_type+import, type+multi_import) ahora son LOCAL sin delegacion.
- La validacion observable de B172 quedo cerrada con `3 passed in 3.70s` en el foco directo de B172 y `607 passed in 310.83s` en el trio canonico frontend, confirmando que la composicion type+import standalone entra sin romper el contrato observable.

- B173 cerro la composicion standalone inversa `import + type` (sin flow/run): se extendio `_match_native_import_program` para intentar `_match_native_type_program` sobre los remaining tokens tras el import prefix. Cinco variantes (import+type_simple, import_dotted+type, import_named+type, multi_import+type, import+multi_type) ahora son LOCAL sin delegacion.
- La validacion observable de B173 quedo cerrada con `3 passed in 6.23s` en el foco directo de B173 y `610 passed in 314.41s` en el trio canonico frontend, confirmando que la composicion import+type standalone entra sin romper el contrato observable.

La frontera de composiciones cross-prefix type+import queda COMPLETAMENTE CERRADA en las cuatro direcciones: type+import+flow/run (B170), import+type+flow/run (B171), type+import standalone (B172), import+type standalone (B173).

- B174 abrio el primer hueco de delegacion real `multi_flow`: se implemento `_match_native_multi_flow_run_program` que parsea N flow blocks vacios (`flow Name() {}`) seguidos de M run statements (`run Name()`) con resolucion local de cada run a su flow declarado. Cuatro variantes verificadas: two flows + two runs, two flows + one run, three flows + three runs, y run order independence.
- La validacion observable de B174 quedo cerrada con `3 passed in 8.16s` en el foco directo de B174 y `613 passed in 318.87s` en el trio canonico frontend, confirmando que multi_flow entra sin romper el contrato observable.

- B175 profundizo multi_flow con run modifiers no-referenciales: se extendio `_match_native_multi_flow_run_program` para parsear modifier tokens entre cada run statement y el siguiente RUN token, reutilizando los helpers existentes de modifier parsing. Seis variantes verificadas: output_to, effort, on_failure log, on_failure raise, on_failure retry, y both-modified.
- La validacion observable de B175 quedo cerrada con `3 passed in 5.32s` en el foco directo de B175 y `616 passed in 321.57s` en el trio canonico frontend, confirmando que multi_flow+modifiers entra sin romper el contrato observable.

- B176 abrio el hueco de delegacion `flow_params`: se implemento `_match_native_parameterized_flow_run_program` que parsea parametros tipados via `_parse_structural_type_expr` reutilizado y genera `IRParameter` por cada parametro. Cinco variantes verificadas: single param, typed param, multi param, optional param, generic param. IR identico a Python en todos los casos.
- La validacion observable de B176 quedo cerrada con `3 passed in 7.03s` en el foco directo de B176 y `619 passed in 315.31s` en el trio canonico frontend, confirmando que flow_params entra sin romper el contrato observable.

- B177 profundizo `flow_params` con non-referential run modifiers: se extendio `_match_native_parameterized_flow_run_program` para que tras parsear `RUN IDENTIFIER LPAREN RPAREN`, si quedan tokens, intente los 5 helpers de modifiers (output_to, effort, on_failure simple/raise/retry). Diez patrones verificados LOCAL incluyendo combinaciones con generic, optional y multi-param. IR identico a Python en 7 casos con modifiers.
- La validacion observable de B177 quedo cerrada con `3 passed in 7.07s` en el foco directo de B177 y `622 passed in 320.26s` en el trio canonico frontend, confirmando que flow_params+modifiers entra sin romper el contrato observable.

La siguiente sesion puede profundizar flow_params con referential modifiers (as, within, constrained_by), multi_flow+params, o moverse a otro hueco real: `flow_body`, `shield_body`, `agent_decl`, `know_decl`, o `type_flow_params`.

- B178 cerro `multi_flow + params`: se extendio `_match_native_multi_flow_run_program` para parsear parametros tipados opcionales en cada flow del loop via `_parse_structural_type_expr`, generando `IRParameter` por cada param. Ocho patrones verificados LOCAL incluyendo combinaciones mixtas bare+param, generic, optional y multi-param con modifiers. IR identico a Python en 8 casos.
- La validacion observable de B178 quedo cerrada con `3 passed in 6.70s` en el foco directo de B178 y `625 passed in 329.72s` en el trio canonico frontend, confirmando que multi_flow+params entra sin romper el contrato observable.

La siguiente sesion puede profundizar flow_params con referential modifiers (as, within, constrained_by) o moverse a otro hueco real: `flow_body`, `know_decl`.

- B179 cerro `flow_params + referential modifiers`: se extendio `_match_native_parameterized_flow_run_program` con kwargs `available_personas`, `available_contexts`, `available_anchors` y se agregaron checks referenciales (as, within, constrained_by) antes de los non-referential. Se modifico `_match_structural_prefixed_native_success_program` para intentar param flow cuando bare flow falla. Tres patrones verificados LOCAL: param+as, param+within, param+constrained_by. IR identico a Python en 3 casos. Fix adicional: validacion de endpoints (shield refs) en structural prefix success path (bug pre-existente).
- La validacion observable de B179 quedo cerrada con `3 passed in 9.81s` en el foco directo de B179 y `656 passed in 393.10s` en el trio canonico frontend, confirmando que flow_params+referential entra sin romper el contrato observable.

La siguiente sesion puede profundizar multi_flow+referential o moverse a otro hueco real: `flow_body`, `know_decl`.

- B180 cerro `multi_flow + referential modifiers`: se extendio `_match_native_multi_flow_run_program` con kwargs `available_personas`, `available_contexts`, `available_anchors` y checks referenciales (as, within, constrained_by) per-run. Se agrego tercer fallback multi-flow en `_match_structural_prefixed_native_success_program` con resolucion de persona/context/anchors por cada run, validacion de endpoints y construccion de IRProgram con multiples flows/runs. Cinco patrones verificados LOCAL: multi+as, multi+within, multi+constrained_by, multi+param+as, multi+param+within. IR identico a Python en 5 casos.
- La validacion observable de B180 quedo cerrada con `3 passed in 1.77s` en el foco directo de B180 y `659 passed in 404.45s` en el trio canonico frontend, confirmando que multi_flow+referential entra sin romper el contrato observable.

La siguiente sesion puede profundizar `flow_body` o `know_decl`.

- B181 cerro `flow_body con empty steps`: se creo helper `_parse_native_flow_body` que parsea cuerpos de flow con step blocks vacios. Se modifico `_match_native_multi_flow_run_program` y `_match_native_parameterized_flow_run_program` para usar el body helper. Se elimino guard `if not params` del parametrizado para habilitar flujos con body pero sin params via el fallback parametrizado. Cuatro patrones verificados LOCAL: flow_body_step, flow_body_multi_step, prefix+flow_body_step, multi_flow_body. IR identico a Python en 5 casos.
- La validacion observable de B181 quedo cerrada con `3 passed in 10.16s` en el foco directo de B181 y `662 passed in 407.62s` en el trio canonico frontend, confirmando que flow_body entra sin romper el contrato observable.

La siguiente sesion puede profundizar `shield_only`, `compute`, u otro hueco delegado restante.