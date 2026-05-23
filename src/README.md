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

| Tool | Phase | What it does |
|---|---|---|
| `axon.primitives(filter?)` | **0 ✅** | List every primitive, optionally filtered by category (`cognition` / `cognitive_io` / `data_plane` / `session_types` / `wire` / `operators`) |
| `axon.primitive_doc(name)` | **0 ✅** | Full reference for one primitive: grammar, top-level status, since-version, complete markdown body (semantic constraints + examples + what-it-is-not + see-also) |
| `axon.check(source)` | **1 ✅** | Validate `.axon` source through the same lex → parse → type-check pipeline `axon check` uses. Returns `{ ok, stage, errors[], warnings[], summary }`. `isError: true` flips on a blocking failure so the agent's "go fix it" reflex fires |
| `axon.parse(source)` | **1 ✅** | Parse to IR (JSON). On success returns `{ ok: true, ir: { node_type: "program", personas, flows, … }, … }`; on failure returns the same diagnostic shape as `axon.check` (uniform parser surface for the agent) |
| `axon.examples(topic)` | 2 | Canonical `.axon` programs by topic (healthcare, banking, chat, multi-agent…) |
| `axon.compose(intent)` | 4 | Given a natural-language brief, return a typed scaffold with the right primitives + compliance shields wired |
| `axon.validate_pattern(source, pattern)` | 4 | Check whether a source fragment matches an idiomatic pattern (e.g. "is this a well-formed dual session?") |

### Resources (it can read these)

| URI | What it serves |
|---|---|
| `axon://primitives/{name}` | Same content as `axon.primitive_doc` but as a read-only resource the agent can quote |
| `axon://grammar/top_level` | The full top-level vs. nested table |
| `axon://grammar/ebnf` | The EBNF grammar |
| `axon://logic/flow_composition` | When do you nest in `flow` vs. declare top-level? |
| `axon://logic/session_duality` | The §Fase 41 algebra rules for dual sessions |
| `axon://compliance/{framework}` | What `compliance: [...]` annotations cover which framework |

## Install

```bash
# From inside a clone of the axon-lang repo:
cargo install --path src/axon-emcp
# → `axon-emcp` is installed to ~/.cargo/bin (or %USERPROFILE%\.cargo\bin)
```

The installed binary is **fully self-contained** — Phase 1 vendored the
knowledge corpus into the executable via `include_dir!` at compile time.
No `share/`, no env var, no post-install steps. Verify:

```bash
axon-emcp --help  # (or run it under your agent — it speaks MCP on stdio)
```

Then point your agent's MCP config at it:

```jsonc
// Claude Code: ~/.config/claude-code/mcp.json (or platform equivalent)
// Cursor:      ~/.cursor/mcp.json
// Codex:       ~/.codex/mcp.json
// Continue:    ~/.continue/config.json (under "mcp.servers")
{
  "mcpServers": {
    "axon": {
      "command": "axon-emcp"
    }
  }
}
```

That's it — restart the agent and it will see `axon.primitives`,
`axon.primitive_doc`, `axon.check`, `axon.parse` as callable tools, plus
the `axon://primitives/{name}` resources, plus the onboarding
instructions on connect.

### Hot-editing the corpus (contributors)

If you're contributing to the corpus (`src/knowledge/primitives/*.md`)
and want edits to take effect WITHOUT recompiling:

```bash
# Option A: run from the repo tree — the binary prefers the in-tree
# dev path over the embedded copy automatically.
cargo run --manifest-path src/axon-emcp/Cargo.toml --release

# Option B: point an installed binary at a checkout via env var.
AXON_EMCP_KNOWLEDGE_DIR=/path/to/axon-lang/src/knowledge axon-emcp
```

The corpus-resolution order (first hit wins): `AXON_EMCP_KNOWLEDGE_DIR`
env var → in-tree dev path (`<crate>/../knowledge`) → embedded corpus.

## Status

| Phase | Surface | Status |
|---|---|---|
| **0** | Server spine (stdio JSON-RPC 2.0), knowledge loader, `axon.primitives` + `axon.primitive_doc`, `axon://primitives/{name}` resources, `socket` primitive documented end-to-end | ✅ |
| **1** | `axon.check` (live validation) + `axon.parse` (IR introspection) + embedded corpus (`cargo install` ships self-contained) | ✅ |
| **2** | The 6 **core cognitive primitives** — `persona`, `flow`, `step`, `anchor`, `tool`, `reason` — each backed by a canonical `.axon` example that round-trips through `axon-frontend` end-to-end. Remaining ~60 primitives staged in follow-up 2.x increments. | ◐ in progress |
| **3** | **Reference resources** — `axon://grammar/{top_level\|composition\|ebnf}`, `axon://logic/{flow_composition\|session_duality}`, `axon://compliance/{hipaa\|gdpr\|pci_dss\|sox\|soc2\|fedramp\|gxp\|fisma\|nist_800_53}`. The Catalog now loads `grammar/`, `logic/`, `compliance/` markdown alongside `primitives/`; the resource dispatcher serves all four URI families with structured errors. | ✅ |
| **4** | `axon.compose(intent)` — natural language brief → typed scaffold with correct compliance shields | |
| **5** | MCP prompts (`flow_design`, `shield_design`, `session_design`) | |

The discipline: every primitive added to `src/knowledge/primitives/` is
backed by a passing `cargo test` that exercises a real `.axon` example
through the live `axon-frontend` parser + type-checker. The knowledge
base does not drift from the language — it is checked against the
implementation on every commit. Phase 1 closed the loop: the agent can
now VALIDATE the code it produces, against the same compiler the `axon`
CLI ships.

Phase 2 proved that discipline in practice: the first draft of three
primitive docs contained inaccuracies (`empathic` → `empathetic`, a
non-existent `<Target>` argument on `reason`, an `effects:` row that
did not match the closed catalog). The integration suite under
`src/axon-emcp/tests/phase2_canonical_programs.rs` rejected all three
on first run, exactly as it will reject any future doc that drifts
from the parser.
