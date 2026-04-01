# Fase B - Backlog de Ejecucion

## Estado de Fase

- Fase activa: `Fase B - Nucleo Nativo`
- Base interna: `v0.30.6`
- Objetivo de fase: separar el core del lenguaje de la infraestructura Python y preparar una base nativa del frontend
- Estado actual: `active`

## Regla de Priorizacion

Cada sesion debe responder `si` a esta pregunta:

`Esto mueve el core del lenguaje fuera de la dependencia estructural de Python?`

Si la respuesta es `no`, no entra en la sesion salvo que sea bug bloqueante de la fase activa.

## Sesiones Iniciales

### Sesion B1

- Version interna objetivo: `v0.30.6-internal.b.1.1`
- Estado: `ready`
- Objetivo: delimitar por escrito que partes del repositorio son core del lenguaje y que partes son infraestructura Python o integracion
- Alcance:
  - inventariar modulos de frontend del lenguaje
  - inventariar modulos de runtime, server, backends e integraciones
  - proponer un corte inicial de `core` vs `infra`
  - identificar acoples que bloquean el salto a un nucleo nativo
- Criterio de terminado:
  - existe un mapa inicial de modulos y fronteras
  - existe una lista corta de acoples criticos a romper en Fase B

### Sesion B2

- Version interna objetivo: `v0.30.6-internal.b.2.1`
- Estado: `queued`
- Objetivo: congelar el contrato inicial de diagnosticos e IR para el frontend
- Alcance:
  - inventario de diagnosticos observables de `check` y `compile`
  - inventario de campos esenciales del IR
  - propuesta de contrato minimo estable para compatibilidad
- Criterio de terminado:
  - existe especificacion inicial de diagnosticos e IR para Fase B

### Sesion B3

- Version interna objetivo: `v0.30.6-internal.b.3.1`
- Estado: `queued`
- Objetivo: crear golden tests de compatibilidad del frontend actual
- Alcance:
  - fixtures representativos
  - salidas canonicas de `check`
  - salidas canonicas de `compile`
  - comparacion automatizable para futuros reemplazos del core
- Criterio de terminado:
  - existe una base de golden tests para compatibilidad del frontend

## Regla de Cierre de Sesion

Una sesion solo se marca como cerrada si alcanza `CHECK = 5/5` en `project/session_current.md`.