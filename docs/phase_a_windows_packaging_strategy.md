# Fase A - Estrategia de Empaquetado para Windows

## Objetivo

Elegir una sola estrategia de empaquetado para el ejecutable puente de AXON en Windows.

La decision debe favorecer:

- tiempo corto hacia el primer binario usable
- bajo riesgo operativo
- facilidad de depuracion
- compatibilidad con el MVP actual
- costo razonable de CI y soporte

## Contexto Real del MVP

El primer binario de `Fase A` solo cubre:

- `axon version`
- `axon check`
- `axon compile`
- `axon trace`

Ese recorte importa porque el MVP actual:

- no necesita red
- no necesita llaves API
- no necesita `uvicorn`, `httpx` ni backends opcionales
- no necesita proceso servidor
- no necesita runtime distribuido

La estrategia correcta para `Fase A` no debe optimizar para una plataforma completa. Debe optimizar para llegar rapido a un binario local, usable y soportable.

## Opciones Evaluadas

### Opcion 1 - PyInstaller one-folder

Descripcion:

- empaqueta el entrypoint Python y su runtime en un directorio distribuible
- genera un `axon.exe` mas archivos de soporte al lado

Ventajas:

- tiempo de adopcion corto
- muy buena compatibilidad con CLIs Python existentes
- menor friccion para depurar imports, recursos y fallos de arranque
- evita varios problemas tipicos de extraccion temporal del modo one-file
- encaja bien con el objetivo de ejecutable puente

Desventajas:

- no produce un unico archivo
- el artefacto distribuido es mas grande y menos elegante

Juicio:

- es la opcion mas pragmatica para el primer corte

### Opcion 2 - PyInstaller one-file

Descripcion:

- empaqueta todo en un unico `axon.exe`

Ventajas:

- mejor percepcion visual de "un solo ejecutable"
- distribucion simple para demos puntuales

Desventajas:

- mayor friccion de arranque por extraccion temporal
- soporte y depuracion mas incomodos
- mayor probabilidad de friccion con antivirus y rutas temporales
- empeora la capacidad de diagnostico justo en la fase puente

Juicio:

- atractivo comercialmente, pero mala opcion para el primer paso de ingenieria

### Opcion 3 - Nuitka standalone

Descripcion:

- compila el proyecto Python con una estrategia mas cercana a binario optimizado

Ventajas:

- puede dar artefactos mas robustos y con mejor rendimiento
- reduce parte de la sensacion de "script congelado"

Desventajas:

- build mas pesado
- toolchain mas exigente
- mayor tiempo de iteracion para el primer binario
- complejidad innecesaria para un objetivo puente

Juicio:

- tecnicamente interesante, pero demasiado costoso para A4-A5

### Opcion 4 - Briefcase o alternativas de app packaging

Descripcion:

- empaquetan aplicaciones con orientacion mas cercana a distribucion de app completa

Ventajas:

- pueden ser utiles en distribuciones mas formales de escritorio

Desventajas:

- no estan alineadas con el problema actual
- agregan complejidad estructural sin mejorar el MVP del CLI

Juicio:

- fuera de foco para Fase A

## Decision

La estrategia elegida para `Fase A` es:

`PyInstaller en modo one-folder para Windows.`

## Por que gana esta opcion

Gana porque maximiza lo que importa ahora:

- velocidad hacia un binario usable
- menor riesgo tecnico en el primer corte
- facilidad de inspeccion y depuracion
- encaje natural con un CLI Python ya existente
- menor costo para la sesion A5 y para CI en A9

No gana por elegancia. Gana por probabilidad de exito.

## Decisiones Secundarias Derivadas

### Forma del artefacto

El primer entregable no se trata como "un solo exe" sino como:

- `axon.exe`
- directorio de soporte distribuible junto al ejecutable

Eso sigue cumpliendo el objetivo de producto de `Fase A`: el usuario ya no instala Python ni crea `.venv` para usar AXON.

### Entry point

El empaquetado debe apuntar al CLI MVP existente y no a una superficie mas amplia.

El entry point del primer binario debe exponer solo la historia del MVP validado.

### Reglas de soporte

- primero se soporta Windows
- primero se soporta el modo one-folder
- primero se soportan solo los cuatro comandos MVP

Todo lo demas es expansion posterior.

## Lo que no se decide todavia

Esta sesion no decide:

- si mas adelante habra modo one-file
- si Nuitka entrara en una fase posterior
- si el ejecutable final de produccion sera Rust o hibrido
- como se empaquetaran `run`, `serve` o `deploy`

Esas decisiones pertenecen a sesiones posteriores o a otras fases.

## Criterio de Aceptacion de A4

La sesion A4 queda cerrada cuando:

- existe una sola estrategia elegida
- las alternativas principales quedaron evaluadas
- la decision esta justificada por el objetivo de `Fase A`
- queda claro que el primer build usara `PyInstaller one-folder`

## Resultado

Para `Fase A`, AXON no va a perseguir el binario mas elegante. Va a perseguir el binario con mayor probabilidad de llegar rapido, verde y usable.