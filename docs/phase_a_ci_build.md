# Fase A - Build del Ejecutable en CI

## Objetivo

Automatizar en CI el build del ejecutable MVP de AXON para Windows y dejar el artefacto listo para validacion.

## Workflow

El build del ejecutable puente queda integrado en:

```text
.github/workflows/ci.yml
```

## Job agregado

```text
windows-mvp-executable
```

## Responsabilidades del job

- preparar Python 3.13 en Windows
- instalar dependencias de desarrollo
- ejecutar `scripts/build_axon_mvp_windows.ps1` usando el `python` configurado por el runner
- validar el binario empaquetado con comandos MVP
- ejecutar `scripts/validate_axon_mvp_error_contract.ps1`
- subir el artefacto generado

## Artefacto publicado

Nombre del artefacto:

```text
axon-mvp-windows
```

Contenido esperado:

```text
build/pyinstaller/dist/axon/
```

## Verificacion minima automatizada

El job valida, como minimo:

- `axon.exe version`
- `axon.exe check examples/contract_analyzer.axon --no-color`
- `axon.exe compile examples/contract_analyzer.axon --output temp_ci_compile.ir.json`
- `axon.exe trace examples/sample.trace.json --no-color`
- contrato principal de errores del binario

## Resultado

Con esta integracion, `Fase A` ya no depende solo del build manual local. El ejecutable puente puede construirse en CI sin asumir una ruta local fija de `.venv`, validar tambien la compilacion exitosa y dejar un artefacto descargable para validacion posterior.