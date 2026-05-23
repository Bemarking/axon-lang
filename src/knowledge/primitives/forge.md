---
name: forge
summary: A flow-body block that constructs typed values from sub-step outputs under explicit construction discipline.
category: operators
top_level: false
since: Fase 18
grammar: |
  # Flow-body block (sibling of step). Body is currently parsed
  # structurally (skipped + audited as a unit); the runtime
  # consumes the block as a typed constructor session.
  forge { ... }
---

# `forge`

`forge` is **a flow-body block** that constructs typed values
from sub-step outputs under explicit construction discipline.
Where `step` operations emit one output each and `weave`
braids multiple step outputs into a unified conclusion,
`forge` declares **an explicit construction session** —
"these inputs combine into this typed output, recorded as a
single audit unit".

The Fase 18 §λ-L-E charter introduced `forge` for cases where
the constructor logic is non-trivial enough to deserve its
own audit row but not big enough to merit a sub-flow. Common
patterns: typed-record assembly from heterogeneous step
outputs, multi-source citation bundles, evidence packages.

## Surface

`forge` is **nested** — it appears as a flow-body block
alongside `step`, `if`, `for`, `weave`. It is *not* a
top-level declaration.

```axon
flow AssembleReport(case: CaseId) -> CaseReport {
    step LoadFacts {
        given: case
        ask: "Fetch case facts."
        output: CaseFacts
    }
    step LoadHistory {
        given: case
        ask: "Fetch case history."
        output: CaseHistory
    }
    step LoadRulings {
        given: case
        ask: "Fetch prior rulings."
        output: RulingsList
    }

    # Explicit construction session — the audit chain treats this
    # block as one unit of work, with the three sources cited.
    forge {
        # The block body is structurally parsed today; the runtime
        # consumes it as a typed constructor. Future Fase increments
        # will land typed fields here (e.g. `sources:`, `target:`).
    }

    step Render {
        given: LoadFacts.output
        ask: "Render the final report from the forged record."
        output: CaseReport
    }
}
```

## Anatomy

### Block — `forge { ... }`

The body is **currently parsed structurally** (via
`parse_block_step("forge")`) — the lexer's brace pair
encloses the block, and the parser skips its contents while
recording the block's position. The runtime treats the block
as a typed constructor session; the audit chain records the
block's input set + output type + duration as a single row.

**Future Fase increments will land typed fields** —
`sources:`, `target:`, `format:` — analogous to `weave`'s
structured body. Until then, the block is a marker /
audit-row primitive, not a rich grammar surface.

## Runtime behaviour

`forge` lowers to a `ForgeBlock` IR node carrying only its
source location. At execution:

1. The runtime takes a snapshot of the current flow scope.
2. The block body runs (today: a no-op constructor placeholder
   the runtime treats per its registered handler).
3. The output is bound back into the flow scope.
4. Audit row `forge:<source_loc>:assembled` carries
   `(input_keys, output_type, duration)`.

The audit row's correlation key lets downstream consumers
trace which step outputs contributed to which constructed
value — useful for evidence-citation patterns in regulated
flows.

## What this primitive is NOT

- **Not a `weave`.** Weave declares HOW multiple step outputs
  combine (synthesise / reconcile / rank / consensus); forge
  is a CONSTRUCTOR session — "these become that". Different
  intent.
- **Not a `step`.** A step is one cognitive operation
  producing one typed output via prompting; forge is a
  structural-construction session typically with no LLM
  invocation.
- **Not a top-level declaration.** The parser rejects `forge`
  outside a flow body.
- **Not free of audit cost.** Each forge block emits its own
  audit row even when the body is a placeholder; for very
  hot paths, batch forges across iterations.

## See also

- `axon://primitives/weave` — multi-source aggregation
  counterpart.
- `axon://primitives/step` — single-operation counterpart.
- `axon://primitives/transact` — atomic-mutation block
  counterpart (different intent: forge = construct, transact
  = mutate).
- `axon://primitives/flow` — the parent of every forge block.
