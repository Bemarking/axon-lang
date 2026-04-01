# AXON MVP Executable - Quick Start

## Alcance

Esta guia cubre el ejecutable puente de `Fase A` para Windows.

No describe toda la plataforma AXON. Describe el primer binario usable del lenguaje.

## Que es este artefacto

El ejecutable MVP de AXON es una distribucion Windows en modo one-folder.

El artefacto esperado desde CI es:

```text
axon-mvp-windows
```

Su contenido principal es:

```text
axon/
  axon.exe
  _internal/
```

## Instalacion

1. Descarga el artefacto `axon-mvp-windows` desde CI.
2. Extrae el contenido en una carpeta local.
3. Conserva `axon.exe` y `_internal/` en el mismo directorio.
4. Ejecuta `axon.exe` desde esa carpeta o agrega esa ruta al `PATH`.

## Verificacion minima

Desde PowerShell:

```powershell
& .\axon.exe version
```

Salida esperada:

```text
axon-lang 0.30.6
```

## Comandos soportados en el MVP

El ejecutable puente soporta solo estos comandos:

- `axon version`
- `axon check <file.axon>`
- `axon compile <file.axon>`
- `axon trace <file.trace.json>`

## Uso rapido

### 1. Ver version

```powershell
& .\axon.exe version
```

### 2. Validar un archivo `.axon`

```powershell
& .\axon.exe check .\examples\contract_analyzer.axon --no-color
```

### 3. Compilar a IR JSON

```powershell
& .\axon.exe compile .\examples\contract_analyzer.axon --output .\contract_analyzer.ir.json
```

### 4. Ver un trace

```powershell
& .\axon.exe trace .\examples\sample.trace.json --no-color
```

## Codigos de salida del MVP

- `0`: exito
- `1`: error de compilacion
- `2`: error de I/O o error de uso del CLI

## Limites conocidos

Este ejecutable MVP todavia no incluye:

- `axon run`
- `axon repl`
- `axon inspect`
- `axon serve`
- `axon deploy`

Tampoco sustituye la estrategia final de produccion de AXON. Es el ejecutable puente de `Fase A`.

## Diagnostico rapido

Si `axon.exe` no funciona:

1. Verifica que `_internal/` siga junto a `axon.exe`.
2. Ejecuta `axon.exe version` primero.
3. Si `check` o `compile` fallan, confirma que el archivo de entrada existe.
4. Si `trace` falla, confirma que el archivo es JSON valido.

## Resultado esperado de Fase A

Con esta guia, un usuario Windows puede instalar y usar el ejecutable puente de AXON sin crear una `.venv` ni instalar Python manualmente.