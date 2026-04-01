# Fase A - Build Local del Ejecutable Puente

## Objetivo

Documentar el flujo local reproducible para generar el primer ejecutable MVP de AXON en Windows.

## Requisito

- entorno Python del repo activo
- `pyinstaller` disponible en dependencias de desarrollo

## Comando de Build

Desde la raiz del repositorio:

```powershell
& .\scripts\build_axon_mvp_windows.ps1
```

## Resultado Esperado

El script genera un artefacto one-folder en:

```text
build/pyinstaller/dist/axon/
```

El ejecutable principal queda en:

```text
build/pyinstaller/dist/axon/axon.exe
```

## Verificacion Minima de Arranque

```powershell
& .\build\pyinstaller\dist\axon\axon.exe version
```

Salida esperada:

```text
axon-lang 0.30.6
```

## Alcance del Binario Actual

Este build corresponde al MVP congelado de `Fase A`.

Solo cubre:

- `version`
- `check`
- `compile`
- `trace`

## Nota de Ingenieria

Este build no representa la estrategia final de produccion. Representa el primer artefacto reproducible del ejecutable puente para Windows.