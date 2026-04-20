# Programa de Implementacion por Fases

## Objetivo Rector

AXON es un lenguaje con su propio ejecutable.

Este programa convierte ese objetivo en una secuencia de implementacion operable por sesiones. La prioridad no es investigar indefinidamente ni perseguir perfeccion. La prioridad es mover AXON, en cada sesion, hacia una salida limpia, instalable, usable y acumulativa.

## Regla de Gobierno

- Solo existe una fase activa a la vez.
- Cada sesion debe mover el producto hacia el ejecutable.
- Los bugs se atienden solo si bloquean la fase activa, rompen compilacion, rompen pruebas criticas o degradan una capacidad ya entregada.
- La investigacion profunda sobre features queda subordinada al programa del ejecutable hasta que AXON este en vitrina como producto usable.
- El SaaS propio puede exigir calidad y descubrir limites, pero no decide la arquitectura de AXON. AXON se construye para todos.

## Definicion de Exito

AXON alcanza este objetivo cuando un usuario puede obtener `axon`, ejecutar comandos del lenguaje y trabajar con programas `.axon` sin depender de instalar Python manualmente ni de crear una `.venv` como historia de uso.

## Politica de Version y Release

La version funcional actual es `v0.30.6`.

El salto a `v1.0.0` se reserva para el cierre completo del programa, no para avances intermedios.

Durante el programa, los merges pueden marcarse como versiones internas de avance, aunque no sean releases publicos.

Esto implica:

- no se publicara `v1.0.0` al cierre de `Fase A`
- no se publicara `v1.0.0` al cierre de `Fase B`
- `v1.0.0` solo se libera cuando `Fase C` este completada al `100%`
- el ultimo merge de cierre de `Fase C` sera el candidato de lanzamiento a produccion
- ese merge debe pasar test fuertes, validacion operativa y verificacion sobre el primer early adopter exigente
- los merges intermedios pueden llevar version interna para trazabilidad, auditoria y documentacion de avances
- una version interna no implica estabilidad publica ni compromiso de compatibilidad externa

La logica de esta politica es simple:

- evitar migraciones frecuentes para terceros desconocidos
- evitar ruido de versionado antes del verdadero punto de estabilidad de producto
- convertir `v1.0.0` en una frontera clara entre investigacion activa y producto utilizable en produccion

## Politica de Version Interna

Las versiones internas existen para ordenar el trabajo, registrar hitos y documentar merges relevantes.

Se usan para:

- trazabilidad tecnica
- documentacion de avances
- identificar el estado exacto asociado a una sesion o merge
- facilitar pruebas fuertes acumulativas antes del release publico

No se usan para:

- comunicar estabilidad publica
- prometer compatibilidad de largo plazo
- anunciar releases de producto

Regla practica:

- cada merge relevante puede marcarse con una version interna
- esas versiones viven como historial de construccion del producto
- solo `v1.0.0` representa el release publico de produccion al cierre de `Fase C`

## Convencion de Versionado Interno

La convencion recomendada para todo el programa es:

`v0.30.6-internal.<fase>.<sesion>.<merge>`

Donde:

- `<fase>` = `a`, `b` o `c`
- `<sesion>` = numero correlativo dentro de la fase activa
- `<merge>` = numero correlativo de merge asociado a esa sesion, empezando en `1`

Ejemplos:

- `v0.30.6-internal.a.1.1`
- `v0.30.6-internal.a.3.1`
- `v0.30.6-internal.b.2.2`
- `v0.30.6-internal.c.7.1`

Lectura:

- `v0.30.6-internal.a.3.1` significa: base funcional `v0.30.6`, trabajo interno, `Fase A`, sesion `3`, merge `1` de esa sesion.

## Regla de Incremento

- Si comienza una nueva fase, cambia el componente `<fase>`.
- Si comienza una nueva sesion dentro de la misma fase, incrementa `<sesion>`.
- Si una sesion requiere mas de un merge relevante, incrementa `<merge>`.
- Si un merge se descarta o se revierte, no se recicla su numero.

## Regla de Estabilidad Interna

No toda version interna representa el mismo nivel de confianza. Para eso se agrega un estado de estabilidad en el registro de avances, no en el nombre semantico de la version.

Estados recomendados:

- `draft` = trabajo aun no cerrado por CHECK
- `validated` = merge con `CHECK = 5/5`
- `hold` = merge util, pero bloqueado por un problema detectado despues
- `superseded` = merge reemplazado por una version interna posterior

Ejemplo de registro:

- `v0.30.6-internal.a.4.1` - `validated`
- `v0.30.6-internal.a.4.2` - `superseded`

## Regla de Uso

- El nombre de version interna identifica el estado exacto del programa en una fase y sesion concretas.
- El estado de estabilidad indica si ese merge cuenta como avance consolidado.
- Un merge solo cuenta formalmente como avance de la fase si su estado es `validated`.

## Regla de Correspondencia con CHECK

La relacion entre version interna y cierre de sesion es esta:

- si `CHECK = 5/5`, el merge puede marcarse como `validated`
- si `CHECK < 5/5`, el merge puede existir, pero no cuenta como entrega cerrada

Esto evita que el historial de versiones internas confunda actividad con progreso real.

## Regla de Early Adopter

Se asume un early adopter empresarial exigente de produccion como referencia mental.

Eso significa:

- valida dureza real del producto
- aporta presion de uso, no control arquitectonico
- no redefine el core de AXON por necesidad local
- sirve como entorno de prueba serio para el release de `v1.0.0`

La regla sigue siendo la misma: AXON se construye para todos. El early adopter endurece la salida, pero no captura el lenguaje.

## Modo de Trabajo

Cada sesion debe cerrar una unidad pequena, verificable y mergeable.

Una sesion valida tiene cinco partes:

1. Objetivo de sesion
2. Alcance cerrado
3. Verificacion
4. Evidencia
5. Handoff a la siguiente sesion

Si falta una de esas partes, hubo trabajo, pero no hubo avance consolidado.

## Formula CHECK

La sesion se considera cerrada solo si cumple la formula `CHECK = 5/5`.

- `C` = Compila o deja el arbol en estado verde para el alcance afectado.
- `H` = Hay handoff explicito para la siguiente sesion.
- `E` = Existe evidencia verificable: tests, comando, diff, artefacto o documento.
- `C` = El cambio cierra un alcance concreto, no deja trabajo partido en el mismo bloque.
- `K` = Keep the phase: el trabajo se mantuvo dentro de la fase activa.

Interpretacion:

- `5/5`: sesion valida y acumulativa.
- `4/5`: sesion util pero no cerrada; no cuenta como avance terminado.
- `3/5` o menos: exploracion o trabajo parcial; no debe marcarse como entregable.

## Regla de Bugs

Un bug puede entrar en la sesion solo si cumple una de estas condiciones:

- bloquea la fase activa
- rompe compilacion
- rompe un comando ya entregado
- rompe un test critico de regresion
- impide generar evidencia de cierre

Si no cumple una de esas condiciones, va al backlog, no a la sesion actual.

## Fase A - Ejecutable Puente

### Proposito

Conseguir un `axon` distribuible y utilizable como producto, aunque internamente siga apoyandose en Python.

### Resultado Esperado

Un usuario en Windows puede descargar AXON, ejecutar `axon version`, `axon check`, `axon compile` y `axon trace` sin instalar Python manualmente.

### No Objetivos

- reescribir el runtime completo
- migrar todo a Rust
- redisenar el lenguaje
- abrir investigacion nueva de features no relacionadas con el ejecutable

### Entregables

- decision formal del empaquetado puente
- artefacto ejecutable reproducible
- comandos MVP definidos y estables
- flujo de build local y CI para generar el ejecutable
- smoke tests para los comandos del ejecutable
- documentacion minima de uso e instalacion

### Criterio de Salida

- existe un binario `axon` reproducible
- `axon version` funciona
- `axon check <file.axon>` funciona
- `axon compile <file.axon>` funciona
- `axon trace <file.trace.json>` funciona
- el flujo de distribucion ya no exige contar la historia de `.venv`

### Backlog Inicial

1. Congelar comportamiento observable de `version`, `check`, `compile` y `trace`.
2. Definir el MVP del ejecutable y dejar fuera comandos no criticos.
3. Elegir estrategia puente de empaquetado para Windows.
4. Crear build reproducible del binario.
5. Crear smoke tests sobre el binario.
6. Ajustar mensajes de error y codigos de salida.
7. Escribir guia corta de instalacion y uso.
8. Integrar build de release en CI.

## Fase B - Nucleo Nativo

### Proposito

Separar el lenguaje de su implementacion Python y mover el core a una implementacion nativa.

### Resultado Esperado

El frontend del lenguaje y el APX core funcionan sobre una base nativa y sostienen un `axon` CLI propio.

### No Objetivos

- paridad total del runtime distribuido en el primer salto
- migrar todas las integraciones externas a la vez
- cambiar la semantica del lenguaje mientras se porta el core

### Entregables

- especificacion estable de diagnosticos
- especificacion estable de IR o contrato intermedio
- lexer nativo
- parser nativo
- type checker nativo
- CLI nativa para comandos del frontend
- suite de compatibilidad contra el comportamiento previo

### Criterio de Salida

- `axon check` corre sobre core nativo
- `axon compile` corre sobre core nativo
- los diagnosticos principales son compatibles con el frontend anterior
- el comportamiento observable de los comandos MVP esta cubierto por pruebas de regresion

### Backlog Inicial

1. Definir que modulo es core y que modulo es infraestructura.
2. Congelar contrato de IR y diagnosticos.
3. Crear golden tests del frontend actual.
4. Implementar lexer nativo.
5. Implementar parser nativo.
6. Implementar type checker nativo.
7. Montar CLI nativa.
8. Agregar compatibilidad opcional con Python solo donde sea necesario.

## Fase C - Independencia Operacional

### Proposito

Reducir Python a compatibilidad opcional y consolidar AXON como lenguaje con toolchain y operacion propias.

### Resultado Esperado

AXON ya no depende conceptualmente de Python para contar su historia de producto ni para su superficie principal de uso.

### No Objetivos

- perseguir perfeccion arquitectonica
- reescribir subsistemas por prestigio tecnico
- abrir ramas de investigacion paralelas que no mejoran la operacion del producto

### Entregables

- estrategia operativa de runtime y server desacoplada de Python
- APX core y observabilidad alineados con el toolchain nativo
- distribucion oficial endurecida
- documentacion de producto alineada con el ejecutable
- decision explicita sobre que queda como compatibilidad y que queda como core

### Criterio de Salida

- el usuario puede entender, instalar y usar AXON como lenguaje y herramienta propia
- Python no es requisito de entrada para la narrativa principal del producto
- las capacidades principales del toolchain y operacion tienen historia de distribucion limpia

### Backlog Inicial

1. Aislar interfaces de runtime que aun acoplan Python.
2. Definir estrategia de runtime transicional vs runtime nativo.
3. Migrar APX core y observabilidad que formen parte de la narrativa operativa.
4. Definir estrategia de server y backends.
5. Limpiar documentacion y release story.
6. Cerrar la capa de compatibilidad Python como opcional y no central.

## Plantilla de Sesion

Cada sesion debe registrarse con esta estructura:

### 1. Fase activa

`Fase A`, `Fase B` o `Fase C`.

### 2. Objetivo de sesion

Una sola frase orientada a cierre.

Ejemplo: `Congelar el comportamiento observable de axon compile.`

### 3. Alcance cerrado

Lista breve de lo que entra y lo que no entra.

### 4. Verificacion

- comandos ejecutados
- tests ejecutados
- artefactos generados

### 5. Evidencia

- archivos modificados
- decision tomada
- riesgo detectado

### 6. Resultado CHECK

Registrar `C/H/E/C/K` como `1` o `0`.

### 7. Handoff

La siguiente accion exacta para la siguiente sesion.

## Politica de Backlog

- El backlog maestro se ordena solo por impacto sobre la fase activa.
- Cada sesion toma un item principal y, como maximo, un item secundario de soporte.
- Un item no puede entrar en sesion si no tiene criterio de terminado.
- Si aparece una idea valiosa fuera de fase, se registra pero no se ejecuta.

## Cadencia Recomendada

- Inicio de sesion: elegir un item con cierre claro.
- Mitad de sesion: verificar si sigue dentro de fase.
- Cierre de sesion: ejecutar CHECK.
- Fin de sesion: dejar handoff escrito.

## Archivos Operativos

Para no inflar la ventana de contexto y no mezclar estrategia con ejecucion diaria, el trabajo se divide en tres archivos operativos.

### 1. Documento rector

Archivo: `docs/axon_executable_implementation_program.md`

Uso:

- define la estrategia general
- fija fases, reglas y politicas
- cambia poco y solo ante decisiones de programa

### 2. Backlog de fase activa

Archivo: `docs/phase_<fase>_execution_backlog.md`

Uso:

- enumera sesiones planeadas de la fase activa
- define objetivo, alcance y criterio de terminado por sesion
- cambia cuando se agrega, reordena o cierra trabajo de fase

Ejemplos:

- `docs/phase_a_execution_backlog.md`
- `docs/phase_b_execution_backlog.md`
- `docs/phase_c_execution_backlog.md`

### 3. Sesion activa

Archivo: `project/session_current.md`

Uso:

- contiene solo la sesion en curso
- registra CHECK, evidencia y handoff inmediato
- se mantiene corto para que siempre entre bien en contexto

Regla:

- la estrategia vive aqui
- la cola de trabajo vive en el backlog de fase
- el trabajo vivo del dia vive en la sesion activa

## Indicadores de Avance

Los indicadores que importan en esta etapa son:

- cantidad de sesiones con `CHECK = 5/5`
- cantidad de comandos MVP funcionando en binario
- cantidad de entregables cerrados por fase
- cantidad de bugs bloqueantes resueltos sin desviar la fase

No son indicadores validos en esta etapa:

- cantidad de ideas abiertas
- cantidad de investigaciones iniciadas
- cantidad de features experimentales sin integracion

## Gate de Release v1.0.0

`v1.0.0` solo puede liberarse si todas estas condiciones son verdaderas:

- `Fase A` cerrada
- `Fase B` cerrada
- `Fase C` cerrada
- test fuertes en verde
- ejecutable distribuible validado
- documentacion minima de instalacion y uso validada
- backlog de bugs bloqueantes en cero
- validacion final con el early adopter completada

Si una sola de estas condiciones falla, no hay release `v1.0.0`.

## Primera Decision Operativa

La primera fase activa debe ser `Fase A - Ejecutable Puente`.

La razon es simple: antes de discutir pureza tecnica, AXON necesita una salida limpia de producto. El ejecutable cambia la superficie de adopcion, disciplina el CLI, obliga a fijar contratos y prepara el terreno para el nucleo nativo.

## Definicion de Prioridad Absoluta

Mientras `Fase A` este activa, la pregunta de priorizacion es:

`Esto acerca a AXON al ejecutable usable?`

Si la respuesta es `no`, no entra en la sesion salvo que sea un bug bloqueante.

## Cierre

Este programa no existe para frenar AXON. Existe para que AXON avance de forma continua, limpia y acumulativa. La urgencia sirve como energia. El programa por fases sirve como direccion.