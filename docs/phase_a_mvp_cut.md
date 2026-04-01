# Fase A - Corte del MVP del Ejecutable Puente

## Objetivo

Definir con precision que entra y que no entra en el primer ejecutable distribuible de AXON durante `Fase A - Ejecutable Puente`.

La regla rectora es:

`El primer binario debe ser usable, pequeno, distribuible y estable.`

Por eso el MVP del ejecutable no intenta cubrir todo el CLI actual. Cubre solo la superficie minima necesaria para presentar AXON como lenguaje con herramienta propia.

## Decision de Producto

El MVP del ejecutable puente incluye solo estos subcomandos:

- `axon version`
- `axon check`
- `axon compile`
- `axon trace`

Estos cuatro comandos son la superficie oficial del primer binario.

## Por que entran estos comandos

### `axon version`

Entra porque:

- identifica el binario instalado
- valida arranque minimo del ejecutable
- sirve como smoke test basico de distribucion

### `axon check`

Entra porque:

- demuestra que AXON tiene frontend de lenguaje usable
- valida fuente `.axon` sin depender de proveedores externos
- es una capacidad esencial para cualquier usuario del lenguaje

### `axon compile`

Entra porque:

- demuestra que AXON compila
- materializa la idea de toolchain propia
- no depende de red ni de llaves API para su comportamiento MVP actual

### `axon trace`

Entra porque:

- completa la historia minima de DX del lenguaje
- permite inspeccionar artefactos de ejecucion ya generados
- agrega utilidad real sin forzar dependencias operativas nuevas

## Comandos excluidos del MVP del ejecutable puente

Quedan fuera del primer binario:

- `axon run`
- `axon repl`
- `axon inspect`
- `axon serve`
- `axon deploy`

## Por que quedan fuera

### `axon run`

Queda fuera porque:

- acopla el ejecutable a backends de ejecucion y configuracion de proveedor
- introduce llaves API, errores de runtime y superficie operativa adicional
- aumenta demasiado el riesgo de soporte para el primer binario

Decision:

- `run` no es necesario para probar que AXON tiene ejecutable propio
- `run` se reevalua despues de fijar el empaquetado puente

### `axon repl`

Queda fuera porque:

- es interactivo y multiplica complejidad de empaquetado y prueba manual
- no es necesario para validar la historia minima de lenguaje + toolchain

Decision:

- el REPL es valioso, pero no es requisito del primer ejecutable usable

### `axon inspect`

Queda fuera porque:

- es utilidad de introspeccion, no capacidad esencial del MVP
- agrega superficie que no cambia la historia de adopcion inicial

Decision:

- puede volver mas adelante como mejora de DX, no como gate del primer binario

### `axon serve`

Queda fuera porque:

- depende de stack de servidor y de dependencias opcionales
- cambia el problema de "ejecutable de lenguaje" a "plataforma operativa completa"
- eleva mucho el riesgo tecnico del primer corte

Decision:

- `serve` pertenece a una etapa posterior del programa, no al MVP de Fase A

### `axon deploy`

Queda fuera porque:

- depende de conectividad, HTTP y existencia de AxonServer
- agrega una historia de integracion distribuida antes de cerrar la historia local del ejecutable

Decision:

- `deploy` se reevalua cuando `serve` y la distribucion operativa formen parte del alcance activo

## Alcance congelado del MVP

El primer binario de `Fase A` debe permitir:

- consultar version
- validar un archivo `.axon`
- compilar un archivo `.axon` a IR JSON
- renderizar un archivo `.trace.json`

No debe prometer todavia:

- ejecucion completa contra proveedores
- REPL interactivo distribuible
- introspeccion completa de stdlib en el binario
- servidor embebido
- despliegue remoto

## Regla de Expansion

Ningun comando fuera de este corte entra al primer binario salvo que ocurra una de estas dos cosas:

- se demuestre que es imprescindible para que el ejecutable sea usable
- se cierre una sesion explicita que actualice este documento

## Criterio de Aceptacion de A3

La sesion A3 queda cerrada cuando:

- el alcance del MVP esta fijado por escrito
- cada comando incluido tiene justificacion
- cada comando excluido tiene justificacion
- el corte es coherente con la meta de `Fase A`

## Resultado

El ejecutable puente de AXON no intenta representar toda la plataforma. Representa el minimo producto capaz de sostener una afirmacion limpia:

`AXON ya se instala y se usa como herramienta propia del lenguaje.`