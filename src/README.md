# `src/` — the ℰMCP OFICIAL

> The official MCP server + knowledge base that lets any coding agent
> (Claude Code, Codex, Cursor, Continue, Cline, …) write **professional
> AXON** from natural-language intent.

## Why this exists

AXON was designed for AI agents, not for humans tapping at a keyboard.
Every primitive — `persona`, `flow`, `shield`, `axonendpoint`, `axonstore`,
`socket`, `session`, the lot — was chosen because *an agent driving a
program* benefits from it: typed dialogue, statically-checked compliance,
audit-chained mutations, epistemically-graded retrieval, deadlock-free
sessions. But until v2.3.0 the **agent-facing interface to the language
itself** was the same as the human-facing one: a README, a paper, and a
folder of examples.

`ℰMCP OFICIAL` closes that loop. It is the **Model Context Protocol
server** AI coding agents connect to so they:

1. **Know every primitive precisely** — grammar, top-level vs. nested,
   what compiles vs. what doesn't, idiomatic patterns.
2. **Validate their output live** — `axon.check(source)` returns
   structured diagnostics; an agent can iterate without leaving the
   conversation.
3. **Compose at the right altitude** — `axon.compose(intent)` returns a
   scaffold from a high-level brief: "a healthcare flow that handles PHI"
   becomes a typed `axonendpoint` + `flow` + `shield` skeleton with the
   correct compliance annotations.
4. **Stay grounded** — every answer the server gives is sourced from the
   canonical knowledge base under `src/knowledge/`, which is itself a
   diff-friendly markdown corpus that humans can review and extend.

The result: a developer **talks** to their AI coding agent in natural
language; the agent **writes** AXON that passes `axon check` at the first
try, uses the right compliance shields by construction, and doesn't have
to guess what's top-level vs. what nests inside a `flow`.

## Architecture

```
src/
├── README.md           ← this file
├── knowledge/          ← the canonical source of truth — diff-reviewed
│   ├── primitives/         one markdown file per primitive (65+)
│   │   ├── persona.md
│   │   ├── flow.md
│   │   ├── socket.md       (§Fase 41 — the newest primitive)
│   │   └── …
│   ├── grammar/
│   │   ├── top_level.md    which primitives are top-level vs. nested
│   │   ├── composition.md  the nesting rules
│   │   └── ebnf.md         the official EBNF
│   ├── flow_logic.md       when to use what
│   ├── idioms.md           idiomatic patterns
│   └── examples/           canonical .axon programs
└── axon-emcp/          ← the Rust MCP server (stdio JSON-RPC 2.0)
    ├── Cargo.toml
    └── src/
        ├── main.rs         stdio transport + server loop
        ├── server.rs       MCP protocol handshake + dispatch
        ├── knowledge.rs    loads + indexes src/knowledge/ at startup
        ├── tools/          MCP tools agents can call
        └── resources/      MCP resources agents can read
```

**Two layers**, deliberately:

- **`knowledge/`** — the source of truth. Markdown with structured
  frontmatter. Humans edit it; the server reads it. Adding a primitive
  or correcting a rule is a `.md` diff, reviewable by anyone.
- **`axon-emcp/`** — the runtime. A small, focused Rust binary that
  speaks MCP (stdio JSON-RPC 2.0) and projects the knowledge base into
  the protocol surface. Consumes `axon-frontend` for live validation
  (the same lexer/parser/type-checker the `axon` CLI uses).

This separation matters: **the knowledge base outlives the server**.
Tomorrow's MCP variants, today's plain-prompt agents, an LSP server, a
docs site — they all hydrate from the same `knowledge/`.

## How agents use it

Once installed (see `axon-emcp/README.md` for `mcp.json` snippets per
agent), the agent has access to:

### Tools (it can call these)

| Tool | What it does |
|---|---|
| `axon.check(source)` | Validate a string of `.axon` source; returns structured diagnostics (rustc-style spans, error codes, suggestions) |
| `axon.parse(source)` | Parse to AST + IR (JSON); useful for the agent to *reason about* what it just wrote |
| `axon.primitives(filter?)` | List every primitive, optionally filtered by category (cognition / cognitive-io / session-types / data-plane) |
| `axon.primitive_doc(name)` | Full reference for one primitive: grammar, top-level status, semantic constraints, idiomatic examples |
| `axon.examples(topic)` | Canonical `.axon` programs by topic (healthcare, banking, chat, multi-agent…) |
| `axon.compose(intent)` | Given a natural-language brief, return a typed scaffold with the right primitives + compliance shields wired |
| `axon.validate_pattern(source, pattern)` | Check whether a source fragment matches an idiomatic pattern (e.g. "is this a well-formed dual session?") |

### Resources (it can read these)

| URI | What it serves |
|---|---|
| `axon://primitives/{name}` | Same content as `axon.primitive_doc` but as a read-only resource the agent can quote |
| `axon://grammar/top_level` | The full top-level vs. nested table |
| `axon://grammar/ebnf` | The EBNF grammar |
| `axon://logic/flow_composition` | When do you nest in `flow` vs. declare top-level? |
| `axon://logic/session_duality` | The §Fase 41 algebra rules for dual sessions |
| `axon://compliance/{framework}` | What `compliance: [...]` annotations cover which framework |

## Install (preview)

```jsonc
// In your agent's mcp.json (Claude Code, Codex, Cursor, …)
{
  "mcpServers": {
    "axon": {
      "command": "axon-emcp",
      "args": []
    }
  }
}
```

```bash
cargo install --path src/axon-emcp
# or: download the binary from a future GitHub release
```

## Status

This is **Phase 0 of the ℰMCP OFICIAL** — the spine is up (server
skeleton, knowledge-base structure, one primitive documented
end-to-end). The full primitive catalog (65+ files) lands in subsequent
phases. See `src/axon-emcp/README.md` for development status.

The discipline: every primitive added to `src/knowledge/primitives/` is
backed by a passing `cargo test` that exercises a real `.axon` example
through the live `axon-frontend` parser + type-checker. The knowledge
base does not drift from the language — it is checked against the
implementation on every commit.
