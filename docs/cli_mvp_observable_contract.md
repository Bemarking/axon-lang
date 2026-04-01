# Contrato Observable del CLI MVP

## Alcance

Este documento congela el comportamiento observable del CLI MVP de AXON para `Fase A - Ejecutable Puente`.

Comandos incluidos:

- `axon version`
- `axon check`
- `axon compile`
- `axon trace`

El objetivo es fijar:

- parametros visibles
- codigos de salida observables en shell
- comportamiento de stdout y stderr
- fixtures canonicos para verificacion

## Fixtures Canonicos

- fuente valida para `check` y `compile`: `examples/contract_analyzer.axon`
- trace valida para `trace`: `examples/sample.trace.json`
- ruta inexistente para errores de I/O: `examples/__missing__.axon`
- entrada invalida para `trace`: `README.md`

## Comando: `axon version`

### Parametros observables

- sin argumentos posicionales
- sin flags propias del subcomando

### Salida esperada

- stdout: `axon-lang 0.30.6`
- stderr: vacio

### Codigo de salida observado

- exito: `0`

### Caso canonico

Comando:

```powershell
python -m axon.cli version
```

## Comando: `axon check`

### Parametros observables

- `file`
- `--no-color`

### Comportamiento observable en exito

- lee el archivo fuente
- ejecuta lexer, parser y type checker
- imprime una linea de resumen en stdout
- no escribe archivos

### Salida esperada en exito

- stdout: `✓ contract_analyzer.axon  168 tokens · 9 declarations · 0 errors`
- stderr: vacio

### Codigo de salida observado

- exito: `0`
- error de compilacion o tipado: `1`
- error de I/O o archivo inexistente: `2`

### Salida esperada en error de I/O

- stderr: `✗ File not found: examples\__missing__.axon`

### Casos canonicos

Comandos:

```powershell
python -m axon.cli check examples/contract_analyzer.axon --no-color
python -m axon.cli check examples/__missing__.axon --no-color
```

## Comando: `axon compile`

### Parametros observables

- `file`
- `-b`, `--backend`
- `-o`, `--output`
- `--stdout`

### Comportamiento observable en exito

- ejecuta lexer, parser, type checker e IR generator
- serializa el IR a JSON
- si `--stdout` esta presente, imprime el JSON en stdout
- si `--stdout` no esta presente, escribe un archivo `.ir.json` o la ruta indicada por `--output`

### Salida esperada en exito con `--output`

- stdout: `✓ Compiled → temp_a1_compile.ir.json`
- stderr: vacio

### Salida esperada en exito con `--stdout`

- stdout: JSON del IR compilado
- el JSON observado incluye `_meta.source`, `_meta.backend` y `_meta.axon_version`
- stderr: vacio

### Codigo de salida observado

- exito: `0`
- error de compilacion: `1`
- error de I/O o archivo inexistente: `2`

### Salida esperada en error de I/O

- stderr: `✗ File not found: examples\__missing__.axon`

### Casos canonicos

Comandos:

```powershell
python -m axon.cli compile examples/contract_analyzer.axon --stdout
python -m axon.cli compile examples/contract_analyzer.axon --output temp_a1_compile.ir.json
python -m axon.cli compile examples/__missing__.axon
```

## Comando: `axon trace`

### Parametros observables

- `file`
- `--no-color`

### Comportamiento observable en exito

- lee un archivo `.trace.json`
- renderiza una salida humana en forma de timeline
- no modifica archivos

### Salida esperada en exito

- stdout: bloque renderizado con encabezado `AXON Execution Trace`
- stdout incluye `source: contract_analyzer.axon`
- stdout incluye `backend: anthropic`
- stdout incluye eventos `step_start`, `model_call`, `anchor_pass` y `step_end`
- stderr: vacio

### Codigo de salida observado

- exito: `0`
- archivo inexistente: `2`
- JSON invalido: `2`

### Salida esperada en error de JSON invalido

- stderr: `✗ Invalid JSON: Expecting value: line 1 column 1 (char 0)`

### Casos canonicos

Comandos:

```powershell
python -m axon.cli trace examples/sample.trace.json --no-color
python -m axon.cli trace README.md --no-color
```

## Notas de Congelamiento

- Este documento congela comportamiento observable de shell, no detalles internos de implementacion.
- Los codigos de salida congelados son los observados en terminal usando `python -m axon.cli`.
- Los ejemplos de stdout y stderr son canonicos para la version base `v0.30.6`.
- Si un cambio futuro modifica estos comportamientos, debe pasar por sesion explicita y actualizar este documento.