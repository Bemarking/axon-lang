---
name: effect_execution_is_mode_invariant
title: "Effects execute structurally — independent of the output mode (`navigate` is not LLM-conditioned)"
summary: "The law that a structural effect verb (`navigate`, `persist`, `mutate`, `retrieve`, `apply: <effect>`, `par`, …) executes its handler the SAME way whether the endpoint streams (SSE) or returns a single JSON response. The output mode is a transport choice; it never changes WHAT runs. A pure-effect flow with no cognitive step never calls the model — and an empty corpus yields an empty result, never a fabricated one."
---

# Effects execute structurally, independent of the output mode

A flow is a graph of **effect nodes**. Some nodes are *cognitive* (an LLM
reasoning step — `step … ask:` / `apply: <Tool>`); most are *structural*
(`navigate` a corpus, `retrieve`/`persist`/`mutate`/`purge` a store,
`remember`/`recall`, `use <Tool>(k=v)`, `par`, control flow). AXON runs
**one executor** over that graph. The endpoint's **output mode** — a
streamed SSE token feed vs a single buffered JSON response — is a choice
of *transport*. It does **not** change which handler runs for a node, nor
its result.

> **The law.** For every node, the effect handler that executes, and the
> value it produces, are **identical** across output modes. Streaming and
> non-streaming differ only in *when bytes reach the client* (live per
> token vs all at once), never in *what executed*.

## Why this is a law, not an implementation detail

`navigate <corpus>` is a **structural graph traversal** (signed-EPR +
ε-informative walk over the MDN graph). It is a pure effect: given the
corpus rows, it deterministically returns the visited documents. **The LLM
backend is irrelevant to it.** A flow that is *only*

```axon
flow Ltm(query: String) -> Docs {
  navigate KnowledgeGraph from query     # structural — no model involved
  return navigate.output
}
```

must execute the traversal and return exactly the documents the graph
contains — in **both** a `transport: sse` endpoint and a plain
JSON-returning one. If the corpus is empty, the honest result is **empty**.

### The failure this law forbids

The error this page exists to prevent: an executor that handles structural
verbs in *one* mode (say, streaming) but, in the *other* mode, falls
through to a generic LLM completion. Then a `navigate` over an **empty**
base does not return "no documents" — the model, handed the prompt,
**fabricates** plausible-looking hits. That is a hallucination produced by
a transport-conditioned executor, and it violates two pillars at once:

- **Philosophy (epistemic honesty)** — a pure-effect flow must never be
  answered by a stochastic kernel. Empty in ⇒ empty out; the runtime does
  not invent evidence.
- **Logic (determinism of effects)** — the same program over the same
  store must produce the same traversal regardless of how the bytes are
  framed on the wire.

## Corollaries

1. **A flow with no cognitive node never calls the model.** If every node
   is structural, no backend key is consulted; the "LLM backend" is not a
   participant. (Contrast `apply: <Tool>` / `step … ask:`, which *are*
   cognitive by construction — see `axon://logic/dispatch_vs_cognition`.)

2. **`par` is genuinely concurrent in every mode.** A `par { … }` block
   fans its branches out concurrently as effects; under streaming the
   branch events are multiplexed (each carries its branch key) rather than
   serialised into a fake order. The *concurrency* is the semantics; the
   *interleaving on the wire* is the honest reflection of it, not a
   client-reassembly burden hidden behind a deterministic façade.

3. **Provenance and epistemics are mode-invariant too.** The audit lineage
   a flow emits (`provenance_events`, `blame_attribution`, the epistemic
   envelope) is derived from the program + the run, not from the framing —
   so it is the same whether the client streamed or polled.

## How to think about it

In operating-system terms: the flow is a process; its effect nodes are
syscalls. Whether you `read()` the process's output as a live stream or
slurp it in one buffer does not change which syscalls the process made or
what they returned. AXON's executor is the kernel; the output mode is the
file-descriptor you chose to read through.

> Choose `transport: sse` when you want tokens live; choose a buffered
> response when you want one payload. Never expect the choice to change the
> answer. If a structural verb seems to behave differently between modes,
> that is a bug in the runtime, not a feature of the transport.

## See also

- `axon://logic/dispatch_vs_cognition` — the *other* axis: a structural
  tool CALL (`use`) vs cognitive delegation (`apply:`). This page is about
  effects being **mode-invariant**; that page is about **call vs
  cognition**.
- `axon://primitives/corpus` — `navigate <corpus>` and the MDN graph
  surface (`corpus from axonstore`, `relations:`, `adaptive:`).
