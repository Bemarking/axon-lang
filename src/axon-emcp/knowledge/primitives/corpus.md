---
name: corpus
summary: A retrieval-ready collection of documents — backs RAG and grounded retrieval with citation provenance.
category: data_plane
top_level: true
since: Fase 36
grammar: |
  # Form (a) — explicit document list (flat corpus, RAG/vector retrieval):
  corpus <Name> {
      documents: [<Doc1>, <Doc2>, ...]      # required for inline corpora
  }

  # Form (b) — MCP-bound shorthand (corpus pulls from a foreign MCP server):
  corpus <Name> from mcp("<server>", "<resource-uri>")

  # Form (c) — MDN corpus graph (§Fase 63, embeddings-free structural navigation):
  corpus <Name> {
      documents: [<Doc1>, <Doc2>, ...]
      relations: [                          # typed weighted edges → MDN graph
          cite(<from>, <to>, <weight>)      # closed catalog; weight ∈ (0,1]
          contradict(<from>, <to>, <weight>)
      ]
      adaptive: true                        # optional — enable the memory endofunctor
  }

  # Form (d) — DYNAMIC store-sourced MDN graph (§Fase 64, a LIVING per-tenant graph):
  corpus <Name> from axonstore {
      documents: <DocStore>(<id_col>, <title_col>)              # rows → nodes
      relations: <EdgeStore>(<from_col>, <to_col>, <etype_col>, <weight_col>)  # rows → edges
      adaptive: true                        # optional — reinforcement persists to the store
  }
---

# `corpus`

`corpus` declares **a retrieval-ready collection of documents**
that flows can ground answers against. Where `memory` is the
cognitive layer's working state and `axonstore` is structured
relational persistence, `corpus` is the **retrieval primitive**
— the source of truth for RAG (retrieval-augmented generation)
patterns and citation-bearing answers.

The corpus surface ships in two forms: an inline document list
(for small, code-tracked corpora — policy documents, FAQ
entries, canonical references) and an MCP-bound shorthand (for
corpora hosted by an external MCP server — typical for large,
externally-curated knowledge bases).

## Surface

`corpus` is a **top-level declaration**. It is *not* nested
inside an axonstore or dataspace.

### Form (a) — Inline document list

```axon
corpus PolicyDocs {
    documents: [PrivacyPolicy, TermsOfService, RefundPolicy]
}
```

### Form (b) — MCP-bound shorthand

```axon
corpus ClinicalGuidelines from mcp("clinical-mcp.internal", "kb://guidelines/2025")
```

The `from mcp("<server>", "<resource-uri>")` form is parsed as a
single-line declaration — no body required. The runtime
connects to the named MCP server at deploy time and treats
its resource URI as the corpus root.

### Form (c) — MDN corpus graph (§Fase 63, embeddings-free)

Add `relations:` (typed weighted edges) and the corpus becomes a
**Multi-Document Navigation (MDN) graph** `C = (D, R, τ, ω, σ)` —
navigated by *relationship*, not by embedding similarity. This is
the **opposite paradigm** from RAG: no vector store, no cosine.

```axon
corpus SessionKnowledge {
    documents: [sess_a, sess_b, sess_c]
    relations: [
        cite(sess_b, sess_a, 0.9)         # sess_b cites sess_a (trust)
        contradict(sess_c, sess_a, 0.7)   # sess_c disputes sess_a (distrust)
        elaborate(sess_c, sess_b, 0.5)
    ]
    adaptive: true                        # navigations learn (memory endofunctor)
}

flow Recall(q: String) -> String {
    navigate SessionKnowledge {
        query: "${q}"
        from:  sess_a       # seed document
        budget: 5           # max documents
        output: hits
    }
    return hits
}
```

A corpus **with** `relations:` is an MDN graph (`navigate <corpus>`
runs the signed-Epistemic-PageRank / ε-informative submodular
traversal — paper `multi_document.md`). A corpus **without**
`relations:` is the flat form (a) above. The two are distinct
retrieval paradigms under one declaration.

### Form (d) — DYNAMIC store-sourced MDN graph (§Fase 64, a living graph)

Form (c) is fixed at deploy (the documents and edges are literals in
the `.axon`). A **living** knowledge graph — one that grows every time
the agent learns something, per tenant — sources its nodes and edges
from **two `axonstore`s** instead: the documents are rows in one store,
the typed edges are rows in another. The graph is rebuilt from the
**live rows at navigate-time**, so a new `persist` = a new node/edge,
with no redeploy. It is per-tenant by inheritance from the store's
column-proof / RLS scope.

```axon
axonstore LtmSummaries {
    backend: postgresql   connection: "..."
    schema { id: Uuid primary_key  summary: Text  created_at: Timestamptz }
}
axonstore LtmEdges {
    backend: postgresql   connection: "..."
    schema { from_id: Uuid  to_id: Uuid  etype: Text  weight: Float }
}

corpus LtmGraph from axonstore {
    documents: LtmSummaries( id, summary )                 # rows → nodes
    relations: LtmEdges( from_id, to_id, etype, weight )   # rows → typed edges
    adaptive: true                                         # learning persists to the store
}

# Ingest = a normal persist (already per-tenant). No new verb.
flow Remember(summary: String) {
    persist LtmSummaries { summary: summary }
    # … a step classifies the typed edges, then persists LtmEdges rows …
}

flow Recall(q: String) -> String {
    navigate LtmGraph { query: "${q}", budget: 5, output: hits }
    return hits
}
```

Two stores because an `axonstore` is **one table**: documents and
edges have different schemas. The edge endpoints (`from`/`to`) must
match the document id column's type. Edges are **explicit** — the flow
writes them (e.g. an LLM step classifies `cite`/`contradict`/`elaborate`
for a new summary); the runtime never *infers* edges (embeddings-free).
With `adaptive: true`, each navigation's edge-weight reinforcement is
**persisted back** to the edge store via an atomic relative update, so
the graph learns across sessions.

## Fields

### `documents:` (required, form a)

A **bracketed list of identifiers** — each name references a
declared `type`, `resource`, or document constant. The
collection is open at the parser level; the runtime resolves
each entry against its document registry.

### `from mcp("<server>", "<uri>")` (required, form b)

Two **string literals** inside `mcp(…, …)`:
- `<server>` — the MCP server slug or hostname.
- `<uri>` — the resource URI exposed by that server.

The form is recognised by the lexer's `from` + `mcp` token
sequence; the parser captures both literals and treats the
corpus as MCP-bound (no body brace).

### `relations:` (optional — §Fase 63, makes the corpus an MDN graph)

A **bracketed list of typed weighted edges** `etype(from, to, weight)`.
`etype` is from the **closed relation catalog** (the type-checker
rejects anything else):

| Polarity | Types | Propagates |
|---|---|---|
| Positive (trust) | `cite`, `elaborate`, `corroborate` | endorsement → `EPR⁺` |
| Negative (distrust) | `contradict`, `supersede` | challenge → `EPR⁻` |
| Neutral (structural) | `depend`, `implement`, `exemplify` | navigability only |

`from`/`to` must be documents declared in `documents:` (invariant
G2); `weight ∈ (0, 1]` (G4). The runtime builds an `mdn::Corpus`
and runs the **signed Epistemic PageRank** + ε-informative
submodular navigation over it. Embeddings-free.

### `adaptive:` (optional — §Fase 63, enables memory)

`adaptive: true` enables the **memory endofunctor**: each
navigation over this corpus reinforces the edges it traversed
(semantic memory) and accumulates a navigation bias (procedural
memory), so later navigations use the memory-modified EPR. Requires
`relations:` — memory deforms the graph's geometry; an edgeless
corpus has nothing to learn (a compile error otherwise).

## Runtime behaviour

`corpus` lowers to a `CorpusDefinition` IR node. At deploy
time, the runtime:

1. **For form (a)** — resolves each document identifier
   against the local document registry; mounts the inline
   collection into the retrieval index.
2. **For form (b)** — opens an MCP client to the named
   server, requests `resources/list` filtered to the URI
   prefix, and proxies retrieval queries through `resources/read`.

Retrieval is exposed via the `retrieve <Corpus>` flow-step
verb (Fase 36): a step body can `retrieve` from a declared
corpus, get back the top-K matches with `(content,
similarity, source_uri)`, and use them to compose an
evidence-backed answer.

Every retrieval emits `corpus:<name>:query` audit rows
carrying `(query, k_returned, latency, top_similarity)`. The
audit chain pairs the query with the eventual answer
downstream — every claim that grounds on retrieved content
can be traced back to its source.

## What this primitive is NOT

- **Not an `axonstore`.** axonstore is for structured,
  mutable, audit-chained records; corpus is for typically
  read-only documents indexed for retrieval.
- **Not a vector store implementation (flat form).** For the
  flat corpus (form a/b), AXON does not run the embedding
  pipeline — that lives in the runtime's retrieval backend
  (chroma, pgvector, weaviate, qdrant). The corpus surface is
  the *declaration*; the embeddings are downstream.
- **MDN form is the opposite — embeddings-free.** A corpus
  WITH `relations:` (form c) is navigated structurally (signed
  EPR / ε-informative traversal), with **no** vector store,
  embeddings, or cosine anywhere. The two forms are distinct
  paradigms (RAG vs. MDN), not variations of one.
- **Not a `memory`.** memory holds agent-written state; corpus
  holds external-curated documents the agent reads from.
- **Not a substitute for source citation.** The corpus
  provides the retrieved content; the flow's `anchor
  require: source_citation` enforces that every claim cites
  it. The two compose.

## See also

- `axon://primitives/axonstore` — relational persistence
  counterpart.
- `axon://primitives/memory` — agent-written working state.
- `axon://primitives/anchor` — `require: source_citation`
  enforces grounding.
- `axon://primitives/mcp` — outbound MCP server bindings.
- `axon://primitives/flow` — `retrieve <Corpus>` is the
  flow-step verb that reads from a corpus.
- `axon://primitives/pix` — single-document structural retrieval
  navigator; `navigate`/`drill`/`trail` operate over a `pix` (tree)
  or a `corpus` graph (MDN).
- `docs/papers/paper_multi_document.md` — the MDN framework
  (signed Epistemic PageRank, ε-informative navigation);
  `paper_memory_augmented_mdn.md` — the `adaptive:` endofunctor.
