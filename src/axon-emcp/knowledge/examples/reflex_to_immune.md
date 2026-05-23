---
name: reflex_to_immune
title: Fast reflex bound to an immune signal stream
summary: Demonstrates the immune→reflex chain. The `immune` watches an `observe`d signal; the `reflex` fires at a declared epistemic level (`doubt | speculate | believe | know`) and takes an action from a closed catalog.
topic: agents
primitives:
  - fabric
  - resource
  - manifest
  - observe
  - immune
  - reflex
---

// The fastest defensive loop in AXON: observe → immune → reflex.
// reflex fires synchronously (sub-second SLA) when the immune
// signal hits the declared epistemic level OR higher.
// epistemic levels (closed catalog): doubt | speculate | believe | know

fabric ClinicalCloud {
    provider:  aws
    region:    "us-east-1"
    zones:     3
    ephemeral: false
}

resource EHRDatabase {
    kind:            postgres
    endpoint:        "ehr.clinical.internal:5432"
    capacity:        300
    lifetime:        linear
    certainty_floor: 0.95
}

manifest ProductionHealthcare {
    resources:  [EHRDatabase]
    fabric:     ClinicalCloud
    region:     "us-east-1"
    zones:      3
    compliance: [HIPAA]
}

observe ClinicalHealth from ProductionHealthcare {
    sources:         [prometheus, healthcheck]
    quorum:          2
    timeout:         5s
    on_partition:    fail
    certainty_floor: 0.92
}

immune ClinicalVigil {
    watch:       [ClinicalHealth]
    sensitivity: 0.90
    baseline:    learned
    window:      800
    scope:       tenant
    tau:         300s
    decay:       exponential
}

reflex QuarantineExfil {
    trigger:  ClinicalVigil
    on_level: speculate
    action:   quarantine
    scope:    tenant
    sla:      1ms
}
