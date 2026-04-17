# Mapeo de Dependencias Python en Runtime AXON (Fase C)

Este documento lista y describe todos los puntos del runtime, toolchain y CLI de AXON que dependen directa o indirectamente de Python.

## Estructura

- **Módulo/Archivo:** Ruta en el repo.
- **Descripción:** Qué hace y por qué depende de Python.
- **Tipo de acoplamiento:** (directo/indirecto, crítico/menor)
- **Impacto:** Qué rompe si se elimina Python.
- **Estrategia de desacoplamiento (propuesta):** Idea inicial para migrar o aislar.
- **Notas:** Observaciones adicionales.

## Tabla de Dependencias

| Módulo/Archivo | Descripción | Tipo de acoplamiento | Impacto | Estrategia de desacoplamiento | Notas |
|---|---|---|---|---|---|
| axon/runtime/server.py | Implementa el servidor principal de AXON, usa threading y dependencias Python para IO y procesos. | Directo, crítico | El servidor no arranca sin Python, no hay manejo de requests. | Reescribir en Rust/Go o aislar en proceso externo. | Requiere definir API estable para desacoplar. |
| axon/cli/main.py | CLI principal, usa argparse y entrypoints Python. | Directo, crítico | Sin Python no hay CLI funcional. | Migrar CLI a binario nativo (ej. Rust, C++). | Puede mantenerse como wrapper opcional. |
| axon/compiler/frontend.py | Parsing y compilación, depende de clases y runtime Python. | Directo, crítico | No hay compilación ni validación sin Python. | Portar parser y checker a core nativo. | Proceso incremental, puede convivir con fallback. |
| axon/backends/ | Drivers de backends (ej. SQLite, Postgres) usan librerías Python. | Indirecto, crítico | No hay persistencia ni acceso a datos. | Implementar drivers nativos o usar FFI. | Requiere definir interfaz mínima. |
| tests/ | Suite de pruebas en pytest. | Directo, menor | Solo afecta testing, no runtime. | Migrar a framework de pruebas nativo o mantener como compatibilidad. | No bloquea operación. |

<!-- Agregar filas por cada punto detectado en la sesión C1 -->

## Resumen y Prioridades

- [ ] Listado completo de dependencias
- [ ] Priorización de puntos críticos
- [ ] Propuestas de desacoplamiento

---

> Este archivo se llena y actualiza durante la sesión C1. Cada fila debe ser concreta y verificable.
