# Fase A - Backlog de Ejecucion

## Estado de Fase

- Fase activa: `Fase A - Ejecutable Puente`
- Base interna: `v0.30.6`
- Objetivo de fase: entregar un `axon` distribuible y usable sin depender de `.venv` como historia de uso
- Estado actual: `closed_ready_for_merge_and_phase_b`

## Regla de Priorizacion

Cada sesion debe responder `si` a esta pregunta:

`Esto acerca a AXON al ejecutable usable?`

Si la respuesta es `no`, no entra en la sesion salvo que sea bug bloqueante.

## Sesiones Iniciales

### Sesion A1

- Version interna objetivo: `v0.30.6-internal.a.1.1`
- Estado: `validated`
- Objetivo: congelar el comportamiento observable de `axon version`, `axon check`, `axon compile` y `axon trace`
- Alcance:
  - inventariar codigos de salida
  - inventariar parametros CLI
  - inventariar stdout y stderr esperados
  - seleccionar casos canonicos de prueba
- Criterio de terminado:
  - existe especificacion observable minima de los cuatro comandos MVP
  - existe listado de fixtures o archivos canonicos para probarlos

### Sesion A2

- Version interna objetivo: `v0.30.6-internal.a.2.1`
- Estado: `validated`
- Objetivo: construir smoke tests para los comandos MVP del CLI actual
- Alcance:
  - tests de `version`
  - tests de `check`
  - tests de `compile`
  - tests de `trace`
- Criterio de terminado:
  - los comandos MVP tienen smoke tests ejecutables y reproducibles

### Sesion A3

- Version interna objetivo: `v0.30.6-internal.a.3.1`
- Estado: `validated`
- Objetivo: definir el corte exacto del MVP del ejecutable puente
- Alcance:
  - dejar explicito que comandos entran
  - dejar explicito que comandos salen del primer binario
  - justificar exclusiones por riesgo o dependencia
- Criterio de terminado:
  - el alcance del ejecutable puente esta fijado por escrito

### Sesion A4

- Version interna objetivo: `v0.30.6-internal.a.4.1`
- Estado: `validated`
- Objetivo: elegir la estrategia de empaquetado del ejecutable para Windows
- Alcance:
  - comparar opciones de empaquetado puente
  - elegir una sola
  - documentar criterio tecnico de eleccion
- Criterio de terminado:
  - existe una decision unica de empaquetado con razones y limites

### Sesion A5

- Version interna objetivo: `v0.30.6-internal.a.5.1`
- Estado: `validated`
- Objetivo: crear el primer build reproducible del ejecutable
- Alcance:
  - script o flujo de build local
  - generacion de artefacto
  - verificacion minima de arranque del binario
- Criterio de terminado:
  - el binario se genera localmente de forma repetible

### Sesion A6

- Version interna objetivo: `v0.30.6-internal.a.6.1`
- Estado: `validated`
- Objetivo: validar `axon version` y `axon check` sobre el binario
- Alcance:
  - prueba del binario empaquetado
  - comparacion contra comportamiento congelado
  - ajuste de fallos de arranque o rutas
- Criterio de terminado:
  - `version` y `check` funcionan desde el binario

### Sesion A7

- Version interna objetivo: `v0.30.6-internal.a.7.1`
- Estado: `validated`
- Objetivo: validar `axon compile` y `axon trace` sobre el binario
- Alcance:
  - prueba del binario empaquetado
  - comparacion contra comportamiento congelado
  - ajuste de salida y artefactos generados
- Criterio de terminado:
  - `compile` y `trace` funcionan desde el binario

### Sesion A8

- Version interna objetivo: `v0.30.6-internal.a.8.1`
- Estado: `validated`
- Objetivo: endurecer mensajes de error y codigos de salida del binario
- Alcance:
  - errores de archivo inexistente
  - errores de compilacion
  - errores de uso de CLI
- Criterio de terminado:
  - los errores principales son consistentes y verificables

### Sesion A9

- Version interna objetivo: `v0.30.6-internal.a.9.1`
- Estado: `validated`
- Objetivo: automatizar el build del ejecutable en CI
- Alcance:
  - flujo de build reproducible en CI
  - generacion de artefactos
  - verificacion minima automatizada
- Criterio de terminado:
  - CI genera el ejecutable y deja artefactos listos para validacion

### Sesion A10

- Version interna objetivo: `v0.30.6-internal.a.10.1`
- Estado: `validated`
- Objetivo: cerrar la documentacion minima de instalacion y uso del ejecutable puente
- Alcance:
  - instalacion
  - comandos MVP
  - limites conocidos
- Criterio de terminado:
  - existe documentacion minima suficiente para entregar el ejecutable puente

## Cierre de Fase A

Checklist de salida de fase:

- A1 validada
- A2 validada
- A3 validada
- A4 validada
- A5 validada
- A6 validada
- A7 validada
- A8 validada
- A9 validada
- A10 validada

Si todos los items anteriores estan en `validated`, `Fase A` queda lista para revision final de cierre.

La revision formal de salida queda registrada en `docs/phase_a_exit_review.md`.

La referencia interna recomendada para el merge administrativo de cierre es `v0.30.6-internal.a.10.2` con estado `validated`.

## Regla de Cierre de Sesion

Una sesion solo se marca como cerrada si alcanza `CHECK = 5/5` en `project/session_current.md`.