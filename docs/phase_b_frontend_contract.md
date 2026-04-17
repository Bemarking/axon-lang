# Fase B - Contrato Inicial de Diagnosticos e IR del Frontend

## Objetivo

Congelar el primer contrato estable que deben respetar el frontend actual en Python y cualquier reemplazo futuro del core nativo para sostener `axon check` y `axon compile`.

Este documento fija el contrato minimo de compatibilidad de `Fase B`. No congela todos los detalles internos del compilador actual.

## Alcance

Este contrato cubre:

- diagnosticos observables de `axon check`
- diagnosticos observables de `axon compile`
- shape minimo estable del IR emitido por `axon compile`
- metadatos minimos que la CLI y las pruebas de compatibilidad pueden exigir

Este contrato no cubre:

- `axon trace`
- runtime, server o backends de ejecucion
- cache de compilacion
- orden exacto de claves JSON
- todos los campos opcionales o transicionales del IR actual

## Evidencia Base

Fuentes verificadas para congelar este contrato:

- `docs/cli_mvp_observable_contract.md`
- `axon/cli/check_cmd.py`
- `axon/cli/compile_cmd.py`
- `axon/compiler/errors.py`
- `axon/compiler/type_checker.py`
- `axon/compiler/ir_nodes.py`
- salida real de `python -m axon.cli compile examples/contract_analyzer.axon --stdout`
- salida real de error de sintaxis para `check` y `compile` con fixture temporal `temp_b2_bad.axon`

## Contrato de Diagnosticos

### 1. Categorias congeladas

Para `axon check` y `axon compile`, el frontend debe distinguir estas categorias:

- exito
- error de I/O o archivo inexistente
- error de lexer o parser
- error semantico o de type checker
- error interno de generacion de IR en `compile`

### 2. Codigos de salida congelados

`axon check`:

- `0`: frontend valido, sin errores
- `1`: error de lexer, parser o type checker
- `2`: error de I/O o archivo inexistente

`axon compile`:

- `0`: compilacion exitosa
- `1`: error de lexer, parser, type checker o generacion de IR
- `2`: error de I/O o archivo inexistente

### 3. Contrato observable de `check`

#### Exito

- escribe una sola linea de resumen humano en stdout
- no escribe nada en stderr
- la linea mantiene esta forma logica:

`<ok-mark> <file-name>  <token-count> tokens · <declaration-count> declarations · 0 errors`

Garantias estables:

- incluye el nombre base del archivo fuente, no la ruta completa
- incluye conteo de tokens
- incluye conteo de declaraciones
- incluye el literal `0 errors`

No se congela para `Fase B`:

- color ANSI
- glifos Unicode frente a fallback ASCII
- espaciado exacto fuera de los separadores principales

#### Error de I/O

- retorna `2`
- no escribe nada en stdout
- escribe una sola linea en stderr con esta forma:

`<error-mark> File not found: <normalized-path>`

Garantias estables:

- la ruta visible usa `/` como separador observable
- el mensaje empieza con `File not found:`

#### Error de lexer o parser

- retorna `1`
- escribe una sola linea principal de diagnostico
- la linea incluye nombre de archivo y ubicacion

Forma minima estable:

`<error-mark> <file-name>:<line>:<column>  <message>`

Garantias estables:

- `line` y `column` son 1-based
- el mensaje humano proviene de `AxonError.message`
- la ubicacion aparece solo si el error la conoce

Observacion actual:

- hoy el error de sintaxis observado para `temp_b2_bad.axon` cae en esta forma exacta:

`✗ temp_b2_bad.axon:1:1  Unexpected token at top level (expected declaration ..., found 42)`

#### Error semantico o de type checker

- retorna `1`
- el frontend puede emitir un resumen y luego una o mas lineas de detalle

Garantias estables:

- cada violacion semantica tiene mensaje humano, linea y columna en el dato interno del frontend
- `type_checker.py` materializa hoy cada violacion como `AxonTypeError(message, line, column)`
- el adaptador CLI puede transformar esas violaciones a texto humano sin perder mensaje ni ubicacion

No se congela para `Fase B`:

- si las lineas de detalle salen por stdout o stderr en `check`
- el texto exacto del resumen de cantidad de errores tipados
- presencia de `severity` o `code` en la salida humana del shell

Decision:

- el contrato estable para reemplazo del frontend exige preservar `message`, `line` y `column` por diagnostico semantico
- `severity` y `code` no son parte del contrato observable minimo de B2

### 4. Contrato observable de `compile`

#### Exito con `--stdout`

- retorna `0`
- escribe exactamente un documento JSON valido a stdout
- no escribe nada en stderr

#### Exito con `--output`

- retorna `0`
- escribe el JSON en la ruta objetivo
- imprime una sola linea de confirmacion en stdout

Forma minima estable:

`<ok-mark> Compiled → <normalized-path>`

Garantias estables:

- la ruta visible usa `/` como separador observable
- el JSON escrito es el mismo shape logico que el emitido con `--stdout`

#### Error de I/O

- retorna `2`
- no escribe nada en stdout
- escribe en stderr:

`<error-mark> File not found: <normalized-path>`

#### Error de lexer o parser

- retorna `1`
- escribe una linea principal con archivo, ubicacion y mensaje
- la forma minima estable coincide con `check`

#### Error semantico o de type checker

- retorna `1`
- escribe resumen y detalles humanos

Garantias estables:

- cada error semantico preserva `message`, `line` y `column`
- el adaptador CLI puede decidir el layout final siempre que no pierda esa informacion

#### Error de generacion de IR

- retorna `1`
- escribe una linea humana en stderr

Forma minima estable:

`<error-mark> IR generation failed: <message>`

## Contrato Minimo de Diagnostico Estructurado

El reemplazo futuro del frontend debe poder exponer, al menos internamente, este shape por diagnostico individual:

```json
{
  "stage": "lexer | parser | type_checker | ir_generator",
  "message": "human readable message",
  "line": 1,
  "column": 1
}
```

Reglas:

- `stage` es obligatorio en la frontera interna del frontend, aunque hoy la CLI no lo imprima
- `message` es obligatorio
- `line` y `column` son obligatorios cuando exista ubicacion conocida
- `severity` y `code` quedan reservados para una expansion posterior, fuera del contrato minimo B2

## Contrato de IR

### 1. Raiz del documento

`axon compile --stdout` debe emitir un JSON cuya raiz tenga:

- `node_type = "program"`
- `source_line`
- `source_column`
- colecciones top-level del programa
- `_meta`

Colecciones top-level minimas congeladas:

- `personas`
- `contexts`
- `anchors`
- `tools`
- `memories`
- `types`
- `flows`
- `runs`
- `imports`
- `agents`
- `shields`
- `daemons`
- `ots_specs`
- `pix_specs`
- `corpus_specs`
- `psyche_specs`
- `mandate_specs`
- `lambda_data_specs`
- `compute_specs`
- `axonstore_specs`
- `endpoints`

Regla:

- estas colecciones deben existir siempre, aunque esten vacias

### 2. Invariante comun de nodos IR

Todo nodo IR serializado que represente una entidad del programa debe conservar:

- `node_type`
- `source_line`
- `source_column`

`node_type` es el discriminador estable del contrato.

### 3. Campos minimos estables por familia de nodo

#### Persona

- `node_type = "persona"`
- `name`

#### Context

- `node_type = "context"`
- `name`
- `memory_scope`
- `language`
- `depth`

#### Anchor

- `node_type = "anchor"`
- `name`
- `require`
- `confidence_floor`
- `on_violation`
- `on_violation_target`

#### Type definition

- `node_type = "type_def"`
- `name`
- `fields`
- `range_min`
- `range_max`
- `where_expression`

#### Flow

- `node_type = "flow"`
- `name`
- `parameters`
- `return_type_name`
- `steps`
- `edges`
- `execution_levels`

#### Parameter

- `node_type = "parameter"`
- `name`
- `type_name`
- `optional`

#### Step

- `node_type = "step"`
- `name`
- `given`
- `ask`
- `output_type`

#### Data edge

- `node_type = "data_edge"`
- `source_step`
- `target_step`
- `type_name`

#### Run

- `node_type = "run"`
- `flow_name`
- `arguments`
- `persona_name`
- `context_name`
- `anchor_names`
- `on_failure`
- `on_failure_params`
- `output_to`
- `effort`

### 4. Metadatos `_meta`

`_meta` queda congelado como metadato observable del comando `compile`, no como parte del IR semantico puro.

Campos minimos:

- `source`
- `backend`
- `axon_version`

Garantias estables:

- `source` usa `/` como separador observable
- `backend` refleja el valor efectivo del argumento `--backend`
- `axon_version` refleja la version del toolchain que emitio el JSON

### 5. Campos transicionales no congelados en B2

El IR actual expone mas informacion de la estrictamente necesaria para compatibilidad minima. En `Fase B`, estos elementos no quedan congelados como obligatorios:

- orden exacto de claves JSON
- detalle completo de nodos no ejercitados por los fixtures de compatibilidad iniciales
- presencia de campos opcionales vacios cuyo unico fin es conveniencia del serializador
- campos `resolved_*` dentro de `run`

Decision importante:

- el frontend actual puede seguir emitiendo `resolved_flow`, `resolved_persona`, `resolved_context` y `resolved_anchors`
- el frontend nativo futuro no queda obligado por B2 a preservarlos si mantiene los campos simbolicos y el contrato minimo de IR

## Regla de Compatibilidad para B3

La suite de golden tests de B3 debe comparar:

- codigos de salida
- categorias de diagnostico
- presencia de archivo, linea y columna en errores observables de parser y lexer
- shape minimo del IR
- `_meta.source`, `_meta.backend` y `_meta.axon_version`

La suite de B3 no debe bloquear la evolucion del core por:

- orden de claves JSON
- campos `resolved_*`
- diferencias cosmeticas de ANSI o fallback ASCII

## Decision de B2

El contrato inicial del frontend queda congelado en dos niveles:

- contrato observable de shell para `check` y `compile`
- contrato minimo estructurado de diagnosticos e IR para desacoplar la CLI del core

Esto habilita la siguiente sesion: crear golden tests que verifiquen compatibilidad sin atar el futuro nucleo nativo a todos los accidentes de la implementacion Python actual.