# Fase B - Revision Formal de Salida

## Fecha

2026-04-06

## Dictamen

`Fase B` no queda aprobada para cierre todavia y no debe activar `Fase C`.

## Criterios revisados

- existe contrato observable congelado para `axon check` y `axon compile`
- existe selector `native-dev` operativo y cubierto por golden tests
- `axon check` corre sobre core nativo
- `axon compile` corre sobre core nativo
- el frontend core ya no depende estructuralmente de delegacion Python para sus cortes principales
- la siguiente fase puede concentrarse en independencia operacional, no en terminar de portar el frontend core

## Evidencia usada

- `docs/axon_executable_implementation_program.md`
- `docs/phase_b_core_infra_cut.md`
- `docs/phase_b_frontend_contract.md`
- `docs/phase_b_native_dev_contract.md`
- `docs/phase_b_execution_backlog.md`
- `project/session_current.md`
- `axon/compiler/frontend.py`

## Hallazgos de revision y resolucion

### 1. El frente endpoint quedo operativamente cerrado para esta linea

La sesion B148 cerro el ultimo ternario pendiente sobre la pareja operativa `retries + timeout` dentro de `axonendpoint`.

Eso elimina el motivo para seguir creciendo la frontera endpoint por inercia combinatoria.

### 2. El criterio de salida formal de Fase B sigue sin cumplirse

El programa de implementacion de `Fase B` sigue exigiendo `lexer nativo`, `parser nativo`, `type checker nativo`, `CLI nativa para comandos del frontend` y que `axon check` y `axon compile` corran sobre `core nativo`.

Esas condiciones todavia no se cumplen de forma honesta ni completa.

### 3. `native-dev` sigue siendo una ruta de delegacion parcial

El contrato operativo vigente dice explicitamente que `native-dev`:

- hoy delega en Python
- no es una implementacion nativa funcional
- solo puede promoverse cuando deje de delegar, al menos, en lexer, parser, type checker o generacion de IR con evidencia verificable

El codigo actual confirma ademas que `check_source` y `compile_source` todavia pueden caer en `self._delegate` fuera del subset local ya portado.

### 4. El hueco mas importante de Fase B ya no esta en endpoint sino en core directo del frontend

`type_checker.py` sigue clasificado como `core directo del frontend` y la linea `type` aparece repetidamente como frontera mantenida fuera por falta de estrategia explicita.

Seguir ampliando endpoint antes de abrir un corte real sobre `type` o sobre delegacion parser-side agravaria el phase drift: mas superficie externa, pero no mas independencia del core.

## Riesgos residuales no bloqueantes

- la deuda de complejidad en `axon/compiler/frontend.py` sigue presente, pero no es por si sola el gate principal de salida
- si se reabre endpoint con cuaternarios o combinaciones mas anchas antes de atacar `type` o una delegacion parser/type-checker real, `Fase B` puede seguir acumulando cobertura local sin acercarse materialmente a su criterio de salida
- `module_resolver`, `interface_generator` y `compilation_cache` siguen documentados como frontera de compilacion que bloquea la consolidacion completa del frontend nativo

## Decision de gate

La fase no debe cerrarse aun.

`Fase B` ya valido su costura operativa y amplio mucho el subset nativo local, pero todavia no puede afirmar que `axon check` y `axon compile` corren sobre core nativo ni que el frontend core haya dejado atras la dependencia estructural de Python.

Por lo tanto, `Fase B` permanece activa y `Fase C` no debe abrirse todavia.

## Recomendacion operativa

La siguiente sesion no debe seguir por `axonendpoint` salvo evidencia excepcional.

La recomendacion es abrir `B150` como primer corte nativo explicito sobre `type`, empezando por el subset ya congelado como fixture estable desde B14:

- `type RiskScore(0.0..1.0)`
- `type Risk { mitigation: Opinion? }`

Razon:

- pertenece al core directo del frontend, no a una superficie operativa externa
- ataca delegacion real de parser y type checker, no solo combinatoria de shapes endpoint
- ya existe evidencia previa de contrato observable para `range_min`, `range_max` y `optional`
- reusa fixtures y expectativas ya estabilizadas en la fase

## Handoff

La siguiente sesion debe abrir `B150` como corte nativo explicito de `type`, con alcance acotado a rangos escalares y campos estructurados opcionales, y debe medir el avance contra el criterio real de salida de `Fase B`, no contra la expansion adicional de `axonendpoint`.