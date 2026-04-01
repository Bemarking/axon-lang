# Fase A - Revision Formal de Salida

## Fecha

2026-04-01

## Dictamen

`Fase A` queda aprobada para cierre y habilitada para activar `Fase B`.

## Criterios revisados

- existe un binario `axon` reproducible
- `axon version` funciona
- `axon check <file.axon>` funciona
- `axon compile <file.axon>` funciona
- `axon trace <file.trace.json>` funciona
- el flujo de distribucion ya no exige contar la historia de `.venv`

## Evidencia usada

- `docs/cli_mvp_observable_contract.md`
- `tests/test_cli_mvp_smoke.py`
- `docs/phase_a_mvp_cut.md`
- `docs/phase_a_windows_packaging_strategy.md`
- `scripts/build_axon_mvp_windows.ps1`
- `docs/phase_a_local_build.md`
- `docs/phase_a_packaged_binary_validation.md`
- `.github/workflows/ci.yml`
- `docs/phase_a_ci_build.md`
- `docs/phase_a_executable_user_guide.md`

## Hallazgos de revision y resolucion

### 1. Bloqueante de CI corregido

Se detecto que `scripts/build_axon_mvp_windows.ps1` dependia de una ruta local fija a `.venv`.

Eso hacia fragil o inviable la ejecucion en runners de CI y no cumplia bien el entregable de build reproducible.

Se corrigio para resolver `python` desde `AXON_PYTHON`, `PATH` o `.venv` local como fallback.

### 2. Cobertura automatizada del binario reforzada

Se detecto que la validacion automatizada del job de Windows no cubria el caso exitoso de `axon.exe compile`.

Se agrego la ejecucion de `compile` con verificacion del artefacto generado dentro de `.github/workflows/ci.yml`.

## Riesgos residuales no bloqueantes

- falta observar la primera corrida remota del job `windows-mvp-executable` despues de estos ultimos ajustes
- el build PyInstaller sigue siendo pesado porque el entorno arrastra dependencias grandes del repositorio; eso es deuda operativa para fases posteriores, no bloqueo de salida de `Fase A`

## Decision de gate

La fase cumple su objetivo de producto: ya existe una historia usable de ejecutable puente en Windows para `version`, `check`, `compile` y `trace`, con build local, build en CI, contrato observable y documentacion minima.

Por lo tanto, `Fase A` se considera cerrada y `Fase B` puede activarse.

## Condicion de merge de cierre

El merge que cierre administrativamente `Fase A` puede hacerse bajo estas condiciones:

- mantener la base funcional publica en `v0.30.6`
- no promover release publico nuevo
- registrar el merge como avance interno de programa
- usar la siguiente referencia interna recomendada: `v0.30.6-internal.a.10.2`
- marcar ese merge como `validated` por cierre de fase
- dejar `Fase B` como unica fase activa despues del merge

Esta condicion de merge no cambia la politica general: `v1.0.0` sigue reservada para el cierre completo de `Fase C`.

## Handoff

La siguiente sesion debe abrir `Fase B - Nucleo Nativo` con un primer corte de delimitacion entre core del lenguaje e infraestructura Python.