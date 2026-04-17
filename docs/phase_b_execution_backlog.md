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
- Estado: `validated`
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
- Estado: `validated`
- Objetivo: congelar el contrato inicial de diagnosticos e IR para el frontend
- Alcance:
  - inventario de diagnosticos observables de `check` y `compile`
  - inventario de campos esenciales del IR
  - propuesta de contrato minimo estable para compatibilidad
- Criterio de terminado:
  - existe especificacion inicial de diagnosticos e IR para Fase B

### Sesion B3

- Version interna objetivo: `v0.30.6-internal.b.3.1`
- Estado: `validated`
- Objetivo: crear golden tests de compatibilidad del frontend actual
- Alcance:
  - fixtures representativos
  - salidas canonicas de `check`
  - salidas canonicas de `compile`
  - comparacion automatizable para futuros reemplazos del core
- Criterio de terminado:
  - existe una base de golden tests para compatibilidad del frontend

### Sesion B4

- Version interna objetivo: `v0.30.6-internal.b.4.1`
- Estado: `validated`
- Objetivo: introducir una fachada unica de frontend consumida por la CLI
- Alcance:
  - definir interfaz unica para `check` y `compile`
  - mover diagnosticos e IR a una frontera interna estable
  - desacoplar `axon/cli/check_cmd.py` y `axon/cli/compile_cmd.py` de `Lexer`, `Parser`, `TypeChecker` e `IRGenerator`
- Criterio de terminado:
  - la CLI consume una fachada de frontend reemplazable sin cambiar su contrato observable

### Sesion B5

- Version interna objetivo: `v0.30.6-internal.b.5.1`
- Estado: `validated`
- Objetivo: definir el contrato de reemplazo del backend de la fachada del frontend
- Alcance:
  - formalizar interfaz de implementacion para frontend Python y frontend nativo
  - separar la abstraccion de la implementacion por defecto
  - dejar el punto de inyeccion preparado para el core nativo
- Criterio de terminado:
  - existe una interfaz de implementacion del frontend y la fachada actual puede delegar en ella

### Sesion B6

- Version interna objetivo: `v0.30.6-internal.b.6.1`
- Estado: `validated`
- Objetivo: introducir seleccion explicita de implementacion para la fachada del frontend
- Alcance:
  - definir mecanismo de seleccion por configuracion o bootstrap
  - preparar registro de implementaciones disponibles
  - dejar un placeholder de frontend nativo sin acoplar la CLI a su presencia
- Criterio de terminado:
  - la eleccion de implementacion del frontend no requiere editar adaptadores CLI

### Sesion B7

- Version interna objetivo: `v0.30.6-internal.b.7.1`
- Estado: `validated`
- Objetivo: aislar el bootstrap de frontend en un modulo de seleccion operativa
- Alcance:
  - separar registro/bootstrap de la implementacion concreta del frontend
  - definir punto de arranque claro para runtime, CLI y futuras builds nativas
  - evitar que la fachada mezcle contrato con politica de seleccion
- Criterio de terminado:
  - existe un bootstrap operativo del frontend desacoplado de la implementacion concreta

### Sesion B8

- Version interna objetivo: `v0.30.6-internal.b.8.1`
- Estado: `validated`
- Objetivo: introducir integracion temprana del bootstrap en un punto de arranque controlado
- Alcance:
  - decidir donde se activa la seleccion operativa del frontend
  - integrar bootstrap sin alterar el comportamiento por defecto del CLI
  - mantener la posibilidad de pruebas deterministas con inyeccion directa
- Criterio de terminado:
  - existe un punto de arranque explicito que puede activar la seleccion operativa sin romper B3-B7

### Sesion B9

- Version interna objetivo: `v0.30.6-internal.b.9.1`
- Estado: `validated`
- Objetivo: extender la cobertura operativa del bootstrap al entrypoint ejecutable de producto
- Alcance:
  - verificar comportamiento del arranque controlado en superficies no-CLI-main
  - unificar criterio de error operativo para seleccion invalida
  - preparar camino para futuras builds con frontend nativo seleccionado
- Criterio de terminado:
  - los entrypoints de producto relevantes comparten una politica de bootstrap consistente

### Sesion B10

- Version interna objetivo: `v0.30.6-internal.b.10.1`
- Estado: `validated`
- Objetivo: preparar un selector nativo real de desarrollo sin cambiar el default de producto
- Alcance:
  - definir un backend nativo de desarrollo o stub ampliado
  - establecer contrato de capacidades minimas del selector nativo
  - mantener el bootstrap productivo estable mientras se abre el camino de implementacion real
- Criterio de terminado:
  - existe una ruta de seleccion nativa de desarrollo mejor definida que el placeholder actual

### Sesion B11

- Version interna objetivo: `v0.30.6-internal.b.11.1`
- Estado: `validated`
- Objetivo: documentar y acotar capacidades del camino `native-dev`
- Alcance:
  - definir que garantiza y que no garantiza `native-dev`
  - separar expectativas de desarrollo frente a expectativas de producto
  - dejar lista la transicion desde delegacion Python hacia implementacion nativa real
- Criterio de terminado:
  - existe una especificacion operativa minima del selector `native-dev`

### Sesion B12

- Version interna objetivo: `v0.30.6-internal.b.12.1`
- Estado: `validated`
- Objetivo: sustituir una primera capacidad real detras de `native-dev`
- Alcance:
  - elegir un corte tecnico pequeno y verificable del frontend
  - implementar sustitucion real solo bajo `native-dev`
  - validar compatibilidad contra pruebas de fachada, CLI y contrato congelado
- Criterio de terminado:
  - existe al menos una capacidad del frontend que ya no delega completamente en Python bajo `native-dev`

### Sesion B13

- Version interna objetivo: `v0.30.6-internal.b.13.1`
- Estado: `validated`
- Objetivo: ampliar la sustitucion de `native-dev` desde el arranque top-level hacia una primera porcion de analisis lexical real
- Alcance:
  - elegir una porcion pequena del lexer compatible con fixtures canonicos
  - ejecutar esa porcion solo bajo `native-dev`
  - mantener compatibilidad observable con golden tests y pruebas de CLI
- Criterio de terminado:
  - `native-dev` ya no delega completamente al lexer Python para un subconjunto explicito del lenguaje

### Sesion B14

- Version interna objetivo: `v0.30.6-internal.b.14.1`
- Estado: `validated`
- Objetivo: ampliar `native-dev` desde el primer token hacia una ventana corta de tokenizacion secuencial util para firmas top-level
- Alcance:
  - escoger una ventana secuencial corta y comun a declaraciones canonicas antes de entrar en parseo especifico
  - fijar la ventana en: keyword top-level + identificador principal + primer token estructural de apertura o separacion
  - cubrir primero formas canonicas de bajo riesgo centradas en firmas y bloques: `persona/context/anchor/tool/flow/run`
  - excluir `type` de B14 para evitar mezclar esta iteracion con sus variantes de restriccion y rango
  - asegurar que `type` siga pasando por delegacion Python completa durante esta sesion
  - congelar validaciones exactas para `type` en ruta Python: rango escalar `type RiskScore(0.0..1.0)` y tipo estructurado con campo opcional `mitigation: Opinion?`
  - verificar en `native-dev` que `check` siga aceptando el rango y que `compile` siga preservando `range_min/range_max` y `optional`
  - dejar fuera por ahora firmas con longitud variable mas inestable como `import` y variantes top-level menos frecuentes
  - mantener delegacion Python para parseo y resto del archivo
  - validar compatibilidad observable en fachada, CLI y golden tests
- Criterio de terminado:
  - `native-dev` puede tokenizar nativamente una secuencia inicial util de tres hitos lexicales, no solo un token aislado
  - las declaraciones `type` continúan pasando sin regresion por la ruta Python estable

### Sesion B15

- Version interna objetivo: `v0.30.6-internal.b.15.1`
- Estado: `validated`
- Objetivo: ampliar `native-dev` desde la ventana de tres tokens hacia una cabecera inicial reusable para mas declaraciones top-level
- Alcance:
  - elegir crecimiento por header compartido mas amplio en lugar de una cuarta pieza estructural fragil
  - extender la validacion temprana `KEYWORD IDENTIFIER {` a familias adicionales con la misma cabecera
  - incluir en este corte: `memory/intent/agent/shield/pix/corpus/psyche/ots/mandate/compute/lambda/daemon/axonstore/axonendpoint`
  - mantener fuera `type` mientras no exista una estrategia explicita para rangos y restricciones
  - preservar compatibilidad observable en fachada, CLI y golden tests
- Criterio de terminado:
  - `native-dev` cubre una porcion mayor de cabecera top-level compartida sin introducir regresion contractual

### Sesion B16

- Version interna objetivo: `v0.30.6-internal.b.16.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente crecimiento entra por una cuarta pieza estructural acotada o por una primera validacion semantica ligera de cabecera
- Alcance:
  - comparar costo/riesgo de extender cabeceras `flow/run` hacia el cuarto token frente a modelar un primer campo de bloque
  - escoger el corte mas seguro y acotado: cuarto token solo para `flow`
  - validar en `flow` que despues de `(` el primer token sea `RPAREN` o `IDENTIFIER`
  - mantener `run` fuera de este crecimiento porque su lista de argumentos es mas permisiva y menos estable
  - mantener `type` fuera mientras no exista una estrategia explicita
  - conservar compatibilidad observable en fachada, CLI y golden tests
- Criterio de terminado:
  - `native-dev` incorpora una cuarta pieza estructural acotada para `flow` sin romper el contrato

### Sesion B17

- Version interna objetivo: `v0.30.6-internal.b.17.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente crecimiento conviene en `run` o en una primera validacion ligera del cuerpo de bloques
- Alcance:
  - evaluar la permisividad real de `run(...)` frente al riesgo de desalinear su contrato observable
  - escoger el camino mas seguro: validar el primer campo de bloques compartidos sin romper mensajes canonicos
  - ampliar `native-dev` para reproducir el error canonico `expected COLON` cuando el primer campo de bloque no introduce `:`
  - mantener `run` fuera de este crecimiento por su mayor permisividad sintactica
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - `native-dev` incorpora una primera validacion ligera de cuerpo de bloques sin romper el contrato

### Sesion B18

- Version interna objetivo: `v0.30.6-internal.b.18.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente crecimiento conviene en `run` o en una profundizacion acotada del cuerpo compartido de bloques
- Alcance:
  - reevaluar `run(...)` con casos reales del parser y fixtures canonicos
  - escoger el camino mas seguro: extender una pieza adicional del primer campo de bloques
  - profundizar solo valores del primer campo que usan la helper canonica `_consume_any_identifier_or_keyword()`
  - reproducir el error canonico `Expected identifier or keyword value (found ...)` cuando ese valor inicial es invalido
  - mantener `run` fuera por su mayor permisividad y mayor riesgo de desalineacion
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - `native-dev` profundiza un paso adicional el cuerpo compartido de bloques sin romper el contrato

### Sesion B19

- Version interna objetivo: `v0.30.6-internal.b.19.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente crecimiento conviene en `run` o en una profundizacion adicional del primer campo compartido de bloques
- Alcance:
  - reevaluar `run(...)` con casos reales y comportamiento observable del parser
  - escoger el camino mas seguro: extender el primer campo compartido de bloques sobre valores booleanos
  - profundizar solo campos del primer valor que usan la regla canonica `_parse_bool()`
  - reproducir el error canonico `Unexpected token (expected BOOL, found ...)` cuando ese valor inicial es invalido
  - mantener `run` fuera por su mayor permisividad y mayor riesgo de desalineacion
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - `native-dev` profundiza un paso adicional el cuerpo compartido de bloques sobre valores booleanos sin romper el contrato

### Sesion B20

- Version interna objetivo: `v0.30.6-internal.b.20.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente crecimiento conviene en `run` o en valores no booleanos/no identifier-like del primer campo compartido de bloques
- Alcance:
  - reevaluar `run(...)` con comportamiento observable y fixtures canonicos
  - caracterizar y congelar las variantes hoy aceptadas por el parser en la cabecera `run(...)`
  - verificar explicitamente bajo `native-dev` que `run` sigue delegado al backend Python para variantes vacia, string, numerica, dotted y forma estilo `key : value`
  - usar esa caracterizacion para aclarar el camino futuro de `run` sin abrirlo aun en la ruta nativa
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - el comportamiento observable de `run(...)` queda fijado y el siguiente corte puede definirse con evidencia

### Sesion B21

- Version interna objetivo: `v0.30.6-internal.b.21.1`
- Estado: `validated`
- Objetivo: abrir el primer corte nativo real para `run(...)` con alcance acotado y sin romper su comportamiento observable congelado
- Alcance:
  - usar la caracterizacion de B20 como base para escoger el subconjunto inicial mas seguro de `run`
  - implementar solo la forma aislada minima `run Name()` sin argumentos adicionales ni otras declaraciones vecinas
  - reproducir de forma nativa el diagnostico canonico `Undefined flow 'Name' in run statement` cuando el flow no existe
  - validar que `native-dev` resuelve este caso sin delegar al backend Python
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un corte nativo inicial de `run` implementado, probado y alineado con el contrato observable

### Sesion B22

- Version interna objetivo: `v0.30.6-internal.b.22.1`
- Estado: `validated`
- Objetivo: ampliar el corte nativo de `run(...)` desde la forma minima aislada hacia variantes seguras de un argumento sin perder alineacion con el frontend Python
- Alcance:
  - comparar convivencia toplevel frente a una primera expansion de argumentos sobre la base observable ya fijada en B20 y B21
  - escoger la expansion de argumentos como siguiente crecimiento de menor superficie y menor riesgo
  - implementar de forma nativa las variantes aisladas `run Name("...")`, `run Name(5)`, `run Name(report.pdf)` y `run Name(depth: 3)`
  - reproducir en todas ellas el mismo diagnostico canonico `Undefined flow 'Name' in run statement`
  - validar que `native-dev` resuelve estas formas sin delegar al backend Python
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - el subconjunto aislado de `run` cubre las variantes objetivo y permanece alineado con el contrato observable

### Sesion B23

- Version interna objetivo: `v0.30.6-internal.b.23.1`
- Estado: `validated`
- Objetivo: definir el primer crecimiento seguro de `run(...)` fuera del corte de argumentos aislados, comparando convivencia toplevel frente a modificadores locales de bajo riesgo
- Alcance:
  - comparar convivencia toplevel frente a modificadores sobre el corte aislado ya validado
  - escoger modificadores locales de bajo riesgo en lugar de convivencia toplevel para no absorber semantica completa de programa
  - implementar de forma nativa las formas aisladas `run Name() output_to: "..."` y `run Name() effort: high`
  - reproducir en ambas el mismo diagnostico canonico `Undefined flow 'Name' in run statement`
  - dejar `on_failure`, `as`, `within` y `constrained_by` en la ruta Python mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte de modificadores de `run` implementado y alineado con el contrato observable

### Sesion B24

- Version interna objetivo: `v0.30.6-internal.b.24.1`
- Estado: `validated`
- Objetivo: abrir una primera convivencia toplevel acotada para `run(...)` sin absorber semantica completa de programa
- Alcance:
  - comparar `on_failure` frente a una primera convivencia toplevel sobre la base observable ya fijada en B20-B23
  - escoger la convivencia toplevel minima como siguiente crecimiento mas preciso y con menor superficie semantica que `on_failure`
  - implementar un unico bloque toplevel previo de familia compartida seguido por un `run(...)` del subconjunto ya soportado
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para ese caso de convivencia
  - mantener fuera `flow` vecino, multiples declaraciones previas y `on_failure` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera convivencia toplevel nativa de `run` implementada, probada y alineada con el contrato observable

### Sesion B25

- Version interna objetivo: `v0.30.6-internal.b.25.1`
- Estado: `validated`
- Objetivo: ampliar la convivencia toplevel segura de `run(...)` hacia multiples bloques compartidos previos sin absorber semantica de programa completo
- Alcance:
  - comparar `on_failure` frente a ampliar la convivencia toplevel sobre la base observable ya fijada en B20-B24
  - escoger multiples bloques compartidos previos como crecimiento de menor superficie semantica que `on_failure`
  - implementar de forma nativa una secuencia de bloques toplevel compartidos previos seguida por un `run(...)` del subconjunto ya soportado
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos ampliados de convivencia
  - mantener fuera la vecindad con `flow` y `on_failure` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una convivencia toplevel ampliada de `run` implementada, probada y alineada con el contrato observable

### Sesion B26

- Version interna objetivo: `v0.30.6-internal.b.26.1`
- Estado: `validated`
- Objetivo: abrir una primera forma local de `on_failure` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar una primera forma local de `on_failure` frente a abrir la vecindad con `flow` sobre la base observable ya fijada en B20-B25
  - escoger `on_failure: <estrategia-simple>` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa las formas `run Name() on_failure: log`, `run Name() on_failure: escalate` y `run Name() on_failure: retry`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `on_failure: raise X`, `on_failure: retry(...)` con parametros y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo de `on_failure` implementado, probado y alineado con el contrato observable

### Sesion B27

- Version interna objetivo: `v0.30.6-internal.b.27.1`
- Estado: `validated`
- Objetivo: abrir una primera forma parametrizada de `on_failure: retry(...)` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar una primera forma parametrizada de `on_failure: retry(...)` frente a abrir la vecindad con `flow` sobre la base observable ya fijada en B20-B26
  - escoger `on_failure: retry(<clave>: <valor>)` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa la forma `run Name() on_failure: retry(backoff: exponential)`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `on_failure: raise X`, `retry(...)` con mas de un par y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo parametrizado de `retry(...)` implementado, probado y alineado con el contrato observable

### Sesion B28

- Version interna objetivo: `v0.30.6-internal.b.28.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa de `on_failure: raise X` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `on_failure: raise X` frente a `retry(...)` con mas de un par y frente a abrir la vecindad con `flow` sobre la base observable ya fijada en B20-B27
  - escoger `on_failure: raise X` como crecimiento de menor superficie gramatical y menor riesgo semantico que `retry(...)` multiparametro o `flow`
  - implementar de forma nativa la forma `run Name() on_failure: raise ErrorName`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `retry(...)` con mas de un par y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo de `on_failure: raise X` implementado, probado y alineado con el contrato observable

### Sesion B29

- Version interna objetivo: `v0.30.6-internal.b.29.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa de `retry(...)` con dos pares `clave: valor` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `retry(...)` con dos pares frente a la vecindad con `flow` sobre la base observable ya fijada en B20-B28
  - escoger `retry(<clave1>: <valor1>, <clave2>: <valor2>)` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa la forma `run Name() on_failure: retry(backoff: exponential, attempts: 3)`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `retry(...)` con tres o mas pares y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo de `retry(...)` con dos pares implementado, probado y alineado con el contrato observable

### Sesion B30

- Version interna objetivo: `v0.30.6-internal.b.30.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa de `retry(...)` con tres pares `clave: valor` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `retry(...)` con tres pares frente a la vecindad con `flow` sobre la base observable ya fijada en B20-B29
  - escoger `retry(<clave1>: <valor1>, <clave2>: <valor2>, <clave3>: <valor3>)` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa la forma `run Name() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `retry(...)` con cuatro o mas pares y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo de `retry(...)` con tres pares implementado, probado y alineado con el contrato observable

### Sesion B31

- Version interna objetivo: `v0.30.6-internal.b.31.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa de `retry(...)` con cuatro pares `clave: valor` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `retry(...)` con cuatro pares frente a la vecindad con `flow` sobre la base observable ya fijada en B20-B30
  - escoger `retry(<clave1>: <valor1>, <clave2>: <valor2>, <clave3>: <valor3>, <clave4>: <valor4>)` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa la forma `run Name() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)`
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `retry(...)` con cinco o mas pares y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo de `retry(...)` con cuatro pares implementado, probado y alineado con el contrato observable

### Sesion B32

- Version interna objetivo: `v0.30.6-internal.b.32.1`
- Estado: `validated`
- Objetivo: generalizar de forma nativa `retry(...)` a una lista variable de pares `clave: valor` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar si el siguiente corte razonable tras cuatro pares es seguir creciendo `retry(...)` por aridad o cerrar la familia completa antes de tocar `flow`
  - escoger la generalizacion de `retry(...)` a una lista variable de pares `clave: valor` como crecimiento de menor superficie semantica que `flow`
  - implementar de forma nativa formas como `run Name() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)` y variantes mas largas
  - extender ese mismo soporte a casos con bloques toplevel compartidos previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - `retry(...)` deja de requerir ampliaciones por aridad y queda soportado como familia regular dentro del subconjunto nativo de `run(...)`

### Sesion B33

- Version interna objetivo: `v0.30.6-internal.b.33.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa contextual de `as Persona` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `as`, `within` y `constrained_by` frente a la vecindad con `flow` sobre la base observable ya fijada en B20-B32
  - escoger `as Persona` como primer modificador local restante de menor superficie gramatical, limitado a casos donde la persona ya existe en los bloques prefijados aceptados por `native-dev`
  - implementar de forma nativa formas como `persona Expert { ... }` seguido de `run Name() as Expert`
  - extender ese mismo soporte a casos con bloques toplevel compartidos adicionales previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `as` aislado o con persona no resuelta, asi como `within`, `constrained_by` y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo contextual de `as Persona` implementado, probado y alineado con el contrato observable

### Sesion B34

- Version interna objetivo: `v0.30.6-internal.b.34.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa contextual de `within Context` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
  - comparar `within`, `constrained_by` y la vecindad con `flow` sobre la base observable ya fijada en B20-B33
  - escoger `within Context` como el siguiente modificador local de menor superficie, limitado a casos donde el contexto ya existe en los bloques prefijados aceptados por `native-dev`
  - implementar de forma nativa formas como `context Review { ... }` seguido de `run Name() within Review`
  - extender ese mismo soporte a casos con bloques toplevel compartidos adicionales previos ya aceptados por `native-dev`
  - reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
  - mantener fuera `within` aislado o con contexto no resuelto, `constrained_by` y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer corte nativo contextual de `within Context` implementado, probado y alineado con el contrato observable

### Sesion B35

- Version interna objetivo: `v0.30.6-internal.b.35.1`
- Estado: `validated`
- Objetivo: abrir una primera forma nativa contextual de `constrained_by [Anchor, ...]` para `run(...)` sin absorber la semantica de programa que introduce `flow`
- Alcance:
- comparar `constrained_by [Anchor, ...]` frente a la vecindad con `flow` sobre la base observable ya fijada en B20-B34
- escoger `constrained_by [Anchor, ...]` como el siguiente modificador local de menor superficie, limitado a casos donde todos los anchors ya existen en los bloques prefijados aceptados por `native-dev`
- implementar de forma nativa formas como `anchor Safety { ... }` seguido de `run Name() constrained_by [Safety]`
- extender ese mismo soporte a casos con multiples anchors y con bloques toplevel compartidos adicionales previos ya aceptados por `native-dev`
- reproducir el diagnostico canonico `Undefined flow 'Name' in run statement` para esos casos
- mantener fuera `constrained_by` aislado o con anchors no resueltos y la vecindad con `flow` mientras no exista un corte mas seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
- existe un primer corte nativo contextual de `constrained_by [Anchor, ...]` implementado, probado y alineado con el contrato observable

### Sesion B36

- Version interna objetivo: `v0.30.6-internal.b.36.1`
- Estado: `validated`
- Objetivo: decidir si existe un primer corte seguro para la vecindad entre `run(...)` y `flow` o si esa frontera debe seguir delegada
- Alcance:
  - comparar la vecindad con `flow` frente a los casos locales aun no abiertos de `run(...)`
  - medir si existe algun subconjunto de `flow` vecino que preserve el contrato observable sin absorber resolucion semantica de programa completa
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada sobre la siguiente frontera segura de `native-dev` tras B35, con evidencia y pruebas objetivo claras

### Sesion B37

- Version interna objetivo: `v0.30.6-internal.b.37.1`
- Estado: `validated`
- Objetivo: abrir el primer camino nativo de exito para `native-dev` sin intentar absorber todavia toda la semantica del frontend Python
- Alcance:
  - partir de la conclusion de B36: la vecindad entre `run(...)` y `flow` no admite ya un corte local util y debe seguir delegada mientras `native-dev` solo sintetiza errores locales
  - escoger como primer camino positivo exacto el programa `flow Name() {}` seguido de `run Name()` sin prefijos ni modificadores adicionales
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para ese caso exacto
  - mantener los casos con `flow` vecino mas amplios, incluidos prefijos compartidos y nombres no resueltos, sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer camino nativo de exito implementado, probado y alineado con el contrato observable

### Sesion B38

- Version interna objetivo: `v0.30.6-internal.b.38.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento positivo mas pequeno tras el caso exacto `flow Name() {}` seguido de `run Name()`
- Alcance:
  - comparar si el siguiente corte positivo debe caer en modificadores locales ya abiertos en la ruta de error, como `output_to`, `effort` u `on_failure`, pero ahora sobre un `run` ya resuelto
  - escoger `output_to` y `effort` como el siguiente crecimiento positivo mas pequeno frente a una primera forma positiva prefijada con bloques compartidos previos ya soportados por `native-dev`
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `flow Name() {}` seguido de `run Name() output_to: ...` y `run Name() effort: ...`
  - mantener `on_failure` resuelto y las formas positivas prefijadas sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente crecimiento positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B39

- Version interna objetivo: `v0.30.6-internal.b.39.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento positivo mas pequeno con `on_failure` simple resuelto antes de una primera forma positiva prefijada
- Alcance:
  - comparar `run Name() on_failure: ...` resuelto frente a una primera forma positiva con bloques compartidos previos a `flow`
  - escoger `on_failure` simple resuelto como el siguiente crecimiento positivo mas pequeno porque solo rellena campos ya presentes en `IRRun` y no agrega nuevas declaraciones o referencias resueltas
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `flow Name() {}` seguido de `run Name() on_failure: log|retry`
  - mantener `raise`, `retry(...)` parametrizado y las formas positivas prefijadas sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente crecimiento positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B40

- Version interna objetivo: `v0.30.6-internal.b.40.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento positivo mas pequeno con `on_failure: raise X` resuelto antes de `retry(...)` parametrizado o de una primera forma positiva prefijada
- Alcance:
  - comparar `run Name() on_failure: raise X` y `run Name() on_failure: retry(...)` resueltos frente a una primera forma positiva con bloques compartidos previos a `flow`
  - escoger `on_failure: raise X` como el siguiente crecimiento positivo mas pequeno porque agrega un unico par `target` en `on_failure_params`, menos superficie que `retry(...)` parametrizado y menos semantica que una forma positiva prefijada
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `flow Name() {}` seguido de `run Name() on_failure: raise X`
  - mantener `retry(...)` parametrizado y las formas positivas prefijadas sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente crecimiento positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B41

- Version interna objetivo: `v0.30.6-internal.b.41.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento positivo mas pequeno con `retry(...)` parametrizado resuelto antes de una primera forma positiva prefijada
- Alcance:
  - comparar `run Name() on_failure: retry(...)` resuelto frente a una primera forma positiva con bloques compartidos previos a `flow`
  - escoger `retry(...)` parametrizado como el siguiente crecimiento positivo mas pequeno porque sigue rellenando solo `on_failure_params` sin agregar declaraciones o referencias resueltas nuevas
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `flow Name() {}` seguido de `run Name() on_failure: retry(...)`, incluyendo pares clave/valor variables
  - mantener las formas positivas prefijadas sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente crecimiento positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B42

- Version interna objetivo: `v0.30.6-internal.b.42.1`
- Estado: `validated`
- Objetivo: abrir la primera forma positiva prefijada para `native-dev`
- Alcance:
  - comparar cual es el primer programa positivo prefijado mas pequeno antes de `flow` y `run`, entre `persona`, `context` o `anchor`
  - escoger `persona` como el primer prefijo positivo mas pequeno porque agrega una sola declaracion con un campo escalar simple y no introduce referencias resueltas adicionales en `run`
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `persona Name { tone: value }` seguido de `flow Name() {}` y `run Name()`
  - mantener `context` y `anchor` sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera forma positiva prefijada implementada, probada y alineada con el contrato observable

### Sesion B43

- Version interna objetivo: `v0.30.6-internal.b.43.1`
- Estado: `validated`
- Objetivo: abrir el siguiente prefijo positivo mas pequeno para `native-dev`
- Alcance:
  - comparar `context` y `anchor` como siguientes formas positivas prefijadas sobre la base ya abierta con `persona`
  - escoger `context` como el siguiente prefijo positivo mas pequeno porque agrega una sola declaracion con un campo de configuracion simple y menor carga semantica observable que `anchor`
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `context Name { memory: value }` seguido de `flow Name() {}` y `run Name()`
  - mantener `anchor` sobre el path Python mientras no exista un siguiente corte seguro
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente prefijo positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B44

- Version interna objetivo: `v0.30.6-internal.b.44.1`
- Estado: `validated`
- Objetivo: abrir `anchor` como el siguiente prefijo positivo para `native-dev`
- Alcance:
  - comparar `anchor` positivo frente a cualquier otra extension positiva aun pendiente sobre la base ya abierta en B37-B43
  - confirmar que el payload observable de `anchor` sigue siendo un corte seguro y suficientemente pequeno: una sola declaracion con `require` y sin referencias resueltas adicionales en `run`
  - sintetizar de forma nativa el resultado exitoso de `check` y el `IRProgram` minimo de `compile` para `anchor Name { require: value }` seguido de `flow Name() {}` y `run Name()`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un siguiente prefijo positivo pequeno implementado, probado y alineado con el contrato observable

### Sesion B45

- Version interna objetivo: `v0.30.6-internal.b.45.1`
- Estado: `validated`
- Objetivo: abrir la primera forma positiva con multiples prefijos compartidos para `native-dev`
- Alcance:
  - comparar el crecimiento mas pequeno entre combinaciones como `persona + context`, `persona + anchor` o `context + anchor` antes de `flow` y `run`
  - medir cual de esos caminos agrega menos semantica observable adicional sobre la base ya abierta en B37-B44
  - implementar de forma exacta `persona Name { tone: value }` seguido de `context Name { memory: value }`, `flow Name() {}` y `run Name()`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera forma positiva multi-prefijo implementada, probada y alineada con el contrato observable

### Sesion B46

- Version interna objetivo: `v0.30.6-internal.b.46.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma positiva multi-prefijo exacta que involucre `anchor` en `native-dev`
- Alcance:
  - comparar el crecimiento mas pequeno entre `persona + anchor` y `context + anchor` antes de `flow` y `run`
  - medir cual de esos caminos agrega menos semantica observable adicional sobre la base ya abierta en B37-B45
  - implementar de forma exacta `persona Name { tone: value }` seguido de `anchor Name { require: value }`, `flow Name() {}` y `run Name()`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una siguiente forma positiva multi-prefijo exacta con `anchor` implementada, probada y alineada con el contrato observable

### Sesion B47

- Version interna objetivo: `v0.30.6-internal.b.47.1`
- Estado: `validated`
- Objetivo: abrir `context + anchor` como la siguiente forma positiva multi-prefijo exacta para `native-dev`
- Alcance:
  - validar si `context + anchor` sigue siendo un corte exacto suficientemente pequeno antes de abrir combinaciones de tres prefijos
  - medir la semantica observable adicional de `context + anchor` sobre la base ya abierta en B37-B46
  - implementar de forma exacta `context Name { memory: value }` seguido de `anchor Name { require: value }`, `flow Name() {}` y `run Name()`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma positiva multi-prefijo exacta `context + anchor` implementada, probada y alineada con el contrato observable

### Sesion B48

- Version interna objetivo: `v0.30.6-internal.b.48.1`
- Estado: `validated`
- Objetivo: abrir la primera forma positiva exacta con tres prefijos compartidos para `native-dev`
- Alcance:
  - validar si `persona + context + anchor` sigue siendo un corte exacto suficientemente pequeno antes de abrir combinaciones con modificadores de `run`
  - medir la semantica observable adicional del primer programa positivo exacto con tres prefijos sobre la base ya abierta en B37-B47
  - implementar de forma exacta `persona Name { tone: value }`, `context Name { memory: value }`, `anchor Name { require: value }`, `flow Name() {}` y `run Name()`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera forma positiva exacta con tres prefijos compartidos implementada, probada y alineada con el contrato observable

### Sesion B49

- Version interna objetivo: `v0.30.6-internal.b.49.1`
- Estado: `validated`
- Objetivo: abrir el primer modificador de `run` para la forma positiva exacta con tres prefijos compartidos en `native-dev`
- Alcance:
  - comparar el crecimiento mas pequeno entre extensiones como `output_to`, `effort` y `on_failure` simple sobre `persona + context + anchor` seguido de `flow` y `run`
  - medir cual de esos caminos agrega menos semantica observable adicional sobre la base ya abierta en B37-B48
  - implementar de forma exacta `output_to` y `effort` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe un primer crecimiento exacto de modificadores de `run` implementado, probado y alineado con el contrato observable para la forma positiva con tres prefijos compartidos

### Sesion B50

- Version interna objetivo: `v0.30.6-internal.b.50.1`
- Estado: `validated`
- Objetivo: abrir la primera forma exacta de `on_failure` sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - comparar el crecimiento mas pequeno entre `on_failure: log`, `on_failure: retry` y otras extensiones de `on_failure` sobre `persona + context + anchor`, `flow` y `run`
  - medir cual de esos caminos agrega menos semantica observable adicional sobre la base ya abierta en B37-B49
  - implementar de forma exacta `on_failure: log` y `on_failure: retry` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera forma exacta de `on_failure` implementada, probada y alineada con el contrato observable para el programa positivo con tres prefijos compartidos

### Sesion B51

- Version interna objetivo: `v0.30.6-internal.b.51.1`
- Estado: `validated`
- Objetivo: abrir la forma exacta `on_failure: raise X` sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `on_failure: raise X` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de `raise` frente a otras extensiones de `on_failure` sobre la base ya abierta en B37-B50
  - implementar de forma exacta `on_failure: raise X` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: raise X` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B52

- Version interna objetivo: `v0.30.6-internal.b.52.1`
- Estado: `validated`
- Objetivo: abrir la primera forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con un solo par `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de `retry(...)` parametrizado frente a formas mas ricas sobre la base ya abierta en B37-B51
  - implementar de forma exacta `on_failure: retry(k: v)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una primera forma exacta `on_failure: retry(k: v)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B53

- Version interna objetivo: `v0.30.6-internal.b.53.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente dos pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de dos pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B52
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B54

- Version interna objetivo: `v0.30.6-internal.b.54.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente tres pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de tres pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B53
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B55

- Version interna objetivo: `v0.30.6-internal.b.55.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente cuatro pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de cuatro pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B54
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B56

- Version interna objetivo: `v0.30.6-internal.b.56.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente cinco pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de cinco pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B55
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B57

- Version interna objetivo: `v0.30.6-internal.b.57.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente seis pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de seis pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B56
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B58

- Version interna objetivo: `v0.30.6-internal.b.58.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente siete pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de siete pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B57
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B59

- Version interna objetivo: `v0.30.6-internal.b.59.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente ocho pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de ocho pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B58
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B60

- Version interna objetivo: `v0.30.6-internal.b.60.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente nueve pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de nueve pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B59
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B61

- Version interna objetivo: `v0.30.6-internal.b.61.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente diez pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de diez pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B60
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B62

- Version interna objetivo: `v0.30.6-internal.b.62.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente once pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de once pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B61
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B63

- Version interna objetivo: `v0.30.6-internal.b.63.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente doce pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de doce pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B62
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B64

- Version interna objetivo: `v0.30.6-internal.b.64.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente trece pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de trece pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B63
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12, k13: v13)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12, k13: v13)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B65

- Version interna objetivo: `v0.30.6-internal.b.65.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma exacta de `retry(...)` parametrizado sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `retry(...)` con exactamente catorce pares `k: v` sigue siendo el siguiente corte suficientemente pequeno sobre `persona + context + anchor`, `flow` y `run`
  - medir la semantica observable adicional de catorce pares parametrizados frente a formas mas ricas sobre la base ya abierta en B37-B64
  - implementar de forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12, k13: v13, k14: v14)` sobre `persona + context + anchor`, `flow` y `run`
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una forma exacta `on_failure: retry(k1: v1, k2: v2, k3: v3, k4: v4, k5: v5, k6: v6, k7: v7, k8: v8, k9: v9, k10: v10, k11: v11, k12: v12, k13: v13, k14: v14)` implementada, probada y alineada con el contrato observable sobre el programa positivo con tres prefijos compartidos

### Sesion B66

- Version interna objetivo: `v0.30.6-internal.b.66.1`
- Estado: `validated`
- Objetivo: decidir si la escalera exacta termina y se reemplaza por una generalizacion controlada del camino `retry(...)` sobre el programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - evaluar si la evidencia acumulada hasta B65 justifica sustituir la igualdad por una aceptacion parametrizada de longitud variable para `on_failure_params`
  - definir guardrails observables para una generalizacion controlada sin romper contrato congelado, golden tests ni honestidad tecnica
  - implementar la generalizacion controlada solo sobre el programa positivo exacto con `persona + context + anchor + flow + run`, manteniendo fuera otras formas de exito prefijado
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada, implementada y verificada que sustituye la igualdad por una aceptacion parametrizada de longitud variable sin romper el contrato observable

### Sesion B67

- Version interna objetivo: `v0.30.6-internal.b.67.1`
- Estado: `validated`
- Objetivo: abrir la siguiente forma positiva exacta fuera del camino `retry(...)` ya generalizado sobre el programa con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `run Name() as PersonaName` con `persona + context + anchor + flow` ya declarados es el siguiente corte positivo mas pequeno fuera del subset actual
  - medir la semantica observable adicional de `as Persona` frente a otras formas positivas aun delegadas como `within Context` o `constrained_by [Anchor]`
  - implementar `run Name() as PersonaName` de forma exacta solo sobre el programa `persona + context + anchor + flow + run`, preservando delegacion para otras formas positivas prefijadas
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada, implementada y verificable que abre `as Persona` como siguiente corte exacto del success path prefijado sin ampliar otras formas positivas

### Sesion B68

- Version interna objetivo: `v0.30.6-internal.b.68.1`
- Estado: `validated`
- Objetivo: decidir si `run Name() within ContextName` es el siguiente corte positivo exacto mas pequeno restante sobre el programa con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `within Context` es ahora el menor crecimiento positivo local restante frente a `constrained_by [Anchor]`
  - medir la semantica observable adicional de `within Context` una vez abierto `as Persona`
  - implementar `run Name() within ContextName` de forma exacta solo sobre el programa `persona + context + anchor + flow + run`, preservando delegacion para otras formas positivas prefijadas
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada, implementada y verificable que abre `within Context` como siguiente corte exacto del success path prefijado sin ampliar otras formas positivas

### Sesion B69

- Version interna objetivo: `v0.30.6-internal.b.69.1`
- Estado: `validated`
- Objetivo: decidir si `run Name() constrained_by [AnchorName]` es el siguiente corte positivo exacto restante sobre el programa con tres prefijos compartidos en `native-dev`
- Alcance:
  - validar si `constrained_by [Anchor]` es ahora el menor crecimiento positivo local restante una vez abiertos `as Persona` y `within Context`
  - medir la semantica observable adicional de la lista de anchors resueltos sobre el mismo programa exacto
  - implementar `run Name() constrained_by [AnchorName]` de forma exacta solo sobre el programa `persona + context + anchor + flow + run`, preservando delegacion para listas mas amplias
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada, implementada y verificable que abre `constrained_by [AnchorName]` como siguiente corte exacto del success path prefijado sin ampliar listas mas amplias

### Sesion B70

- Version interna objetivo: `v0.30.6-internal.b.70.1`
- Estado: `validated`
- Objetivo: decidir si `constrained_by [...]` con mas de un anchor merece otra sesion exacta o si la escalera de modificadores locales del programa positivo con tres prefijos compartidos ya debe darse por cerrada
- Alcance:
  - evaluar el valor tecnico de abrir listas de anchors mas amplias frente a cerrar el ladder local del programa exacto ya cubierto
  - medir la semantica observable adicional de `constrained_by [A, B]` o listas repetidas frente al corte singular ya abierto
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada y verificable sobre si el siguiente trabajo debe seguir con listas multi-anchor o cerrar el ladder local actual

### Sesion B71

- Version interna objetivo: `v0.30.6-internal.b.71.1`
- Estado: `validated`
- Objetivo: decidir cual es el siguiente frente de mayor valor despues del cierre del ladder local exacto del programa positivo con tres prefijos compartidos en `native-dev`
- Alcance:
  - evaluar si el siguiente avance debe salir del ladder local ya cerrado y moverse a otra familia de programas o a una generalizacion justificada distinta
  - comparar el valor tecnico de seguir creciendo formas repetitivas de bajo signal frente a abrir un nuevo frente semantico con mejor retorno
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada y verificable sobre el siguiente frente de trabajo despues del cierre del ladder local actual

### Sesion B72

- Version interna objetivo: `v0.30.6-internal.b.72.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente avance debe convertir el success path prefijado en un matcher estructural compartido para bloques ya soportados en lugar de seguir enumerando combinaciones exactas
- Alcance:
  - evaluar el reemplazo de la escalera exacta de combinaciones prefijadas por un matcher estructural reusable para bloques `persona`, `context` y `anchor` ya portados
  - comparar el valor de esa generalizacion frente a seguir ampliando otras familias de declaraciones o mejoras de preparse con menor impacto sobre delegacion de exito
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada y verificable sobre si el siguiente paso debe ser un matcher estructural compartido para success paths prefijados ya conocidos

### Sesion B73

- Version interna objetivo: `v0.30.6-internal.b.73.1`
- Estado: `validated`
- Objetivo: decidir si el siguiente paso implementa un matcher estructural compartido para success paths prefijados con bloques unicos `persona`, `context` y `anchor` en cualquier orden seguidos de `flow Name() {}` y `run Name()` sin modifiers
- Alcance:
  - evaluar una implementacion que reemplace la enumeracion exacta de casos base prefijados por un matcher reusable sobre bloques conocidos ya portados
  - fijar como guardrails iniciales: bloques contiguos, unicos por kind, solo `persona/context/anchor`, cualquier orden, sin bloques ajenos intermedios y sin run modifiers en este primer corte estructural
  - mantener fuera duplicados, bloques adicionales como `memory`, y modifiers de `run` que hoy siguen en caminos exactos separados
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada y verificable sobre si ese matcher estructural acotado es el siguiente corte implementable de mayor valor

### Sesion B74

- Version interna objetivo: `v0.30.6-internal.b.74.1`
- Estado: `validated`
- Objetivo: decidir si el matcher estructural compartido debe extenderse a modifiers de `run` ya portados o mantenerse limitado al caso bare en este momento
- Alcance:
  - evaluar el valor tecnico de extender el matcher estructural a modifiers ya conocidos frente a mantener los modifiers en caminos exactos separados
  - comparar el riesgo de mezclar la nueva estructura reusable con los guardrails ya establecidos para `as`, `within`, `constrained_by`, `output_to`, `effort` y `on_failure`
  - mantener fuera bloques ajenos y duplicados mientras no exista evidencia nueva
  - mantener `type` fuera mientras no exista una estrategia explicita
- Criterio de terminado:
  - existe una decision documentada y verificable sobre si el siguiente corte debe extender el matcher estructural a modifiers o preservar esa frontera

### Resultado de B74

- Decision: el matcher estructural compartido no debe quedarse permanentemente bare, pero su primera extension futura debe limitarse a modifiers no referenciales que solo llenan campos ya existentes de `IRRun`
- Entran como siguiente corte justificable: `output_to`, `effort`, `on_failure` simple, `on_failure: raise X` y `on_failure: retry(...)` parametrizado sobre el programa prefijado estructural ya aceptado
- Permanecen fuera de esa primera extension: `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [...]`, porque agregan referencias resueltas o listas observables y no son solo relleno escalar/parametrico
- Se mantiene fuera cualquier bloque ajeno, duplicado de `persona/context/anchor` y cualquier apertura de `type`
- La siguiente sesion ya no necesita volver a decidir la frontera de B74; debe usar esta decision para escoger si implementa o no la primera extension estructural limitada a modifiers no referenciales

### Sesion B75

- Version interna objetivo: `v0.30.6-internal.b.75.1`
- Estado: `validated`
- Objetivo: implementar la primera extension estructural del success matcher para modifiers no referenciales de `run` sobre bloques unicos `persona/context/anchor` en cualquier orden
- Alcance:
  - extender el matcher estructural ya implementado en B73 para aceptar `output_to`, `effort`, `on_failure` simple, `on_failure: raise X` y `on_failure: retry(...)` parametrizado sobre ordenes alternos validos del programa prefijado estructural
  - reutilizar la informacion de prefijos disponibles para seguir rechazando dentro de este corte los modifiers referenciales `as`, `within` y `constrained_by [...]`
  - agregar cobertura de fachada y CLI para los nuevos casos estructurales con modifiers no referenciales
  - preservar fuera del corte bloques ajenos, duplicados y cualquier apertura de `type`
- Criterio de terminado:
  - los programas prefijados estructurales en orden alterno con modifiers no referenciales ya no delegan en Python y permanecen verdes en fachada, CLI y golden tests

### Resultado de B75

- Decision implementada: el matcher estructural compartido ya acepta modifiers no referenciales de `run` mientras mantiene fuera los modifiers con referencias resueltas
- Entran efectivamente en el camino nativo estructural: `output_to`, `effort`, `on_failure` simple, `on_failure: raise X` y `on_failure: retry(...)` parametrizado
- Permanecen fuera de este corte: `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [...]`, que siguen cayendo en los caminos exactos previos o en delegacion Python segun corresponda
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `184 passed`
- La siguiente sesion ya puede decidir si conviene abrir los modifiers referenciales estructurales o mover el frente a otro corte de mayor valor

### Sesion B76

- Version interna objetivo: `v0.30.6-internal.b.76.1`
- Estado: `validated`
- Objetivo: decidir si conviene abrir modifiers estructurales con referencias resueltas como `as`, `within` y `constrained_by [...]`, o si el siguiente corte de mayor valor esta fuera de ese frente
- Alcance:
  - caracterizar las formas estructurales alternas validas con `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [...]`
  - distinguir entre referencias resueltas singulares ya acotadas y listas mas amplias de anchors con mayor carga observable
  - verificar si esos casos siguen delegando en `native-dev` hoy y si el frontend Python ya los acepta con shape estable
  - mantener fuera bloques ajenos, duplicados de prefijos y cualquier apertura de `type`
- Criterio de terminado:
  - existe una decision documentada y verificable sobre si el siguiente corte debe abrir modifiers estructurales referenciales o mover el frente a otra zona

### Resultado de B76

- Decision: si el frente estructural continua, el siguiente corte justificable no esta fuera de este frente sino en una apertura parcial de modifiers referenciales singulares ya acotados por declaraciones disponibles
- Entran como siguiente corte justificable: `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [AnchorName]` singular sobre el programa prefijado estructural ya aceptado en orden alterno
- Permanece fuera de ese corte: `run Name() constrained_by [A, B, ...]` y cualquier lista repetida o mas amplia, porque agrega carga observable lineal sobre `anchor_names` y `resolved_anchors` que no queda justificada por analogia con la forma singular
- Evidencia: Python ya acepta las formas alternas `as`, `within`, `constrained_by [Safety]` y `constrained_by [Safety, Safety]` con shape estable; `native-dev` todavia delega todas esas formas hoy, asi que el hueco real y acotado es la forma referencial singular, no un cambio de frente
- La siguiente sesion ya puede implementar esa apertura parcial sin reabrir la duda sobre listas multi-anchor o repetir la caracterizacion

### Sesion B77

- Version interna objetivo: `v0.30.6-internal.b.77.1`
- Estado: `validated`
- Objetivo: implementar la apertura estructural parcial para `as`, `within` y `constrained_by [AnchorName]` singular sobre el programa prefijado estructural en orden alterno
- Alcance:
  - extender el matcher estructural compartido para aceptar `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [AnchorName]` singular cuando las declaraciones requeridas ya existen en los bloques estructurales parseados
  - resolver dentro de ese matcher las referencias singulares hacia `resolved_persona`, `resolved_context` y `resolved_anchors`
  - mantener fuera de este corte listas multi-anchor o repetidas en `constrained_by [...]`
  - agregar cobertura de fachada y CLI para los nuevos casos estructurales referenciales singulares
- Criterio de terminado:
  - los programas prefijados estructurales en orden alterno con `as`, `within` y `constrained_by [AnchorName]` singular ya no delegan en Python y permanecen verdes en fachada, CLI y golden tests

### Resultado de B77

- Decision implementada: el matcher estructural compartido ya acepta tambien las formas referenciales singulares `as`, `within` y `constrained_by [AnchorName]`
- Entran efectivamente en el camino nativo estructural: `run Name() as PersonaName`, `run Name() within ContextName` y `run Name() constrained_by [AnchorName]` singular sobre bloques unicos `persona/context/anchor` en cualquier orden
- Permanece fuera de este corte: `run Name() constrained_by [A, B, ...]` y cualquier lista repetida o mas amplia, que siguen cayendo en caminos exactos previos o en delegacion Python segun corresponda
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `187 passed`
- La siguiente sesion ya puede decidir si conviene abrir listas multi-anchor estructurales o mover el frente a otro corte de mayor valor

### Sesion B78

- Version interna objetivo: `v0.30.6-internal.b.78.1`
- Estado: `validated`
- Objetivo: implementar la apertura estructural acotada para `run Name() constrained_by [A, B, ...]` cuando el prefijo estructural ya declara multiples anchors distintos
- Alcance:
  - permitir que el matcher estructural compartido acepte multiples bloques `anchor` contiguos y en orden alterno junto con `persona` y `context`, manteniendo singleton a `persona` y `context`
  - resolver listas estructurales `constrained_by [A, B, ...]` hacia `anchor_names` y `resolved_anchors` en el mismo orden declarado en el `run`
  - mantener fuera de este corte listas repetidas como `[A, A]`, declaraciones `anchor` duplicadas por nombre y cualquier bloque ajeno al frente estructural ya abierto
  - agregar cobertura de fachada y CLI para el nuevo success path multi-anchor estructural
- Criterio de terminado:
  - los programas prefijados estructurales con multiples `anchor` distintos y `run Name() constrained_by [A, B, ...]` ya no delegan en Python y permanecen verdes en fachada, CLI y golden tests

### Resultado de B78

- Decision implementada: el matcher estructural compartido ya acepta multiples declaraciones `anchor` con nombres unicos y listas `constrained_by [A, B, ...]` sin delegacion Python
- Entran efectivamente en el camino nativo estructural: bloques contiguos en orden alterno con `persona` y `context` unicos, uno o mas `anchor` distintos, `flow Name() {}` y `run Name() constrained_by [A, B, ...]`
- Permanece fuera de este corte: listas repetidas como `constrained_by [Safety, Safety]`, declaraciones `anchor` duplicadas por nombre y cualquier otra ampliacion estructural ajena a este frente
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `190 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir listas repetidas o duplicados estructurales relacionados con `constrained_by [...]`, o mover el frente a otro corte de mayor valor

### Sesion B79

- Version interna objetivo: `v0.30.6-internal.b.79.1`
- Estado: `validated`
- Objetivo: implementar la apertura estructural acotada para listas repetidas en `run Name() constrained_by [A, A, B, ...]` cuando los anchors referidos ya existen en el prefijo estructural
- Alcance:
  - permitir que el matcher estructural compartido preserve repeticiones en `anchor_names` y `resolved_anchors` para `constrained_by [...]`
  - mantener fuera de este corte declaraciones `anchor` duplicadas por nombre, duplicados de `persona/context` y cualquier bloque ajeno al frente estructural abierto
  - agregar cobertura de fachada y CLI para el success path estructural con repeticiones en la lista del `run`
- Criterio de terminado:
  - los programas estructurales con `run Name() constrained_by [A, A, B, ...]` ya no delegan en Python y preservan el mismo shape observable de repeticiones en IR

### Resultado de B79

- Decision implementada: el matcher estructural compartido ya acepta listas repetidas en `constrained_by [...]` y conserva esas repeticiones tanto en `anchor_names` como en `resolved_anchors`
- Entran efectivamente en el camino nativo estructural: bloques contiguos en orden alterno con `persona` y `context` singleton, uno o mas `anchor` distintos por nombre, `flow Name() {}` y `run Name() constrained_by [A, A, B, ...]`
- Permanece fuera de este corte: declaraciones `anchor` duplicadas por nombre, duplicados de `persona/context` y cualquier otra ampliacion estructural ajena a este frente
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `193 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir duplicados estructurales de declaracion `anchor` por nombre o mover el frente a otro corte de mayor valor

### Sesion B80

- Version interna objetivo: `v0.30.6-internal.b.80.1`
- Estado: `validated`
- Objetivo: implementar una ruta local de diagnostico para declaraciones `anchor` duplicadas por nombre dentro del prefijo estructural ya soportado por `native-dev`
- Alcance:
  - detectar localmente un segundo bloque `anchor Name { ... }` con el mismo nombre dentro del prefijo estructural contiguo ya abierto
  - devolver el diagnostico canonico de Python `Duplicate declaration: 'Name' already defined as anchor (first defined at line X)` sin producir IR
  - mantener fuera de este corte combinaciones mas amplias de duplicados estructurales de `persona/context` o cualquier otro bloque ajeno al frente ya abierto
  - agregar cobertura de fachada y CLI para el nuevo path local de error
- Criterio de terminado:
  - los programas estructurales con `anchor` duplicado por nombre y resto de shape ya soportado dejan de delegar en Python y exponen el mismo diagnostico observable que la referencia

### Resultado de B80

- Decision implementada: `native-dev` ya detecta localmente declaraciones `anchor` duplicadas por nombre dentro del prefijo estructural soportado y devuelve el mismo diagnostico canonico de Python sin IR
- Entran efectivamente en el path local de error: bloques contiguos en orden alterno con un segundo `anchor Name { ... }` repetido por nombre, junto con `flow Name() {}` y `run Name()` o sus modifiers estructurales ya soportados cuando no introducen errores extra fuera del corte
- Permanece fuera de este corte: duplicados estructurales de `persona/context`, combinaciones con errores adicionales no portados y cualquier otra ampliacion ajena a este frente
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `196 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir otros duplicados estructurales o mover el frente a otro corte de mayor valor

### Sesion B81

- Version interna objetivo: `v0.30.6-internal.b.81.1`
- Estado: `validated`
- Objetivo: generalizar el path local de duplicados estructurales para cubrir tambien duplicados limpios de `persona` y `context` dentro del prefijo ya soportado por `native-dev`
- Alcance:
  - extender el path local de error para duplicados estructurales por nombre desde `anchor` hacia casos limpios de `persona` y `context`
  - exigir que el shape siga dentro del frente estructural ya soportado y que `context` no introduzca errores adicionales de `memory_scope`
  - mantener fuera de este corte combinaciones con multiples duplicados acumulados o errores extra no portados
  - agregar cobertura de fachada y CLI para los nuevos diagnosticos locales de `persona/context`
- Criterio de terminado:
  - los programas estructurales con duplicado limpio de `persona` o `context` dejan de delegar en Python y exponen el mismo diagnostico observable canonico sin IR

### Resultado de B81

- Decision implementada: `native-dev` ya detecta localmente duplicados estructurales limpios de `persona`, `context` y `anchor` por nombre dentro del prefijo soportado
- Entran efectivamente en el path local de error: un segundo bloque `persona Name { ... }`, `context Name { ... }` o `anchor Name { ... }` repetido por nombre cuando el resto del programa permanece dentro del frente estructural ya abierto y no introduce errores adicionales fuera del corte
- Permanece fuera de este corte: combinaciones con multiples duplicados acumulados, `context` con `memory_scope` invalido y cualquier otra ampliacion estructural ajena a este frente
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `199 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir combinaciones de duplicados mas amplias o si el siguiente corte de mayor valor esta en otro frente

### Sesion B82

- Version interna objetivo: `v0.30.6-internal.b.82.1`
- Estado: `validated`
- Objetivo: implementar acumulacion local de duplicate declarations estructurales limpias para combinaciones de `persona/context/anchor` dentro del prefijo ya soportado por `native-dev`
- Alcance:
  - acumular en orden de aparicion los diagnosticos canonicos de duplicate declaration para combinaciones limpias de duplicados estructurales `persona/context/anchor`
  - preservar el mismo orden observable de diagnosticos que Python en `check` y `compile`, sin producir IR
  - mantener fuera de este corte `context` con `memory_scope` invalido y combinaciones con errores extra no portados
  - agregar cobertura de fachada y CLI para casos con dos y tres duplicate declarations limpias
- Criterio de terminado:
  - los programas estructurales con multiples duplicate declarations limpias ya no delegan en Python y exponen el mismo conjunto ordenado de diagnosticos observables

### Resultado de B82

- Decision implementada: `native-dev` ya acumula localmente duplicate declarations estructurales limpias para combinaciones soportadas de `persona`, `context` y `anchor`
- Entran efectivamente en el path local de error: combinaciones limpias como `persona + context` duplicados, `persona + anchor` duplicados o `persona + context + anchor` duplicados cuando el resto del programa permanece dentro del frente estructural ya abierto
- Permanece fuera de este corte: `context` con `memory_scope` invalido, mezclas con errores adicionales y cualquier otra ampliacion estructural ajena a este frente limpio
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `202 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir combinaciones estructurales no limpias o si el siguiente corte de mayor valor esta en otro frente

### Sesion B83

- Version interna objetivo: `v0.30.6-internal.b.83.1`
- Estado: `validated`
- Objetivo: extender el path local de duplicate declarations estructurales para cubrir combinaciones no limpias acotadas donde un `context` duplicado tambien introduce `memory_scope` invalido
- Alcance:
  - preservar el orden observable de Python cuando un `context` duplicado emite primero duplicate declaration y luego `Unknown memory scope ...`
  - permitir acumulacion local de ese diagnostico adicional junto con duplicate declarations limpias ya portadas de `persona/context/anchor`
  - mantener fuera de este corte otras mezclas de errores estructurales no caracterizadas
  - agregar cobertura de fachada y CLI para combinaciones no limpias acotadas de duplicate declaration + invalid context memory
- Criterio de terminado:
  - los programas estructurales con duplicado limpio adicional y `context` repetido con `memory_scope` invalido dejan de delegar en Python y exponen el mismo orden de diagnosticos observable

### Resultado de B83

- Decision implementada: `native-dev` ya reproduce localmente las combinaciones no limpias acotadas donde un `context` duplicado añade el diagnostico canonico de `Unknown memory scope ...` despues de los duplicate declarations pertinentes
- Entran efectivamente en el path local de error: combinaciones estructurales ya soportadas donde `context Name { memory: invalid }` aparece como duplicado por nombre junto a duplicate declarations limpias de `persona/context/anchor`
- Permanece fuera de este corte: otras mezclas de errores estructurales no caracterizadas y validaciones adicionales fuera del frente actual
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `205 passed`
- La siguiente sesion ya puede decidir si vale la pena abrir otras mezclas estructurales no limpias o si el siguiente corte de mayor valor esta en otro frente

### Sesion B84

- Version interna objetivo: `v0.30.6-internal.b.84.1`
- Estado: `validated`
- Objetivo: extender el path local de duplicate declarations estructurales para cubrir combinaciones no limpias acotadas donde el primer `context` ya introduce `memory_scope` invalido y el programa aun acumula duplicate declarations soportadas
- Alcance:
  - preservar el orden observable de Python cuando hay duplicate declarations soportadas y uno o mas `context` estructurales emiten `Unknown memory scope ...`
  - permitir que ese orden siga siendo `duplicate declarations` primero y luego diagnosticos de `memory_scope` invalido en orden de fuente
  - incluir casos acotados donde el primer `context` ya es invalido, el duplicado posterior es valido o invalido, y puede coexistir con duplicados limpios de `persona`
  - mantener fuera de este corte otras mezclas de errores estructurales no caracterizadas fuera del frente `context.memory_scope`
- Criterio de terminado:
  - los programas estructurales soportados con duplicate declarations y `context` invalido desde la primera declaracion dejan de delegar en Python y preservan el mismo orden diagnostico observable

### Resultado de B84

- Decision implementada: `native-dev` ya acumula localmente diagnosticos canonicos de `Unknown memory scope ...` para cualquier `context` estructural soportado dentro del path de duplicate declarations, incluyendo cuando el primer `context` ya es invalido
- Entran efectivamente en el path local de error: combinaciones estructurales ya soportadas con `context Name { memory: invalid }` en la primera declaracion, con posterior duplicado del mismo `context` valido o invalido, y combinaciones junto a duplicate declarations limpias de `persona`
- Permanece fuera de este corte: programas con `context` invalido pero sin duplicate declarations soportadas, mismatches de nombre singleton, y otras validaciones no limpias fuera del frente `context.memory_scope`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `205 passed`
- La siguiente sesion ya puede decidir si conviene abrir otra familia acotada de validaciones estructurales no limpias o si el siguiente corte de mayor valor esta fuera de este frente

### Sesion B85

- Version interna objetivo: `v0.30.6-internal.b.85.1`
- Estado: `validated`
- Objetivo: extender el frente estructural local para cubrir `context.memory_scope` invalido sin duplicate declarations, cuando el resto del programa permanece dentro de las formas estructurales ya soportadas
- Alcance:
  - reproducir localmente el diagnostico canonico `Unknown memory scope ...` para programas estructurales soportados con un unico `context` invalido
  - preservar el orden observable de Python cuando ese mismo programa tambien produce el error local ya portado `Undefined flow ...`
  - cerrar la fuga donde algunos success matchers nativos aceptaban `context.memory_scope` invalido como si fuera un programa valido
  - agregar cobertura de fachada y CLI para `flow + run` estructural con `context` invalido y para `run` estructural prefijado que ademas termina en `Undefined flow ...`
- Criterio de terminado:
  - los programas estructurales soportados con `context` invalido y sin duplicate declarations dejan de delegar en Python, preservando el mismo orden diagnostico observable

### Resultado de B85

- Decision implementada: `native-dev` ya cubre localmente el frente `context.memory_scope` tambien sin duplicate declarations, tanto en programas estructurales con `flow + run` como en programas estructurales prefijados que terminan en `Undefined flow ...`
- Entran efectivamente en el path local de error: programas con un unico `context Name { memory: invalid }` dentro del frente estructural soportado, incluyendo combinaciones con `persona` y `anchor` unicos y `run ... within ContextName`
- Endurecimiento adicional: los matchers de exito nativos con `context` ya no aceptan `memory_scope` fuera de `VALID_MEMORY_SCOPES`
- Permanece fuera de este corte: otras familias de validacion estructural no limpia ajenas a `context.memory_scope`, combinaciones de `run` no soportadas por el subset local, y programas con singleton mismatches
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `209 passed`
- La siguiente sesion ya puede decidir si el frente no limpio sigue creciendo con otra familia acotada o si el siguiente corte de mayor valor esta fuera de estas validaciones estructurales

### Sesion B86

- Version interna objetivo: `v0.30.6-internal.b.86.1`
- Estado: `validated`
- Objetivo: extender el frente estructural local de validaciones sobre bloques soportados para cubrir `persona.tone` invalido y sus combinaciones acotadas con `context.memory_scope`
- Alcance:
  - reproducir localmente el diagnostico canonico `Unknown tone ...` para programas estructurales soportados con un unico `persona` invalido
  - preservar el orden observable de Python cuando `Unknown tone ...` y `Unknown memory scope ...` coexisten en prefijos estructurales soportados
  - preservar ese mismo orden cuando despues aparece tambien `Undefined flow ...` en el subset local ya portado
  - endurecer los success matchers nativos con `persona` para que no acepten `tone` fuera de `VALID_TONES`
- Criterio de terminado:
  - los programas estructurales soportados con `persona.tone` invalido dejan de delegar en Python y exponen el mismo orden diagnostico observable, solos o junto a `context.memory_scope`

### Resultado de B86

- Decision implementada: `native-dev` ya cubre localmente el frente estructural de validacion sobre `persona/context` para los campos ya soportados (`tone` y `memory`), acumulando diagnosticos en orden de fuente y preservando el orden adicional de `Undefined flow ...` cuando aparece despues
- Entran efectivamente en el path local de error: programas con `persona Name { tone: invalid }` dentro del frente estructural soportado, solos o combinados con `context Name { memory: invalid }`, tanto con `flow + run` como con `run` prefijado que termina en `Undefined flow ...`
- Endurecimiento adicional: los matchers de exito nativos con `persona` ya no aceptan `tone` fuera de `VALID_TONES`
- Permanece fuera de este corte: otras familias de validacion estructural no limpia ajenas a `persona.tone` y `context.memory_scope`, combinaciones de `run` fuera del subset local soportado, y bloques semanticos fuera del frente actual
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `213 passed`
- La siguiente sesion ya puede decidir si todavia vale la pena abrir otra familia acotada de validacion estructural o si el siguiente corte de mayor valor esta fuera de este frente

### Sesion B87

- Version interna objetivo: `v0.30.6-internal.b.87.1`
- Estado: `validated`
- Objetivo: cerrar la divergencia observada en el path estructural de duplicate declarations cuando una `persona` duplicada tambien emite `Unknown tone ...`
- Alcance:
  - acumular localmente `Unknown tone ...` en programas estructurales soportados con `persona` duplicada, tanto si la invalidez aparece en la primera declaracion, en la duplicada o en ambas
  - preservar el orden observable de Python: primero `Duplicate declaration ...` y despues las validaciones estructurales por orden de fuente
  - cubrir combinaciones acotadas donde `persona` duplicada invalida coexiste con `context.memory_scope` invalido ya portado
  - agregar regresion de fachada y CLI para el hueco detectado en la revision de B80-B86
- Criterio de terminado:
  - el path local de duplicate declarations para `persona` deja de divergir de Python cuando tambien interviene `Unknown tone ...`

### Resultado de B87

- Decision implementada: `native-dev` ya acumula `Unknown tone ...` tambien dentro del path estructural de duplicate declarations para `persona`, preservando el orden observable de Python en los casos caracterizados
- Entran efectivamente en el path local de error: `persona` duplicada con `tone` invalido en la primera declaracion, en la duplicada o en ambas, y combinaciones acotadas junto a `context.memory_scope` invalido
- Cierre de brecha: la divergencia detectada en la revision B80-B86 entre Python y `native-dev` para duplicate persona + invalid tone ya no existe
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `216 passed`
- La siguiente sesion ya puede decidir si conviene abrir otra familia acotada no limpia o si el siguiente corte de mayor valor esta fuera de este frente

### Sesion B88

- Version interna objetivo: `v0.30.6-internal.b.88.1`
- Estado: `validated`
- Objetivo: decidir si el frente estructural no limpio abierto en B80-B87 todavia tiene otra familia acotada de alto valor o si ya conviene mover el siguiente corte a otra parte del frontend
- Alcance:
  - contrastar el grammar estructural realmente soportado por `native-dev` con las validaciones adicionales del type checker Python
  - determinar si queda alguna familia no limpia pequena dentro de los bloques ya parseados localmente
  - explicitar si los siguientes candidatos ya exigen ampliar el parser local en vez de extender el mismo frente
  - dejar handoff documentado si el frente actual se considera agotado
- Criterio de terminado:
  - existe una decision documentada y justificada sobre si continuar o cerrar este frente estructural no limpio

### Resultado de B88

- Decision implementada: el frente estructural no limpio abierto en B80-B87 se considera agotado con el grammar actual; no queda otra familia pequena de alto valor dentro de los bloques ya parseados localmente
- Evidencia principal: el parser estructural compartido solo reconoce `persona { tone: ... }`, `context { memory: ... }` y `anchor { require: ... }`; dentro de esos campos ya quedaron cubiertos los diagnosticos locales relevantes de `persona.tone` y `context.memory_scope`, mientras `anchor.require` no abre una validacion local equivalente en Python
- Consecuencia: candidatos como `context.depth`, `persona.confidence_threshold`, `anchor.confidence_floor` y `anchor.on_violation` ya no son extensiones pequenas del mismo frente sino trabajo de crecimiento del grammar local
- Validacion: sesion de decision y documentacion; sin cambios funcionales ni rerun adicional requerido
- La siguiente sesion ya puede ejecutar B89 para elegir el siguiente corte de mayor valor fuera de este frente estructural no limpio agotado

### Sesion B89

- Version interna objetivo: `v0.30.6-internal.b.89.1`
- Estado: `validated`
- Objetivo: abrir el primer crecimiento acotado del grammar estructural compartido mas alla de `tone`/`memory`/`require`, empezando por `context.depth`
- Alcance:
  - extender el parser estructural local para reconocer `context Name { depth: value }`
  - permitir exito nativo local para programas estructurales soportados que usan `context.depth` valido
  - reproducir localmente los diagnosticos canonicos de `Unknown depth ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte campos numericos y variantes de `anchor` que exigen mas crecimiento de grammar
- Criterio de terminado:
  - `native-dev` ya no delega en Python para el primer corte acotado de `context.depth` dentro del frente estructural compartido

### Resultado de B89

- Decision implementada: `native-dev` ya soporta localmente `context { depth: ... }` en el parser estructural compartido, tanto en exito como en validacion y duplicate declarations
- Entran efectivamente en el path local: `context.depth` valido en programas estructurales soportados con `flow + run`, `Unknown depth ...` sin duplicados, `Unknown depth ...` seguido de `Undefined flow ...`, y duplicados de `context` que acumulan `Duplicate declaration ...` antes de los diagnosticos de depth invalido
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer `depth`, se agrego el diagnostico local de `Unknown depth ...`, y se endurecieron los success matchers estructurales para rechazar depth invalido igual que Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `221 passed`
- La siguiente sesion ya puede ejecutar B90 para decidir si el siguiente crecimiento de grammar compartido debe entrar por otro campo estructural de bajo costo o por otro corte del frontend con mejor retorno

### Sesion B90

- Version interna objetivo: `v0.30.6-internal.b.90.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el siguiente campo identificador-like de bajo costo, `anchor.enforce`, para que sus paths de exito y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { enforce: value }`
  - permitir exito nativo local para programas estructurales soportados que usan `anchor.enforce` y `run ... constrained_by [Anchor]`
  - permitir duplicate declarations locales de `anchor` tambien cuando el bloque estructural soportado usa `enforce` en vez de `require`
  - mantener fuera de este corte variantes de `anchor` que exigen parsing o validacion adicional, como `confidence_floor` y `on_violation`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.enforce` dentro del frente estructural compartido

### Resultado de B90

- Decision implementada: `native-dev` ya soporta localmente `anchor { enforce: ... }` en el parser estructural compartido, cubriendo exito y duplicate declarations sin delegacion a Python
- Entran efectivamente en el path local: programas estructurales soportados con `anchor.enforce` valido y `run ... constrained_by [Anchor]`, y duplicados de `anchor` con `enforce` que acumulan el diagnostico canonico de `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer `enforce`, reutilizando el mismo modelado IR de `IRAnchor` y los mismos paths locales de exito y duplicate declarations ya portados para `anchor`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `225 passed`
- La siguiente sesion ya puede ejecutar B91 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B91

- Version interna objetivo: `v0.30.6-internal.b.91.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el primer campo bool de bajo costo, `cite_sources`, sobre `persona` y `context`, para que sus paths de exito y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { cite_sources: true|false }`
  - extender el parser estructural local para reconocer `context Name { cite_sources: true|false }`
  - permitir exito nativo local para programas estructurales soportados con `cite_sources` en `persona/context`
  - permitir duplicate declarations locales de `persona/context` tambien cuando el bloque usa `cite_sources`
  - mantener fuera de este corte campos string o numericos que exigen otra justificacion de grammar
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `cite_sources` en `persona/context` dentro del frente estructural compartido

### Resultado de B91

- Decision implementada: `native-dev` ya soporta localmente `cite_sources` sobre `persona` y `context` en el parser estructural compartido, cubriendo exito y duplicate declarations sin delegacion a Python
- Entran efectivamente en el path local: programas estructurales soportados con `persona/context { cite_sources: true|false }` mas `flow + run`, y duplicados de `persona/context` con `cite_sources` que acumulan el diagnostico canonico de `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer bools en `cite_sources`, manteniendo el comportamiento Python donde `persona` sin `tone` sigue siendo valido y sin abrir validaciones nuevas
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `229 passed`
- La siguiente sesion ya puede ejecutar B92 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B92

- Version interna objetivo: `v0.30.6-internal.b.92.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el siguiente campo string de bajo costo, `language`, sobre `persona` y `context`, para que sus paths de exito y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { language: "..." }`
  - extender el parser estructural local para reconocer `context Name { language: "..." }`
  - permitir exito nativo local para programas estructurales soportados con `language` en `persona/context`
  - permitir duplicate declarations locales de `persona/context` tambien cuando el bloque usa `language`
  - mantener fuera de este corte otros campos string como `description` y `unknown_response`, y cualquier campo numerico o policy que requiera parsing o validacion adicional
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `language` en `persona/context` dentro del frente estructural compartido

### Resultado de B92

- Decision implementada: `native-dev` ya soporta localmente `language` sobre `persona` y `context` en el parser estructural compartido, cubriendo exito y duplicate declarations sin delegacion a Python
- Entran efectivamente en el path local: programas estructurales soportados con `persona/context { language: "es" }` mas `flow + run`, y duplicados de `persona/context` con `language` que acumulan el diagnostico canonico de `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer strings en `language`, reutilizando los campos ya presentes en `IRPersona` e `IRContext` sin abrir validaciones nuevas
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `233 passed`
- La siguiente sesion ya puede ejecutar B93 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B93

- Version interna objetivo: `v0.30.6-internal.b.93.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el siguiente campo string de bajo costo, `description`, sobre `persona` y `anchor`, para que sus paths de exito y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { description: "..." }`
  - extender el parser estructural local para reconocer `anchor Name { description: "..." }`
  - permitir exito nativo local para programas estructurales soportados con `description` en `persona/anchor`
  - permitir duplicate declarations locales de `persona/anchor` tambien cuando el bloque usa `description`
  - mantener fuera de este corte `unknown_response` y cualquier campo numerico o policy que requiera parsing o validacion adicional
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `description` en `persona/anchor` dentro del frente estructural compartido

### Resultado de B93

- Decision implementada: `native-dev` ya soporta localmente `description` sobre `persona` y `anchor` en el parser estructural compartido, cubriendo exito y duplicate declarations sin delegacion a Python
- Entran efectivamente en el path local: programas estructurales soportados con `persona { description: "..." }` mas `run ... as Persona`, `anchor { description: "..." }` mas `run ... constrained_by [Anchor]`, y duplicados de `persona/anchor` con `description` que acumulan el diagnostico canonico de `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer strings en `description`, reutilizando los campos ya presentes en `IRPersona` e `IRAnchor` sin abrir validaciones nuevas
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `237 passed`
- La siguiente sesion ya puede ejecutar B94 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B94

- Version interna objetivo: `v0.30.6-internal.b.94.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el siguiente campo string de bajo costo, `unknown_response`, sobre `anchor`, para que sus paths de exito y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { unknown_response: "..." }`
  - permitir exito nativo local para programas estructurales soportados con `unknown_response` en `anchor`
  - permitir duplicate declarations locales de `anchor` tambien cuando el bloque usa `unknown_response`
  - mantener fuera de este corte variantes de `anchor` que exigen parsing o validacion adicional, como `on_violation` y `confidence_floor`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `unknown_response` en `anchor` dentro del frente estructural compartido

### Resultado de B94

- Decision implementada: `native-dev` ya soporta localmente `unknown_response` sobre `anchor` en el parser estructural compartido, cubriendo exito y duplicate declarations sin delegacion a Python
- Entran efectivamente en el path local: programas estructurales soportados con `anchor { unknown_response: "..." }` mas `run ... constrained_by [Anchor]`, y duplicados de `anchor` con `unknown_response` que acumulan el diagnostico canonico de `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer strings en `unknown_response`, reutilizando el campo ya presente en `IRAnchor` sin abrir validaciones nuevas
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `241 passed`
- La siguiente sesion ya puede ejecutar B95 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B95

- Version interna objetivo: `v0.30.6-internal.b.95.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el primer campo entero validado de bajo costo, `context.max_tokens`, para que sus paths de exito, validacion y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `context Name { max_tokens: N }` con literales enteros de un solo token
  - permitir exito nativo local para programas estructurales soportados con `max_tokens` positivo en `context`
  - reproducir localmente el diagnostico canonico `max_tokens must be positive ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte floats y variantes mas ricas como `temperature`, `confidence_threshold`, `confidence_floor` u otros campos que exigen otra decision de grammar
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `context.max_tokens` dentro del frente estructural compartido

### Resultado de B95

- Decision implementada: `native-dev` ya soporta localmente `context { max_tokens: N }` en el parser estructural compartido, tanto en exito como en validacion y duplicate declarations
- Entran efectivamente en el path local: `context.max_tokens` positivo en programas estructurales soportados con `flow + run`, `max_tokens must be positive ...` sin duplicados, `max_tokens must be positive ...` seguido de `Undefined flow ...`, y duplicados de `context` que acumulan `Duplicate declaration ...` antes del diagnostico de `max_tokens` invalido
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer enteros en `max_tokens`, se agrego el diagnostico local de positividad y se endurecieron los success matchers estructurales para rechazar `max_tokens <= 0` igual que Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `246 passed`
- La siguiente sesion ya puede ejecutar B96 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B96

- Version interna objetivo: `v0.30.6-internal.b.96.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el primer campo float validado de bajo costo, `context.temperature`, para que sus paths de exito, validacion y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `context Name { temperature: N }` con literales numericos de un solo token
  - permitir exito nativo local para programas estructurales soportados con `temperature` en rango sobre `context`
  - reproducir localmente el diagnostico canonico `temperature must be between 0.0 and 2.0 ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte otros floats como `persona.confidence_threshold` y `anchor.confidence_floor`, ademas de policy fields como `on_violation`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `context.temperature` dentro del frente estructural compartido

### Resultado de B96

- Decision implementada: `native-dev` ya soporta localmente `context { temperature: N }` en el parser estructural compartido, tanto en exito como en validacion y duplicate declarations
- Entran efectivamente en el path local: `context.temperature` en rango en programas estructurales soportados con `flow + run`, `temperature must be between 0.0 and 2.0 ...` sin duplicados, `temperature must be between 0.0 and 2.0 ...` seguido de `Undefined flow ...`, y duplicados de `context` que acumulan `Duplicate declaration ...` antes del diagnostico de `temperature` invalida
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer numericos de un solo token en `temperature`, se agrego el diagnostico local de rango y se endurecieron los success matchers estructurales para rechazar temperaturas fuera de `[0.0, 2.0]` igual que Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `251 passed`
- La siguiente sesion ya puede ejecutar B97 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B97

- Version interna objetivo: `v0.30.6-internal.b.97.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el siguiente campo float validado de bajo costo, `persona.confidence_threshold`, para que sus paths de exito, validacion y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { confidence_threshold: N }` con literales numericos de un solo token
  - permitir exito nativo local para programas estructurales soportados con `confidence_threshold` en rango sobre `persona`
  - reproducir localmente el diagnostico canonico `confidence_threshold must be between 0.0 and 1.0 ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte `anchor.confidence_floor` y policy fields como `on_violation`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `persona.confidence_threshold` dentro del frente estructural compartido

### Resultado de B97

- Decision implementada: `native-dev` ya soporta localmente `persona { confidence_threshold: N }` en el parser estructural compartido, tanto en exito como en validacion y duplicate declarations
- Entran efectivamente en el path local: `persona.confidence_threshold` en rango en programas estructurales soportados con `flow + run`, `confidence_threshold must be between 0.0 and 1.0 ...` sin duplicados, `confidence_threshold must be between 0.0 and 1.0 ...` seguido de `Undefined flow ...`, y duplicados de `persona` que acumulan `Duplicate declaration ...` antes del diagnostico de `confidence_threshold` invalido
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer numericos de un solo token en `confidence_threshold`, se agrego el diagnostico local de rango y se endurecieron los success matchers estructurales para rechazar valores fuera de `[0.0, 1.0]` igual que Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `256 passed`
- La siguiente sesion ya puede ejecutar B98 para decidir si conviene abrir otro crecimiento pequeno del grammar estructural compartido o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B98

- Version interna objetivo: `v0.30.6-internal.b.98.1`
- Estado: `validated`
- Objetivo: extender el grammar estructural compartido con el ultimo float validado de bajo costo, `anchor.confidence_floor`, para que sus paths de exito, validacion y duplicate declarations dejen de delegar en Python
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { confidence_floor: N }` con literales numericos de un solo token
  - permitir exito nativo local para programas estructurales soportados con `confidence_floor` en rango sobre `anchor`
  - reproducir localmente el diagnostico canonico `confidence_floor must be between 0.0 and 1.0 ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte policy fields como `on_violation`, que exigen otra decision de grammar y validacion
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.confidence_floor` dentro del frente estructural compartido

### Resultado de B98

- Decision implementada: `native-dev` ya soporta localmente `anchor { confidence_floor: N }` en el parser estructural compartido, tanto en exito como en validacion y duplicate declarations
- Entran efectivamente en el path local: `anchor.confidence_floor` en rango en programas estructurales soportados con `flow + run`, `confidence_floor must be between 0.0 and 1.0 ...` sin duplicados, `confidence_floor must be between 0.0 and 1.0 ...` seguido de `Undefined flow ...`, y duplicados de `anchor` que acumulan `Duplicate declaration ...` antes del diagnostico de `confidence_floor` invalido
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer numericos de un solo token en `confidence_floor`, se agrego el diagnostico local de rango y se endurecieron los success matchers estructurales para rechazar valores fuera de `[0.0, 1.0]` igual que Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `261 passed`
- La siguiente sesion ya puede ejecutar B99 para decidir si conviene abrir el frente de policy fields como `on_violation` o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B99

- Version interna objetivo: `v0.30.6-internal.b.99.1`
- Estado: `validated`
- Objetivo: abrir el primer corte acotado de `anchor.on_violation` dentro del grammar estructural compartido sin entrar todavia en las formas parser-side que requieren target o argumentos
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { on_violation: action }` solo cuando `action` es una forma de un solo token que no abre parsing adicional
  - permitir exito nativo local para `warn`, `log` y `escalate` sobre `anchor` en programas estructurales soportados con `flow + run`
  - reproducir localmente el diagnostico canonico `Unknown on_violation action ...` y su orden relativo con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera de este corte las formas `raise ErrorName` y `fallback("...")`, que siguen requiriendo otra decision de grammar
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.on_violation` de un solo token dentro del frente estructural compartido, preservando la delegacion para `raise` y `fallback`

### Resultado de B99

- Decision implementada: `native-dev` ya soporta localmente `anchor { on_violation: action }` para el subconjunto de un solo token que no exige parsing adicional, incluyendo exito para `warn`, `log` y `escalate`, y validacion local para acciones desconocidas como `explode`
- Entran efectivamente en el path local: `anchor.on_violation` valido en programas estructurales soportados con `flow + run`, `Unknown on_violation action ...` sin duplicados, `Unknown on_violation action ...` seguido de `Undefined flow ...`, y duplicados de `anchor` que acumulan `Duplicate declaration ...` antes del diagnostico de `on_violation` invalido
- Implementacion: se extendio el parser compartido de bloques estructurales para reconocer el subconjunto ident-like de `on_violation`, se agrego el diagnostico local canonico para acciones desconocidas y se endurecieron los success matchers estructurales para rechazar acciones fuera de `VALID_VIOLATION_ACTIONS`; `raise` y `fallback` quedan deliberadamente fuera del matcher local para conservar el comportamiento parser-side de Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `266 passed`
- La siguiente sesion ya puede ejecutar B100 para decidir si conviene abrir las formas parser-side restantes de `on_violation` (`raise ErrorName` o `fallback("...")`) o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B100

- Version interna objetivo: `v0.30.6-internal.b.100.1`
- Estado: `validated`
- Objetivo: abrir el menor corte parser-side restante de `anchor.on_violation` dentro del grammar estructural compartido mediante la forma `raise ErrorName`, sin entrar todavia en `fallback("...")`
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { on_violation: raise ErrorName }`
  - permitir exito nativo local para programas estructurales soportados con `raise ErrorName` sobre `anchor`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `raise ErrorName` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el orden de `Duplicate declaration ...` seguido de `Unknown on_violation action ...` cuando el primer `anchor` usa `raise ErrorName` y el segundo duplicado usa una accion invalida
  - mantener fuera de este corte la forma `fallback("...")` y los errores parser-side mal formados como `raise }` o `raise "Err"`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.on_violation: raise ErrorName` dentro del frente estructural compartido, preservando la delegacion del resto de formas parser-side

### Resultado de B100

- Decision implementada: `native-dev` ya soporta localmente `anchor { on_violation: raise ErrorName }` en el parser estructural compartido, incluyendo la propagacion de `on_violation_target` al IR sintetizado
- Entran efectivamente en el path local: `raise ErrorName` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque `raise ErrorName` es valido pero el `run` referencia un flow ausente, y duplicados de `anchor` que acumulan `Duplicate declaration ...` antes del diagnostico `Unknown on_violation action ...` si el segundo duplicado es invalido
- Implementacion: se generalizo el parser compartido para aceptar bloques estructurales de `anchor` con longitud variable solo en el caso acotado `on_violation: raise IDENTIFIER`, se ajusto la ruta local de duplicate declarations para no depender de un tamano fijo de bloque y se mantuvo `fallback("...")` fuera del matcher local
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `271 passed`
- La siguiente sesion ya puede ejecutar B101 para decidir si conviene abrir `anchor.on_violation: fallback("...")` o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B101

- Version interna objetivo: `v0.30.6-internal.b.101.1`
- Estado: `validated`
- Objetivo: abrir la ultima forma valida restante de `anchor.on_violation` dentro del grammar estructural compartido mediante `fallback("...")`, sin entrar en errores parser-side mal formados
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { on_violation: fallback("...") }`
  - permitir exito nativo local para programas estructurales soportados con `fallback("...")` sobre `anchor`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `fallback("...")` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el orden de `Duplicate declaration ...` seguido de `Unknown on_violation action ...` cuando el primer `anchor` usa `fallback("...")` y el segundo duplicado usa una accion invalida
  - mantener fuera de este corte los errores parser-side mal formados como `fallback }` o `fallback(123)`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.on_violation: fallback("...")` dentro del frente estructural compartido, preservando la delegacion de las variantes parser-side mal formadas

### Resultado de B101

- Decision implementada: `native-dev` ya soporta localmente `anchor { on_violation: fallback("...") }` en el parser estructural compartido, incluyendo la propagacion del mensaje de fallback a `on_violation_target` en el IR sintetizado
- Entran efectivamente en el path local: `fallback("...")` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque `fallback("...")` es valido pero el `run` referencia un flow ausente, y duplicados de `anchor` que acumulan `Duplicate declaration ...` antes del diagnostico `Unknown on_violation action ...` si el segundo duplicado es invalido
- Implementacion: se extendio el parser compartido con el patron acotado `on_violation: fallback ( STRING )`, reutilizando la misma ruta local de duplicate declarations ya generalizada en B100 y manteniendo delegadas las variantes parser-side mal formadas como `fallback }` y `fallback(123)`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `276 passed`
- La siguiente sesion ya puede ejecutar B102 para decidir si queda algun crecimiento pequeno de mayor valor en otra parte del frontend o si el frente de `anchor.on_violation` puede considerarse cerrado salvo las formas parser-side mal formadas que deben seguir delegadas

### Sesion B102

- Version interna objetivo: `v0.30.6-internal.b.102.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento pequeno del grammar estructural compartido fuera de `on_violation` mediante `anchor.reject`, manteniendo delegadas las formas parser-side que no encajan en un corte limpio
- Alcance:
  - extender el parser estructural local para reconocer `anchor Name { reject: [a, b, ...] }` con una o mas entradas identifier-like
  - permitir exito nativo local para programas estructurales soportados con `reject` sobre `anchor`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `reject` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` cuando un segundo `anchor` estructural repite el mismo nombre usando tambien `reject`
  - mantener fuera de este corte formas parser-side como `reject: []`, que siguen devolviendo error de parser en Python
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `anchor.reject` dentro del frente estructural compartido, preservando la delegacion de las variantes parser-side no limpias

### Resultado de B102

- Decision implementada: `native-dev` ya soporta localmente `anchor { reject: [a, b, ...] }` en el parser estructural compartido, incluyendo la propagacion de la lista `reject` al IR sintetizado
- Entran efectivamente en el path local: `reject` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque `reject` es valido pero el `run` referencia un flow ausente, y duplicados de `anchor` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se extendio el parser compartido con un helper acotado para listas bracketed de uno o mas valores identifier-like en `anchor.reject`, manteniendo delegadas formas parser-side como `reject: []` que Python trata como error de parser
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `281 passed`
- La siguiente sesion ya puede ejecutar B103 para decidir si el siguiente crecimiento pequeno de mayor valor esta en otro field estructural como `persona.refuse_if` o `persona.domain`, o si conviene mover el foco a otra parte del frontend

### Sesion B103

- Version interna objetivo: `v0.30.6-internal.b.103.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento pequeno del grammar estructural compartido en `persona` mediante `refuse_if`, manteniendo fuera listas string como `domain`
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { refuse_if: [a, b, ...] }` con una o mas entradas identifier-like
  - permitir exito nativo local para programas estructurales soportados con `refuse_if` sobre `persona`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `refuse_if` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` cuando un segundo `persona` estructural repite el mismo nombre usando tambien `refuse_if`
  - mantener fuera de este corte formas parser-side como `refuse_if: []` y listas string como `persona.domain`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `persona.refuse_if` dentro del frente estructural compartido, preservando la delegacion de variantes no limpias y de listas string

### Resultado de B103

- Decision implementada: `native-dev` ya soporta localmente `persona { refuse_if: [a, b, ...] }` en el parser estructural compartido, incluyendo la propagacion de la lista `refuse_if` al IR sintetizado
- Entran efectivamente en el path local: `refuse_if` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque `refuse_if` es valido pero el `run` referencia un flow ausente, y duplicados de `persona` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se reutilizo el helper acotado de listas bracketed identifier-like introducido para `anchor.reject`, extendiendo el parser compartido a `persona.refuse_if` sin abrir listas string ni listas vacias; `refuse_if: []` y `persona.domain` siguen delegados a Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `286 passed`
- La siguiente sesion ya puede ejecutar B104 para decidir si el siguiente crecimiento pequeno de mayor valor esta en otro field estructural como `persona.domain` o si conviene mover el foco a otra parte del frontend

### Sesion B104

- Version interna objetivo: `v0.30.6-internal.b.104.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento pequeno del grammar estructural compartido en `persona` mediante `domain`, acotado a listas bracketed de strings
- Alcance:
  - extender el parser estructural local para reconocer `persona Name { domain: ["a", "b", ...] }` con una o mas entradas string
  - permitir exito nativo local para programas estructurales soportados con `domain` sobre `persona`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `domain` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` cuando un segundo `persona` estructural repite el mismo nombre usando tambien `domain`
  - mantener fuera de este corte formas parser-side como `domain: []` y listas bracketed de identificadores como `domain: [science]`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `persona.domain` dentro del frente estructural compartido, preservando la delegacion de variantes parser-side no limpias

### Resultado de B104

- Decision implementada: `native-dev` ya soporta localmente `persona { domain: ["a", "b", ...] }` en el parser estructural compartido, incluyendo la propagacion de la lista `domain` al IR sintetizado
- Entran efectivamente en el path local: `domain` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque `domain` es valido pero el `run` referencia un flow ausente, y duplicados de `persona` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se agrego un parser acotado para listas bracketed de uno o mas strings y se conecto al dispatcher estructural compartido sin abrir listas vacias ni listas identifier-like; `domain: []` y `domain: [science]` siguen delegados a Python
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `291 passed`
- La siguiente sesion ya puede ejecutar B105 para decidir si conviene abrir otro frente estructural pequeno fuera de `persona.domain` o mover el foco a otra parte del frontend

### Sesion B105

- Version interna objetivo: `v0.30.6-internal.b.105.1`
- Estado: `validated`
- Objetivo: abrir el siguiente crecimiento pequeno fuera del trio `persona/context/anchor` mediante `memory.store`, sin ensanchar todavia el resto de `memory`
- Alcance:
  - extender el parser estructural local para reconocer `memory Name { store: value }` con un unico valor identifier-like
  - permitir exito nativo local para programas estructurales soportados con `memory.store` prefijado antes de `flow + run`
  - reproducir localmente la validacion canonica `Unknown store type ...` cuando `store` cae fuera de `VALID_MEMORY_SCOPES`
  - preservar localmente el orden observable de Python cuando `Unknown store type ...` coexiste con `Undefined flow ...`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para memorias duplicadas por nombre, acumulado junto a la validacion de `store` invalido cuando corresponda
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `memory.store` dentro del frente estructural compartido, preservando la delegacion del resto de fields de `memory`

### Resultado de B105

- Decision implementada: `native-dev` ya soporta localmente `memory { store: value }` en el parser estructural compartido, incluyendo la propagacion de `memory.store` al IR sintetizado
- Entran efectivamente en el path local: `memory.store` valido en programas estructurales soportados con `flow + run`, `Unknown store type ...` para valores fuera de `VALID_MEMORY_SCOPES`, `Undefined flow ...` cuando el bloque es estructuralmente valido pero el `run` referencia un flow ausente, y duplicados de `memory` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se abrio el kind top-level `memory` en el matcher estructural compartido con un corte minimo centrado solo en `store`, reutilizando la validacion local ya congelada en Python sin abrir todavia `backend`, `retrieval` ni `decay`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `297 passed`
- La siguiente sesion ya puede ejecutar B106 para decidir si conviene seguir creciendo el frente `memory` con otro field pequeno como `backend` o `retrieval`, o si el siguiente corte de mayor valor esta en otra parte del frontend

### Sesion B106

- Version interna objetivo: `v0.30.6-internal.b.106.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `memory` por el corte mas pequeno disponible mediante `backend`, sin abrir todavia validaciones nuevas ni valores mixtos como `decay`
- Alcance:
  - extender el parser estructural local para reconocer `memory Name { backend: value }` con un unico valor identifier-like
  - permitir exito nativo local para programas estructurales soportados con `memory.backend` prefijado antes de `flow + run`
  - preservar localmente el comportamiento observado con `Undefined flow ...` cuando el bloque `backend` es valido pero el `run` referencia un flow ausente
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para memorias duplicadas por nombre cuando el bloque usa `backend`
  - mantener fuera de este corte `memory.retrieval` y `memory.decay`, que introducen validacion adicional o grammar mixto
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `memory.backend` dentro del frente estructural compartido, preservando la delegacion del resto de fields de `memory`

### Resultado de B106

- Decision implementada: `native-dev` ya soporta localmente `memory { backend: value }` en el parser estructural compartido, incluyendo la propagacion de `memory.backend` al IR sintetizado
- Entran efectivamente en el path local: `memory.backend` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque es estructuralmente valido pero el `run` referencia un flow ausente, y duplicados de `memory` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se extendio el corte minimo ya abierto para `memory` con otro field identifier-like sin validaciones nuevas, manteniendo delegados `memory.retrieval` y `memory.decay`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `302 passed`
- La siguiente sesion ya puede ejecutar B107 para decidir si conviene seguir con `memory.retrieval`, abrir `memory.decay`, o mover el foco a otra parte del frontend

### Sesion B107

- Version interna objetivo: `v0.30.6-internal.b.107.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `memory` por `retrieval`, manteniendo fuera por ahora el grammar mixto de `decay`
- Alcance:
  - extender el parser estructural local para reconocer `memory Name { retrieval: value }` con un unico valor identifier-like
  - permitir exito nativo local para programas estructurales soportados con `memory.retrieval` prefijado antes de `flow + run`
  - reproducir localmente la validacion canonica `Unknown retrieval strategy ...` cuando `retrieval` cae fuera de `VALID_RETRIEVAL_STRATEGIES`
  - preservar localmente el orden observable de Python cuando `Unknown retrieval strategy ...` coexiste con `Undefined flow ...`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para memorias duplicadas por nombre, acumulado junto a la validacion de `retrieval` invalido cuando corresponda
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `memory.retrieval` dentro del frente estructural compartido, preservando la delegacion de `memory.decay`

### Resultado de B107

- Decision implementada: `native-dev` ya soporta localmente `memory { retrieval: value }` en el parser estructural compartido, incluyendo la propagacion de `memory.retrieval` al IR sintetizado
- Entran efectivamente en el path local: `memory.retrieval` valido en programas estructurales soportados con `flow + run`, `Unknown retrieval strategy ...` para valores fuera de `VALID_RETRIEVAL_STRATEGIES`, `Undefined flow ...` cuando el bloque es estructuralmente valido pero el `run` referencia un flow ausente, y duplicados de `memory` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se extendio el frente `memory` con otro field identifier-like, añadiendo la validacion local de retrieval y endureciendo el success matcher para que los valores invalidos no se acepten como exito nativo
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `308 passed`
- La siguiente sesion ya puede ejecutar B108 para decidir si conviene abrir `memory.decay` o mover el foco a otra parte del frontend

### Sesion B108

- Version interna objetivo: `v0.30.6-internal.b.108.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `memory` por `decay`, aprovechando que el lexer nativo ya reconoce `DURATION`
- Alcance:
  - extender el parser estructural local para reconocer `memory Name { decay: value }` tanto en su forma `DURATION` como en su forma identifier-like
  - permitir exito nativo local para programas estructurales soportados con `memory.decay` prefijado antes de `flow + run`
  - preservar localmente `Undefined flow ...` cuando el bloque `memory.decay` es estructuralmente valido pero el `run` referencia un flow ausente
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para memorias duplicadas por nombre cuando usan `decay`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `memory.decay` dentro del frente estructural compartido

### Resultado de B108

- Decision implementada: `native-dev` ya soporta localmente `memory { decay: value }` dentro del parser estructural compartido, tanto para valores `DURATION` como para valores identifier-like, propagando `memory.decay` al IR sintetizado
- Entran efectivamente en el path local: `memory.decay` valido en programas estructurales soportados con `flow + run`, `Undefined flow ...` cuando el bloque es estructuralmente valido pero el `run` referencia un flow ausente, y duplicados de `memory` que acumulan el diagnostico canonico `Duplicate declaration ...`
- Implementacion: se extendio el frente `memory` sin abrir un kind nuevo, reutilizando el lexer nativo ya capaz de tokenizar `DURATION` y manteniendo fuera por ahora otros frentes como `tool.provider`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `313 passed`
- La siguiente sesion ya puede ejecutar B109 para decidir si conviene abrir otro field pequeno en `memory`, pasar a `tool.provider`, o mover el foco a otra parte del frontend

### Sesion B109

- Version interna objetivo: `v0.30.6-internal.b.109.1`
- Estado: `validated`
- Objetivo: abrir el siguiente corte pequeno fuera del frente `memory`, empezando por `tool.provider`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { provider: value }` con un unico valor identifier-like
  - permitir exito nativo local para programas estructurales soportados con `tool.provider` prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para tools duplicados por nombre cuando usan `provider`
  - mantener fuera validaciones de `tool` mas pesadas como `max_results`, `timeout`, `sandbox` o `effects`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.provider` dentro del frente estructural compartido

### Resultado de B109

- Decision implementada: `native-dev` ya soporta localmente `tool { provider: value }` dentro del parser estructural compartido, propagando `tool.provider` al IR sintetizado sin abrir validaciones nuevas
- Entran efectivamente en el path local: `tool.provider` valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se abrio el kind `tool` por su field mas pequeno y estable, `provider`, evitando mezclar en la misma sesion integer validation (`max_results`) o grammar adicional como `timeout` y `effects`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `317 passed`
- La siguiente sesion ya puede ejecutar B110 para decidir si conviene seguir con otro field pequeno de `tool` como `runtime` o `sandbox`, abrir `max_results` con validacion local, o mover el foco a otra parte del frontend

### Sesion B110

- Version interna objetivo: `v0.30.6-internal.b.110.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `tool` por su siguiente field mas pequeno, `runtime`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { runtime: value }` con un unico valor identifier-like
  - permitir exito nativo local para programas estructurales soportados con `tool.runtime` prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para tools duplicados por nombre cuando usan `runtime`
  - mantener fuera fields de `tool` que abren bool parsing o validacion local adicional como `sandbox` y `max_results`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.runtime` dentro del frente estructural compartido

### Resultado de B110

- Decision implementada: `native-dev` ya soporta localmente `tool { runtime: value }` dentro del parser estructural compartido, propagando `tool.runtime` al IR sintetizado sin abrir validaciones nuevas
- Entran efectivamente en el path local: `tool.runtime` valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se siguio creciendo `tool` por otro field identifier-like sin validacion local, `runtime`, evitando en esta sesion abrir bool parsing (`sandbox`) o integer validation (`max_results`)
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `321 passed`
- La siguiente sesion ya puede ejecutar B111 para decidir si conviene abrir `tool.sandbox`, pasar a `tool.max_results` con validacion local, o mover el foco a otra parte del frontend

### Sesion B111

- Version interna objetivo: `v0.30.6-internal.b.111.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `tool` por su siguiente field mas pequeno, `sandbox`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { sandbox: true|false }`
  - permitir exito nativo local para programas estructurales soportados con `tool.sandbox` prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para tools duplicados por nombre cuando usan `sandbox`
  - mantener fuera fields de `tool` que abren validacion local adicional o rutas parser-side especificas, como `max_results` y `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.sandbox` dentro del frente estructural compartido

### Resultado de B111

- Decision implementada: `native-dev` ya soporta localmente `tool { sandbox: true|false }` dentro del parser estructural compartido, propagando `tool.sandbox` al IR sintetizado sin abrir validaciones nuevas
- Entran efectivamente en el path local: `tool.sandbox` valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se eligio `sandbox` porque el carril estructural ya aceptaba `BOOL` en este frente y solo faltaba mapearlo a `IRToolSpec`; `timeout` seguia exigiendo una ruta `DURATION` especifica y `max_results` seguia siendo mayor por validacion local y orden diagnostico
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `325 passed`
- La siguiente sesion ya puede ejecutar B112 para decidir si conviene abrir `tool.timeout`, pasar a `tool.max_results` con validacion local, o mover el foco a otra parte del frontend

### Sesion B112

- Version interna objetivo: `v0.30.6-internal.b.112.1`
- Estado: `validated`
- Objetivo: seguir creciendo el frente `tool` por su siguiente field mas pequeno, `timeout`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { timeout: 10s }` con un unico valor `DURATION`
  - permitir exito nativo local para programas estructurales soportados con `tool.timeout` prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico de `Duplicate declaration ...` para tools duplicados por nombre cuando usan `timeout`
  - mantener fuera fields de `tool` que abren validacion local adicional o semantica parser-side mayor, como `max_results`, `filter` o `effects`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.timeout` dentro del frente estructural compartido

### Resultado de B112

- Decision implementada: `native-dev` ya soporta localmente `tool { timeout: <duration> }` dentro del parser estructural compartido, propagando `tool.timeout` al IR sintetizado sin abrir validaciones nuevas
- Entran efectivamente en el path local: `tool.timeout` valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se eligio `timeout` porque el lexer estructural ya produce tokens `DURATION` y solo faltaba abrir una ruta local acotada para ese valor; `max_results` sigue siendo mayor por validacion local y orden diagnostico observable
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `329 passed`
- La siguiente sesion ya puede ejecutar B113 para decidir si conviene abrir `tool.max_results`, mover el foco a otro field de `tool` de mayor coste parser-side, o salir a otro frente del frontend

### Sesion B113

- Version interna objetivo: `v0.30.6-internal.b.113.1`
- Estado: `validated`
- Objetivo: abrir el siguiente field de `tool` con mejor costo marginal, `max_results`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { max_results: 3 }` con un unico valor `INTEGER`
  - permitir exito nativo local para programas estructurales soportados con `tool.max_results` prefijado antes de `flow + run`
  - reproducir localmente la validacion canonica `max_results must be positive ...`, incluyendo su acumulacion con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera fields de `tool` que siguen abriendo semantica parser-side mas grande, como `filter` o `effects`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.max_results` dentro del frente estructural compartido, preservando el orden diagnostico observable

### Resultado de B113

- Decision implementada: `native-dev` ya soporta localmente `tool { max_results: <integer> }` dentro del parser estructural compartido, propagando `tool.max_results` al IR sintetizado y reproduciendo la validacion local de positividad
- Entran efectivamente en el path local: `tool.max_results` valido en programas estructurales soportados con `flow + run`, el diagnostico `max_results must be positive ...`, su acumulacion con `Undefined flow ...`, y duplicados de `tool` que mantienen el orden observable `Duplicate declaration ...` seguido por la validacion de positividad
- Implementacion: se eligio `max_results` porque el carril estructural ya aceptaba `INTEGER` como valor simple y el hueco real quedaba limitado a cablear `IRToolSpec.max_results` y anexar la validacion local de type-checker; `filter` y `effects` siguen siendo claramente mas caros por parseo estructural adicional
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `335 passed`
- La siguiente sesion ya puede ejecutar B114 para decidir si conviene abrir `tool.filter`, comparar `tool.effects` contra otro frente, o salir del frontier `tool` hacia otra parte del frontend

### Sesion B114

- Version interna objetivo: `v0.30.6-internal.b.114.1`
- Estado: `validated`
- Objetivo: abrir el siguiente corte acotado de `tool.filter` sin absorber aun la forma parser-side `filter(...)`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { filter: value }` con un unico valor ident-like de un token
  - permitir exito nativo local para programas estructurales soportados con `tool.filter` ident-like prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico `Duplicate declaration ...` para tools duplicados por nombre cuando usan `filter` ident-like
  - mantener fuera la forma mas costosa `tool.filter: recent(days: 30)` y el frente `tool.effects`
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.filter` ident-like dentro del frente estructural compartido

### Resultado de B114

- Decision implementada: `native-dev` ya soporta localmente `tool { filter: value }` dentro del parser estructural compartido para valores ident-like de un solo token, propagando `tool.filter_expr` al IR sintetizado sin abrir validaciones nuevas
- Entran efectivamente en el path local: `tool.filter` ident-like valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se eligio este corte porque reutiliza el carril estructural de valores simples y mantiene fuera la forma parser-side `filter(...)`; `tool.effects` sigue siendo mayor por parseo dedicado y validacion semantica de effect rows
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `339 passed`
- La siguiente sesion ya puede ejecutar B115 para decidir si conviene abrir `tool.filter(...)`, comparar `tool.effects` contra otro frente, o salir del frontier `tool` hacia otra parte del frontend

### Sesion B115

- Version interna objetivo: `v0.30.6-internal.b.115.1`
- Estado: `validated`
- Objetivo: extender el corte de `tool.filter` para cubrir tambien la forma parser-side `filter(...)`
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { filter: recent(days: 30) }` y compactar esa expresion al mismo `filter_expr` observable que Python
  - permitir exito nativo local para programas estructurales soportados con `tool.filter(...)` prefijado antes de `flow + run`
  - reproducir localmente el diagnostico canonico `Duplicate declaration ...` para tools duplicados por nombre cuando usan `filter(...)`
  - mantener fuera `tool.effects` y otras rutas con parseo o validacion estructural mayor
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.filter(...)` dentro del frente estructural compartido

### Resultado de B115

- Decision implementada: `native-dev` ya soporta localmente `tool { filter: recent(...) }` dentro del parser estructural compartido, compactando la expresion al mismo `filter_expr` observable que Python, por ejemplo `recent(days:30)`
- Entran efectivamente en el path local: `tool.filter(...)` valido en programas estructurales soportados con `flow + run` y duplicados de `tool` que acumulan el diagnostico canonico `Duplicate declaration ...`; el caso `Undefined flow ...` ya estaba cubierto localmente por el subset prefijado compartido
- Implementacion: se eligio este corte porque solo exigia una helper parser-side acotada para capturar tokens hasta `)` y cerrar en `}`; `tool.effects` sigue siendo mayor porque conserva parseo dedicado y validacion semantica propia
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `343 passed`
- La siguiente sesion ya puede ejecutar B116 para decidir si conviene abrir `tool.effects` o salir del frontier `tool` hacia otra parte del frontend

### Sesion B116

- Version interna objetivo: `v0.30.6-internal.b.116.1`
- Estado: `validated`
- Objetivo: abrir `tool.effects` como siguiente corte acotado, reproduciendo el shape de IR y la validacion semantica observable de Python
- Alcance:
  - extender el parser estructural local para reconocer `tool Name { effects: <network, epistemic:know> }`
  - permitir exito nativo local para programas estructurales soportados con `tool.effects` prefijado antes de `flow + run`
  - reproducir localmente los diagnosticos `Unknown effect ...` y `Unknown epistemic level ...`, incluyendo su acumulacion con `Duplicate declaration ...` y `Undefined flow ...`
  - mantener fuera otros fields de `tool` con una superficie parser-side o semantica todavia mayor
- Criterio de terminado:
  - `native-dev` deja de delegar en Python para el corte acotado de `tool.effects` dentro del frente estructural compartido

### Resultado de B116

- Decision implementada: `native-dev` ya soporta localmente `tool { effects: <...> }` dentro del parser estructural compartido, propagando `effect_row` con el mismo shape observable que Python y reproduciendo la validacion local de effect rows
- Entran efectivamente en el path local: `tool.effects` valido en programas estructurales soportados con `flow + run`, el diagnostico `Unknown effect ...`, el diagnostico `Unknown epistemic level ...`, su acumulacion con `Undefined flow ...`, y duplicados de `tool` que mantienen el orden observable `Duplicate declaration ...` seguido por la validacion semantica
- Implementacion: se eligio este corte porque, aunque mas caro que `filter`, seguia siendo un frente delimitado de parser mas validacion; la captura local construye `effect_row` como tupla de strings igual que Python, incluyendo `epistemic:<level>` al final
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `350 passed`
- La siguiente sesion ya puede ejecutar B117 para decidir si conviene seguir dentro de `tool` con fields mas caros como `input_schema` o `output_schema`, o salir a otra parte del frontend

### Sesion B117

- Version interna objetivo: `v0.30.6-internal.b.117.1`
- Estado: `validated`
- Objetivo: decidir si convenia seguir dentro del frontier `tool` y abrir el siguiente corte pequeno real de `native-dev` post-B116
- Alcance:
  - re-caracterizar el frontier post-B116 y verificar si `tool.input_schema` u `tool.output_schema` existian realmente en la semantica observable del parser Python actual
  - si `tool` ya no ofrecia un corte pequeno honesto, abrir el siguiente hueco real del matcher estructural compartido fuera de `tool`
  - mantener el contrato congelado y no inventar shape de IR o diagnosticos que Python no expone hoy
- Criterio de terminado:
  - `native-dev` cubre localmente un nuevo corte pequeno y verificable posterior a B116, con evidencia de por que ese corte es preferible al siguiente candidato dentro de `tool`

### Resultado de B117

- Decision implementada: se cierra operativamente el frontier `tool` para este tramo de Fase B y se sale a `intent`, porque `tool.input_schema` y `tool.output_schema` no forman parte de la semantica observable del parser, type checker e IR Python actuales; el siguiente corte real y pequeno era `intent { ask: "..." }`
- Entra efectivamente en el path local: `intent.ask` valido en programas estructurales soportados con `flow + run`, incluyendo conteo de declaraciones compatible con Python y duplicate declarations por nombre `intent`; el IR observable se mantiene igual que Python, es decir, el `IRProgram` compilado no introduce una coleccion nueva de intents
- Implementacion: `native-dev` ya reconoce localmente `intent Name { ask: "..." }`, lo cuenta como declaracion estructural soportada y reproduce `Duplicate declaration: '...' already defined as intent ...`; `intent.given` y `intent.confidence_floor` siguen fuera porque abren validaciones o combinaciones de campos adicionales
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `354 passed`
- La siguiente sesion ya puede ejecutar B118 para decidir si conviene profundizar `intent` con `given` o `confidence_floor`, o salir hacia otro kind con mejor relacion costo/valor

### Sesion B118

- Version interna objetivo: `v0.30.6-internal.b.118.1`
- Estado: `validated`
- Objetivo: profundizar `intent` con el siguiente corte pequeno de exito real sin abrir todavia validaciones de rango ni parseo de `type_expr`
- Alcance:
  - comparar `intent.given`, `intent.confidence_floor` y `intent.output` contra el comportamiento observable Python y elegir el frente mas pequeno y honesto
  - abrir solo la forma acotada `intent { given: X ask: "..." }`, preservando el mismo `IRProgram` observable que Python
  - mantener fuera `intent.output` y `intent.confidence_floor` mientras exijan parseo o validacion adicional
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y duplicate declarations del corte parser-side acotado `intent.given + ask`

### Resultado de B118

- Decision implementada: `native-dev` ya soporta localmente la forma acotada `intent { given: X ask: "..." }` y su orden alterno `intent { ask: "..." given: X }`, porque era el siguiente corte de exito real mas barato dentro de `intent`; `confidence_floor` y `output` siguen fuera
- Entra efectivamente en el path local: `intent.given + ask` valido en programas estructurales soportados con `flow + run`, incluyendo duplicate declarations por nombre `intent`; se mantiene el mismo IR observable que Python, sin materializar intents top-level en `IRProgram`
- Implementacion: se agrego una helper parser-side acotada para exactamente dos fields `given` y `ask` en cualquier orden, requiriendo `IDENTIFIER` para `given` y `STRING` para `ask`; `intent.output` sigue delegado y funciona como boundary para no abrir `type_expr`
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `358 passed`
- La siguiente sesion ya puede ejecutar B119 para decidir si conviene profundizar `intent` con `confidence_floor`, abrir `intent.output`, o salir a otro kind con mejor relacion costo/valor

### Sesion B119

- Version interna objetivo: `v0.30.6-internal.b.119.1`
- Estado: `validated`
- Objetivo: profundizar `intent` con el siguiente corte pequeno que agregara validacion real sin abrir todavia parseo de `type_expr`
- Alcance:
  - comparar `intent.confidence_floor` frente a `intent.output` y elegir el corte mas pequeno y honesto segun la semantica observable Python
  - abrir solo la forma acotada `intent { ask: "..." confidence_floor: N }` en cualquier orden dentro de programas estructurales soportados con `flow + run`
  - reproducir localmente el diagnostico canonico de rango de `confidence_floor` y su acumulacion con `Undefined flow ...` y duplicate declarations de `intent`
  - mantener fuera `intent.output` para no abrir todavia parseo de `type_expr` ni validacion de referencias de tipo
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, la validacion de rango y duplicate declarations del corte parser-side acotado `intent.ask + confidence_floor`

### Resultado de B119

- Decision implementada: `native-dev` ya soporta localmente la forma acotada `intent { ask: "..." confidence_floor: N }` y su orden alterno, porque era el siguiente corte menor dentro de `intent`; `intent.output` sigue fuera por requerir `type_expr`
- Entra efectivamente en el path local: `intent.ask + confidence_floor` en programas estructurales soportados con `flow + run`, incluyendo exito, diagnostico local `confidence_floor must be between 0.0 and 1.0, got ...`, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`; se mantiene el mismo IR observable que Python, sin materializar intents top-level en `IRProgram`
- Implementacion: se agrego una helper parser-side acotada para exactamente dos fields `ask` y `confidence_floor` en cualquier orden, se conecto validacion local de rango con el mismo mensaje canonico de Python y se extendieron los success/validation matchers para rechazar valores fuera de rango sin delegar
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `364 passed`
- La siguiente sesion ya puede ejecutar B120 para decidir si conviene abrir `intent.output` o salir de `intent` hacia otro kind con mejor relacion costo/valor

### Sesion B120

- Version interna objetivo: `v0.30.6-internal.b.120.1`
- Estado: `validated`
- Objetivo: priorizar valor observable del `compile` y abrir el siguiente corte acotado que si cambie el JSON top-level generado por `native-dev`
- Alcance:
  - recomparar `intent.output` frente a salir de `intent` con criterio de valor observable, no solo costo parser-side
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName }` en cualquier orden dentro de programas estructurales soportados con `flow + run`
  - reproducir localmente el diagnostico canonico de metodo HTTP invalido, path invalido, referencia de `execute` a flow inexistente y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `endpoints` en el `IRProgram` compilado para este corte observable
  - mantener fuera `body`, `output`, `shield`, `retries` y `timeout` para no abrir todavia chequeos o parseo adicionales de endpoint
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, la validacion y duplicate declarations del corte parser-side acotado `axonendpoint.method + path + execute`

### Resultado de B120

- Decision implementada: se priorizo valor observable sobre costo parser-side y se salio de `intent` hacia `axonendpoint`, porque `intent.output` apenas afecta semantica interna mientras que `axonendpoint` si aparece en el JSON compilado top-level
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName }` en cualquier orden para programas estructurales soportados con `flow + run`, incluyendo exito con `endpoints` en `IRProgram`, diagnostico local `Unknown HTTP method ...`, `path must start with '/' ...`, acumulacion con `Undefined flow ...` via `execute`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente tres fields `method`, `path` y `execute`; `method` se normaliza a uppercase igual que Python y el assembler local ahora materializa `endpoints` en `IRProgram`; `output`, `shield`, `body`, `retries` y `timeout` siguen delegados como boundary explicito
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `371 passed`

### Resultado de B121

- Decision implementada: se volvio a `intent.output` porque AXON debe mantenerse epistemico, cognitivo y semantico; bajo esa lectura, y con `lambda` como norte interno, el siguiente corte honesto ya no era otro field observable de `axonendpoint` sino la continuidad tipada dentro de `intent`
- Entra efectivamente en el path local: `intent { ask: "..." output: TypeExpr }` en cualquier orden para programas estructurales soportados, incluyendo exito, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
- Implementacion: se agrego parseo local acotado de `type_expr` para `IDENTIFIER`, `IDENTIFIER<IDENTIFIER>` y sufijo opcional `?`, alineado con la semantica Python actual donde las referencias de tipo no resueltas siguen siendo soft; `lambda` no reemplaza todavia esa representacion interna, pero si redefine como debe compararse el siguiente frente para preservar la identidad epistemica/cognitiva/semantica del lenguaje
- Boundary explicito: `intent { given + ask + output }`, `intent { ask + output + confidence_floor }` y formas mas ricas siguen delegadas; tambien siguen fuera `axonendpoint.output` y `axonendpoint.shield` mientras no se decida reabrir la frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `376 passed`
- La siguiente sesion ya debe ejecutar B122: abrir el corte interno `intent { ask + output + confidence_floor }` en cualquier orden como siguiente crecimiento de mayor valor, porque conserva continuidad con B119 y B121, refuerza la dimension epistemica del `intent`, y mantiene a `axonendpoint.output` y `axonendpoint.shield` como boundary delegado hasta que la frontera operativa externa se consolide explicitamente

### Sesion B122

- Version interna objetivo: `v0.30.6-internal.b.122.1`
- Estado: `validated`
- Objetivo: profundizar la frontera semantica interna de `intent` combinando salida tipada y control epistemico en un mismo corte acotado
- Alcance:
  - abrir solo la forma acotada `intent { ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion canonica de rango para `confidence_floor`, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
  - reutilizar el parseo local ya abierto para `type_expr` y la validacion local ya abierta para `confidence_floor`, sin ampliar referencias de tipo duras
  - mantener fuera `intent { given + ask + output }` y formas mas ricas que mezclen varias ramas parser-side adicionales
  - mantener `axonendpoint.output` y `axonendpoint.shield` como boundary delegado mientras no se reabra la frontera operativa externa
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, la validacion y duplicate declarations del corte parser-side acotado `intent.ask + output + confidence_floor`

### Resultado de B122

- Decision implementada: se profundizo el carril interno de `intent` en lugar de reabrir todavia `axonendpoint`, porque combinar `output` y `confidence_floor` preserva mejor la continuidad epistemica, cognitiva y semantica de AXON
- Entra efectivamente en el path local: `intent { ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden para programas estructurales soportados, incluyendo exito, diagnostico local `confidence_floor must be between 0.0 and 1.0, got ...`, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
- Implementacion: se agrego una helper parser-side acotada para exactamente tres fields `ask`, `output` y `confidence_floor`, reutilizando el parseo local de `type_expr` abierto en B121 y la validacion local de rango abierta en B119, sin abrir referencias de tipo duras ni materializar intents top-level en `IRProgram`
- Boundary explicito: `intent { given + ask + output }` y formas mas ricas de `intent` siguen delegadas; `axonendpoint.output` y `axonendpoint.shield` siguen fuera mientras no se reabra la frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `381 passed`
- La siguiente sesion ya debe ejecutar B123: abrir el corte interno `intent { given + ask + output }` en cualquier orden como siguiente crecimiento de mayor valor, porque combina dos ramas ya abiertas dentro de `intent` con menos superficie que reabrir transporte externo en `axonendpoint`

### Sesion B123

- Version interna objetivo: `v0.30.6-internal.b.123.1`
- Estado: `validated`
- Objetivo: profundizar la frontera semantica interna de `intent` integrando el contexto cognitivo `given` con la salida tipada en un mismo corte acotado
- Alcance:
  - abrir solo la forma acotada `intent { given: Type ask: "..." output: TypeExpr }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
  - reutilizar el parseo local ya abierto para `given` como `IDENTIFIER` y para `type_expr`, sin ampliar referencias de tipo duras ni validaciones nuevas
  - mantener fuera `intent { given + ask + output + confidence_floor }` y formas mas ricas que mezclen varias ramas parser-side adicionales
  - mantener `axonendpoint.output` y `axonendpoint.shield` como boundary delegado mientras no se reabra la frontera operativa externa
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, undefined-flow y duplicate declarations del corte parser-side acotado `intent.given + ask + output`

### Resultado de B123

- Decision implementada: se siguio profundizando el carril interno de `intent` en lugar de reabrir todavia `axonendpoint`, porque `given + ask + output` combina dos ramas ya abiertas con menor superficie que `axonendpoint.output` o `axonendpoint.shield`
- Entra efectivamente en el path local: `intent { given: Document ask: "..." output: TypeExpr }` en cualquier orden para programas estructurales soportados, incluyendo exito, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
- Implementacion: se agrego una helper parser-side acotada para exactamente tres fields `given`, `ask` y `output`, reutilizando el parseo local de `given` abierto en B118 y el parseo local de `type_expr` abierto en B121, sin introducir validacion nueva ni materializar intents top-level en `IRProgram`
- Boundary explicito: `intent { given + ask + output + confidence_floor }` y formas mas ricas de `intent` siguen delegadas; `axonendpoint.output` y `axonendpoint.shield` siguen fuera mientras no se reabra la frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `386 passed`
- La siguiente sesion ya debe ejecutar B124: abrir el corte interno `intent { given + ask + output + confidence_floor }` en cualquier orden como siguiente crecimiento de mayor valor, porque combina tres ramas ya abiertas dentro de `intent` con menos superficie que reabrir transporte externo en `axonendpoint`

### Sesion B124

- Version interna objetivo: `v0.30.6-internal.b.124.1`
- Estado: `validated`
- Objetivo: profundizar la frontera semantica interna de `intent` integrando el contexto cognitivo `given`, la salida tipada y el control epistemico en un mismo corte acotado
- Alcance:
  - abrir solo la forma acotada `intent { given: Type ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion canonica de rango para `confidence_floor`, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
  - reutilizar el parseo local ya abierto para `given` como `IDENTIFIER`, para `type_expr` y para la validacion local de `confidence_floor`, sin ampliar referencias de tipo duras
  - mantener fuera formas mas ricas de `intent` que mezclen varias ramas parser-side adicionales
  - mantener `axonendpoint.output` y `axonendpoint.shield` como boundary delegado mientras no se reabra la frontera operativa externa
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, la validacion y duplicate declarations del corte parser-side acotado `intent.given + ask + output + confidence_floor`

### Resultado de B124

- Decision implementada: se siguio profundizando el carril interno de `intent` en lugar de reabrir todavia `axonendpoint`, porque `given + ask + output + confidence_floor` combina tres ramas ya abiertas con menor superficie que `axonendpoint.output` o `axonendpoint.shield`
- Entra efectivamente en el path local: `intent { given: Document ask: "..." output: TypeExpr confidence_floor: N }` en cualquier orden para programas estructurales soportados, incluyendo exito, diagnostico local `confidence_floor must be between 0.0 and 1.0, got ...`, acumulacion con `Undefined flow ...` y duplicate declarations por nombre `intent`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `given`, `ask`, `output` y `confidence_floor`, reutilizando el parseo local de `given` abierto en B118, el parseo local de `type_expr` abierto en B121 y la validacion local de rango abierta en B119, sin introducir transporte externo ni materializar intents top-level en `IRProgram`
- Boundary explicito: `axonendpoint.output` y `axonendpoint.shield` siguen fuera mientras no se reabra la frontera operativa externa; las formas mas ricas de `intent` siguen delegadas
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `391 passed`
- La siguiente sesion ya debe ejecutar B125: abrir `axonendpoint.output` como siguiente corte de mayor valor, porque reabre la frontera operativa externa con menor superficie que `axonendpoint.shield`

### Sesion B125

- Version interna objetivo: `v0.30.6-internal.b.125.1`
- Estado: `validated`
- Objetivo: reabrir de forma controlada la frontera operativa externa de `axonendpoint` mediante el field `output`, manteniendo `shield` todavia delegado
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type` en `IREndpoint` y en el JSON compilado observable
  - reutilizar las validaciones locales ya abiertas para `method`, `path` y `execute`, sin introducir validacion nueva para `output_type` porque sigue siendo referencia soft en Python
  - mantener `axonendpoint.shield` como boundary delegado mientras no se reabra la siguiente pieza de la frontera operativa externa
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito, undefined-flow y duplicate declarations del corte parser-side acotado `axonendpoint.method + path + execute + output`

### Resultado de B125

- Decision implementada: se reabrio la frontera operativa externa por `axonendpoint.output`, no por `axonendpoint.shield`, porque `output_type` es el corte menor y mas honesto: agrega superficie observable en compile sin introducir la validacion dura de referencias `shield`
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `method`, `path`, `execute` y `output`, reutilizando las validaciones locales ya abiertas para endpoint y materializando `output_type` en el IR local sin introducir validacion nueva adicional
- Boundary explicito: `axonendpoint.shield` sigue delegado como siguiente comparacion honesta de frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -q` -> `396 passed`
- La siguiente sesion ya debe definir B126: comparar si el siguiente corte de mayor valor debe abrir `axonendpoint.shield`, o si existe otro corte alternativo con mejor relacion costo/valor

### Sesion B126

- Version interna objetivo: `v0.30.6-internal.b.126.1`
- Estado: `validated`
- Objetivo: reabrir la siguiente pieza minima de la frontera operativa externa mediante `axonendpoint.shield`, sosteniendola con la declaracion top-level minima necesaria de `shield`
- Alcance:
  - abrir solo la declaracion estructural minima `shield Name { }` para soportar simbolos `shield` reales en el path local
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, `axonendpoint ... references undefined shield ...`, diagnostico `is a X, not a shield`, y duplicate declarations por nombre `shield`
  - materializar localmente `shields` en `IRProgram` y `shield_ref` en `IREndpoint`
  - mantener fuera `axonendpoint { ... output + shield }`, `body`, `retries` y `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y las validaciones duras del corte parser-side acotado `shield { }` + `axonendpoint.method + path + execute + shield`

### Resultado de B126

- Decision implementada: se abrio `axonendpoint.shield` porque, una vez cerrado B125, ya era la siguiente pieza minima honesta de la frontera operativa externa y exigia exactamente un soporte adicional minimo: declarar `shield` top-level en su forma vacia canonica
- Entra efectivamente en el path local: `shield Name { }` y `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `shields` en `IRProgram`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnostico duro `axonendpoint 'Name' references undefined shield 'ShieldName'`, diagnostico de kind mismatch `'<Name>' is a <kind>, not a shield`, y duplicate declarations por nombre `shield`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `method`, `path`, `execute` y `shield`, junto con el cableado estructural minimo para registrar `shield Name { }` en el escaneo local, validarlo como simbolo disponible y materializarlo en el `IRProgram`
- Boundary explicito: `axonendpoint { ... output + shield }`, `body`, `retries` y `timeout` siguen fuera como siguiente comparacion honesta de frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py -k "shield or flow_prefixed_run_"` -> `5 passed`; `pytest tests/test_cli.py -k "axonendpoint_shield_paths"` -> `2 passed`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `403 passed`
- La siguiente sesion ya debe definir B127: comparar si el siguiente corte de mayor valor debe componer `axonendpoint.output + shield`, o si existe un corte alternativo mas pequeno como `axonendpoint.body`

### Sesion B127

- Version interna objetivo: `v0.30.6-internal.b.127.1`
- Estado: `validated`
- Objetivo: abrir la siguiente pieza minima y honesta de la frontera operativa externa mediante `axonendpoint.body`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: TypeName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type` en `IREndpoint` y en el JSON compilado
  - mantener fuera `axonendpoint { ... output + shield }`, `retries` y `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body`

### Resultado de B127

- Decision implementada: se abrio `axonendpoint.body` porque la revision previa del IR y del checker Python mostro que era el siguiente corte externo realmente menor frente a componer `output + shield`: `body_type` ya existia en AST, IR y lowering, y su semantica observable en Python es solo referencia de tipo blanda
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: TypeName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `method`, `path`, `execute` y `body`, reutilizando el mismo patron de B125 sin introducir validacion nueva adicional porque `body` ya existia como field del endpoint y su chequeo Python es blando
- Boundary explicito: `axonendpoint { ... output + shield }`, `retries` y `timeout` siguen fuera como siguiente comparacion honesta de frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py -k "endpoint_with_body or duplicate_axonendpoint_with_body"` -> `3 passed`; `pytest tests/test_cli.py -k "axonendpoint_body_paths"` -> `2 passed`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `408 passed`
- La siguiente sesion ya debe definir B128: comparar si el siguiente corte de mayor valor debe componer `axonendpoint.output + shield`, o si existe un corte alternativo realmente menor dentro de `retries` o `timeout`

### Sesion B128

- Version interna objetivo: `v0.30.6-internal.b.128.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.output + shield` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName shield: ShieldName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, diagnostico duro `axonendpoint ... references undefined shield ...`, diagnostico `is a X, not a shield`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type` y `shield_ref` en `IREndpoint`
  - mantener fuera `retries` y `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + shield`

### Resultado de B128

- Decision implementada: se abrio `axonendpoint.output + shield` porque, tras B127, era la siguiente composicion operativa de mayor valor ya preparada por AST, IR y checker Python; frente a eso, `retries` y `timeout` eran cortes menores en superficie pero tambien menores en valor semantico inmediato
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: TypeName shield: ShieldName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type` y `shield_ref` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnostico duro `axonendpoint 'Name' references undefined shield 'ShieldName'`, diagnostico de kind mismatch `'<Name>' is a <kind>, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `output` y `shield`, reutilizando las validaciones ya abiertas en B125 y B126 sin introducir reglas conjuntas nuevas entre ambos fields
- Boundary explicito: `retries` y `timeout` siguen fuera como siguiente comparacion honesta de frontera operativa externa
- Validacion: `pytest tests/test_frontend_facade.py -k "output_and_shield or duplicate_axonendpoint_with_output_and_shield"` -> `3 passed`; `pytest tests/test_cli.py -k "axonendpoint_output_shield_paths"` -> `2 passed`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `415 passed`
- La siguiente sesion ya debe definir B129: comparar si el siguiente corte realmente menor del endpoint debe ser `axonendpoint.retries` o `axonendpoint.timeout`

### Sesion B129

- Version interna objetivo: `v0.30.6-internal.b.129.1`
- Estado: `validated`
- Objetivo: abrir la pieza minima restante del endpoint mediante `axonendpoint.timeout`, dejando `retries` todavia fuera por su validacion dura
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `timeout` en `IREndpoint` y en el JSON compilado, aceptando `DURATION` e identifier-like sin validacion endpoint nueva
  - mantener fuera `retries`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + timeout`

### Resultado de B129

- Decision implementada: se abrio `axonendpoint.timeout` porque, entre los knobs endpoint restantes, era el corte realmente menor y mas honesto: ya existia como shape observable en AST/parser/IR y no exigia validacion dura local, mientras que `retries` sigue requiriendo reproducir la regla numerica `>= 0`
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `method`, `path`, `execute` y `timeout`, reutilizando el endpoint local ya abierto y aceptando tanto `DURATION` como valores identifier-like para mantenerse alineado con el parser Python sin introducir validacion adicional
- Boundary explicito: `retries` sigue fuera como siguiente corte honesto de frontera operativa externa, porque todavia abre validacion numerica local
- Validacion: `pytest tests/test_frontend_facade.py -k "axonendpoint_with_timeout or duplicate_axonendpoint_with_timeout"` -> `3 passed`; `pytest tests/test_cli.py -k "axonendpoint_timeout_paths"` -> `2 passed`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `420 passed`
- La siguiente sesion ya debe definir B130: abrir `axonendpoint.retries` con su validacion numerica local `>= 0`

### Sesion B130

- Version interna objetivo: `v0.30.6-internal.b.130.1`
- Estado: `validated`
- Objetivo: abrir el ultimo knob atomico restante del endpoint mediante `axonendpoint.retries`, reproduciendo localmente su validacion numerica `>= 0`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `timeout`, `body`, `output` o `shield`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + retries`

### Resultado de B130

- Decision implementada: se abrio `axonendpoint.retries` porque, tras B129, era el siguiente corte endpoint realmente necesario y ya no quedaba otro field atomico menor; ademas, el checker Python ya fijaba con precision la validacion observable `retries >= 0`
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `retries` en `IREndpoint`, diagnostico `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cuatro fields `method`, `path`, `execute` y `retries`, mas el diagnostico local de positividad no negativa, manteniendo el orden observable de errores frente a `undefined flow` y duplicates
- Boundary explicito: las composiciones nuevas como `retries + timeout` siguen fuera hasta decidir si la linea endpoint debe continuar o cerrarse temporalmente
- Validacion: `pytest tests/test_frontend_facade.py -k "axonendpoint_with_retries or duplicate_axonendpoint_with_invalid_retries or invalid_retries"` -> `4 passed`; `pytest tests/test_cli.py -k "axonendpoint_retries_paths"` -> `2 passed`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `426 passed`
- La siguiente sesion ya debe definir B131: comparar si conviene abrir la composicion `axonendpoint { ... retries + timeout }` o cerrar temporalmente la linea endpoint

### Sesion B131

- Version interna objetivo: `v0.30.6-internal.b.131.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.retries + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName retries: N timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `retries` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `body`, `output` o `shield`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + retries + timeout`

### Resultado de B131

- Decision implementada: se abrio `axonendpoint.retries + timeout` porque, una vez abiertos ambos knobs por separado, su composicion era el siguiente corte endpoint de menor costo incremental y mayor continuidad operativa; pausar la linea aqui habria dejado abierta una pareja ya claramente preparada por AST, parser, IR y checker Python
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName retries: N timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `retries` y `timeout` en `IREndpoint`, diagnostico `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `retries` y `timeout`, reutilizando la validacion local ya abierta de `retries` y el shape observable ya abierto de `timeout` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `body`, `output` o `shield` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "retries_and_timeout or invalid_retries_and_timeout or duplicate_axonendpoint_with_invalid_retries_and_timeout"` -> `3 passed, 207 deselected`; `pytest tests/test_cli.py -k "axonendpoint_retries_timeout_paths"` -> `2 passed, 210 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `431 passed in 200.77s`
- La siguiente sesion ya debe definir B132: comparar si conviene abrir la composicion `axonendpoint { ... body + output }` o cerrar temporalmente la linea endpoint

### Sesion B132

- Version interna objetivo: `v0.30.6-internal.b.132.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.body + output` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type` y `output_type` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `shield`, `retries` o `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + output`

### Resultado de B132

- Decision implementada: se abrio `axonendpoint.body + output` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico y mayor continuidad sobre el payload observable del endpoint; pausar la linea aqui habria dejado sin cerrar la pareja mas natural de request/response ya preparada por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type` y `output_type` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `body` y `output`, reutilizando los shapes suaves ya abiertos de ambos fields sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `shield`, `retries` o `timeout` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_output or duplicate_axonendpoint_with_body_and_output or body_output_missing_flow"` -> `3 passed, 210 deselected`; `pytest tests/test_cli.py -k "axonendpoint_body_output_paths"` -> `2 passed, 212 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `436 passed in 195.95s`
- La siguiente sesion ya debe definir B133: comparar si conviene abrir la composicion `axonendpoint { ... body + shield }` o cerrar temporalmente la linea endpoint

### Sesion B133

- Version interna objetivo: `v0.30.6-internal.b.133.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.body + shield` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, diagnostico duro `axonendpoint ... references undefined shield ...`, diagnostico `is a X, not a shield`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type` y `shield_ref` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `output`, `retries` o `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + shield`

### Resultado de B133

- Decision implementada: se abrio `axonendpoint.body + shield` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que incorporaba una referencia dura de politica sobre un payload ya abierto; pausar la linea aqui habria dejado sin cerrar un cruce ya claramente preparado por AST, parser, IR y chequeos de simbolos
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type` y `shield_ref` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnostico duro `axonendpoint 'Name' references undefined shield 'ShieldName'`, diagnostico de kind mismatch `'<Name>' is a <kind>, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `body` y `shield`, reutilizando el field suave ya abierto y las validaciones duras ya abiertas de `shield` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `output`, `retries` o `timeout` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_shield or body_and_undefined_shield or body_and_not_a_shield or duplicate_axonendpoint_with_body_and_shield"` -> `5 passed, 213 deselected`; `pytest tests/test_cli.py -k "axonendpoint_body_shield_paths"` -> `2 passed, 214 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `443 passed in 198.32s`
- La siguiente sesion ya debe definir B134: comparar si conviene abrir la composicion `axonendpoint { ... output + timeout }` o cerrar temporalmente la linea endpoint

### Sesion B134

- Version interna objetivo: `v0.30.6-internal.b.134.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.output + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `body`, `shield` o `retries`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + timeout`

### Resultado de B134

- Decision implementada: se abrio `axonendpoint.output + timeout` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que agregaba valor observable sin validacion dura nueva; pausar la linea aqui habria dejado sin cerrar un cruce ya claramente preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `output` y `timeout`, reutilizando el field suave ya abierto y el shape observable ya abierto de `timeout` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `body`, `shield` o `retries` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "output_and_timeout or duplicate_axonendpoint_with_output_and_timeout or output_timeout_missing_flow"` -> `3 passed, 218 deselected`; `pytest tests/test_cli.py -k "axonendpoint_output_timeout_paths"` -> `2 passed, 216 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `448 passed in 205.94s`
- La siguiente sesion ya debe definir B135: comparar si conviene abrir la composicion `axonendpoint { ... body + timeout }` o cerrar temporalmente la linea endpoint

### Sesion B135

- Version interna objetivo: `v0.30.6-internal.b.135.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.body + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `output`, `shield` o `retries`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + timeout`

### Resultado de B135

- Decision implementada: se abrio `axonendpoint.body + timeout` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que agregaba valor observable sin validacion dura nueva; pausar la linea aqui habria dejado sin cerrar un cruce ya claramente preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `body` y `timeout`, reutilizando el field suave ya abierto y el shape observable ya abierto de `timeout` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `output`, `shield` o `retries` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_timeout or duplicate_axonendpoint_with_body_and_timeout or body_timeout_missing_flow"` -> `3 passed, 221 deselected`; `pytest tests/test_cli.py -k "axonendpoint_body_timeout_paths"` -> `2 passed, 218 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `453 passed in 237.70s`
- La siguiente sesion ya debe definir B136: comparar si conviene abrir la composicion `axonendpoint { ... output + retries }` o cerrar temporalmente la linea endpoint

### Sesion B136

- Version interna objetivo: `v0.30.6-internal.b.136.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.output + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, validacion local `retries >= 0`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `body`, `shield` o `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + retries`

### Resultado de B136

- Decision implementada: se abrio `axonendpoint.output + retries` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que agregaba valor observable reutilizando una validacion local ya absorbida; pausar la linea aqui habria dejado sin cerrar un cruce ya preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type` y `retries` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, validacion local `Endpoint 'Name' retries must be >= 0`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `output` y `retries`, reutilizando el field suave ya abierto y la validacion observable ya abierta de `retries` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `body`, `shield` o `timeout` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "output_and_retries or output_and_invalid_retries or duplicate_axonendpoint_with_output_and_invalid_retries"` -> `4 passed, 224 deselected`; `pytest tests/test_cli.py -k "axonendpoint_output_retries_paths"` -> `2 passed, 220 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `459 passed in 209.75s`
- La siguiente sesion ya debe definir B137: comparar si conviene abrir la composicion `axonendpoint { ... body + retries }` o cerrar temporalmente la linea endpoint

### Sesion B137

- Version interna objetivo: `v0.30.6-internal.b.137.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.body + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, validacion local `retries >= 0`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `output`, `shield` o `timeout`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + retries`

### Resultado de B137

- Decision implementada: se abrio `axonendpoint.body + retries` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que agregaba valor observable reutilizando una validacion local ya absorbida; pausar la linea aqui habria dejado sin cerrar un cruce ya preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type` y `retries` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, validacion local `Endpoint 'Name' retries must be >= 0`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `body` y `retries`, reutilizando el field suave ya abierto y la validacion observable ya abierta de `retries` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `output`, `shield` o `timeout` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_retries"` -> `1 passed, 231 deselected`; `pytest tests/test_frontend_facade.py -k "body_and_invalid_retries or duplicate_axonendpoint_with_body_and_invalid_retries"` -> `3 passed, 229 deselected`; `pytest tests/test_cli.py -k "axonendpoint_body_retries_paths"` -> `2 passed, 222 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `465 passed in 207.55s`
- La siguiente sesion ya debe definir B138: comparar si conviene abrir la composicion `axonendpoint { ... shield + timeout }` o cerrar temporalmente la linea endpoint

### Sesion B138

- Version interna objetivo: `v0.30.6-internal.b.138.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.shield + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `shield_ref` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones nuevas con `body`, `output` o `retries`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + shield + timeout`

### Resultado de B138

- Decision implementada: se abrio `axonendpoint.shield + timeout` porque, una vez abiertos ambos fields por separado, su composicion era el siguiente corte endpoint de menor costo semantico que agregaba valor observable sin introducir validacion dura nueva; pausar la linea aqui habria dejado sin cerrar un cruce ya preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `shield_ref` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Name' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `shield` y `timeout`, reutilizando la referencia ya abierta de `shield` y el shape observable ya abierto de `timeout` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que mezclen este par con `body`, `output` o `retries` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "shield_and_timeout_success or shield_and_timeout_undefined_flow or shield_and_timeout_undefined_shield or shield_and_timeout_not_a_shield or duplicate_axonendpoint_with_shield_and_timeout"` -> `5 passed, 232 deselected`; `pytest tests/test_cli.py -k "axonendpoint_shield_timeout_paths"` -> `2 passed, 224 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `472 passed in 449.70s`
- La siguiente sesion ya debe definir B139: comparar si conviene abrir la composicion `axonendpoint { ... shield + retries }` o cerrar temporalmente la linea endpoint

### Sesion B139

- Version interna objetivo: `v0.30.6-internal.b.139.1`
- Estado: `validated`
- Objetivo: abrir la composicion operativa minima `axonendpoint.shield + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, validacion local `retries >= 0`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `shield_ref` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones ternarias del endpoint mientras no exista una justificacion honesta de frontera
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + shield + retries`

### Resultado de B139

- Decision implementada: se abrio `axonendpoint.shield + retries` porque, una vez abiertos ambos fields por separado, su composicion era el ultimo corte endpoint binario de menor costo semantico que agregaba valor observable reutilizando validaciones ya absorbidas; pausar la linea aqui habria dejado incompleta la malla binaria del endpoint ya preparada por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName shield: ShieldName retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `shield_ref` y `retries` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Name' is a anchor, not a shield`, validacion local `Endpoint 'Name' retries must be >= 0`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente cinco fields `method`, `path`, `execute`, `shield` y `retries`, reutilizando la referencia ya abierta de `shield` y la validacion observable ya abierta de `retries` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones de tres fields del endpoint siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "shield_and_retries or shield_and_invalid_retries or duplicate_axonendpoint_with_shield_and_invalid_retries"` -> `6 passed, 237 deselected`; `pytest tests/test_cli.py -k "shield_retries_paths"` -> `2 passed, 226 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `480 passed in 405.23s`
- La siguiente sesion ya debe definir B140: comparar si conviene pausar la linea endpoint ahora que la malla binaria ya esta completa, o si existe justificacion real para abrir una primera composicion ternaria acotada

### Sesion B140

- Version interna objetivo: `v0.30.6-internal.b.140.1`
- Estado: `validated`
- Objetivo: abrir la primera composicion ternaria minima `axonendpoint.body + output + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `output_type` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera ternarios que introduzcan `shield` o `retries`, y composiciones aun mas anchas
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + output + timeout`

### Resultado de B140

- Decision implementada: se abrio `axonendpoint.body + output + timeout` porque, una vez cerrada la malla binaria del endpoint, era el primer ternario de menor costo semantico: combina solo fields suaves ya abiertos y evita todavia referencia de politica o validacion dura; pausar la linea aqui habria cortado justo antes del triangulo suave mas preparado por AST, parser e IR
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `output_type` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente seis fields `method`, `path`, `execute`, `body`, `output` y `timeout`, reutilizando tres fields suaves ya abiertos sin introducir reglas conjuntas adicionales
- Boundary explicito: ternarios con `shield` o `retries` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_output_and_timeout"` -> `3 passed, 243 deselected`; `pytest tests/test_cli.py -k "body_output_timeout_paths"` -> `2 passed, 228 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `485 passed in 429.88s`
- La siguiente sesion ya debe definir B141: comparar si conviene seguir con `axonendpoint { ... body + output + retries }` como siguiente ternario de menor costo o pausar la linea endpoint

### Sesion B141

- Version interna objetivo: `v0.30.6-internal.b.141.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.body + output + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...`, validacion local `axonendpoint ... retries must be >= 0 ...`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `output_type` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera ternarios que introduzcan `shield`, y composiciones aun mas anchas
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + output + retries`

### Resultado de B141

- Decision implementada: se abrio `axonendpoint.body + output + retries` porque, una vez abierto el triangulo suave en B140, el siguiente ternario de menor costo seguia siendo el mismo par de payload con la validacion local `retries` ya absorbida; pausar la linea aqui habria dejado a medias la extension mas pequena que aun evita mezclar politica
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `output_type` y `retries` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...`, `axonendpoint 'Name' retries must be >= 0, got -1`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente seis fields `method`, `path`, `execute`, `body`, `output` y `retries`, reutilizando el par de payload ya abierto y la validacion observable ya abierta de `retries` sin introducir reglas conjuntas adicionales
- Boundary explicito: ternarios con `shield` siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_output_and_retries or body_and_output_and_invalid_retries"` -> `4 passed, 246 deselected`; `pytest tests/test_cli.py -k "body_output_retries_paths"` -> `2 passed, 230 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `491 passed in 379.28s`
- La siguiente sesion ya debe definir B142: comparar si conviene seguir con `axonendpoint { ... body + output + shield }` como siguiente ternario que introduce politica sobre el par de payload o pausar la linea endpoint

### Sesion B142

- Version interna objetivo: `v0.30.6-internal.b.142.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.body + output + shield` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType shield: ShieldName }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `output_type` y `shield_ref` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones que agreguen un cuarto field operativo como `timeout` o `retries`
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + output + shield`

### Resultado de B142

- Decision implementada: se abrio `axonendpoint.body + output + shield` porque, una vez agotadas las variantes del par de payload con `timeout` y `retries`, el siguiente ternario de menor costo seguia siendo el mismo par con la referencia de politica ya absorbida; pausar la linea aqui habria dejado incompleto el triangulo de payload justo antes de cerrar su variante normativa
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType output: OutputType shield: ShieldName }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `output_type` y `shield_ref` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Name' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego una helper parser-side acotada para exactamente seis fields `method`, `path`, `execute`, `body`, `output` y `shield`, reutilizando el par de payload ya abierto y la referencia observable ya abierta de `shield` sin introducir reglas conjuntas adicionales
- Boundary explicito: composiciones mas anchas que agreguen `timeout` o `retries` sobre este ternario siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_output_and_shield or body_and_output_and_undefined_shield or body_and_output_and_not_a_shield or duplicate_axonendpoint_with_body_and_output_and_shield"` -> `5 passed, 250 deselected`; `pytest tests/test_cli.py -k "body_output_shield_paths"` -> `2 passed, 232 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `498 passed in 366.74s`
- La siguiente sesion ya debe definir B143: comparar si conviene seguir con `axonendpoint { ... body + shield + timeout }` como siguiente ternario de menor costo o pausar la linea endpoint

### Sesion B143

- Version interna objetivo: `v0.30.6-internal.b.143.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.body + shield + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `shield_ref` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones que reemplacen `timeout` por `retries` sobre este mismo ternario y composiciones aun mas anchas
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + shield + timeout`

### Resultado de B143

- Decision implementada: se abrio `axonendpoint.body + shield + timeout` porque, una vez abierta la composicion con politica `body + shield`, el siguiente ternario de menor costo seguia siendo agregar solo el knob operativo suave `timeout`; pausar la linea aqui habria dejado abierta una extension pequena que no introduce validacion dura nueva
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `shield_ref` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Safety' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego y registro una helper parser-side acotada para exactamente seis fields `method`, `path`, `execute`, `body`, `shield` y `timeout`; la validacion focal detecto una fuga inicial donde el helper no habia quedado registrado en `extended_parsers`, y la sesion la corrigio antes del trio canonico
- Boundary explicito: la variante simetrica `body + shield + retries` y composiciones aun mas anchas siguen fuera hasta la siguiente comparacion honesta de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_shield_and_timeout or body_and_shield_and_undefined_shield or duplicate_axonendpoint_with_body_and_shield_and_timeout_invalid_method"` -> `5 passed, 255 deselected`; `pytest tests/test_cli.py -k "body_shield_timeout_paths"` -> `2 passed, 234 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `505 passed in 268.12s`
- La siguiente sesion ya debe definir B144: comparar si conviene seguir con `axonendpoint { ... body + shield + retries }` como siguiente ternario de menor costo o pausar la linea endpoint

### Sesion B144

- Version interna objetivo: `v0.30.6-internal.b.144.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.body + shield + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, validacion local `retries >= 0`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `shield_ref` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones que reemplacen `body` por `output` sobre esta familia con politica y composiciones aun mas anchas
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + shield + retries`

### Resultado de B144

- Decision implementada: se abrio `axonendpoint.body + shield + retries` porque, una vez cerrada la variante suave `body + shield + timeout`, el siguiente ternario de menor costo sobre la misma composicion con politica seguia siendo agregar la validacion dura `retries >= 0` ya absorbida; pausar la linea aqui habria dejado incompleta la pareja suave/dura de ese triangulo
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType shield: ShieldName retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `shield_ref` y `retries` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...`, `axonendpoint 'Name' retries must be >= 0, got -1` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Safety' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: se agrego y registro una helper parser-side acotada para exactamente seis fields `method`, `path`, `execute`, `body`, `shield` y `retries`, reutilizando la composicion `body + shield` ya abierta y la validacion observable ya abierta de `retries` sin introducir reglas conjuntas adicionales
- Boundary explicito: la siguiente comparacion honesta dentro de la familia con politica pasa a `output + shield + timeout`; composiciones aun mas anchas siguen fuera hasta la siguiente decision explicita de frontera externa
- Validacion: `pytest tests/test_frontend_facade.py -k "body_and_shield_and_retries_success or body_and_shield_and_invalid_retries_without_delegate or body_and_shield_and_invalid_retries_undefined_flow or body_and_shield_and_undefined_shield_and_retries or body_and_shield_and_retries_not_a_shield or duplicate_axonendpoint_with_body_and_shield_and_invalid_retries"` -> `6 passed, 260 deselected`; `pytest tests/test_cli.py -k "body_shield_retries_paths"` -> `2 passed, 236 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `513 passed in 217.18s`
- La siguiente sesion ya debe definir B145: comparar si conviene seguir con `axonendpoint { ... output + shield + timeout }` como siguiente ternario de menor costo o pausar la linea endpoint

### Sesion B145

- Version interna objetivo: `v0.30.6-internal.b.145.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.output + shield + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, acumulacion con `axonendpoint ... references undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type`, `shield_ref` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - mantener fuera composiciones que reemplacen `timeout` por `retries` sobre esta misma composicion normativa y composiciones aun mas anchas
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + shield + timeout`

### Resultado de B145

- Decision implementada: se abrio `axonendpoint.output + shield + timeout` porque, una vez abierta la composicion normativa `output + shield`, el siguiente ternario de menor costo seguia siendo agregar solo el knob operativo suave `timeout`; pausar la linea aqui habria dejado abierta una extension pequena sin validacion dura nueva
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type`, `shield_ref` y `timeout` en `IREndpoint`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Safety' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: el cierre funcional de B145 quedo seguido por un hardening parser-side previo a B146; las combinaciones soportadas de `axonendpoint` dejaron de vivir como helpers casi duplicadas y pasaron a un parser estructural unico guiado por un registro central de field-sets, eliminando la clase de bug vista en B143 cuando una helper nueva no quedo registrada en `extended_parsers`
- Boundary explicito: la siguiente comparacion honesta dentro de esta misma familia normativa sigue siendo `output + shield + retries`; composiciones aun mas anchas siguen fuera hasta la siguiente decision explicita de frontera externa, pero ahora B146 debe entrar extendiendo el registro central y no agregando otra helper manual
- Validacion: `pytest tests/test_frontend_facade.py -k "output_and_shield_and_timeout_success or output_and_shield_and_timeout_undefined_flow or output_and_shield_and_undefined_shield_and_timeout or output_and_shield_and_timeout_not_a_shield or duplicate_axonendpoint_with_output_and_shield_and_timeout_invalid_method"` -> `5 passed, 266 deselected`; `pytest tests/test_cli.py -k "output_shield_timeout_paths"` -> `2 passed, 238 deselected`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `520 passed in 224.53s`
- Validacion adicional del hardening previo a B146: `pytest tests/test_frontend_facade.py tests/test_cli.py -k axonendpoint` -> `135 passed, 376 deselected in 58.03s`; `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `520 passed in 221.04s`
- La siguiente sesion ya debe definir B146: comparar si conviene seguir con `axonendpoint { ... output + shield + retries }` como siguiente ternario de menor costo o pausar la linea endpoint, partiendo ahora de un parser endpoint centralizado y mas robusto

### Sesion B146

- Version interna objetivo: `v0.30.6-internal.b.146.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.output + shield + retries` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName retries: N }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion `retries >= 0`, acumulacion con `axonendpoint ... references undefined flow ...`, diagnosticos `undefined shield`, kind mismatch `not a shield`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type`, `shield_ref` y `retries` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - reutilizar la arquitectura endurecida previa a B146, manteniendo la extension como un nuevo field-set soportado y no como otra helper manual
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + shield + retries`

### Resultado de B146

- Decision implementada: se abrio `axonendpoint.output + shield + retries` porque, una vez cerrada la variante suave `output + shield + timeout`, el siguiente ternario de menor costo sobre la misma composicion normativa seguia siendo agregar la validacion dura `retries >= 0` ya absorbida; pausar la linea aqui habria dejado abierta la contraparte dura de una familia ya delimitada
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType shield: ShieldName retries: N }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type`, `shield_ref` y `retries` en `IREndpoint`, validacion local `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, diagnosticos `axonendpoint 'Name' references undefined shield 'Missing'` y `'Safety' is a anchor, not a shield`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: la arquitectura endurecida previa a B146 se reutilizo correctamente; la extension quedo reducida a agregar el nuevo field-set `output + shield + retries` al registro central de combinaciones soportadas y a ampliar la cobertura de fachada y CLI, sin reintroducir helpers parser-side manuales
- Boundary explicito: con B146 queda cerrada la pareja suave/dura sobre la composicion normativa `output + shield`; los siguientes candidatos honestos ya son los ternarios restantes sobre la pareja operativa `retries + timeout`, que requieren una comparacion explicita antes de abrir B147
- Validacion focal de B146: `pytest tests/test_frontend_facade.py tests/test_cli.py -k "output_and_shield_and_retries or output_shield_retries_paths"` -> `4 passed, 514 deselected in 7.56s`
- Validacion ampliada del frontier endpoint: `pytest tests/test_frontend_facade.py tests/test_cli.py -k axonendpoint` -> `142 passed, 376 deselected in 62.84s`
- Validacion canonica: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `527 passed in 229.03s`
- La siguiente sesion ya debe definir B147: comparar si conviene seguir con alguno de los ternarios restantes sobre la pareja operativa `retries + timeout`, empezando por `output + retries + timeout` frente a `body + retries + timeout`, o pausar la linea endpoint

### Sesion B147

- Version interna objetivo: `v0.30.6-internal.b.147.1`
- Estado: `validated`
- Objetivo: abrir la siguiente composicion ternaria minima `axonendpoint.output + retries + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion `retries >= 0`, acumulacion con `axonendpoint ... references undefined flow ...`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `output_type`, `retries` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - reutilizar la arquitectura endurecida previa a B146, manteniendo la extension como un nuevo field-set soportado y no como otra helper manual
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + output + retries + timeout`

### Resultado de B147

- Decision implementada: se abrio `axonendpoint.output + retries + timeout` porque, entre los ternarios restantes sobre la pareja operativa ya abierta, seguia siendo el corte mas honesto para completar primero la rama de respuesta antes de ensanchar la superficie de request con `body`; pausar la linea aqui habria dejado incompleta la variante de respuesta sobre una pareja operativa ya caracterizada
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName output: OutputType retries: N timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `output_type`, `retries` y `timeout` en `IREndpoint`, validacion local `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: la arquitectura endurecida previa a B146 se reutilizo correctamente; la extension quedo reducida a agregar el nuevo field-set `output + retries + timeout` al registro central de combinaciones soportadas y a ampliar la cobertura de fachada y CLI, sin reintroducir helpers parser-side manuales
- Boundary explicito: con B147 queda cerrada la variante de respuesta sobre la pareja operativa `retries + timeout`; el siguiente candidato honesto pasa a ser `body + retries + timeout`, que requiere otra decision explicita antes de abrir B148
- Validacion focal de B147: `pytest tests/test_frontend_facade.py tests/test_cli.py -k "output_and_retries_and_timeout or output_retries_timeout_paths"` -> `5 passed, 518 deselected in 6.08s`
- Validacion ampliada del frontier endpoint: `pytest tests/test_frontend_facade.py tests/test_cli.py -k axonendpoint` -> `147 passed, 376 deselected in 63.88s`
- Validacion canonica: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `532 passed in 226.16s`
- La siguiente sesion ya debe definir B148: comparar si conviene seguir con `body + retries + timeout` como ultimo ternario pendiente sobre la pareja operativa `retries + timeout`, o pausar la linea endpoint

### Sesion B148

- Version interna objetivo: `v0.30.6-internal.b.148.1`
- Estado: `validated`
- Objetivo: abrir la ultima composicion ternaria minima pendiente `axonendpoint.body + retries + timeout` sobre el endpoint estructural ya soportado por `native-dev`
- Alcance:
  - abrir solo la forma acotada `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N timeout: TimeoutValue }` en cualquier orden dentro de programas estructurales soportados
  - reproducir localmente exito, validacion `retries >= 0`, acumulacion con `axonendpoint ... references undefined flow ...`, `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
  - materializar localmente `body_type`, `retries` y `timeout` en `IREndpoint` y en el JSON compilado con el mismo shape observable que Python
  - reutilizar la arquitectura endurecida previa a B146, manteniendo la extension como un nuevo field-set soportado y no como otra helper manual
- Criterio de terminado:
  - `native-dev` deja de delegar para el exito y los errores ya cubiertos por el corte parser-side acotado `axonendpoint.method + path + execute + body + retries + timeout`

### Resultado de B148

- Decision implementada: se abrio `axonendpoint.body + retries + timeout` porque, una vez cerrada en B147 la variante de respuesta sobre la pareja operativa ya abierta, quedaba como ultimo ternario pendiente y era mas honesto cerrarlo que dejar la rama de request a medias
- Entra efectivamente en el path local: `axonendpoint { method: X path: "/..." execute: FlowName body: BodyType retries: N timeout: TimeoutValue }` en cualquier orden para programas estructurales soportados, incluyendo exito con `body_type`, `retries` y `timeout` en `IREndpoint`, validacion local `axonendpoint 'Name' retries must be >= 0, got N`, acumulacion con `axonendpoint 'Name' references undefined flow ...` y `Undefined flow ...`, y duplicate declarations por nombre `axonendpoint`
- Implementacion: la arquitectura endurecida previa a B146 se reutilizo correctamente; la extension quedo reducida a agregar el nuevo field-set `body + retries + timeout` al registro central de combinaciones soportadas y a ampliar la cobertura de fachada y CLI, sin reintroducir helpers parser-side manuales
- Boundary explicito: con B148 queda cerrada la ultima variante ternaria pendiente sobre la pareja operativa `retries + timeout`; cualquier crecimiento siguiente ya deja de ser continuacion mecanica y debe justificarse explicitamente antes de ensanchar la superficie endpoint
- Validacion focal de B148: `pytest tests/test_frontend_facade.py tests/test_cli.py -k "body_and_retries_and_timeout or body_retries_timeout_paths"` -> `5 passed, 523 deselected in 3.27s`
- Validacion ampliada del frontier endpoint: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py -k axonendpoint` -> `152 passed, 385 deselected in 73.56s`
- Validacion canonica: `pytest tests/test_frontend_facade.py tests/test_cli.py tests/test_frontend_contract_golden.py` -> `537 passed in 249.84s`
- La siguiente sesion ya no debe asumir otra extension endpoint automatica: primero debe decidir si conviene pausar la frontera endpoint o si existe evidencia suficiente para abrir una composicion mas ancha

### Sesion B149

- Version interna objetivo: `v0.30.6-internal.b.149.1`
- Estado: `validated`
- Objetivo: revisar formalmente si `Fase B` puede cerrarse tras B148 y fijar el siguiente corte tecnico recomendado si la fase debe continuar activa
- Alcance:
  - contrastar el criterio de salida de `Fase B` frente al estado real de `native-dev`, del frontend core y del backlog validado hasta B148
  - emitir un dictamen explicito de gate entre continuar en `Fase B` o habilitar `Fase C`
  - dejar cerrada la decision de pausar la linea endpoint salvo evidencia extraordinaria
  - recomendar el siguiente corte tecnico con mejor relacion valor/fase
- Criterio de terminado:
  - existe una revision formal de salida con dictamen verificable y un handoff tecnico que vuelva a atacar delegacion real del core, no expansion adicional de endpoint

### Resultado de B149

- Decision implementada: `Fase B` no se cierra todavia y `Fase C` no debe abrirse tras B148; cerrar la malla ternaria de `axonendpoint` no satisface el criterio formal que sigue exigiendo `lexer`, `parser` y `type checker` nativos, ademas de `axon check` y `axon compile` sobre core nativo
- Evidencia principal: `native-dev` sigue documentado como ruta que delega en Python fuera de su subset local y `frontend.py` mantiene caidas explicitas a `self._delegate.check_source(...)` y `self._delegate.compile_source(...)`
- Boundary explicito: la linea `axonendpoint` queda pausada por defecto despues de B148; cualquier reapertura requiere evidencia extraordinaria y ya no cuenta como continuacion mecanica honesta de `Fase B`
- Recomendacion tecnica: la siguiente sesion debe ser `B150` y debe abrir el primer corte nativo explicito de `type`, empezando por `type RiskScore(0.0..1.0)` y por tipos estructurados con campos opcionales como `mitigation: Opinion?`, porque es core directo del frontend, sigue repetidamente fuera por falta de estrategia y ataca delegacion parser/type-checker real

### Sesion B150

- Version interna objetivo: `v0.30.6-internal.b.150.1`
- Estado: `closed`
- Objetivo: abrir el primer corte nativo explicito de `type` para mover una porcion real del parser/type checker fuera de la delegacion Python en `native-dev`
- Alcance:
  - soportar localmente el rango escalar acotado `type RiskScore(0.0..1.0)` preservando `range_min` y `range_max` en compile
  - soportar localmente un tipo estructurado acotado con campos simples y opcionales como `mitigation: Opinion?`, preservando `fields`, `type_name` y `optional`
  - mantener fuera `where`, restricciones mas ricas, generics complejos y cualquier composicion que exceda el subset ya congelado como fixture estable
  - validar el corte contra fachada, CLI y golden tests, demostrando un avance real sobre delegacion parser/type-checker del core
- Criterio de terminado:
  - `native-dev` deja de delegar a Python para `check` y `compile` en el subset `type` acotado elegido, preservando el contrato observable ya congelado

### Resultado de B150

- Decision implementada: `native-dev` ya no delega en Python para programas formados solo por declaraciones `type` dentro del subset B150, cubriendo el rango escalar `type RiskScore(0.0..1.0)` y tipos estructurados acotados con fields simples y opcionales como `mitigation: Opinion?`
- Superficie preservada: `compile` mantiene el mismo shape observable para `types`, incluyendo `range_min`, `range_max`, `fields`, `type_name`, `generic_param` y `optional`
- Boundary explicito: `where`, validaciones semanticas mas ricas, duplicate declarations de `type` y archivos mixtos `type + flow/run` siguen delegados para no ensanchar el corte mas alla del fixture estable definido para B150
- Validacion: foco B150 `6 passed, 524 deselected` y trio canonico frontend `539 passed`

### Sesion B151

- Version interna objetivo: `v0.30.6-internal.b.151.1`
- Estado: `closed`
- Objetivo: combinar el subset local de `type` abierto en B150 con el success path nativo ya existente de `flow/run`, de modo que los programas mixtos mas pequenos dejen de delegar el archivo entero a Python
- Alcance:
  - soportar localmente archivos acotados `type + flow + run` donde las declaraciones `type` ya caen dentro del subset B150 y `flow/run` dentro del success path nativo actual
  - preservar el contrato observable ya congelado para `check`, `compile` e IR, incluyendo `types`, `flows` y `runs`
  - mantener fuera `where`, tipos complejos y composiciones mixtas que exijan validacion semantica no abierta todavia
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer programa mixto acotado `type + flow + run`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B151

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer programa mixto acotado `type + flow + run`, reutilizando el success path minimo ya existente de `run` y combinandolo con el subset `type` abierto en B150
- Superficie preservada: `compile` mantiene el mismo shape observable para `types`, `flows` y `runs`, incluyendo `range_min`, `range_max`, `fields`, `type_name`, `generic_param`, `optional`, `output_to` y `resolved_flow`
- Boundary explicito: `where`, validaciones semanticas mas ricas de tipos y programas mixtos prefijados `persona/context/anchor + type + flow/run` siguen delegados para no ensanchar el corte mas alla del primer archivo mixto honesto
- Validacion: foco B151 `4 passed, 530 deselected` y trio canonico frontend `543 passed`

### Sesion B152

- Version interna objetivo: `v0.30.6-internal.b.152.1`
- Estado: `closed`
- Objetivo: combinar el frente mixto `type + flow/run` abierto en B151 con los success paths prefijados `persona/context/anchor`, de modo que los archivos acotados con encabezado semantico minimo dejen de delegar enteros a Python
- Alcance:
  - soportar localmente programas acotados `type + persona/context/anchor + flow + run` cuando los `type` caen dentro del subset B150 y el resto ya cae dentro de un success path prefijado existente
  - preservar el contrato observable ya congelado para `check`, `compile` e IR, incluyendo `types`, `personas`, `contexts`, `anchors`, `flows` y `runs`
  - mantener fuera `where`, tipos complejos y composiciones mixtas que exijan validacion semantica no abierta todavia
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer programa prefijado acotado `type + persona/context/anchor + flow + run`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B152

- Decision implementada: `native-dev` ya no rebota entero a Python para archivos acotados `type + persona/context/anchor + flow + run`, componiendo el subset `type` abierto en B150 con los success paths prefijados ya existentes en `persona/context/anchor`
- Superficie preservada: `compile` mantiene el mismo shape observable para `types`, `personas`, `contexts`, `anchors`, `flows` y `runs`, incluyendo `range_min`, `range_max`, `fields`, `type_name`, `generic_param`, `optional`, `output_to` y `resolved_flow`
- Boundary explicito: `where`, validaciones semanticas mas ricas de tipos y programas mixtos negativos/estructurales siguen delegados para no ensanchar el corte mas alla del primer frente prefijado honesto
- Validacion: foco B152 `3 passed, 535 deselected` y trio canonico frontend `547 passed`

### Sesion B153

- Version interna objetivo: `v0.30.6-internal.b.153.1`
- Estado: `closed`
- Objetivo: llevar el frente mixto positivo ya abierto en B152 a los primeros paths negativos y estructurales ya soportados localmente, de modo que los archivos acotados no deleguen enteros a Python cuando el fallo ya pertenece a una frontera nativa conocida
- Alcance:
  - soportar localmente archivos acotados `type + persona/context/anchor + run` que hoy solo fallan por `undefined flow`, duplicate declarations o validaciones prefijadas ya abiertas
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo mensajes y orden de diagnosticos en los casos ya soportados localmente
  - mantener fuera `where`, tipos complejos y validaciones semanticas nuevas de tipos no abiertas todavia
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas mixtos negativos/estructurales `type + persona/context/anchor + run`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B153

- Decision implementada: `native-dev` ya no rebota entero a Python para archivos acotados con uno o mas `type` del subset B150 cuando el resto del archivo cae dentro de los matchers estructurales locales ya abiertos de validacion o duplicate declarations, incluyendo la acumulacion observable de `Undefined flow ...`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de mensajes, orden de diagnosticos, `token_count` y `declaration_count` al componer el prefijo `type` con los paths estructurales negativos ya portados
- Boundary explicito: `where`, duplicate declarations de `type`, validaciones semanticas nuevas de tipos y el hueco `type + run Missing()` sin prefijos estructurales siguen delegados para no ensanchar el corte mas alla del primer frente negativo mixto honesto
- Validacion: foco B153 `4 passed, 538 deselected` y trio canonico frontend `551 passed`

### Sesion B154

- Version interna objetivo: `v0.30.6-internal.b.154.1`
- Estado: `closed`
- Objetivo: cerrar el hueco negativo mas pequeno que queda tras B153 para que los archivos `type + run Missing()` sin prefijos estructurales no deleguen enteros a Python cuando el unico fallo ya es el diagnostico local `Undefined flow ...`
- Alcance:
  - soportar localmente archivos acotados con uno o mas `type` del subset B150 seguidos solo por `run Missing()` y sus formas ya abiertas del subset local de `run`
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo mensaje, `token_count` y `declaration_count`
  - mantener fuera `where`, duplicate declarations de `type` y validaciones semanticas nuevas de tipos no abiertas todavia
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas `type + run` negativos sin prefijos estructurales, con validacion verde en fachada, CLI y trio canonico

### Resultado de B154

- Decision implementada: `native-dev` ya no rebota entero a Python para archivos acotados con uno o mas `type` del subset B150 cuando el resto del archivo cae dentro del subset aislado de `run` que produce el diagnostico local `Undefined flow ...`, incluyendo argumentos y modifiers ya abiertos en ese mismo path
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de mensaje, `token_count` y `declaration_count` al componer el prefijo `type` con el matcher aislado de `run`
- Boundary explicito: `where`, duplicate declarations de `type`, validaciones semanticas nuevas de tipos y el hueco limpio `type + persona/context/anchor + run Missing()` siguen delegados para no ensanchar el corte mas alla del siguiente negativo mixto honesto
- Validacion: foco B154 `3 passed, 542 deselected` y trio canonico frontend `554 passed`

### Sesion B155

- Version interna objetivo: `v0.30.6-internal.b.155.1`
- Estado: `closed`
- Objetivo: cerrar el siguiente hueco mixto limpio tras B154 para que los archivos `type + persona/context/anchor + run Missing()` no deleguen enteros a Python cuando el unico fallo ya es el diagnostico local `Undefined flow ...`
- Alcance:
  - soportar localmente archivos acotados con uno o mas `type` del subset B150 seguidos por prefixes limpios `persona/context/anchor` ya abiertos y por `run Missing()` dentro del prefixed run subset ya soportado
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo mensaje, `token_count` y `declaration_count`
  - mantener fuera `where`, duplicate declarations de `type`, validaciones estructurales no limpias y validaciones semanticas nuevas de tipos no abiertas todavia
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas limpios `type + persona/context/anchor + run` negativos, con validacion verde en fachada, CLI y trio canonico

### Resultado de B155

- Decision implementada: `native-dev` ya no rebota entero a Python para archivos acotados con uno o mas `type` del subset B150 cuando el resto del archivo cae dentro del prefixed run subset limpio de `persona/context/anchor` que emite localmente `Undefined flow ...`, incluyendo referencias prefijadas ya abiertas y modifiers ya soportados en ese mismo path
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de mensaje, `token_count` y `declaration_count` al componer el prefijo `type` con el prefixed run subset limpio
- Boundary explicito: `where`, duplicate declarations de `type`, validaciones estructurales no limpias y validaciones semanticas nuevas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente hueco honesto dentro del propio prefijo `type`
- Validacion: foco B155 `3 passed, 545 deselected` y trio canonico frontend `557 passed`

### Sesion B156

- Version interna objetivo: `v0.30.6-internal.b.156.1`
- Estado: `closed`
- Objetivo: cerrar el hueco local mas pequeno que queda dentro del prefijo `type`, para que duplicate declarations de `type` en programas acotados ya soportados localmente no deleguen enteros a Python cuando el unico faltante ya es ese diagnostico canonico
- Alcance:
  - soportar localmente duplicate declarations de `type` sobre el subset B150 en programas type-only y en composiciones mixtas ya abiertas localmente
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo mensaje, orden, `token_count` y `declaration_count`
  - mantener fuera `where`, validaciones semanticas nuevas de tipos y restricciones ricas todavia no abiertas
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas con duplicate declarations de `type`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B156

- Decision implementada: `native-dev` ya no rebota entero a Python para duplicate declarations de `type` sobre el subset B150 cuando el resto del archivo cae dentro de un subset local ya soportado, acumulando tambien diagnosticos posteriores ya abiertos localmente como `Undefined flow ...` o los paths estructurales existentes cuando corresponden
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de mensaje, orden, `token_count` y `declaration_count` para duplicate `type` en programas type-only y mixtos ya portados
- Boundary explicito: `where`, validaciones semanticas nuevas de tipos y restricciones ricas siguen delegadas para no ensanchar el corte mas alla del siguiente frente parser-side honesto dentro de `type`
- Validacion: foco B156 `3 passed, 548 deselected` y trio canonico frontend `560 passed`

### Sesion B157

- Version interna objetivo: `v0.30.6-internal.b.157.1`
- Estado: `closed`
- Objetivo: abrir el primer corte parser-side acotado de `type ... where ...` sobre programas type-only, para que el frente `type` avance mas alla de ranges, fields simples y duplicate declarations sin mezclar todavia validacion semantica rica
- Alcance:
  - soportar localmente una primera forma acotada de `where` sobre declaraciones `type` dentro de programas type-only del subset B150
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo mensaje, `token_count` y `declaration_count`
  - mantener fuera restricciones ricas, combinaciones mixtas y validaciones semanticas nuevas de tipos que excedan el primer corte parser-side
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas `type ... where ...` en type-only, con validacion verde en fachada, CLI y trio canonico

### Resultado de B157

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas type-only con `type ... where ...`, preservando localmente `where_expression` en el IR compilado junto con `range` y `fields` cuando existen
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count` y shape compilado para `where_expression`, `range_min`, `range_max` y `fields`
- Boundary explicito: las composiciones mixtas con `flow/run`, prefijos `persona/context/anchor`, duplicate declarations mixtos y validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B157 `4 passed, 551 deselected` y trio canonico frontend `564 passed`

### Sesion B158

- Version interna objetivo: `v0.30.6-internal.b.158.1`
- Estado: `closed`
- Objetivo: componer el primer corte parser-side de `type ... where ...` con el success path minimo ya abierto de `flow/run`, para que la primera composicion mixta positiva con `where` deje tambien de rebotar entero a Python
- Alcance:
  - soportar localmente uno o mas `type` del subset B150 con `where` opcional en archivos que, fuera de ese prefijo, caen dentro del success path minimo ya abierto de `flow/run`
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo `token_count`, `declaration_count` y el shape compilado de `where_expression` junto con `flows` y `runs`
  - mantener fuera prefijos `persona/context/anchor`, paths negativos, duplicate declarations mixtos y validaciones semanticas nuevas de tipos
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas mixtos `type ... where ... + flow/run`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B158

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas mixtos `type ... where ... + flow/run`, reutilizando el parser local de `type` y preservando `where_expression` junto con `flows`, `runs` y modifiers ya abiertos como `output_to`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count` y shape compilado para `where_expression`, `range_min`, `range_max`, `flows`, `runs` y `output_to`
- Boundary explicito: los prefijos `persona/context/anchor`, los paths negativos, duplicate declarations mixtos con `where` y las validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B158 `7 passed, 551 deselected` y trio canonico frontend `567 passed`

### Sesion B159

- Version interna objetivo: `v0.30.6-internal.b.159.1`
- Estado: `closed`
- Objetivo: componer `type ... where ...` con el success path prefijado ya abierto de `persona/context/anchor + flow/run`, para que la primera composicion positiva prefijada con `where` deje tambien de rebotar entero a Python
- Alcance:
  - soportar localmente uno o mas `type` del subset B150 con `where` opcional en archivos que, fuera de ese prefijo, caen dentro del success path prefijado ya abierto de `persona/context/anchor + flow/run`
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo `token_count`, `declaration_count` y el shape compilado de `where_expression` junto con `personas`, `contexts`, `anchors`, `flows` y `runs`
  - mantener fuera paths negativos, duplicate declarations mixtos con `where` y validaciones semanticas nuevas de tipos
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas prefijados `type ... where ... + persona/context/anchor + flow/run`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B159

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas prefijados `type ... where ... + persona/context/anchor + flow/run`, preservando localmente `where_expression` junto con `personas`, `contexts`, `anchors`, `flows`, `runs` y modifiers ya abiertos como `output_to`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count` y shape compilado para `where_expression`, `personas`, `contexts`, `anchors`, `flows`, `runs` y `output_to`
- Boundary explicito: los paths negativos, duplicate declarations mixtos con `where` y las validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B159 `3 passed, 558 deselected` y trio canonico frontend `570 passed`

### Sesion B160

- Version interna objetivo: `v0.30.6-internal.b.160.1`
- Estado: `closed`
- Objetivo: llevar `type ... where ...` a los paths estructurales negativos y de duplicate declarations ya abiertos localmente, para que el frente `type` replique con `where` el siguiente escalon que ya siguio el prefijo `type` simple despues de B152
- Alcance:
  - soportar localmente uno o mas `type` del subset B150 con `where` opcional en archivos que, fuera de ese prefijo, caen dentro de los matchers estructurales negativos y de duplicate declarations ya abiertos para `persona/context/anchor`
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo orden de diagnosticos, `token_count`, `declaration_count` y el shape compilado cuando el path siga siendo de exito local
  - mantener fuera isolated run, clean prefixed run negativos, duplicate declarations de `type` con `where` y validaciones semanticas nuevas de tipos
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas estructurales negativos y de duplicate declarations con `type ... where ...`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B160

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas estructurales negativos y de duplicate declarations con `type ... where ...`, preservando el mismo orden local de `Unknown memory scope ...`, `Undefined flow ...` y `Duplicate declaration ...` que Python
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count`, orden de diagnosticos e `ir_program = None` cuando el path sigue siendo de error local
- Boundary explicito: isolated run, clean prefixed run, duplicate declarations de `type` con `where` y validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B160 `6 passed, 559 deselected` y trio canonico frontend `574 passed`

### Sesion B161

- Version interna objetivo: `v0.30.6-internal.b.161.1`
- Estado: `closed`
- Objetivo: llevar `type ... where ...` al subset aislado de `run Missing()` ya abierto localmente, para que el frente `type` siga replicando con `where` el mismo ladder negativo que ya siguio el prefijo `type` simple
- Alcance:
  - soportar localmente uno o mas `type` del subset B150 con `where` opcional en archivos que, fuera de ese prefijo, caen dentro del subset aislado de `run Missing()` ya abierto localmente
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo orden de diagnosticos, `token_count`, `declaration_count` e `ir_program = None`
  - mantener fuera clean prefixed run, duplicate declarations de `type` con `where` y validaciones semanticas nuevas de tipos
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas `type ... where ... + run Missing()` del subset aislado ya abierto, con validacion verde en fachada, CLI y trio canonico

### Resultado de B161

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas `type ... where ... + run Missing()` del subset aislado ya abierto, preservando localmente el diagnostico canonico `Undefined flow 'Missing' in run statement`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count`, diagnosticos e `ir_program = None` cuando el path sigue siendo de error local
- Boundary explicito: clean prefixed run, duplicate declarations de `type` con `where` y validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B161 `4 passed, 564 deselected` y trio canonico frontend `577 passed`

### Sesion B162

- Version interna objetivo: `v0.30.6-internal.b.162.1`
- Estado: `closed`
- Objetivo: llevar `type ... where ...` al clean prefixed run ya abierto localmente, para que el frente `type` siga replicando con `where` el mismo ladder negativo antes de tocar duplicate `type` con `where`
- Alcance:
  - soportar localmente uno o mas `type` del subset B150 con `where` opcional en archivos que, fuera de ese prefijo, caen dentro del clean prefixed run ya abierto localmente
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo orden de diagnosticos, `token_count`, `declaration_count` e `ir_program = None`
  - mantener fuera duplicate declarations de `type` con `where` y validaciones semanticas nuevas de tipos
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de programas `type ... where ...` sobre el clean prefixed run ya abierto, con validacion verde en fachada, CLI y trio canonico

### Resultado de B162

- Decision implementada: `native-dev` ya no rebota entero a Python para el primer conjunto acotado de programas `type ... where ...` sobre el clean prefixed run ya abierto, preservando localmente el diagnostico canonico `Undefined flow 'Missing' in run statement`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count`, diagnosticos e `ir_program = None` cuando el path sigue siendo de error local
- Boundary explicito: duplicate declarations de `type` con `where` y validaciones semanticas ricas de tipos siguen delegadas para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B162 `4 passed, 567 deselected` y trio canonico frontend `580 passed`

### Sesion B163

- Version interna objetivo: `v0.30.6-internal.b.163.1`
- Estado: `closed`
- Objetivo: cerrar el hueco local que queda dentro del propio prefijo `type`: duplicate declarations de `type` cuando el prefijo ya usa `where`, para que el ladder de `type ... where ...` replique el cierre que B156 dio al prefijo `type` simple
- Alcance:
  - soportar localmente duplicate declarations de `type` cuando las declaraciones caen dentro del subset B150 ya ampliado con `where`
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo orden de diagnosticos, `token_count`, `declaration_count` e `ir_program = None`
  - mantener fuera validaciones semanticas nuevas de tipos y restricciones ricas fuera del subset ya abierto
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python para el primer conjunto acotado de duplicate declarations de `type` con `where`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B163

- Decision implementada: `native-dev` ya no rebota entero a Python para duplicate declarations de `type` cuando el prefijo ya usa `where`, reutilizando el scanner local B156 con `allow_where_clause=True`
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count`, orden de diagnosticos e `ir_program = None` cuando el path sigue siendo de error local
- Boundary explicito: validaciones semanticas ricas de tipos y cualquier comportamiento de `where` fuera del subset ya abierto siguen delegados para no ensanchar el corte mas alla del siguiente frente honesto
- Validacion: foco B163 `3 passed` y trio canonico frontend `580 passed`

### Sesion B164

- Version interna objetivo: `v0.30.6-internal.b.164.1`
- Estado: `closed`
- Objetivo: llevar al subset local de `type` la unica validacion semantica observable que Python ya aplica sobre `TypeDefinition`: `Invalid range constraint ...` cuando `min >= max`, para cerrar el primer hueco real de type checker dentro del frente `type` ya abierto
- Alcance:
  - soportar localmente `Invalid range constraint ...` sobre declaraciones `type` dentro del subset ya ampliado con `where`, tanto en type-only como en las composiciones mixtas ya abiertas localmente
  - preservar el contrato observable ya congelado para `check` y `compile`, incluyendo orden de diagnosticos, `token_count`, `declaration_count` e `ir_program = None`
  - mantener fuera type compatibility epistemica, propagacion de incertidumbre y cualquier semantica no observable que Python todavia no expone como diagnostico sobre `TypeDefinition`
- Criterio de terminado:
  - `native-dev` deja de rebotar a Python y deja de aceptar en falso rangos invalidos en el subset local de `type`, con validacion verde en fachada, CLI y trio canonico

### Resultado de B164

- Decision implementada: `native-dev` ya no acepta en falso `type` con `min >= max` dentro del subset local y emite localmente `Invalid range constraint ...`, reutilizando los wrappers abiertos del prefijo `type` en lugar de reintroducir otra familia de matchers paralelos
- Superficie preservada: `check` y `compile` mantienen el mismo contrato observable de `token_count`, `declaration_count`, orden de diagnosticos e `ir_program = None` cuando el path sigue siendo de error local
- Boundary explicito: referencias de tipo desconocidas siguen aceptadas sin diagnostico porque Python las trata hoy como soft unresolved references, y la lattice epistemic sigue sin entrar todavia en un path observable del frontend
- Validacion: foco B164 `10 passed` y trio canonico frontend `583 passed`

### Sesion B165

- Version interna objetivo: `v0.30.6-internal.b.165.1`
- Estado: `closed`
- Objetivo: decidir si la siguiente reduccion honesta sigue dentro de `type` mediante una primera integracion observable de `check_type_compatible` / `check_uncertainty_propagation`, o si ya no queda un corte pequeno verificable en esa frontera y conviene mover el foco a otra costura del core
- Resultado: la frontera `type` queda temporalmente agotada — `check_type_compatible` y `check_uncertainty_propagation` son codigo muerto en el pipeline de produccion, nunca invocadas desde `TypeChecker.check()`. Se implemento el siguiente corte honesto mas pequeno: `import SomeModule` (3 tokens, 1 declaracion) ahora se maneja localmente sin delegacion a Python, produciendo `IRImport(module_path=("SomeModule",))` en el IR compilado.
- Validacion: foco B165 `3 passed in 6.09s`, trio canonico frontend `586 passed in 359.29s`
- Alcance:
  - verificar con evidencia de codigo y de Python si la lattice epistemic participa hoy en algun path observable del frontend que pueda portarse de forma acotada
  - descartar como siguiente corte inmediato cualquier validacion que Python no emita todavia, como referencias de tipo desconocidas dentro de `TypeDefinition`
  - dejar fijado un siguiente subset pequeno y justificable, o documentar que la frontera `type` ya no tiene otro corte pequeno honesto antes de salir a otra costura del core
- Criterio de terminado:
  - existe un siguiente corte B165 explicitamente elegido y justificado contra el criterio de `Fase B`, con evidencia base suficiente para implementarlo sin phase drift

### Sesion B166

- Version interna objetivo: `v0.30.6-internal.b.166.1`
- Estado: `closed`
- Objetivo: decidir el siguiente corte honesto mas pequeno dentro de la frontera `import` abierta por B165, o mover el foco a otro hueco de delegacion real identificado por la deteccion instrumentada
- Resultado: dotted imports (`import a.b`, `import a.b.c`, `import a.b.c.d`) son el siguiente corte honesto mas pequeno — se generalizo `_match_native_import_program` de `len == 2` exacto a un loop `IMPORT IDENTIFIER (DOT IDENTIFIER)*`, produciendo `IRImport(module_path=("a", "b", "c"))` identico al IR de Python
- Validacion: foco B166 `6 passed in 7.82s`, trio canonico frontend `589 passed in 351.12s`
- Alcance:
  - comparar extensiones de `import` (dotted paths `import a.b`, named imports `import a { X, Y }`, composicion `import + flow/run`) contra otros huecos reales identificados (`multi_flow`, `shield_body`, parser error delegation para `flow_params`, `flow_body`, `agent_decl`, `type_flow_params`, `know_decl`)
  - elegir el siguiente corte que mas reduzca delegacion real con el menor costo
- Criterio de terminado:
  - existe un siguiente corte B166 explicitamente elegido y justificado contra el criterio de `Fase B`, con evidencia base suficiente para implementarlo sin phase drift

### Sesion B167

- Version interna objetivo: `v0.30.6-internal.b.167.1`
- Estado: `closed`
- Objetivo: decidir el siguiente corte honesto mas pequeno dentro de la frontera `import` (named imports `import a { X, Y }`) o mover el foco a otro hueco de delegacion real
- Resultado: named imports son el siguiente corte honesto — se extendio `_match_native_import_program` con consumo opcional de `LBRACE IDENTIFIER (COMMA IDENTIFIER)* RBRACE`, cubriendo `import a { X }`, `import a { X, Y }`, `import a.b { X, Y }` y `import a.b.c { X, Y, Z }`, produciendo `IRImport(module_path=..., names=...)` identico al IR de Python
- Validacion: foco B167 `7 passed in 7.70s`, trio canonico frontend `592 passed in 339.34s`

### Sesion B168

- Version interna objetivo: `v0.30.6-internal.b.168.1`
- Estado: `closed`
- Objetivo: componer la frontera `import` con el exito no-tipo existente (`flow/run`, prefijos estructurales) para que `native-dev` maneje localmente programas `import + flow/run` sin delegacion a Python
- Resultado: se extrajo `_parse_native_single_import` y `_parse_native_import_prefix`, se creo `_match_native_import_flow_run_program` que compone prefix import + non-type success matcher + merge, y se inserto en la cadena de dispatch. Cuatro variantes (simple, dotted, named, structural prefix) ahora son LOCAL. Foco B168: `6 passed in 3.78s`. Trio canonico: `595 passed in 310.49s`.

### Sesion B169

- Version interna objetivo: `v0.30.6-internal.b.169.1`
- Estado: `closed`
- Objetivo: extender `_match_native_import_program` para manejar multiples imports standalone sin delegacion a Python
- Resultado: se generalizo `_match_native_import_program` de single-import a loop multi-import via `_parse_native_single_import` con terminal check. Cuatro variantes de multi-import (simple, triple, dotted, named) ahora son LOCAL. Foco B169: `7 passed in 7.39s`. Trio canonico: `598 passed in 306.34s`.

### Sesion B170

- Version interna objetivo: `v0.30.6-internal.b.170.1`
- Estado: `closed`
- Objetivo: componer `type + import + flow/run` en el mismo programa sin delegacion a Python
- Alcance:
  - extender `_match_native_type_flow_run_program` para intentar `_match_native_import_flow_run_program` sobre remaining tokens tras type prefix
  - cubre: type+import+flow/run, type+multi_import+flow/run, multi_type+import+flow/run
- Criterio de terminado:
  - facade test con 4 casos pasa sin delegacion
  - CLI tests de check y compile pasan con `native-dev`
  - trio canonico: 601 passed in 336.74s

### Sesion B171

- Version interna objetivo: `v0.30.6-internal.b.171.1`
- Estado: `closed`
- Objetivo: componer `import + type + flow/run` en el mismo programa sin delegacion a Python
- Alcance:
  - extender `_match_native_import_flow_run_program` para intentar `_match_native_type_flow_run_program` sobre remaining tokens tras import prefix
  - cubre: import+type+flow/run, multi_import+type+flow/run, import+multi_type+flow/run, import+type+import+flow/run
- Criterio de terminado:
  - facade test con 4 casos pasa sin delegacion
  - CLI tests de check y compile pasan con `native-dev`
  - trio canonico: 604 passed in 309.41s

### Sesion B172

- Version interna objetivo: `v0.30.6-internal.b.172.1`
- Estado: `validated`
- Objetivo: decidir el siguiente corte honesto: composicion `type + import standalone`, composicion `import + type standalone`, o mover el foco a otro hueco de delegacion real
- Alcance:
  - caracterizar candidatos DELEGATED restantes en composiciones standalone type+import
  - comparar contra otros huecos reales (`multi_flow`, `shield_body`, parser error delegation`)
  - elegir el siguiente corte que mas reduzca delegacion real con menor costo
- Criterio de terminado:
  - existe un siguiente corte B172 explicitamente elegido e implementado con evidencia verificable
- Resultado:
  - corte elegido: `type + import standalone` (type primero, import despues, sin flow/run)
  - refactorizacion de `_match_native_type_program` para usar `_parse_native_type_prefix` + `_match_native_import_program`
  - 5 variantes ahora LOCAL sin delegacion
  - foco directo: `3 passed in 3.70s`
  - trio canonico: `607 passed in 310.83s`

### Sesion B173

- Version interna objetivo: `v0.30.6-internal.b.173.1`
- Estado: `validated`
- Objetivo: decidir el siguiente corte honesto: composicion `import + type standalone` (import primero, type despues) o mover el foco a otro hueco de delegacion real
- Alcance:
  - caracterizar composicion `import + type standalone` contra otros huecos reales (`multi_flow`, `shield_body`, `agent_decl`, etc.)
  - elegir el siguiente corte que mas reduzca delegacion real con menor costo
- Criterio de terminado:
  - existe un siguiente corte B173 explicitamente elegido e implementado con evidencia verificable
- Resultado:
  - corte elegido: `import + type standalone` (import primero, type despues, sin flow/run)
  - extension de `_match_native_import_program` para intentar `_match_native_type_program` en remaining tokens
  - 5 variantes ahora LOCAL sin delegacion
  - foco directo: `3 passed in 6.23s`
  - trio canonico: `610 passed in 314.41s`

### Sesion B174

- Version interna objetivo: `v0.30.6-internal.b.174.1`
- Estado: `validated`
- Objetivo: abrir el primer hueco de delegacion real `multi_flow` ahora que la frontera cross-prefix type+import queda completamente cerrada
- Alcance:
  - caracterizar 7 huecos de delegacion reales restantes
  - elegir `multi_flow` como menor corte honesto (loop sobre patrones existentes sin nueva gramatica)
  - implementar `_match_native_multi_flow_run_program`: N flow blocks vacios + M run statements con resolucion local
- Resultado:
  - Foco directo: 3 passed in 8.16s
  - Trio canonico: 613 passed in 318.87s
  - CHECK 5/5

### Sesion B175

- Version interna objetivo: `v0.30.6-internal.b.175.1`
- Estado: `validated`
- Objetivo: profundizar multi_flow con run modifiers no-referenciales
- Alcance:
  - extension de `_match_native_multi_flow_run_program` para parsear modifier tokens entre cada run
  - reutiliza helpers existentes de modifier parsing
  - 6 patrones ahora LOCAL: output_to, effort, on_failure log/raise/retry, both-modified
- Resultado:
  - Foco directo: 3 passed in 5.32s
  - Trio canonico: 616 passed in 321.57s
  - CHECK 5/5

### Sesion B176

- Version interna objetivo: `v0.30.6-internal.b.176.1`
- Estado: `validated`
- Objetivo: abrir el hueco de delegacion flow_params
- Alcance:
  - implementacion de `_match_native_parameterized_flow_run_program` para parsear parametros tipados
  - reutiliza `_parse_structural_type_expr` existente y genera `IRParameter` por parametro
  - 5 patrones ahora LOCAL: single param, typed param, multi param, optional param, generic param
- Resultado:
  - Foco directo: 3 passed in 7.03s
  - Trio canonico: 619 passed in 315.31s
  - CHECK 5/5

### Sesion B177

- Version interna objetivo: `v0.30.6-internal.b.177.1`
- Estado: `closed`
- Objetivo: profundizar flow_params con non-referential run modifiers
- Alcance cerrado:
  - extendido _match_native_parameterized_flow_run_program con modifier handling post-RPAREN
  - 10 patrones LOCAL: param+output_to, param+effort, param+on_failure_log/raise/retry, generic+effort, optional+output_to, multi_param+effort, bare_single, type+param+mod
  - IR identico a Python en 7 casos con modifiers
  - Trio: 622 passed

### Sesion B178

- Version interna objetivo: `v0.30.6-internal.b.178.1`
- Estado: `closed`
- Objetivo: cerrar multi_flow + params
- Alcance cerrado:
  - extendido _match_native_multi_flow_run_program para parsear parametros tipados opcionales en cada flow del loop
  - 8 patrones LOCAL: mixed bare+param, both params, generic, optional, multi_params, params+modifiers
  - IR identico a Python en 8 casos
  - Trio: 625 passed

### Sesion B179

- Version interna objetivo: `v0.30.6-internal.b.179.1`
- Estado: `closed`
- Objetivo: flow_params + referential modifiers (as, within, constrained_by) locales sin delegacion
- Alcance cerrado:
  - extendido `_match_native_parameterized_flow_run_program` con kwargs `available_personas/contexts/anchors`
  - agregados checks referenciales (as, within, constrained_by) antes de non-referential
  - modificado `_match_structural_prefixed_native_success_program` para intentar param flow cuando bare falla
  - fix pre-existente: validacion de endpoints en structural prefix success path
  - 3 patrones LOCAL: param+as, param+within, param+constrained_by
  - IR identico a Python en 3 casos
  - Trio: 656 passed (+31 vs B178, incluye fix de bug pre-existente en endpoint shield validation)

### Sesion B180

- Version interna objetivo: `v0.30.6-internal.b.180.1`
- Estado: `closed`
- Objetivo: cerrar multi_flow + referential modifiers
- Alcance cerrado:
  - Extendido `_match_native_multi_flow_run_program` con kwargs `available_personas`, `available_contexts`, `available_anchors` y checks referenciales per-run
  - Agregado tercer fallback multi-flow en `_match_structural_prefixed_native_success_program`
  - 5 patrones LOCAL: multi+as, multi+within, multi+constrained_by, multi+param+as, multi+param+within
  - IR identico a Python en 5 casos
  - Tests: facade (5 cases), CLI check (3 cases), CLI compile (1 case)
- Resultado: 659 passed in 404.45s (trio), +3 vs B179, CHECK 5/5

### Sesion B181

- Version interna objetivo: `v0.30.6-internal.b.181.1`
- Estado: `closed`
- Objetivo: cerrar flow_body con empty steps
- Alcance cerrado:
  - Creado helper `_parse_native_flow_body` para parsear cuerpos de flow con step blocks
  - Modificado `_match_native_multi_flow_run_program` y `_match_native_parameterized_flow_run_program` para usar el body helper
  - Eliminado guard `if not params` del parametrizado para habilitar flujos con body pero sin params
  - 4 patrones LOCAL: flow_body_step, flow_body_multi_step, prefix+flow_body_step, multi_flow_body
  - IR identico a Python en 5 casos
  - Tests: facade (4 cases), CLI check (3 cases), CLI compile (1 case)
- Resultado: 662 passed in 407.62s (trio), +3 vs B180, CHECK 5/5

### Sesion B182

- Version interna objetivo: `v0.30.6-internal.b.182.1`
- Estado: `closed`
- Objetivo: shield con campos y compute como prefix blocks
- Alcance cerrado:
  - shield con campos (single/multi field) ahora LOCAL cuando se combina con flow+run
  - compute reconocido como prefix block kind (empty y con campos)
  - 4 patrones nuevos LOCAL: shield_fields+flow+run, prefix+shield_fields+flow+run, compute_empty+flow+run, compute_fields+flow+run
  - IR equivalencia verificada para 6 casos
- Evidencia: `axon/compiler/frontend.py`, `tests/test_frontend_facade.py`, `tests/test_cli.py`
- Trio: 665 passed in 361.66s (+3 vs B181)

### Sesion B183

- Version interna objetivo: `v0.30.6-internal.b.183.1`
- Estado: `closed`
- Objetivo: standalone prefix-only declarations sin flow+run manejados localmente
- Alcance cerrado:
  - Caracterizacion exhaustiva con DelegateDetector probe (31 casos)
  - Corte: programas con solo bloques prefix (persona, context, anchor, intent, memory, tool, shield, compute) sin flow+run
  - Bug prefix lexer: `scan_all_tokens()` no incluye EOF — condicion ajustada a `len(run_tokens) == 0`
  - Fix IR: IRToolSpec con `effect_row=()` para matching PY (8 constructores)
  - 3 tests existentes actualizados de `allows_*_to_delegate` a `handles_*_locally`
  - 13 patrones nuevos LOCAL con IR verificado identico a Python
- Evidencia: `axon/compiler/frontend.py`, `tests/test_frontend_facade.py`, `tests/test_cli.py`
- Trio: 706 passed in 339.51s (+41 vs B182)

### Sesion B184

- Version interna objetivo: `v0.30.6-internal.b.184.1`
- Estado: `closed`
- Objetivo: eliminar delegacion de dataspace y axonstore
- Alcance:
  - dataspace y axonstore agregados como block kinds del parser structural prefix
  - 10-tuple → 12-tuple (dataspaces, axonstore_specs)
  - handlers: _append_structural_success_dataspace_declaration, _append_structural_success_axonstore_declaration
  - source_line fix: min() across all declarations including dataspaces
  - axonstore_specs propagado a 3 constructores de IRProgram + _collect_structural_available_declarations
- Resultado: DELEGATED ok=True eliminado por completo (0 restantes)
- Trio: 3236 passed, 21 skipped, 0 failed
- Archivos: frontend.py, test_frontend_facade.py
- Criterio de terminado: CHECK 5/5

### Sesion B185

- Version interna objetivo: `v0.30.6-internal.b.185.1`
- Estado: `closed`
- Objetivo: fix crash regression de B184 en scanners de validacion/duplicados
- Alcance:
  - `_append_structural_duplicate_declaration`: agregado early-return para "dataspace" y "axonstore" antes del fallback anchor
  - `_append_structural_validation_declaration`: idem
  - sin este fix, `axonstore+flow+run` y `dataspace+flow+run` causaban `AttributeError: 'IRAxonStore' object has no attribute 'on_violation'`
  - caracterizacion exhaustiva confirma 0 DELEGATED ok=True restantes; todos los ok=False son errores de sintaxis genuinos
- Resultado: crash eliminado, diagnosticos identicos ND==PY
- Trio: 3237 passed, 21 skipped, 0 failed (+1 vs B184)
- Archivos: frontend.py, test_frontend_facade.py
- Criterio de terminado: CHECK 5/5

### Sesion B186

- Version interna objetivo: `v0.30.6-internal.b.186.1`
- Estado: `ready`
- Objetivo: profundizar siguiente dimension del nucleo nativo
- Alcance:
  - delegacion completamente eliminada (0 DELEGATED ok=True)
  - opciones: (a) profundizar body parsing (axonstore con campos, dataspace con entidades), (b) explorar nuevos tipos de patron, (c) otra dimension del nucleo
- Criterio de terminado:
  - existe un siguiente corte B186 explicitamente elegido e implementado con evidencia verificable

## Regla de Cierre de Sesion

Una sesion solo se marca como cerrada si alcanza `CHECK = 5/5` en `project/session_current.md`.

## Evidencia de B1

- `docs/phase_b_core_infra_cut.md`

## Evidencia de B2

- `docs/phase_b_frontend_contract.md`

## Evidencia de B3

- `tests/test_frontend_contract_golden.py`

## Evidencia de B4

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`

## Evidencia de B5

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`

## Evidencia de B6

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`

## Evidencia de B7

- `axon/compiler/frontend_bootstrap.py`
- `tests/test_frontend_facade.py`

## Evidencia de B8

- `axon/cli/__init__.py`
- `packaging/axon_mvp_entry.py`
- `tests/test_cli.py`

## Evidencia de B9

- `axon/cli/frontend_runtime.py`
- `packaging/axon_mvp_entry.py`
- `tests/test_packaging_entry.py`

## Evidencia de B10

- `axon/compiler/frontend.py`
- `axon/compiler/frontend_bootstrap.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B11

- `docs/phase_b_native_dev_contract.md`

## Evidencia de B12

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B13

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B14

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B15

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B16

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B17

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B18

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B19

- `axon/compiler/frontend.py`
- `tests/test_frontend_facade.py`
- `tests/test_cli.py`

## Evidencia de B20

- `tests/test_frontend_facade.py`
- `tests/test_cli.py`