---
name: shield
summary: A composable defence layer — scans inputs/outputs for declared threats with a structured on-breach policy.
category: operators
top_level: true
since: Fase 20
grammar: |
  shield <Name> {
      scan: [<category1>, <category2>, ...]    # required — closed-catalog threat list
      strategy: <canary|classifier|dual_llm|ensemble|pattern|perplexity>  # optional
      on_breach: <deflect|escalate|halt|quarantine|sanitize_and_retry>    # required
      severity: <low|medium|high|critical>                                # required
      quarantine: <ident>                       # optional — quarantine sink
      max_retries: <integer>                    # optional — retry budget on sanitize
      confidence_threshold: <0.0..1.0>          # optional — classifier confidence floor
      allow_tools: [<Tool1>, ...]               # optional — whitelist
      deny_tools: [<Tool1>, ...]                # optional — blacklist
      sandbox: <true|false>                     # optional — force sandboxed execution
      redact: [<field1>, <field2>, ...]         # optional — fields to redact on emission
      log: <ident>                              # optional — audit sink
      deflect_message: "<text>"                 # optional — message on deflect
      taint: <ident>                            # optional — taint tag for downstream
      compliance: [<Tag1>, ...]                 # optional — compliance attestation
  }
---

# `shield`

`shield` declares **a composable defence layer** that scans
inputs and outputs against a closed catalogue of threat
categories, decides per the bound `on_breach:` policy, and
emits structured audit rows. It is the **transform-side
counterpart** to `anchor` (which is a predicate): shields
*mutate* candidates (redact, sanitise, deflect); anchors
*decide* whether candidates are accepted.

A shield binds to one or more wire surfaces — `axonendpoint`,
`socket`, `axonstore`, `resource`, `fabric`, `agent`, `daemon`
— and runs on every emission across that surface. The compose
order is **scan → decide → mutate (or halt) → log**.

## Surface

`shield` is a **top-level declaration**. It is *not* nested
inside another primitive.

```axon
shield PHIShield {
    scan:       [prompt_injection, pii_leak, data_exfil]
    on_breach:  quarantine
    severity:   critical
    redact:     [ssn, dob]
    compliance: [HIPAA, GDPR, SOC2]
}
```

## Fields

### `scan:` (required)

A **bracketed list of identifiers** from the **closed scan
catalogue**
(`axon-frontend::type_checker::VALID_SCAN_CATEGORIES`):

| Category | Detects |
|---|---|
| `prompt_injection` | Injected instructions in user input |
| `jailbreak` | Attempts to override the persona/anchor stack |
| `pii_leak` | PII/PHI/financial data in outputs |
| `data_exfil` | Data exfiltration patterns |
| `model_theft` | Model-extraction probes |
| `social_engineering` | Social-engineering content |
| `hallucination` | Unsupported claims in outputs |
| `toxicity` | Toxic / harmful content |
| `bias` | Biased content detection |
| `code_injection` | Code injection in user input |
| `training_poisoning` | Training-data poisoning patterns |

### `strategy:` (optional)

A **single identifier** from the closed strategy catalogue
(`axon-frontend::type_checker::VALID_SHIELD_STRATEGIES`):

| Value | Detection mechanism |
|---|---|
| `pattern` | Regex / dictionary matching. Cheapest. |
| `classifier` | A trained classifier model. |
| `perplexity` | Outlier detection by language-model perplexity. |
| `canary` | Honeytoken / canary string detection. |
| `dual_llm` | Two-model adversarial check. |
| `ensemble` | Combine multiple strategies under a quorum. |

### `on_breach:` (required)

A **single identifier** from the closed on-breach catalogue
(`axon-frontend::type_checker::VALID_ON_BREACH_POLICIES`):

| Value | Behaviour |
|---|---|
| `halt` | Stop execution; surface a typed error. |
| `quarantine` | Route the candidate to the quarantine sink. |
| `deflect` | Emit the `deflect_message:` instead of the candidate. |
| `sanitize_and_retry` | Apply `redact:` + retry up to `max_retries:`. |
| `escalate` | Hand off to the escalation queue. |

### `severity:` (required)

A **single identifier** from the closed catalogue
(`axon-frontend::type_checker::VALID_SEVERITY_LEVELS`):
`low | medium | high | critical`. Drives the runtime's alert
routing — `critical` invokes the page-the-on-call channel;
`low` lands in periodic-review queues.

### `quarantine:` / `max_retries:` / `confidence_threshold:` / `allow_tools:` / `deny_tools:` / `sandbox:` / `redact:` / `log:` / `deflect_message:` / `taint:` (optional)

Operational dials — most are obvious from their names; the
type checker validates types but not values (open catalogues
at this layer; the runtime gives meaning to the slugs against
its sink + redactor registries).

### `compliance:` (optional)

A **bracketed list of identifiers** from the closed compliance
catalogue. A shield's compliance tags must **cover** the
compliance tags of every surface it binds — a `compliance:
[SOC2]` shield cannot guard a HIPAA-tagged endpoint without
adding HIPAA. The §40 cross-tag check enforces this at deploy
time.

## Composition with anchors

A flow's `run` can carry both:

```axon
run AnalyzeContract(doc)
    constrained_by [NoHallucination, NoPHI]   # anchor stack — predicates
    # …and the bound axonendpoint declares a shield (transforms)
```

The compose order at every emission:

1. **Shield scans** the candidate.
2. If clean → **anchors evaluate** the predicates.
3. If anchors pass → emission proceeds.
4. If shield triggers → `on_breach:` policy runs.
5. If anchor triggers → `on_violation:` policy runs.

The two are orthogonal and compose freely.

## What this primitive is NOT

- **Not an `anchor`.** Anchor is a predicate (`require:`);
  shield is a transform (scan + mutate). Different layers.
- **Not a single-strategy product.** A shield can stack
  multiple `scan:` categories under one `strategy:`; for
  multi-strategy detection, use `strategy: ensemble`.
- **Not free.** Each scan runs on every emission. Heavy
  strategies (`classifier`, `dual_llm`) measurably affect
  latency; declare deliberately.
- **Not a substitute for compliance attestation.** A
  HIPAA-tagged shield enforces shield-level scans; the
  `compliance: [HIPAA]` tag on the bound endpoint + the BAA
  with downstream providers still attest the human / contract
  layer.

## See also

- `axon://primitives/anchor` — the predicate counterpart.
- `axon://primitives/axonendpoint` — `shield:` binding site.
- `axon://primitives/socket` — `shield:` binding site
  (per-frame).
- `axon://primitives/axonstore` — `shield:` binding for
  read/write gates.
- `axon://compliance/hipaa` — example of shield + endpoint
  cross-tag attestation.
