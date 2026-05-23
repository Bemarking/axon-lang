# `axon-emcp`

> The official ℰMCP (Epistemic Model Context Protocol) server for
> [AXON](https://github.com/Bemarking/axon-lang) — a stdio JSON-RPC 2.0
> Model Context Protocol server that exposes the AXON language to AI
> coding agents (Claude Code, Codex, Cursor, Continue, Cline, …).

[![crates.io](https://img.shields.io/crates/v/axon-emcp.svg)](https://crates.io/crates/axon-emcp)
[![docs.rs](https://docs.rs/axon-emcp/badge.svg)](https://docs.rs/axon-emcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## What it does

Any MCP-compatible coding agent that launches `axon-emcp` as a
subprocess gets:

- **6 tools** — `axon.primitives`, `axon.primitive_doc`, `axon.check`,
  `axon.parse`, `axon.compose`, `axon.examples`. Live language
  reference + structured validation through the same `axon-frontend`
  lexer/parser/type-checker the `axon` CLI uses (byte-identical
  diagnostics), plus a curated drift-gated example corpus organised
  by language idea.
- **14+ resources** under `axon://` — full primitive references
  (`primitives/{name}`), grammar maps (`grammar/{top_level|composition|ebnf}`),
  composition logic (`logic/{flow_composition|session_duality}`), and
  per-framework compliance maps (`compliance/{hipaa|gdpr|pci_dss|sox|soc2|fedramp|gxp|fisma|nist_800_53}`).
- **3 prompts** — `flow_design`, `shield_design`, `session_design`.
  Host-surfaced design recipes that drive the agent through a structured
  workflow (`axon.compose` → `axon.primitive_doc` → `axon.check`).

The result: a developer talks to their AI coding agent in natural
language; the agent writes AXON that passes `axon check` on first
try, with the right compliance shields by construction.

## Install

```bash
cargo install axon-emcp
```

The installed binary is **fully self-contained** — the knowledge
corpus (45 primitive docs + 33 templates + 17 idiomatic examples +
grammar/logic/compliance references) is baked into the executable
via `include_dir!` at compile time. No `share/` directory, no env
vars, no post-install steps.

```bash
axon-emcp --help
```

## Configure your agent

Point the agent's MCP config at the installed binary:

```jsonc
// Claude Code:    ~/.config/claude-code/mcp.json
// Cursor:         ~/.cursor/mcp.json
// Codex:          ~/.codex/mcp.json
// Continue:       ~/.continue/config.json (under "mcp.servers")
{
  "mcpServers": {
    "axon": {
      "command": "axon-emcp"
    }
  }
}
```

Restart the agent. The 6 tools, 14+ resources, and 3 prompts now
appear in the agent's surface — the agent will quote them when you
ask it to write AXON.

## Closed-domain composition

```
You: write me a healthcare flow that handles PHI.

Agent: [calls axon.compose(intent: "healthcare flow PHI")]
       ✓ Scaffold returned (axon_check_verdict: well-formed)
       ✓ Domain: healthcare (matched: patient, phi, hipaa, …)
       ✓ Compliance applied: HIPAA, GDPR, GxP, SOC2
       ✓ Primitives used: type, persona, shield, flow, axonendpoint

       Here is your scaffold: …
```

The classifier picks from a **closed 33-domain catalogue** spanning
verticals (healthcare, banking, government, legal, legaltech, fintech,
pharmatech, medic_research), agent patterns (chat_research, chat_tools,
chat_skills, whatsapp, voice, dev, sales_consultive, sales_widget), and
application patterns (workflow_automation, business_intelligence,
corporate_integration, self_learning, document_analysis, ticket_triage,
content_moderation, knowledge_extraction, compliance_monitoring,
recruitment, education, financial_advisor, data_pipeline). Every
template proven to compile through the live `axon-frontend` pipeline.

## Focused examples library

Where `axon.compose` gives you a full-app scaffold by *domain*,
`axon.examples` returns minimal complete programs (~20–60 LOC)
organised by *idea*:

```
You: show me how to use weave correctly.

Agent: [calls axon.examples(primitive: "weave")]
       ✓ Match: weave_braid — Weave braid — composing multiple sub-derivations
       ✓ Topic: composition
       ✓ Primitives: persona, flow, step, weave
       ✓ Source: (verified to compile through axon-frontend)

       Here is the canonical pattern: …
```

Filter on three independent axes (combine freely):

- `name:` — single-example resolution by slug, returns full `.axon`
  source the agent can paste / `axon.check` directly.
- `topic:` — closed 10-entry taxonomy (`composition`, `session_types`,
  `shields`, `effects`, `streaming`, `data`, `agents`, `endpoints`,
  `memory`, `validation`).
- `primitive:` — every example that exercises a given primitive name.

Every example is drift-gated through the same `axon-frontend`
pipeline `axon.check` uses, so what the agent receives is **guaranteed
to compile**.

## Contributor surface

Beyond the MCP server mode (no arguments), `axon-emcp` ships two
contributor-facing subcommands:

```bash
# Scaffold a new primitive doc with frontmatter pre-populated from the
# canonical PRIMITIVE_REGISTRY.
axon-emcp scaffold-primitive <name>

# Aggregate a JSONL telemetry log into a structured snapshot.
axon-emcp telemetry summarize <file>
```

## Telemetry (privacy-first)

Opt-in only — no network egress without an explicit env var:

| Env var | Effect |
|---|---|
| `AXON_EMCP_TELEMETRY_FILE` | Append JSONL events to this path (default: disabled) |
| `AXON_EMCP_DEPLOYMENT_ID` | Correlation tag stamped on every event |
| `AXON_EMCP_TELEMETRY_MAX_SAMPLES` | Latency histogram window per tool (default: 1000) |

Five privacy invariants are enforced by construction:

1. AXON source content is **never** recorded.
2. `axon.compose` intent strings are **never** recorded.
3. Tool error messages are **never** recorded.
4. No remote egress without explicit opt-in.
5. Deployment ID is operator-supplied (default: empty).

The JSONL is OTLP-data-model compatible — downstream pipelines
(Vector / Fluent Bit / otel-collector with the `filelog` receiver)
ingest it and forward as OTLP wire.

## License

MIT. See [the repository](https://github.com/Bemarking/axon-lang) for
the full sources, the knowledge corpus under `src/knowledge/`, and the
contributor guide.
