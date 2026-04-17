# Plan de Migración del CLI AXON a Binario Nativo (Sesión C2)

## 1. Análisis del CLI Python Actual

- **Archivo principal:** axon/cli/main.py
- **Dependencias:** argparse, sys, importlib, runtime Python, módulos internos AXON
- **Comandos soportados:**
  - axon version
  - axon check <file>
  - axon compile <file>
  - axon trace <file>
- **Flags y opciones:**
  - --help, --version, --output, etc.
- **Errores y códigos de salida:**
  - 0: éxito, 1: error de usuario, 2: error interno
- **Notas:**
  - El CLI invoca funciones Python directamente.
  - El output y los errores se imprimen por stdout/stderr.

## 2. Requerimientos Mínimos para el CLI Nativo

- Replicar los comandos MVP: version, check, compile, trace
- Soportar flags básicos (--help, --version, --output)
- Manejar errores y códigos de salida compatibles
- Output legible y consistente
- Portabilidad Windows/Linux

## 3. Propuesta de Stack Tecnológico

- **Lenguaje sugerido:** Rust (por ecosistema CLI, binarios estáticos, FFI)
- **Alternativas:** Go, C++
- **Librerías CLI:** clap (Rust), cobra (Go), argparse (C++)
- **Estrategia de integración:**
  - Fase 1: CLI nativo como wrapper que llama al runtime Python vía proceso externo
  - Fase 2: Migrar llamadas críticas a FFI o reimplementación nativa

## 4. Estrategia de Migración

1. Definir interfaz mínima entre CLI y runtime (contrato de comandos y salida)
2. Implementar prototipo de `axon version` en Rust
3. Iterar con `check`, `compile`, `trace`
4. Validar paridad de salida y errores
5. Documentar diferencias y riesgos

## 5. Riesgos y Dependencias

- Complejidad de integración con runtime Python
- Paridad de errores y salida
- Portabilidad y distribución
- Mantenimiento dual durante transición

## 6. Handoff

La siguiente sesión (C3) debe iniciar la implementación del CLI nativo, comenzando por el comando `axon version` y validando su funcionamiento en Windows.

---

> Este plan se irá ajustando según los hallazgos y bloqueos durante la migración.
