# Fase A - Validacion del Binario Empaquetado

## Alcance

Este documento registra la validacion directa del binario empaquetado generado en `Fase A`.

La validacion se divide por sesiones:

- `A6`: `version` y `check`
- `A7`: `compile` y `trace`

## A6 - `version` y `check`

### Binario validado

```text
build/pyinstaller/dist/axon/axon.exe
```

### Comandos ejecutados

```powershell
& .\build\pyinstaller\dist\axon\axon.exe version
& .\build\pyinstaller\dist\axon\axon.exe check examples/contract_analyzer.axon --no-color
& .\build\pyinstaller\dist\axon\axon.exe check examples/__missing__.axon --no-color
```

### Resultados observados

- `version` imprime `axon-lang 0.30.6`
- `version` devuelve `0`
- `check` sobre `examples/contract_analyzer.axon` imprime `✓ contract_analyzer.axon  168 tokens · 9 declarations · 0 errors`
- `check` sobre fuente valida devuelve `0`
- `check` sobre `examples/__missing__.axon` imprime `✗ File not found: examples\__missing__.axon`
- `check` sobre archivo inexistente devuelve `2`

### Conclusión

El binario empaquetado conserva el contrato observable congelado para `version` y `check` en el alcance actual del MVP.

## A7 - `compile` y `trace`

### Binario validado

```text
build/pyinstaller/dist/axon/axon.exe
```

### Comandos ejecutados

```powershell
& .\build\pyinstaller\dist\axon\axon.exe compile examples/contract_analyzer.axon --output temp_a7_compile.ir.json
& .\build\pyinstaller\dist\axon\axon.exe compile examples/__missing__.axon
& .\build\pyinstaller\dist\axon\axon.exe trace examples/sample.trace.json --no-color
& .\build\pyinstaller\dist\axon\axon.exe trace README.md --no-color
```

### Resultados observados

- `compile` sobre `examples/contract_analyzer.axon` imprime `✓ Compiled → temp_a7_compile.ir.json`
- `compile` sobre fuente valida devuelve `0`
- el archivo `temp_a7_compile.ir.json` se genera correctamente
- el IR generado incluye `node_type: "program"`
- `compile` sobre `examples/__missing__.axon` imprime `✗ File not found: examples\__missing__.axon`
- `compile` sobre archivo inexistente devuelve `2`
- `trace` sobre `examples/sample.trace.json` renderiza el encabezado `AXON Execution Trace`
- `trace` sobre `examples/sample.trace.json` devuelve `0`
- `trace` sobre `README.md` imprime `✗ Invalid JSON: Expecting value: line 1 column 1 (char 0)`
- `trace` sobre JSON invalido devuelve `2`

### Conclusión

El binario empaquetado conserva el contrato observable congelado para `compile` y `trace` en el alcance actual del MVP.

## A8 - Endurecimiento de errores del binario

### Ajuste aplicado

- `compile` ahora reporta errores de compilacion con formato consistente respecto a `check`
- el caso de parseo invalido del binario queda normalizado como `✗ <archivo>:<linea>:<columna>  <mensaje>`

### Casos verificados

- `check` sobre archivo inexistente devuelve `2`
- `compile` sobre archivo inexistente devuelve `2`
- `compile` sobre sintaxis invalida devuelve `1`
- `trace` sobre JSON invalido devuelve `2`
- `check` sin argumento requerido devuelve `2`
- comando desconocido devuelve `2`

### Script de validacion

```powershell
& .\scripts\validate_axon_mvp_error_contract.ps1
```

### Conclusión

El binario MVP queda con un contrato de error principal consistente y verificable para los casos canónicos de `Fase A`.