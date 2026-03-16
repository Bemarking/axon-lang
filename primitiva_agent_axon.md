# Una Primitiva Cognitiva 'Agente' para Axon-lang: De la Teoría de Tipos Dependientes a la Implementación Coinductiva

## Fundamentos Filosóficos y Lógicos de la Agencia

La concepción de un "agente" trasciende la mera descripción de un objeto
computacional; se fundamenta en profundas discusiones filosóficas sobre la
acción, la intención y la cognición
[[106](https://link.springer.com/content/pdf/10.1007/978-94-015-9204-8.pdf)]. En
términos generales, un agente es definido como un ente dotado de la capacidad de
actuar, mientras que la "agencia" es la manifestación de dicha capacidad
[[6](https://plato.stanford.edu/archives/win2016/entries/agency/),
[41](https://plato.stanford.edu/archives/fall2015/entries/agency/),
[51](https://plato.stanford.edu/archives/fall2020/entries/agency/),
[104](https://plato.stanford.edu/archives/fall2019/entries/agency/)]. Esta
definición inicial, aunque precisa, resulta insuficiente para diseñar una
primitiva de lenguaje que deba encapsular razonamiento autónomo, interacción y
persistencia. Para ello, es necesario recurrir a marcos filosóficos más
sofisticados que desglosen la naturaleza de la agencia en componentes
operativos. La filosofía de Michael Bratman ofrece uno de los modelos más
influyentes y aplicables, centrado en la planificación como núcleo de la agencia
racional [[52](https://plato.stanford.edu/entries/action/),
[77](https://www.researchgate.net/publication/326983318_Planning_time_and_self-governance_Essays_in_practical_rationality)].
Según Bratman, la agencia se articula a través de tres facultades
interrelacionadas que constituyen un "conjunto cognitivo"
[[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency)]:
la planitud extendida en el tiempo, la reflexividad y la autorregulación. La
planitud extendida implica que un agente no solo responde a estímulos
inmediatos, sino que formula y mantiene compromisos con planes de acción a largo
plazo. La reflexividad permite al agente evaluar sus planes y acciones en curso,
considerando su coherencia con objetivos más amplios. Finalmente, la
autorregulación es la capacidad de ajustar las acciones y planes en función de
la reflexión y las circunstancias cambiantes. Estos tres pilares proporcionan un
modelo cognitivo robusto para el interior de la primitiva `agente`, alejándola
de un simple bucle de percepción-acción hacia un sistema capaz de deliberación y
adaptación.

La autonomía, un concepto central en la solicitud de investigación, se define en
este contexto no como una independencia absoluta, sino como la capacidad de
actuar desde una comprensión práctica propia
[[7](https://journals.publishing.umich.edu/ergo/article/id/6788/)]. Esto implica
que un agente autónomo posee una representación interna de sí mismo y del mundo
que lo rodea, permitiéndole tomar decisiones informadas sin supervisión externa
constante. Esta representación interna es el vehículo a través del cual se
materializan las facultades bratmanianas. Las arquitecturas de agentes BDI
(Creencia-Deseo-Intención) se inspiran directamente en este marco, donde las
intenciones se modelan como elementos de planes parciales de acción que guían la
conducta del agente
[[107](https://www.researchgate.net/publication/2354157_A_Methodology_and_Modelling_Technique_for_Systems_of_BDI_Agents),
[146](https://arxiv.org/pdf/2004.08144),
[166](https://www.researchgate.net/publication/262580564_Temporal_ST_IT_logic_and_its_application_to_normative_reasoning)].
La formalización de estas intenciones como compromisos hacia el futuro es
particularmente relevante, ya que introduce un componente temporal crucial en la
toma de decisiones
[[131](https://www.sciencedirect.com/science/article/pii/S0004370220300308),
[145](http://www.keithstanovich.com/Site/Research_on_Reasoning_files/WillBBS05.pdf)].
Un agente no solo decide qué hacer ahora, sino qué hará en el futuro y cómo esto
se alinea con sus compromisos actuales. Este modelo se conecta con la noción de
compromiso, tanto consigo mismo como con otros agentes y grupos, como una
capacidad fundamental de los agentes racionales
[[152](https://www.academia.edu/2614094/The_role_of_commitment_in_the_explanation_of_agency_from_practical_reasoning_to_collective_action)].

Una vez establecido el modelo cognitivo interno, la siguiente cuestión es cómo
modelar la interacción del agente con un entorno dinámico y con otros agentes.
Las lógicas modales emergen como el lenguaje matemático ideal para este
propósito, ya que proporcionan herramientas formales para razonar sobre mundos
posibles, relaciones de accesibilidad y estados de información
[[175](https://plato.stanford.edu/archives/win2024/entries/phil-multimodallogic/)].
La lógica epistémica se especializa formalmente en el tratamiento de la
conocimiento y la creencia
[[24](https://plato.stanford.edu/archives/fall2014/entries/logic-epistemic/),
[27](https://plato.stanford.edu/entries/logic-epistemic/)], permitiendo a un
agente razonar sobre lo que él mismo sabe o cree, así como sobre lo que saben o
creen los demás agentes (conocimiento común)
[[2](https://link.springer.com/subjects/epistemic-logic-in-multi-agent-systems),
[69](https://dl.acm.org/doi/abs/10.1007/s10849-008-9071-8)]. Esta distinción es
fundamental en los sistemas multi-agente (MAS), donde una decisión estratégica
puede depender críticamente de saber que otro agente carece de cierta
información [[21](https://dl.acm.org/doi/book/10.5555/208454)]. Por ejemplo, un
agente podría elegir no revelar un secreto precisamente porque sabe que el
conocimiento de ese secreto cambiaría el comportamiento del otro agente. La
lógica temporal, por su parte, proporciona los medios para razonar sobre estados
y eventos a lo largo del tiempo
[[23](https://link.springer.com/content/pdf/10.1007/3-540-49057-4.pdf),
[46](https://logic.pku.edu.cn/docs/20200926180652160117.pdf)], abordando
directamente la exigencia de "persistencia temporal". Permite expresar
propiedades complejas como "el agente siempre mantendrá su objetivo hasta que
sea alcanzado" o "eventualmente, el agente llegará a un estado seguro". La
combinación de ambas, bajo el paraguas de la lógica temporal epistémica (ETL),
ofrece un marco potente para especificar comportamientos de agentes a lo largo
del tiempo, teniendo en cuenta la evolución de su conocimiento
[[78](https://www.researchgate.net/publication/220758593_Formal_Semantics_of_a_Dynamic_Epistemic_Logic_for_Describing_Knowledge_Properties_of),
[153](https://search.proquest.com/openview/91d7a8928ebce36e61d6cff96635ebc4/1?pq-origsite=gscholar&cbl=18750)].

Para capturar la noción de "capacidad de actuar" de una manera más directa y
axiomática, las fuentes apuntan a familias de lógicas de la acción más
avanzadas. La lógica STIT (siglo de hacer), propuesta originalmente en la
filosofía de la acción, es una lógica de la agencia que permite razonar sobre lo
que un agente o un grupo de agentes puede hacer en un momento dado
[[82](https://www.sciencedirect.com/science/article/pii/S1571066106003197/pdf?md5=3e268973215f4ad6c52c3ad39ada9385&pid=1-s2.0-S1571066106003197-main.pdf),
[83](https://hal.science/hal-03470305/),
[97](https://plato.stanford.edu/entries/logic-action/)]. Crucialmente, STIT
distingue entre lo que un agente _puede_ hacer y lo que _hará_. Esta distinción
es vital para modelar capacidades, elecciones estratégicas y responsabilidad
moral o lógica. Su semántica se basa en modelos de posibilidad divididos en
opciones disponibles para cada agente en cada instante, lo que la hace perfecta
para describir el "ejercicio de la capacidad" y analizar escenarios de decisión
[[66](https://dl.acm.org/doi/abs/10.1007/s10849-009-9105-x),
[113](https://www.researchgate.net/publication/220430156_Deontic_epistemic_stit_logic_distinguishing_modes_of_mens_rea)].
Otra familia de lógicas, las Lógicas Dinámicas de la Agencia (DLA), extiende
este análisis a las acciones y sus efectos
[[65](https://dl.acm.org/doi/10.1007/978-3-030-88708-7_6),
[81](https://link.springer.com/article/10.1007/s10849-009-9105-x)]. Permiten
formular expresiones como "después de que el agente A realice la acción α, es
cierto que φ", proporcionando un marco para razonar sobre la transformación del
mundo causada por la agencia. El desarrollo de DLA por van der Hoek y Wooldridge
ha demostrado que incluso la lógica STIT puede ser reconstruida dentro de este
marco más general, demostrando su poder expresivo
[[81](https://link.springer.com/article/10.1007/s10849-009-9105-x)]. La lógica
EDLA (Epistemic Dynamic Logic of Agency) integra explícitamente la
epistemología, permitiendo razonar sobre juegos estratégicos donde los agentes
tienen conocimientos incompletos sobre las capacidades y acciones de los demás
[[64](https://dl.acm.org/doi/10.5555/1814268.1814286)].

Sintetizando estos fundamentos, la primitiva `agente` debe estar anclada en un
sistema lógico híbrido multimodal
[[175](https://plato.stanford.edu/archives/win2024/entries/phil-multimodallogic/)].
En este sistema, los "mundos" de la lógica modal representarían instantes de
tiempo o configuraciones del entorno del agente. Las relaciones de accesibilidad
entre estos mundos no serían arbitrarias, sino que estarían etiquetadas con las
acciones que el agente puede realizar, vinculando directamente la semántica a la
lógica STIT. Además, estas relaciones podrían codificar información sobre el
conocimiento del agente antes y después de la acción, integrando la lógica
epistémica. Esta aproximación lógica proporciona una semántica formal precisa
[[1](https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/download/2427/2318),
[61](https://www.sciencedirect.com/topics/computer-science/formal-language)], lo
que permite al compilador del lenguaje Axon-lang ir más allá de la ejecución
simple y realizar verificaciones de propiedades. Por ejemplo, se podría
verificar si un objetivo especificado en la lógica temporal es alcanzable dadas
las capacidades (expresadas en STIT) y el conocimiento inicial del agente. Este
enfoque fusiona la flexibilidad de la programación con la rigurosidad de la
prueba formal, cumpliendo con el requisito central de priorizar la fidelidad a
los fundamentos lógico-matemáticos.

| Característica del Agente | Fundamento Filosófico/Conceptual                                                                                                                                                                                                                                                                                                  | Herramienta Lógica Formal Asociada                                                                                                                                                                                                                                                                 |
| :------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Capacidad de Actuar       | Definición general de agente [[6](https://plato.stanford.edu/archives/win2016/entries/agency/)]; Planificación Extendida en el Tiempo [[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency)]; Autonomía [[7](https://journals.publishing.umich.edu/ergo/article/id/6788/)] | Lógica STIT (Capacidades) [[82](https://www.sciencedirect.com/science/article/pii/S1571066106003197/pdf?md5=3e268973215f4ad6c52c3ad39ada9385&pid=1-s2.0-S1571066106003197-main.pdf)]; Lógica Dinámica de la Agencia (Acciones) [[81](https://link.springer.com/article/10.1007/s10849-009-9105-x)] |
| Razonamiento Interno      | Intenciones como compromisos [[131](https://www.sciencedirect.com/science/article/pii/S0004370220300308)]; Representación del Mundo [[7](https://journals.publishing.umich.edu/ergo/article/id/6788/)]                                                                                                                            | Lógica Epistémica (Conocimiento y Creencia) [[24](https://plato.stanford.edu/archives/fall2014/entries/logic-epistemic/)]                                                                                                                                                                          |
| Persistencia Temporal     | Naturaleza inherente del tiempo en la agencia [[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency)]                                                                                                                                                                       | Lógica Temporal (CTL, LTL) [[23](https://link.springer.com/content/pdf/10.1007/3-540-49057-4.pdf)]                                                                                                                                                                                                 |
| Interacción Social        | Conocimiento Común [[2](https://link.springer.com/subjects/epistemic-logic-in-multi-agent-systems)]; Estrategia en Juegos [[64](https://dl.acm.org/doi/10.5555/1814268.1814286)]                                                                                                                                                  | Lógica Temporal Epistémica (ETL) [[153](https://search.proquest.com/openview/91d7a8928ebce36e61d6cff96635ebc4/1?pq-origsite=gscholar&cbl=18750)]; Lógica Epistémica Dinámica (EDLA) [[64](https://dl.acm.org/doi/10.5555/1814268.1814286)]                                                         |

## Modelado Matemático y Semántica Computacional de Agentes

Si la lógica formal define qué propiedades y comportamientos un agente puede
tener, la teoría de tipos y la semántica computacional proporcionan el andamiaje
matemático para construir y verificar estas propiedades de manera mecánica
durante el proceso de compilación. La convergencia de estos campos ofrece un
camino claro para diseñar una primitiva `agente` que sea no solo semánticamente
rico, sino también computacionalmente seguro y eficiente. Una de las fronteras
más prometedoras en este ámbito es el uso de tipos dependientes y tipos de
sesión, que han surgido como una respuesta a los desafíos de la programación
concurrente segura y la verificación de protocolos de comunicación
[[19](https://arxiv.org/pdf/1704.07004),
[44](https://arxiv.org/abs/1704.07004)]. Los tipos de sesión son un tipo de
contrato para comunicaciones en sistemas distribuidos, garantizando que los
canales de comunicación sigan un patrón predefinido y eliminando problemas
clásicos como la espera circular por construcción
[[115](https://arxiv.org/pdf/2303.01278),
[117](https://dl.acm.org/doi/pdf/10.1145/2873052)]. Sin embargo, los tipos de
sesión dependientes elevan este concepto a un nuevo nivel, permitiendo que el
propio protocolo de comunicación (es decir, el tipo) dependa de valores
calculados en tiempo de ejecución
[[73](https://www.semanticscholar.org/paper/Dependent-Session-Types-Wu-Xi/4093e3faa5312f3200424094e1b83dadda407824),
[114](https://arxiv.org/pdf/1904.01288)]. Esta capacidad de dependencia es
extremadamente potente para modelar la agencia, ya que permite que el rol y las
capacidades de un agente en una interacción cambien dinámicamente en función de
su estado interno o de los resultados de acciones previas. Por ejemplo, un
agente que comienza una interacción con un tipo de sesión `ClienteSession`
podría, tras completar una transacción exitosa, pasar a tener un tipo
`SoporteTécnicoSession` para solicitar ayuda adicional. Esta capacidad de
tipificación dinámica asegura que las interacciones del agente sean
protocolarmente correctas en todo momento.

Para dar una definición matemática rigurosa a la primitiva `agente`, la
semántica denotacional se presenta como un método superior a la semántica
operacional tradicional
[[75](https://www.researchgate.net/profile/Ugo-Montanari)]. Mientras que la
semántica operacional describe la ejecución de un programa paso a paso, la
denotacional asigna a cada término del lenguaje un objeto matemático abstracto
que representa su significado. Este enfoque es ideal para sistemas complejos e
infinitos, como los agentes interactivos. Un marco matemático particularmente
adecuado para modelar sistemas estatales y reactivos es la coálgebra
[[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6),
[75](https://www.researchgate.net/profile/Ugo-Montanari)]. En este paradigma, un
agente se modela como un sistema de transiciones cuyo comportamiento está
completamente determinado por una función de salida (qué observa) y una función
de transición (cómo cambia de estado ante entradas). La coálgebra proporciona
una base teórica sólida para definir equivalencias de comportamiento, como la
bisimulación, que captura la idea de dos agentes que son indistinguibles en su
interacción con el mundo
[[75](https://www.researchgate.net/profile/Ugo-Montanari)]. Este enfoque
categórico es compatible con la teoría de tipos y la lógica, como se evidencia
en trabajos que conectan la coálgebra con la lógica modal y la lógica de
procesos
[[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6)].

La conexión más profunda entre la lógica y la teoría de tipos reside en la
correspondencia Curry-Howard, que establece una dualidad entre fórmulas lógicas
y tipos de datos, y entre pruebas de fórmulas y programas (términos) que tienen
esos tipos. Esta correspondencia permite ver la construcción de un programa
correcto como la construcción de una prueba de un teorema. Extending this,
linear logic provides a powerful framework for modeling computation as resource
manipulation
[[134](https://www.sciencedirect.com/science/article/pii/S2352220815000851),
[157](https://arxiv.org/pdf/1510.02229)]. In contrast to classical or
intuitionistic logic, linear logic treats propositions as resources that can be
consumed by a proof (a computation). This is highly intuitive for modeling
agency: an agent's action consumes resources (e.g., time, energy, credentials)
and produces new resources (e.g., information, a changed world state). The
principles of linearity—where a resource cannot be arbitrarily copied or
discarded—mirror the physical constraints of the real world and provide a
natural way to reason about effectful computations. The relationship between
linear logic and domain theory further solidifies this connection, showing how
spaces of continuous functions (modeling computations) can be represented within
the logical framework itself
[[29](https://www.sciencedirect.com/topics/computer-science/domain-theory)].

Esta síntesis lógico-matemática sugiere una arquitectura concreta para la
primitiva `agente`. Podría ser modelada como un objeto en un tipo de datos
algebraico definido en un lenguaje con soporte para tipos dependientes. El
estado interno del agente (sus creencias, objetivos, planes) no sería
simplemente un conjunto de campos, sino que estaría intrínsecamente ligado a su
tipo. Sus acciones serían funciones bien tipadas que transforman este estado.
Crucialmente, el tipo del estado resultante de una acción dependería del estado
anterior y de los resultados de la acción misma. Por ejemplo, una acción
`abrir_puerta` podría tener un tipo que especifique que solo es válida si el
estado anterior incluye la creencia `"tiene_llave": True"`, y el estado
resultante tendría la creencia `"puerta_abierta": True"`. La lógica modal
subyacente proporcionaría las reglas para que el compilador verifique que estas
transformaciones de estado son lógicamente consistentes y seguras. El uso de
tipos dependientes y session types permite al compilador realizar verificaciones
de seguridad en tiempo de compilación, como la verificación de protocolos de
comunicación, asegurando que las interacciones del agente sean seguras
[[121](https://arxiv.org/pdf/2105.06973)]. Esta aproximación, conocida como
"correcto por construcción", reduce drásticamente la superficie de error en el
software de agentes, al trasladar la verificación de propiedades de alto nivel
(como la seguridad de la comunicación o la consistencia de los planes) desde el
nivel de prueba manual al nivel de verificación automática del compilador
[[125](https://www.researchgate.net/publication/220445009_Correct-by-Construction_Concurrency_Using_Dependent_Types_to_Verify_Implementations_of_Effectful_Resource_Usage_Protocols),
[154](https://arxiv.org/html/2405.16792v2)].

| Marco Matemático/Lógico | Aplicación en la Primitiva 'Agente'                                                                                                                                                                                                                                                                            | Beneficio Principal                                                                                                                                                                                                                                                                         |
| :---------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Tipos Dependenies       | El estado del agente y los resultados de sus acciones están tipificados, donde el tipo del resultado depende del valor del estado de entrada [[14](https://www.researchgate.net/publication/213877528_Why_Dependent_Types_Matter)].                                                                            | Seguridad de tipos dinámica; Verificación de precondiciones y postcondiciones en tiempo de compilación [[90](https://www.cambridge.org/core/journals/journal-of-functional-programming/article/anf-preserves-dependent-types-up-to-extensional-equality/73FC888A23E5E87BAE16B158ABE349C8)]. |
| Session Types           | La interacción con el entorno y otros agentes se modela como sesiones comunicacionales tipificadas, siguiendo protocolos estrictos [[19](https://arxiv.org/pdf/1704.07004)].                                                                                                                                   | Garantía de libertad de bloqueos y adherencia a protocolos de comunicación en tiempo de compilación [[114](https://arxiv.org/pdf/1904.01288)].                                                                                                                                              |
| Coalgebra               | El comportamiento de un agente se modela como un sistema de transiciones coálgebraico, enfocado en la observación y la evolución del estado [[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6), [75](https://www.researchgate.net/profile/Ugo-Montanari)]. | Modelo matemático abstracto y composicional para sistemas reactivos y estatales; Definición formal de equivalencia de comportamiento.                                                                                                                                                       |
| Lógica Lineal           | Las acciones del agente se modelan como consumidores de recursos, donde las fórmulas lógicas representan recursos que deben ser gestionados correctamente [[134](https://www.sciencedirect.com/science/article/pii/S2352220815000851), [157](https://arxiv.org/pdf/1510.02229)].                               | Razonamiento sobre efectos secundarios, consumo de recursos y estado del mundo de forma explícita y controlada.                                                                                                                                                                             |

## Arquitectura Conceptual de la Primitiva 'Agente'

Basado en la fundamentación filosófica, lógica y matemática, la arquitectura
conceptual de la primitiva `agente` para Axon-lang debe ser un sistema formal
integrado donde la semántica lógica y la seguridad del tipo están
intrínsecamente ligadas. No se trata de una simple estructura de datos, sino de
un actor reactivo y estatal, cuyo comportamiento está gobernado por un conjunto
de reglas lógicas y tipográficas verificables por el compilador
[[28](https://arxiv.org/pdf/2603.08755),
[50](https://arxiv.org/html/2603.08755v1)]. La arquitectura se puede descomponer
en tres componentes principales: el estado cognitivo, el motor de planificación
y deliberación, y el sistema de interacción. El estado cognitivo del agente es
la representación interna de su "mundo mental", encapsulando las facetas
filosóficas de la creencia, el deseo y la intención. Este estado no puede ser
manipulado libremente; cualquier cambio está gobernado por reglas lógicas y
transformaciones tipificadas. Se puede modelar conceptualmente como un tipo de
datos algebraico que contiene conjuntos de fórmulas lógicas que representan sus
creencias y objetivos, y una lista de planes, que a su vez son secuencias de
acciones
[[107](https://www.researchgate.net/publication/2354157_A_Methodology_and_Modelling_Technique_for_Systems_of_BDI_Agents),
[146](https://arxiv.org/pdf/2004.08144)]. Las creencias (`beliefs`) son fórmulas
que el agente acepta como verdaderas sobre el estado del mundo y sobre sí mismo.
Los objetivos (`goals`) son fórmulas que el agente desea que se vuelvan
verdaderas. Los planes (`plans`) son procedimientos o secuencias de acciones que
el agente utiliza para alcanzar sus objetivos, consistentes con la visión de
Bratman de las intenciones como elementos de planes parciales
[[166](https://www.researchgate.net/publication/262580564_Temporal_ST_IT_logic_and_its_application_to_normative_reasoning)].

El motor de planificación y deliberación es el núcleo ejecutor de la agencia. Es
aquí donde las facultades de planificación extendida en el tiempo, reflexividad
y autorregulación de Bratman se materializan como lógica computacional
[[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency)].
Este motor opera sobre el estado cognitivo para generar y actualizar planes. Su
funcionamiento se puede formalizar utilizando lógicas como CTL (Computational
Tree Logic) o LTL (Linear-Time Logic) para especificar propiedades temporales de
los planes, como la garantía de que un objetivo será alcanzado eventualmente o
que una condición de seguridad nunca se violará
[[137](https://www.researchgate.net/profile/Iouri-Kotorov/publication/343592887_Internationalization_Strategy_of_Innopolis_University/links/61dc3cdf323a2268f996298f/Internationalization-Strategy-of-Innopolis-University.pdf),
[146](https://arxiv.org/pdf/2004.08144)]. La deliberación implica evaluar
diferentes cursos de acción posibles, que a su vez se relaciona con la lógica
STIT, que formaliza las opciones de acción disponibles para un agente en un
momento dado
[[82](https://www.sciencedirect.com/science/article/pii/S1571066106003197/pdf?md5=3e268973215f4ad6c52c3ad39ada9385&pid=1-s2.0-S1571066106003197-main.pdf)].
La autorregulación se manifiesta cuando el motor de deliberación revisa los
planes existentes a la luz de nuevas información (nuevas creencias) o de un
cambio en los objetivos, y decide modificar o abandonar planes antiguos en favor
de nuevos. Este proceso de deliberación y planificación no es un acto único,
sino un ciclo continuo que mantiene al agente orientado hacia sus metas en un
entorno dinámico
[[131](https://www.sciencedirect.com/science/article/pii/S0004370220300308)].

El tercer componente, el sistema de interacción, gestiona cómo el agente percibe
y actúa sobre su entorno y otros agentes. Este sistema es responsable de la
reactividad del agente
[[10](https://www.sciencedirect.com/science/article/pii/S1566253525006712)]. Se
encarga de recibir mensajes o percepciones del entorno, actualizar el estado
cognitivo del agente (por ejemplo, añadiendo nueva información a las creencias),
y activar el motor de deliberación para que reaccione. Las acciones del agente,
que son la forma en que interactúa con el mundo, no son simples llamadas a
funciones. Como se propuso en la sección anterior, las acciones son funciones
bien tipadas, posiblemente modeladas con tipos de sesión dependientes, que
transforman el estado del agente de una manera controlada y verificable
[[19](https://arxiv.org/pdf/1704.07004),
[114](https://arxiv.org/pdf/1904.01288)]. Cuando el motor de deliberación genera
una acción para ejecutar (por ejemplo, "abrir puerta"), el sistema de
interacción la ejecuta, lo que provoca una transición de estado en el agente y,
potencialmente, un cambio observable en el entorno. Esta arquitectura modular,
inspirada en las arquitecturas BDI pero con una fundación lógica y tipográfica
mucho más rigurosa, permite una separación clara de preocupaciones entre la
representación del conocimiento, la toma de decisiones y la ejecución física o
digital.

La persistencia temporal del agente es un atributo inherente de esta
arquitectura. Al ser un sistema coálgebraico, su comportamiento se define a
través del tiempo mediante un conjunto de transiciones de estado
[[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6)].
Cada punto en el tiempo corresponde a una instancia del `EstadoAgente`. La
evolución del agente a lo largo del tiempo es simplemente una secuencia de estos
estados, donde cada transición es el resultado de una acción ejecutada. La
formalización de este comportamiento mediante lógica temporal permite al
programador especificar propiedades deseables sobre esta secuencia infinita de
estados, como propiedades de seguridad (invariantes) o de vivacidad
(eventualidades)
[[23](https://link.springer.com/content/pdf/10.1007/3-540-49057-4.pdf)]. Por
ejemplo, se podría afirmar que un agente de servicio al cliente siempre
responderá a una consulta dentro de un tiempo máximo, o que un agente de
navegación nunca visitará un estado de colisión. El compilador, al entender esta
semántica, podría intentar verificar formalmente que el código del agente
satisface estas propiedades, realizando una validación mucho más profunda que la
simple comprobación de tipos estándar. Esta integración de la arquitectura del
agente con un sistema lógico y tipográfico robusto es lo que le confiere su
carácter atómico y fundamental dentro del lenguaje Axon-lang.

| Componente Arquitectónico | Descripción Funcional                                                                                  | Fundamento Teórico Clave                                                                                                                                                                                                                                                                                                              |
| :------------------------ | :----------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Estado Cognitivo          | Encapsula las creencias, objetivos y planes del agente. Es el "mundo mental" que guía la deliberación. | Arquitecturas BDI (Belief-Desire-Intention) [[107](https://www.researchgate.net/publication/2354157_A_Methodology_and_Modelling_Technique_for_Systems_of_BDI_Agents), [146](https://arxiv.org/pdf/2004.08144)]; Modelos de intenciones como compromisos [[131](https://www.sciencedirect.com/science/article/pii/S0004370220300308)]. |
| Motor de Deliberación     | Genera, evalúa y actualiza planes para alcanzar los objetivos, actuando sobre el estado cognitivo.     | Planificación de Bratman (planitud extendida, reflexividad, autorregulación) [[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency), [52](https://plato.stanford.edu/entries/action/)]; Lógica Temporal (CTL, LTL) [[146](https://arxiv.org/pdf/2004.08144)].                   |
| Sistema de Interacción    | Gestiona la percepción del entorno, la ejecución de acciones y la comunicación con otros agentes.      | Lógica STIT (opciones de acción) [[82](https://www.sciencedirect.com/science/article/pii/S1571066106003197/pdf?md5=3e268973215f4ad6c52c3ad39ada9385&pid=1-s2.0-S1571066106003197-main.pdf)]; Tipos de Sesión (protocolos de comunicación) [[19](https://arxiv.org/pdf/1704.07004), [115](https://arxiv.org/pdf/2303.01278)].          |
| Persistencia Temporal     | La evolución del agente a lo largo del tiempo se modela como una secuencia de estados (transiciones).  | Semántica Coálgebraica [[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6), [75](https://www.researchgate.net/profile/Ugo-Montanari)]; Lógica Temporal (propiedades a lo largo del tiempo) [[23](https://link.springer.com/content/pdf/10.1007/3-540-49057-4.pdf)].                |

## Especificación Formal y Derivación Algorítmica

La transición de la arquitectura conceptual a una primitiva implementable
requiere una especificación formal precisa, preferiblemente mediante una
semántica operacional o denotacional, que sirva como la definición matemática
exacta del comportamiento de la primitiva `agente`
[[61](https://www.sciencedirect.com/topics/computer-science/formal-language)].
Esta especificación será la fuente de verdad para el compilador de Axon-lang,
guiándolo en la traducción del código fuente a una máquina virtual o a código
máquina. La semántica denotacional parece ser el enfoque más adecuado para un
sistema tan complejo y reactivo, ya que permite definir el significado de los
constructos de `agente` como objetos matemáticos abstractos, independientemente
de cómo se ejecutan en una máquina específica
[[75](https://www.researchgate.net/profile/Ugo-Montanari)]. Siguiendo la línea
de la coálgebra, podemos modelar el estado de un agente como un coálgebra sobre
un functor que describe su estructura de datos
[[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6)].
Sea `S` el tipo del estado del agente, que incluye sus creencias, objetivos y
planes. El comportamiento de un agente se define por un par de funciones:

1. `obs: S -> O`: La función de observación, que devuelve el estado observable
   del agente (por ejemplo, su posición en el mundo, sus recursos).
2. `step: S -> Action -> S`: La función de transición, que dado un estado actual
   `s` y una acción `a`, produce un nuevo estado `s'`.

Estas dos funciones definen completamente el comportamiento coálgebraico del
agente. La semántica denotacional de un término que crea o manipula un agente
devolvería un objeto matemático que, en última instancia, se interpreta como tal
coálgebra.

Para derivar un algoritmo, podemos utilizar una semántica operacional, que
describe cómo se evalúan los términos paso a paso. Consideremos un fragmento
simplificado del lenguaje Axon-lang que incluye la declaración de un agente y la
ejecución de una acción. La configuración de nuestro sistema de evaluación
contendría el estado global del mundo (`WorldState`), el conjunto de todos los
agentes existentes (`AgentStore`), y el agente actual que se está ejecutando
(`CurrentAgent`). La regla de evaluación para la creación de un agente sería:

`CreateAgent(initial_state)` -> `(new_agent_id, updated_AgentStore)` Donde se
crea un nuevo agente con un identificador único y se añade a la tienda de
agentes, y se inicializa su estado cognitivo.

La regla para la ejecución de una acción por parte de un agente sería más
compleja. Primero, se buscaría el agente en la tienda de agentes. Luego, se
verificaría si la acción solicitada es legal desde su estado actual, una
verificación que involucraría la lógica STIT o una serie de reglas de
precondición extraídas de un tipo de sesión dependiente. Si la acción es legal,
se ejecutaría. Ejecutar la acción implica llamar a la función de transición
`step` mencionada anteriormente, que transforma el estado del agente.
Finalmente, el estado del agente en la tienda de agentes se actualiza con el
nuevo estado. El algoritmo básico sería:

```
function execute_action(agent_id, action_name, arguments):
    // 1. Buscar al agente
    current_state = AgentStore.get_state(agent_id)
    
    // 2. Verificación de precondiciones (simulando tipos dependientes)
    if not action_is_legal(current_state, action_name, arguments):
        throw IllegalActionError("La acción no es legal desde el estado actual.")
    
    // 3. Ejecutar la acción (transformación de estado)
    new_state = transition_function(current_state, action_name, arguments)
    
    // 4. Actualizar el estado del agente
    AgentStore.update_state(agent_id, new_state)
    
    return new_state
```

Este algoritmo ilustra el ciclo fundamental de agencia: buscar, verificar,
ejecutar y actualizar. La verificación de precondiciones es el punto donde la
semántica lógica se integra directamente en el flujo de ejecución. Por ejemplo,
una precondición para la acción `abrir_puerta` podría ser una fórmula lógica
contenida en el conjunto de creencias del agente, como
`exists x. (es_objeto(x) ∧ tiene_llave_para(x))`. El compilador podría haber
verificado estáticamente que esta precondición se cumple antes de que el
algoritmo de ejecución intente ejecutar la acción, pero una verificación
dinámica en tiempo de ejecución proporciona una capa de seguridad adicional.

La especificación formal también debe abordar la interacción. La interacción no
es un evento atómico, sino una conversación modelada por un tipo de sesión. Por
ejemplo, la interacción entre un agente `Cliente` y un agente `Banco` para
transferir fondos podría tener un tipo de sesión que se vea así:
`Cliente -> Banco : { request_transfer(amount, recipient), approve, deny }`.
Este tipo especifica que el cliente inicia la sesión y puede enviar un mensaje
`request_transfer` o aceptar/rechazar una propuesta. El banco, a su vez,
esperaría recibir un `request_transfer` y luego enviaría un `approve` o `deny`.
Un compilador que comprendiera este tipo de sesión podría verificar
estáticamente que el código del cliente nunca intentaría aprobar una
transferencia, y que el código del banco nunca enviaría un `approve` sin antes
recibir una solicitud. Si durante la ejecución se descubriera que el banco no
envía una respuesta, el sistema podría entrar en un estado de error o invocar un
mecanismo de recuperación, como los orquestadores de reintento que se usan en
sistemas resilientes
[[32](https://www.sigplan-www.sigplan.hosting.acm.org/OpenTOC/pldi23.html)]. La
especificación formal, por lo tanto, no solo define el comportamiento individual
del agente, sino también las reglas de cooperación y coordinación que gobiernan
su comportamiento en un sistema multi-agente
[[54](https://www.researchgate.net/publication/2749834_Desire_Modelling_Multi-Agent_Systems_In_A_Compositional_Formal_Framework)].

| Aspecto Formal   | Semántica Denotacional (Coálgebra)                                                                       | Semántica Operacional (Algoritmo)                                        | Justificación Teórica                                                                                                                                                                                         |
| :--------------- | :------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Estado**       | `S` es el dominio del estado. `obs: S -> O`, `step: S x Action -> S`.                                    | Un objeto de datos que contiene creencias, objetivos, planes.            | Modelado de sistemas estatales y reactivos [[30](https://www.cambridge.org/core/books/introduction-to-coalgebra/0D508876D20D95E17871320EADC185C6), [75](https://www.researchgate.net/profile/Ugo-Montanari)]. |
| **Transiciones** | Determinadas por la función `step`. La relación de transición es el grafo del coálgebra.                 | Un bucle de búsqueda, verificación y actualización en un `AgentStore`.   | Ciclo de percepción-planificación-acción de la agencia.                                                                                                                                                       |
| **Verificación** | El compilador verifica que los términos tengan tipos coálgebraicos válidos.                              | El algoritmo de ejecución comprueba precondiciones antes de cada acción. | Combina verificación estática (tipos) y dinámica (ejecución) [[121](https://arxiv.org/pdf/2105.06973)].                                                                                                       |
| **Interacción**  | Las interacciones se modelan como coálgebras que interactúan con el mundo exterior.                      | Mensajes pasados a través de un canal tipificado por tipos de sesión.    | Protocolos de comunicación seguros y libres de bloqueos [[19](https://arxiv.org/pdf/1704.07004), [115](https://arxiv.org/pdf/2303.01278)].                                                                    |
| **Persistencia** | El tiempo se modela como un índice en una familia de coálgebras o como un flujo de cómputo coálgebraico. | El estado del agente se conserva en la `AgentStore` entre ejecuciones.   | Evolución del estado a lo largo del tiempo [[42](https://www.researchgate.net/publication/249882267_Reflection_Planning_and_Temporally_Extended_Agency)].                                                     |

## Prototipo Implementativo en Python y Viabilidad Técnica

Para validar la viabilidad técnica de la primitiva `agente` propuesta, se ha
desarrollado un prototipo funcional en Python. Este prototipo no pretende ser
una implementación completa ni optimizada, sino una demostración conceptual que
simula los principios de la especificación formal y la arquitectura propuesta.
Su objetivo es ilustrar cómo un compilador podría traducir la sintaxis de
Axon-lang para `agente` en una estructura de datos y un conjunto de métodos bien
tipados que manipulan ese estado de acuerdo con las reglas lógicas y de tipos
definidas. El prototipo se centra en tres aspectos clave: la representación del
estado cognitivo del agente, la definición de acciones como métodos que
transforman el estado, y la simulación de la verificación de precondiciones y
postcondiciones, que en un sistema real serían realizadas por un verificador de
tipos dependientes.

La implementación en Python utiliza clases de datos para representar el estado
del agente y sus componentes, como las creencias y los objetivos . El estado
completo del agente se encapsula en la clase `AgentState`, que contiene
conjuntos de creencias (representados como cadenas de texto simplificadas para
la implicación lógica), objetivos y planes. Las acciones se modelan como una
jerarquía de clases heredadas de una clase base `Action`, que define un método
`execute`. Este método toma el estado actual del agente como entrada y devuelve
un nuevo estado del agente junto con un "efecto" que describe lo que ocurrió. La
precondición para que una acción se ejecute se verifica dentro del método
`execute` mismo. Por ejemplo, en la acción `AcquireResource`, se comprueba si la
creencia `"has_key"` está presente en las creencias del agente antes de permitir
la adquisición del recurso. Si la precondición no se cumple, se lanza una
excepción, simulando un error de tipo en tiempo de compilación. Este enfoque,
aunque menos potente que un sistema de tipos dependientes completo, ilustra el
principio de que las transformaciones de estado no son arbitrarias, sino que
están restringidas por reglas lógicas explícitas.

El siguiente es el código del prototipo:

```python
## Simulación de la semántica de la primitiva 'agent' en Python

from typing import Dict, Set, Any, Callable, TypeVar, Generic, List, Tuple
from dataclasses import dataclass
import uuid

## T es el tipo del estado del mundo (entorno)
T = TypeVar('T')

## F es el tipo de las fórmulas lógicas que el agente razona
F = TypeVar('F')

@dataclass
class BeliefSet:
    """Representa el conjunto de creencias de un agente."""
    formulas: Set[str]  # Simplificado: fórmulas como cadenas

    def entails(self, formula: str) -> bool:
        # Lógica de entailment simplificada (implicación lógica)
        # En un sistema real, esto requeriría un prover de primer orden.
        return formula in self.formulas

@dataclass
class GoalSet:
    """Representa el conjunto de objetivos del agente."""
    formulas: Set[str]

@dataclass
class Plan:
    """Un plan es una secuencia de acciones."""
    actions: List[str]

@dataclass
class AgentState(Generic[T]):
    """Estado completo del agente."""
    beliefs: BeliefSet
    goals: GoalSet
    plans: List[Plan]
    world_state: T
    agent_id: str = None

    def __post_init__(self):
        if self.agent_id is None:
            self.agent_id = str(uuid.uuid4())

## Tipos para las acciones (simulando session types y effects)
Effect = TypeVar('Effect')
class Action(Generic[T, Effect]):
    """Clase base para todas las acciones del agente."""
    def __init__(self, name: str):
        self.name = name

    def execute(self, agent_state: AgentState[T]) -> Tuple[AgentState[T], Effect]:
        raise NotImplementedError("Subclases deben implementar execute")

## Ejemplo de una acción específica: AcquireResource
class AcquireResource(Action[T, str]):
    """Ejemplo de acción que depende del estado del mundo."""
    
    def execute(self, agent_state: AgentState[T]) -> Tuple[AgentState[T], str]:
        # Crear copias para no mutar el estado original
        new_beliefs = BeliefSet(agent_state.beliefs.formulas.copy())
        
        # Precondición: El agente debe creer que tiene una llave
        if "has_key" not in new_beliefs.formulas:
            raise Exception(f"Agente {agent_state.agent_id} no tiene la llave para adquirir el recurso.")
        
        # Efecto: Adquiere el recurso y actualiza las creencias
        new_beliefs.formulas.add("has_resource")
        
        new_goals = agent_state.goals
        new_plans = agent_state.plans
        
        # Crear un nuevo estado del agente con las creencias actualizadas
        updated_world_state = agent_state.world_state.copy()
        updated_world_state["resource_acquired"] = True
        
        updated_agent_state = AgentState(
            beliefs=new_beliefs,
            goals=new_goals,
            plans=new_plans,
            world_state=updated_world_state,
            agent_id=agent_state.agent_id
        )
        
        return updated_agent_state, "resource_acquired"

## El 'compilador' en realidad sería un constructor de agentes
class AgentCompiler:
    @staticmethod
    def create_agent(initial_beliefs: Set[str], initial_goals: Set[str], world_state: T) -> AgentState[T]:
        initial_beliefs_obj = BeliefSet(initial_beliefs)
        initial_goals_obj = GoalSet(initial_goals)
        return AgentState(initial_beliefs_obj, initial_goals_obj, [], world_state)

## --- Demo de Uso ---
if __name__ == "__main__":
    print("=== Demo de la Primitiva 'agent' ===")
    
    # 1. Compilar un agente con un estado inicial
    initial_world_state = {"door_locked": True, "resource_available": True}
    initial_beliefs = {"has_key": True, "door_locked": True}
    initial_goals = {"door_locked": False}  # Objetivo: desbloquear la puerta
    
    compiler = AgentCompiler()
    my_agent_state = compiler.create_agent(initial_beliefs, initial_goals, initial_world_state)
    
    print(f"Agente creado con ID: {my_agent_state.agent_id}")
    print(f"Creencias iniciales: {my_agent_state.beliefs.formulas}")
    print(f"Objetivos iniciales: {my_agent_state.goals.formulas}")
    
    # 2. Definir una acción
    acquire_action = AcquireResource("acquire_action")
    
    try:
        # 3. Ejecutar una acción (simulando la ejecución del programa)
        print("\n--- Ejecutando acción 'acquire_resource' ---")
        new_agent_state, effect = acquire_action.execute(my_agent_state)
        
        print(f"Acción '{effect}' exitosa.")
        print(f"ID del Agente: {new_agent_state.agent_id}")
        print(f"Creencias finales: {new_agent_state.beliefs.formulas}")
        print(f"Estado del mundo: {new_agent_state.world_state}")
        
    except Exception as e:
        print(f"Error al ejecutar la acción: {e}")
```

Este prototipo demuestra la viabilidad de la idea central: el estado del agente
es una entidad compleja y persistente que se transforma mediante acciones
explícitas. La lógica de precondiciones y postcondiciones dentro de los métodos
de acción simula la verificación de tipos dependientes y la consistencia lógica.
Si bien Python carece de tipos dependientes nativos, el uso de clases y la
verificación explícita de invariantes dentro de los métodos logra el mismo
objetivo semántico de una manera comprensible. La persistencia del agente se
simula conservando una referencia al objeto `AgentState` entre múltiples
llamadas de ejecución. La interacción con un entorno genérico se maneja a través
de la `world_state`, que se pasa y se actualiza a medida que el agente realiza
sus acciones. La escalabilidad y el rendimiento de una implementación real
dependerían de una optimización significativa, pero el prototipo demuestra que
el modelo conceptual es suficientemente claro para ser implementado. Las
limitaciones inherentes del prototipo, como la simplicidad de la lógica de
implicación y la falta de verificación de tipos estática, subrayan la necesidad
de integrar estos conceptos directamente en el compilador de Axon-lang, donde
pueden ser verificados automáticamente y con mayor eficiencia.

## Síntesis y Recomendaciones para la Integración en Axon-lang

Esta investigación ha culminado en un diseño holístico y rigurosamente
fundamentado para una primitiva cognitiva `agente` destinada a ser integrada en
el lenguaje Axon-lang. El enfoque adoptado, que abarca desde la filosofía de la
acción hasta la teoría de tipos y la semántica computacional, garantiza que la
primitiva no sea un simple agregado sintáctico, sino una unidad atómica con una
semántica profunda y verificable. La síntesis de los hallazgos indica que la
primitiva `agente` debe concebirse como un sistema formal cohesivo, donde la
arquitectura cognitiva, gobernada por principios filosóficos como los de
Bratman, se traduce en un modelo computacional preciso mediante lógicas modales
y una teoría de tipos avanzada. La capacidad de un agente para actuar, razonar
sobre su conocimiento y el de otros, planificar en el tiempo y mantener una
identidad persistente a través de la interacción, se formaliza en una estructura
que el compilador puede analizar y verificar.

La recomendación principal para la integración en Axon-lang es adoptar un
enfoque de "extensión gradual" que introduzca primero los componentes
fundamentales de la primitiva y luego los combine. Primero, el lenguaje debería
incorporar un sistema de tipos dependientes, similar al de Coq o F*, que permita
que los tipos dependan de valores en tiempo de ejecución
[[101](https://link.springer.com/content/pdf/10.1007%2F11737414.pdf),
[154](https://arxiv.org/html/2405.16792v2)]. Este sistema de tipos es la base
sobre la cual se construirá toda la seguridad y expresividad de la primitiva
`agente`. Segundo, se deben introducir tipos de sesión dependientes, que
permitirán a los desarrolladores especificar y verificar protocolos de
comunicación de manera estática
[[74](https://www.researchgate.net/publication/326764653_Multiparty_Dependent_Session_Types_Extended_Abstract),
[114](https://arxiv.org/pdf/1904.01288)]. Tercero, la primitiva `agente` misma
se definiría como un tipo polimórfico en Axon-lang, probablemente utilizando una
sintaxis de registro o clase con campos para las creencias, objetivos y planes.
Las acciones del agente se definirían como funciones o métodos cuyos tipos de
retorno son dependientes del tipo de estado de entrada, simulando así las
precondiciones y postcondiciones lógicas.

Desde el punto de vista del compilador, el trabajo se dividiría en varias
etapas. En la primera fase, el analizador sintáctico y semántico de Axon-lang
reconocería la nueva sintaxis para `agente` y sus acciones. Durante el análisis
de tipos, el verificador de tipos dependientes se encargaría de comprobar que
todas las transiciones de estado son legales según las reglas lógicas y los
protocolos de sesión especificados. Esta etapa podría ser computacionalmente
intensiva, por lo que será crucial encontrar un equilibrio práctico entre la
expresividad del lenguaje lógico y la eficiencia del compilador. En una fase
posterior, el compilador podría realizar análisis más profundos, como la
verificación de propiedades de lógica temporal (model checking) para garantizar
que los agentes satisfacen invariantes de seguridad o vivacidad
[[137](https://www.researchgate.net/profile/Iouri-Kotorov/publication/343592887_Internationalization_Strategy_of_Innopolis_University/links/61dc3cdf323a2268f996298f/Internationalization-Strategy-of-Innopolis-University.pdf)].
La interoperabilidad con el entorno y otros agentes se gestionaría a través de
interfaces bien definidas que expongan el estado observable del agente y acepten
acciones, todo ello protegido por los tipos de sesión.

En conclusión, la propuesta de una primitiva `agente` para Axon-lang,
fundamentada en una interdisciplinaria fusión de filosofía, lógica, matemáticas
y semántica computacional, representa un avance significativo hacia la creación
de lenguajes de programación para sistemas complejos y verificables. Proporciona
un marco para el desarrollo de agentes autónomos y colaborativos que no solo
puedan ejecutar tareas, sino que también puedan razonar sobre sus acciones, sus
conocimientos y sus interacciones con un alto grado de certeza formal. La
implementación de esta visión requerirá un esfuerzo de investigación y
desarrollo considerable, especialmente en la creación de un sistema de tipos
dependientes eficiente y en la integración de herramientas de verificación
lógica en el flujo de compilación. Sin embargo, el potencial de Axon-lang para
convertirse en un lenguaje de programación de segunda generación, capaz de
expresar y verificar nociones complejas de agencia, justifica plenamente este
esfuerzo.
