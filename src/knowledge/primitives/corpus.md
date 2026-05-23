---
name: corpus
summary: A retrieval-ready collection of documents — backs RAG and grounded retrieval with citation provenance.
category: data_plane
top_level: true
since: Fase 36
grammar: |
  # Form (a) — explicit document list:
  corpus <Name> {
      documents: [<Doc1>, <Doc2>, ...]      # required for inline corpora
  }

  # Form (b) — MCP-bound shorthand (corpus pulls from a foreign MCP server):
  corpus <Name> from mcp("<server>", "<resource-uri>")
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
- **Not a vector store implementation.** AXON does not run
  the embedding pipeline — that lives in the runtime's
  retrieval backend (chroma, pgvector, weaviate, qdrant).
  The corpus surface is the *declaration*; the embeddings
  are downstream.
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
