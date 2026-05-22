---
title: "Visión: bases de datos como efectos tipados — y el co-diseño con SpacetimeDB"
status: 🧭 NORTH-STAR — aporte de lenguaje, post-v2.0.0. NO planificado, NO agendado. Brújula, no plan.
owner: AXON Compiler + Runtime Team
created: 2026-05-22
gating: No se inicia hasta que Fase 40 cierre (axon-enterprise v2.0.0 + pin-cap levantado). Disciplina "Axon for Axon": primero terminamos el silicio puro.
---

# ▶ 0. Por qué existe este documento

El fundador encontró **SpacetimeDB** y vio en él un pariente filosófico de axon.
La intuición es correcta y vale la pena no perderla. Pero la disciplina manda:
esto es un **aporte de lenguaje** para *después* de v2.0.0, no algo que descarrile
el catch-up de enterprise. Este doc captura la visión con honestidad de ingeniero
—incluyendo lo que **NO** vamos a hacer— para diseñar hacia allá sin perder foco.

Relación: [[project_fase_40_plan]] (el catch-up que va primero),
[[feedback_axon_for_axon]] (toda implementación mejora el lenguaje, no a un adopter).

# ▶ 1. La tesis

> **Una base de datos es un efecto tipado, *capability-honest*, capturado por el
> sistema de replay + provenance de axon.**

No un ORM universal. No "una API para todas las bases". Un *efecto* — del mismo
linaje que los 7 backends LLM detrás del `Backend` trait, y de los efectos
algebraicos de Fase 23.

# ▶ 2. Por qué axon está, casi solo en el mundo, posicionado para esto

Axon **ya tiene el ADN**. Esto no es un paradigma nuevo; es extender uno que ya
corre en producción:

| Pieza existente | Qué aporta a la visión |
|-----------------|------------------------|
| **Fase 23 — efectos algebraicos** | Una lectura/escritura externa YA es un efecto con handler tipado. |
| **Fase 11.c / 40.t — replay tokens** | El módulo `replay` modela hoy `effect_name="db_read:customers"` con `inputs_hash`/`outputs_hash`, re-ejecución determinista y detección de divergencia. **Ese es, literalmente, el mecanismo de un reducer de SpacetimeDB.** |
| **7 backends LLM tras `Backend` trait** | El patrón "catálogo cerrado de providers tras una interfaz tipada" ya está probado — se replica como `DataBackend`. |
| **`axon::storage_postgres` + GUC `axon.current_tenant`** | El plano de datos relacional + aislamiento multi-tenant fail-closed ya existe. |
| **FlowEnvelope⟨T⟩ + provenance hash-chained** | El determinismo y la auditabilidad no se rompen al tocar bases mutables: se **preservan**, porque cada efecto externo ya se hashea, audita y reproduce. |

El cuatro-pilares aplicado a datos: el efecto es **tipado** (matemática), el
dispatch es **total/cerrado** (lógica), lo **declarado es lo que corre**
(filosofía), y el backend es **Rust/C nativo** (computación).

# ▶ 3. Nivel 1 — integración: el catálogo `DataBackend`

Pragmático, incremental, construye directo sobre lo que existe. Cada motor
(Postgres, Oracle, IBM DB2, Redis, MongoDB, DynamoDB) implementa una interfaz de
efecto común; cada operación queda capturada por replay/provenance.

**La regla de oro — *capability-honest*, no *capability-faking*:** cada backend
**declara** lo que puede, y el sistema de tipos/efectos hace la diferencia
**explícita** en vez de taparla:

- ¿Transacciones ACID? ¿O consistencia eventual?
- ¿Joins del lado del servidor? ¿Índices secundarios?
- ¿Consistencia fuerte vs. read-your-writes vs. eventual?
- ¿Modelo relacional, documental, clave-valor, wide-column?

Un flow que pide una transacción cross-tabla contra un backend que no la soporta
debe **fallar en compile-time o type-check**, no en runtime con corrupción
silenciosa. Esa es la contribución que nadie más hace bien.

# ▶ 4. Nivel 2 — substrato: el co-diseño con SpacetimeDB (lo realmente potente)

SpacetimeDB **no es "otra SQL a la que conectarse"** — es un *modelo de ejecución*:
la lógica vive *dentro* de la base como **reducers** (funciones transaccionales
deterministas), y los clientes se suscriben a queries con deltas en tiempo real.
Colapsa la frontera app-server/DB.

La pregunta grande, y la que justifica "algo más potente todavía":

> **¿Pueden los flows deterministas de axon compilar a reducers de SpacetimeDB?**

Axon ya compila a IR y tiene runtime determinista. Los reducers son funciones
transaccionales deterministas. Si axon puede *targetear* SpacetimeDB como
substrato transaccional determinista —con Postgres al lado como el plano
relacional clásico— entonces axon deja de ser "un lenguaje que habla con bases"
y pasa a ser "un lenguaje cuyos flows **son** transacciones deterministas
reproducibles sobre un substrato vivo". Eso es investigación, y es exactamente
donde apunta la intuición del fundador.

# ▶ 5. El cementerio que NO vamos a pisar

"Una API para todas las bases" mató a ODBC/JDBC-como-abstracción, a los ORM
"polyglot persistence" y a media docena de productos. **Filtran** porque Mongo,
Redis y Oracle tienen modelos de consistencia, lenguajes de query y semántica
transaccional fundamentalmente distintos. Axon **no fingirá** que son iguales.
La honestidad de los cuatro pilares es justo lo contrario del ORM universal:
hacemos las diferencias *visibles y tipadas*, no invisibles.

# ▶ 6. Cómo sigue siendo "Axon for Axon"

El catálogo `DataBackend` es una **capacidad del lenguaje**, no un parche para un
adopter. Mejora axon como axon: cualquiera que adopte el lenguaje gana
integración multi-base determinista y auditable, independientemente de qué base
use o de cuántos lo adopten. (Founder directive [[feedback_axon_for_axon]].)

# ▶ 7. Aporte hermano diferido — SAML completo nativo

Capturado junto a esta visión por decisión del fundador (2026-05-22). El §40.j
SSO dejó el **`XmlDsigBackend`** detrás de un type-state que hace imposible usar
una aserción SAML sin verificar (anti-XSW, strict binding, anti-XXE/bomb). D15
difirió la *implementación* de ese backend a v2.0.0+ (OIDC cubre la mayoría).

El norte: **SAML completo, nativo en Rust** — verificación XML-DSig vetada
(sin DTD/entidades externas, expansión de entidades acotada, firma envolvente
por ID, timeout + memcap), **no** un binding vendored frágil. Es trabajo cripto
delicado y merece su propia fase, con el mismo rigor que el resto del silicio.
El type-state ya garantiza que diferirlo **no** abre ningún hueco de seguridad.

# ▶ 8. Disciplina

Este documento es una **brújula, no un plan**. No tiene sub-fases, no está
agendado, y **no se toca hasta que Fase 40 cierre** (enterprise v2.0.0 vivo,
pin-cap levantado). Cuando llegue su momento, el Nivel 1 entra como fase de
lenguaje en axon-lang (OSS) + backends BSL en axon-enterprise donde aplique; el
Nivel 2 entra como investigación; el SAML nativo como fase de seguridad en
axon-enterprise. Hasta entonces: terminamos el catch-up.
