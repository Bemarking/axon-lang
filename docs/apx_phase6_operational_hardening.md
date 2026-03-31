# APX Fase 6: Hardening Operacional

Este documento define el cierre operacional de APX para entornos regulados y de alta exigencia.

## 1. Objetivo

Fase 6 introduce mecanismos de enforcement verificable sobre la observabilidad ya construida en Fase 5:

- Gating de compliance por politica configurable.
- Export forense de eventos para archivado y auditoria.
- Interfaces operativas directas en runtime y registry.

## 2. Componentes

- APXObservability:
  - recent_events(limit, event_type)
  - export_events(format) soporta json y jsonl
  - evaluate_compliance(policy)
  - assert_compliance(policy)
- APXCompliancePolicy:
  - require_full_pcc_success
  - max_mec_failures
  - max_blame_faults
  - max_contract_violations
  - max_quarantine_actions
- APXComplianceError: error estructurado de gate fallido.

## 3. Flujo recomendado de operacion

1. Ejecutar resoluciones APX durante el ciclo normal de importacion.
2. Obtener snapshot y compliance report al final del ciclo.
3. Aplicar assert_compliance con politica del entorno.
4. Exportar eventos en jsonl para almacenamiento inmutable.

## 4. Politicas sugeridas

- Desarrollo:
  - max_blame_faults: 5
  - max_contract_violations: 10
  - max_quarantine_actions: null
- Preproduccion:
  - max_blame_faults: 1
  - max_contract_violations: 2
  - max_quarantine_actions: 1
- Produccion regulada:
  - require_full_pcc_success: true
  - max_mec_failures: 0
  - max_blame_faults: 0
  - max_contract_violations: 0
  - max_quarantine_actions: 0

## 5. Evidencia minima para auditoria

- Export jsonl de eventos del periodo.
- Compliance report evaluado contra la politica activa.
- Historial de paquetes en cuarentena y decisiones de resolucion.
- Metricas de latencia/error por operacion APX.
