# Fase B - Corte Inicial Core vs Infra

## Objetivo

Fijar el primer corte operativo entre el `core` del lenguaje AXON y la infraestructura Python que hoy lo rodea.

Este documento no implementa el nucleo nativo. Define que debe migrarse primero, que debe quedarse como adaptador y que acoples bloquean el salto de `Fase B`.

## Regla del Corte

En `Fase B`, `core` significa:

- frontend del lenguaje
- contratos semanticos y diagnosticos
- contrato de IR necesario para `check` y `compile`

En `Fase B`, `infra` significa:

- ejecucion runtime
- integraciones externas
- FFI
- server
- canales
- storage
- despliegue
- adaptadores CLI

## Clasificacion Inicial

### 1. Core directo del frontend

Estos modulos pertenecen al nucleo del lenguaje y son los mejores candidatos para una implementacion nativa temprana:

- `axon/compiler/tokens.py`
- `axon/compiler/errors.py`
- `axon/compiler/ast_nodes.py`
- `axon/compiler/ir_nodes.py`
- `axon/compiler/lexer.py`
- `axon/compiler/parser.py`
- `axon/compiler/type_checker.py`
- `axon/compiler/ir_generator.py`

Razon:

- definen la sintaxis
- definen el AST y el IR
- fijan los diagnosticos primarios de `check` y `compile`
- no dependen conceptualmente de proveedores, red o runtime distribuido

### 2. Core adyacente que debe quedar como frontera explicita

Estos modulos no son runtime operativo, pero tampoco son frontend puro. Deben tratarse como frontera de compilacion:

- `axon/compiler/module_resolver.py`
- `axon/compiler/interface_generator.py`
- `axon/compiler/compilation_cache.py`

Razon:

- sostienen compilacion incremental, resolucion de imports y cache
- hoy dependen de `Path`, layout de archivos y serializacion Python
- su semantica debe preservarse, pero su implementacion puede cambiar despues de congelar contratos de diagnosticos e IR

Decision:

- en `Fase B`, estos modulos se clasifican como `compiler boundary services`
- no bloquean el arranque del nucleo nativo del lexer/parser/type checker
- si bloquean la consolidacion del frontend nativo completo

### 3. Infraestructura de adaptacion al frontend

Estos modulos exponen el frontend al usuario, pero no pertenecen al core del lenguaje:

- `axon/cli/check_cmd.py`
- `axon/cli/compile_cmd.py`
- `axon/cli/trace_cmd.py`
- `axon/cli/version_cmd.py`
- `axon/cli/__init__.py`
- `packaging/axon_mvp_entry.py`

Razon:

- son adaptadores de shell
- formatean salida, rutas y codigos de error
- deben seguir consumiendo el frontend, no definirlo

Decision:

- la CLI queda como `adapter layer`
- en `Fase B` no se porta primero la CLI; primero se congela el contrato que la CLI debe consumir

### 4. Infraestructura runtime y operativa

Estos modulos quedan fuera del core de `Fase B`:

- `axon/runtime/executor.py`
- `axon/runtime/context_mgr.py`
- `axon/runtime/retry_engine.py`
- `axon/runtime/tracer.py`
- `axon/runtime/semantic_validator.py`
- `axon/runtime/memory_backend.py`
- `axon/runtime/state_backends/`
- `axon/runtime/store_backends/`
- `axon/runtime/channels/`
- `axon/runtime/tools/`
- `axon/runtime/routers/`
- `axon/runtime/supervisor.py`
- `axon/engine/`
- `axon/server/`

Razon:

- dependen de efectos, integraciones, storage, modelo de ejecucion y operacion distribuida
- no son necesarios para portar primero `check` y `compile`
- pertenecen mas a `Fase C` o a una integracion posterior del core nativo

### 5. Puentes y piezas transicionales ya existentes

Estas piezas confirman que el repositorio ya reconoce una frontera entre lenguaje y ejecucion nativa, pero hoy viven del lado Python:

- `axon/runtime/native_compiler.py`
- `axon/runtime/rust_transpiler.py`
- `axon/runtime/ffi_bridge.py`

Razon:

- intentan llevar logica a Rust/C via FFI
- hoy se aplican al runtime compute, no al frontend del lenguaje
- prueban que el repositorio ya tiene intuicion de puente nativo, pero en el lugar incorrecto para `Fase B`

Decision:

- no son el nucleo nativo de `Fase B`
- se clasifican como `transitional native runtime infrastructure`

## Acoples Criticos Detectados

### A1. Resolucion de modulos acoplada a filesystem Python

Archivo principal:

- `axon/compiler/module_resolver.py`

Problema:

- usa `Path`, lectura directa de archivos y convenciones de layout del repo para descubrir modulos
- eso impide que el frontend nativo se piense aun como un componente puro con interfaz de entrada/salida bien delimitada

Impacto:

- bloquea portar el frontend completo como libreria nativa limpia

### A2. Cache de compilacion acoplada a JSON y estado Python

Archivo principal:

- `axon/compiler/compilation_cache.py`

Problema:

- persiste `ir_data` como `dict[str, Any]` serializado a JSON desde estructuras Python
- el contrato del cache todavia no esta separado del formato interno del compilador actual

Impacto:

- bloquea cache compartible o intercambiable entre implementaciones

### A3. CLI consume directamente implementacion Python del frontend

Archivos principales:

- `axon/cli/check_cmd.py`
- `axon/cli/compile_cmd.py`
- `axon/cli/__init__.py`

Problema:

- la CLI invoca directamente `Lexer`, `Parser`, `TypeChecker` e `IRGenerator`
- no existe aun una fachada de frontend estable que pueda ser reemplazada por un backend nativo sin tocar adaptadores

Impacto:

- obliga a modificar CLI y frontend a la vez

### A4. Runtime nativo existente esta orientado a compute, no al frontend

Archivos principales:

- `axon/runtime/native_compiler.py`
- `axon/runtime/rust_transpiler.py`
- `axon/runtime/ffi_bridge.py`

Problema:

- la infraestructura nativa actual compila bloques de compute y usa `ctypes`
- no sirve directamente como arquitectura del frontend nativo del lenguaje

Impacto:

- puede distraer la migracion hacia el lugar incorrecto del sistema

## Corte Operativo Recomendado para Fase B

El corte inicial recomendado es este:

- `frontend core v1`: `tokens`, `errors`, `ast_nodes`, `ir_nodes`, `lexer`, `parser`, `type_checker`, `ir_generator`
- `compiler boundary v1`: `module_resolver`, `interface_generator`, `compilation_cache`
- `adapter layer v1`: `axon/cli/check_cmd.py`, `axon/cli/compile_cmd.py`, `axon/cli/__init__.py`, `packaging/axon_mvp_entry.py`
- `runtime/ops excluded from B1`: todo `axon/runtime/` salvo piezas usadas solo como referencia arquitectonica

## Secuencia Recomendada

1. Congelar contrato observable de diagnosticos para `check` y `compile`.
2. Congelar contrato minimo de IR.
3. Introducir una fachada unica de frontend consumida por la CLI.
4. Reimplementar esa fachada sobre nucleo nativo.
5. Mover resolucion modular y cache a contratos estables independientes del runtime Python.

## Decision de B1

Para `Fase B`, el primer objetivo tecnico no es portar `run`, ni FFI, ni runtime compute.

El primer objetivo tecnico es separar y fijar el `frontend core` que sostiene `check` y `compile`.

## Handoff

La siguiente sesion debe congelar el contrato inicial de diagnosticos e IR del frontend para que el reemplazo del core no arrastre a la CLI ni al runtime.