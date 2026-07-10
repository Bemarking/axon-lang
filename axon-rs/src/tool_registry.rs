//! Tool registry — extensible tool dispatch for AXON execution.
//!
//! The `ToolRegistry` collects tool definitions from two sources:
//!   1. Built-in tools: Calculator, DateTimeTool (always available)
//!   2. Program-defined tools: declared via `tool Name { ... }` in .axon files
//!
//! When a `use_tool` step fires, the runner queries the registry:
//!   - Built-in tools execute natively (no LLM call)
//!   - Program-defined tools with known providers execute via provider adapters
//!   - Unknown tools fall through to LLM dispatch
//!
//! Provider adapters:
//!   - "native"  → built-in Calculator/DateTimeTool
//!   - "stub"    → returns a stub response (for testing/development)
//!   - "http"    → REST endpoint via reqwest (URL in runtime field)
//!   - "mcp"     → ℰMCP transducer (JSON-RPC 2.0 + blame + taint)
//!   - others    → fall through to LLM (future: gRPC, etc.)

use std::collections::HashMap;

use crate::emcp;
use crate::http_tool;
use crate::ir_nodes::IRToolSpec;
use crate::tool_executor::{self, ToolResult};

// ── Tool entry ─────────────────────────────────────────────────────────────

/// A registered tool with its metadata and dispatch configuration.
#[derive(Debug, Clone)]
pub struct ToolEntry {
    pub name: String,
    pub provider: String,
    pub timeout: String,
    pub runtime: String,
    pub sandbox: Option<bool>,
    pub max_results: Option<i64>,
    pub output_schema: String,
    pub effect_row: Vec<String>,
    /// §Fase 58.f.2 — the tool's typed INPUT SCHEMA (D1) as resolved
    /// `(param_name, type_name)` pairs, populated from
    /// `IRToolSpec.parameters` at [`ToolRegistry::register_from_ir`].
    /// The streaming dispatcher's `run_use_tool` reads this to coerce
    /// each `use Tool(k = v, …)` arg to its declared JSON type — the
    /// SAME `coerce_tool_arg_value` discipline the synchronous server
    /// path (§58.e/58.f) applies via `CompiledStep.tool_param_types`.
    /// Empty for a schema-less tool (D5) and for the built-ins.
    pub parameters: Vec<(String, String)>,
    /// §Fase 94.c — the per-tenant secret KEY injected into every dispatch
    /// of this tool under the reserved `axon_secret` request field
    /// (`rotation_without_revelation`). Populated from `IRToolSpec.secret`
    /// at [`ToolRegistry::register_from_ir`]. Empty = no injection (every
    /// pre-§94 tool and the built-ins). The dispatch handlers resolve the
    /// key against the `SecretCustody` port — fail-closed when the key is
    /// set and no custody is attached.
    pub secret: String,
    /// §Fase 95.a — the `secret_partition:` parameter name
    /// (`selection_without_revelation`). Populated from
    /// `IRToolSpec.secret_partition`. When non-empty, the dispatch handlers
    /// read this parameter's resolved value from the structured tool body,
    /// validate it to a single dot-free key segment, and append it to
    /// [`secret`] before the custody lookup — so one tool serves N
    /// sub-tenants while the resolved key never leaves `secret`'s class.
    /// Empty = the §94 static-key behaviour. Meaningless without `secret`
    /// (`axon-T903`); inert for the built-ins.
    pub secret_partition: String,
    pub source: ToolSource,
    /// §Fase 34.c (v1.29.0) — Whether this tool is a stream
    /// producer. Auto-derived at registration time from
    /// `effect_row` via [`derive_is_streaming`] when the tool comes
    /// from the IR (`register_from_ir`). Adopters programmatically
    /// registering tools via [`ToolRegistry::register`] set this
    /// flag explicitly (or use [`derive_is_streaming`] for the
    /// canonical rule).
    ///
    /// The dispatcher's `pure_shape::run_step` (Fase 34.d) reads
    /// this flag to decide whether to route through the streaming
    /// path (`tool.stream(args, ctx)`) or the synchronous path
    /// (`tool.execute(args, ctx)`). Built-in tools default to
    /// `false`; tools declaring `effects: <stream:<policy>>` in
    /// their AST get `true` automatically.
    pub is_streaming: bool,
    /// §Fase 98.b — the resolved web-acquisition config for a tool whose
    /// `provider:` is `scrape_http` / `scrape_dom` / `scrape_crawl`.
    /// Populated from `IRToolSpec.scrape` at
    /// [`ToolRegistry::register_from_ir`]; `None` for every non-scrape tool
    /// and the built-ins. The scrape dispatch (`crate::scrape_tool`) reads
    /// it to select the engine, extraction specs, and crawl bounds. Both
    /// the synchronous (`dispatch`) and streaming (`resolve_streaming_tool`)
    /// paths receive the `&ToolEntry`, so the config reaches both.
    pub scrape: Option<ScrapeConfig>,
}

/// §Fase 98.b — the runtime mirror of `ir_nodes::IRScrapeSpec`: the closed
/// web-acquisition configuration a scrape tool dispatches with. Owned +
/// `Clone` so a `ToolEntry` stays cheap to clone into a request-scoped
/// registry. Every field defaults to its inert form so a bare `scrape: {}`
/// tool is well-formed. See [`crate::scrape_tool`] for how each field
/// steers dispatch.
#[derive(Debug, Clone, Default)]
pub struct ScrapeConfig {
    /// `impersonate` (HTTP-fingerprint stealth; the OSS fallback is plain
    /// `reqwest`) | `browser` (headless-render sidecar). Empty ⇒ default
    /// `impersonate` (D98.3).
    pub engine: String,
    /// The declared impersonation fingerprint profile (`chrome`/…). Empty ⇒
    /// engine default. Consumed by the enterprise engine (§98.g).
    pub impersonate: String,
    /// Browser-tier post-navigation settle wait (a Duration string).
    pub render_wait: String,
    /// Per-tenant proxy-pool config KEY (resolved via SecretResolver).
    pub proxy: String,
    /// Whether `robots.txt` is honored (default TRUE — D98.6).
    pub respect_robots: bool,
    /// `scrape_dom` extraction FieldSpecs, each `name=selector`.
    pub extract: Vec<String>,
    /// `scrape_dom` adaptive relocation toggle (heuristic — D98.4).
    pub adaptive: bool,
    /// `scrape_dom` adaptive similarity threshold ∈ [0,1].
    pub similarity_floor: f64,
    /// `scrape_crawl` link-follow selector.
    pub follow: String,
    /// `scrape_crawl` maximum link depth (bounded — D98.11).
    pub max_depth: i64,
    /// `scrape_crawl` maximum total pages (bounded — D98.11).
    pub max_pages: i64,
    /// `scrape_crawl` fetch concurrency.
    pub concurrency: i64,
    /// `scrape_crawl` politeness budget reference (§72 budget kernel).
    pub politeness: String,
    /// `scrape_crawl` checkpoint store reference (resumable crawls).
    pub checkpoint: String,
}

impl ScrapeConfig {
    /// §Fase 98.b — resolve an `IRScrapeSpec` into the runtime config,
    /// applying the documented defaults (engine ⇒ `impersonate`,
    /// `respect_robots` ⇒ true, `concurrency` ⇒ 1).
    pub fn from_ir(spec: &crate::ir_nodes::IRScrapeSpec) -> Self {
        ScrapeConfig {
            engine: spec.engine.clone().unwrap_or_default(),
            impersonate: spec.impersonate.clone().unwrap_or_default(),
            render_wait: spec.render_wait.clone().unwrap_or_default(),
            proxy: spec.proxy.clone(),
            // Default-secure: robots honored unless explicitly disabled.
            respect_robots: spec.respect_robots.unwrap_or(true),
            extract: spec.extract.clone(),
            adaptive: spec.adaptive.unwrap_or(false),
            similarity_floor: spec.similarity_floor.unwrap_or(0.0),
            follow: spec.follow.clone(),
            max_depth: spec.max_depth.unwrap_or(0),
            max_pages: spec.max_pages.unwrap_or(0),
            concurrency: spec.concurrency.unwrap_or(1),
            politeness: spec.politeness.clone(),
            checkpoint: spec.checkpoint.clone(),
        }
    }

    /// Whether the effective engine is the browser (sidecar) tier.
    pub fn is_browser(&self) -> bool {
        self.engine == "browser"
    }

    /// The effective engine slug, applying the `impersonate` default.
    pub fn effective_engine(&self) -> &str {
        if self.engine.is_empty() {
            "impersonate"
        } else {
            &self.engine
        }
    }
}

/// §Fase 34.c (v1.29.0) — Canonical derivation rule for the
/// [`ToolEntry::is_streaming`] field.
///
/// A tool is a stream producer iff at least one entry in its
/// `effect_row` begins with the `stream:` slug prefix. This is the
/// AST-level structural signal the paper §3-§6 defines:
/// `effects: <stream:<policy>>` on a tool declaration means "this
/// tool is a stream producer with backpressure policy ⟨policy⟩".
///
/// The closed-catalog `<stream:<policy>>` payloads are
/// `{drop_oldest, degrade_quality, pause_upstream, fail}` per
/// Fase 33.e; new policies require a deliberate sub-fase. The
/// derivation rule itself is policy-agnostic — any `stream:` slug
/// flags the tool as a stream producer.
///
/// # Cross-stack contract (D10)
///
/// The Python mirror lives in `axon.runtime.tools.streaming`
/// (Fase 34.b). Both stacks check the same prefix predicate; the
/// drift gate `tests/test_fase34_c_registry_drift_cross_stack.py`
/// pins the 1-to-1 contract.
pub fn derive_is_streaming(effect_row: &[String]) -> bool {
    effect_row.iter().any(|e| e.starts_with("stream:"))
}

/// §Fase 58.g — resolve a tool's declared `runtime` into a concrete
/// dispatch URL against a per-tenant / per-server **base URL** (D7).
///
/// The resolution rule (config-driven provider→endpoint, never
/// hardcoded in the compiler):
///
/// - An ALREADY-ABSOLUTE `runtime` (`http://…` / `https://…`) is used
///   verbatim — the program pinned its own endpoint (D5 back-compat).
/// - Otherwise the declared `runtime` is treated as a **slug / path**
///   and joined onto `base_url`: `{base}/{slug}`. An empty `runtime`
///   falls back to the tool's name as the slug, so a `tool Crm {
///   provider: http }` with no `runtime:` resolves to `{base}/Crm`.
/// - An empty `base_url` is a no-op (returns `runtime` unchanged) — the
///   adopter hasn't wired a tool-server, so a relative runtime stays
///   relative and the dispatcher surfaces the actionable "no/invalid
///   endpoint URL" diagnostic.
///
/// Leading/trailing slashes are normalised so the join never produces a
/// `//` or a missing separator.
pub fn resolve_tool_endpoint(runtime: &str, tool_name: &str, base_url: &str) -> String {
    let rt = runtime.trim();
    if rt.starts_with("http://") || rt.starts_with("https://") {
        return runtime.to_string();
    }
    let base = base_url.trim().trim_end_matches('/');
    if base.is_empty() {
        return runtime.to_string();
    }
    let slug = if rt.is_empty() { tool_name } else { rt };
    let slug = slug.trim_start_matches('/');
    if slug.is_empty() {
        base.to_string()
    } else {
        format!("{base}/{slug}")
    }
}

/// Where the tool was defined.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolSource {
    /// Built-in tool (Calculator, DateTimeTool).
    Builtin,
    /// Defined in the AXON program via `tool Name { ... }`.
    Program,
}

// ── Tool registry ──────────────────────────────────────────────────────────

/// Central registry for all available tools during execution.
#[derive(Debug)]
pub struct ToolRegistry {
    tools: HashMap<String, ToolEntry>,
}

impl ToolRegistry {
    /// Create a new registry pre-loaded with built-in tools.
    pub fn new() -> Self {
        let mut registry = ToolRegistry {
            tools: HashMap::new(),
        };
        registry.register_builtins();
        registry
    }

    /// Register the built-in native tools.
    fn register_builtins(&mut self) {
        self.tools.insert(
            "Calculator".to_string(),
            ToolEntry {
                name: "Calculator".to_string(),
                provider: "native".to_string(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                max_results: None,
                output_schema: "number".to_string(),
                effect_row: vec!["compute".to_string()],
                // §Fase 58.f.2 — built-ins declare no typed input schema;
                // they accept the legacy positional `on <arg>` form.
                parameters: Vec::new(),
                secret: String::new(),
                secret_partition: String::new(),
                source: ToolSource::Builtin,
                // §Fase 34.c — Calculator declares `compute` effect only.
                // No stream effect → is_streaming = false.
                is_streaming: false,
                scrape: None,
            },
        );
        self.tools.insert(
            "DateTimeTool".to_string(),
            ToolEntry {
                name: "DateTimeTool".to_string(),
                provider: "native".to_string(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                max_results: None,
                output_schema: String::new(),
                effect_row: vec!["read".to_string()],
                // §Fase 58.f.2 — see Calculator: no typed input schema.
                parameters: Vec::new(),
                secret: String::new(),
                secret_partition: String::new(),
                source: ToolSource::Builtin,
                // §Fase 34.c — DateTimeTool declares `read` effect only.
                is_streaming: false,
                scrape: None,
            },
        );
    }

    /// Register tools from the IR program's tool definitions.
    ///
    /// §Fase 34.c (v1.29.0) — `is_streaming` is auto-derived from
    /// each spec's `effect_row` via [`derive_is_streaming`]. Tools
    /// declaring `effects: <stream:<policy>>` automatically register
    /// as stream producers; the dispatcher (Fase 34.d) routes them
    /// through the streaming path.
    pub fn register_from_ir(&mut self, tool_specs: &[IRToolSpec]) {
        for spec in tool_specs {
            let is_streaming = derive_is_streaming(&spec.effect_row);
            // §Fase 58.f.2 — resolve the typed input schema (D1) into
            // `(name, type_name)` pairs, matching the synchronous path's
            // `CompiledStep.tool_param_types` (runner.rs §58.e) so the
            // streaming `run_use_tool` coerces args identically.
            let parameters: Vec<(String, String)> = spec
                .parameters
                .iter()
                .map(|p| (p.name.clone(), p.type_name.clone()))
                .collect();
            self.tools.insert(
                spec.name.clone(),
                ToolEntry {
                    name: spec.name.clone(),
                    provider: spec.provider.clone(),
                    timeout: spec.timeout.clone(),
                    runtime: spec.runtime.clone(),
                    sandbox: spec.sandbox,
                    max_results: spec.max_results,
                    output_schema: spec.output_schema.clone(),
                    effect_row: spec.effect_row.clone(),
                    parameters,
                    // §Fase 94.c — the dispatch-injection secret KEY.
                    secret: spec.secret.clone(),
                    // §Fase 95.a — the partition parameter (empty for every
                    // pre-§95 tool; the value never rides the registry).
                    secret_partition: spec.secret_partition.clone(),
                    source: ToolSource::Program,
                    is_streaming,
                    // §Fase 98.b — resolve the web-acquisition config (None
                    // for every non-scrape tool; the value never rides the
                    // registry for a non-scrape program).
                    scrape: spec.scrape.as_ref().map(ScrapeConfig::from_ir),
                },
            );
        }
    }

    /// Register a single tool entry directly.
    pub fn register(&mut self, entry: ToolEntry) {
        self.tools.insert(entry.name.clone(), entry);
    }

    /// §Fase 58.g — resolve every URL-dispatched **program** tool's
    /// relative `runtime` against `base_url` (D7, see
    /// [`resolve_tool_endpoint`]). Only `http` / `mcp` providers carry a
    /// dispatch URL, so only those are rewritten; `native` / `stub`
    /// builtins (and any tool whose `runtime` is already absolute) are
    /// left untouched. A blank `base_url` is a no-op.
    ///
    /// Called by the server entry points (`execute_server_flow` /
    /// `run_streaming_via_dispatcher`) when the caller supplies a
    /// per-tenant / per-server tool base URL — the request-scoped
    /// registry is rewritten before any dispatch, so resolution is
    /// per-request with zero cross-tenant leakage (§58 D10).
    pub fn resolve_relative_endpoints(&mut self, base_url: &str) {
        if base_url.trim().is_empty() {
            return;
        }
        for entry in self.tools.values_mut() {
            if entry.source != ToolSource::Program {
                continue;
            }
            if entry.provider != "http" && entry.provider != "mcp" {
                continue;
            }
            entry.runtime = resolve_tool_endpoint(&entry.runtime, &entry.name, base_url);
        }
    }

    /// Look up a tool by name.
    pub fn get(&self, name: &str) -> Option<&ToolEntry> {
        self.tools.get(name)
    }

    /// Check if a tool is registered.
    pub fn contains(&self, name: &str) -> bool {
        self.tools.contains_key(name)
    }

    /// Dispatch a tool call. Returns:
    ///   - `Some(ToolResult)` if the tool was handled locally
    ///   - `None` if the tool should fall through to LLM
    pub fn dispatch(&self, tool_name: &str, argument: &str) -> Option<ToolResult> {
        let entry = self.tools.get(tool_name)?;

        match entry.provider.as_str() {
            // Native built-in execution
            "native" => tool_executor::dispatch(tool_name, argument),

            // Stub provider: returns a synthetic response for testing
            "stub" => Some(ToolResult {
                success: true,
                output: format!("[stub] {}({})", tool_name, argument),
                tool_name: tool_name.to_string(),
            }),

            // HTTP provider: REST endpoint dispatch
            "http" => Some(http_tool::dispatch_http(entry, argument)),

            // ℰMCP provider: epistemic MCP transducer (JSON-RPC + blame + taint)
            "mcp" => Some(emcp::dispatch_mcp(entry, argument)),

            // §Fase 98.e — Native Web Acquisition. `scrape_http` (fetch) +
            // `scrape_dom` (parse, no I/O). `scrape_crawl` is streaming and
            // routes through `resolve_streaming_tool`; a synchronous dispatch
            // of it degrades to a single seed fetch. Every output is born
            // Untrusted (D98.1) — the taint rides the internal ScrapeOutcome;
            // the ToolResult integrates with the registry as usual.
            "scrape_http" | "scrape_dom" | "scrape_crawl" => {
                Some(crate::scrape_tool::dispatch_scrape(entry, argument))
            }

            // Known providers that currently fall through to LLM
            // Future: "grpc" adapters
            _ => None,
        }
    }

    /// Number of registered tools.
    pub fn len(&self) -> usize {
        self.tools.len()
    }

    /// Check if registry is empty.
    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    /// List all registered tool names.
    pub fn tool_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.tools.keys().map(|k| k.as_str()).collect();
        names.sort();
        names
    }

    /// List only built-in tool names.
    pub fn builtin_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self
            .tools
            .values()
            .filter(|e| e.source == ToolSource::Builtin)
            .map(|e| e.name.as_str())
            .collect();
        names.sort();
        names
    }

    /// List only program-defined tool names.
    pub fn program_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self
            .tools
            .values()
            .filter(|e| e.source == ToolSource::Program)
            .map(|e| e.name.as_str())
            .collect();
        names.sort();
        names
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // §Fase 34.c — derive_is_streaming canonical rule pin.
    //
    // This lib unit test pins the derivation predicate semantics
    // at the language layer: a tool is a stream producer iff at
    // least one entry in its effect_row begins with `stream:`.
    // The drift gate `axon-rs/tests/fase34_c_registry_drift.rs`
    // extends this pin across a 30-tool synthetic corpus.
    #[test]
    fn fase34_c_derive_is_streaming_canonical_rule() {
        // Empty effect_row → not a stream producer.
        assert!(!derive_is_streaming(&[]));
        // Single non-stream effect → not a stream producer.
        assert!(!derive_is_streaming(&["compute".to_string()]));
        assert!(!derive_is_streaming(&["read".to_string()]));
        assert!(!derive_is_streaming(&["network".to_string()]));
        assert!(!derive_is_streaming(&["io".to_string()]));
        assert!(!derive_is_streaming(&["epistemic:speculate".to_string()]));
        // Multiple non-stream effects → not a stream producer.
        assert!(!derive_is_streaming(&[
            "compute".to_string(),
            "read".to_string(),
            "epistemic:speculate".to_string(),
        ]));
        // Any `stream:<policy>` prefix → stream producer.
        assert!(derive_is_streaming(&["stream:drop_oldest".to_string()]));
        assert!(derive_is_streaming(&["stream:degrade_quality".to_string()]));
        assert!(derive_is_streaming(&["stream:pause_upstream".to_string()]));
        assert!(derive_is_streaming(&["stream:fail".to_string()]));
        // Mixed: stream effect among other effects still flags streaming.
        assert!(derive_is_streaming(&[
            "compute".to_string(),
            "stream:drop_oldest".to_string(),
            "network".to_string(),
        ]));
        // `stream` substring NOT at prefix → not a stream effect
        // (the rule is `starts_with("stream:")`, not `contains`).
        assert!(!derive_is_streaming(&["downstream".to_string()]));
        assert!(!derive_is_streaming(&["upstream-flow".to_string()]));
        // `stream:` with empty policy — still detected as streaming
        // intent. The closed-catalog policy validation lives in the
        // resolver (Fase 33.e); the derive_is_streaming rule is the
        // CHEAPER predicate (used at registration time only).
        assert!(derive_is_streaming(&["stream:".to_string()]));
    }

    #[test]
    fn fase34_c_register_from_ir_auto_derives_is_streaming() {
        let mut reg = ToolRegistry::new();
        let specs = vec![
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 1,
                source_column: 1,
                name: "ChatStreamer".to_string(),
                provider: "anthropic".to_string(),
                max_results: None,
                filter_expr: String::new(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                input_schema: Vec::new(),
                output_schema: String::new(),
                parameters: Vec::new(),
                output_type: None,
                secret: String::new(),
                secret_partition: String::new(),
                effect_row: vec!["stream:drop_oldest".to_string()],
                target: None,
                risk: None,
                argv: Vec::new(),
                cache: String::new(),
                scrape: None,
            },
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 5,
                source_column: 1,
                name: "PlainScanner".to_string(),
                provider: "stub".to_string(),
                max_results: None,
                filter_expr: String::new(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                input_schema: Vec::new(),
                output_schema: String::new(),
                parameters: Vec::new(),
                output_type: None,
                secret: String::new(),
                secret_partition: String::new(),
                effect_row: vec!["compute".to_string()],
                target: None,
                risk: None,
                argv: Vec::new(),
                cache: String::new(),
                scrape: None,
            },
        ];
        reg.register_from_ir(&specs);
        let chat_entry = reg.get("ChatStreamer").unwrap();
        assert!(
            chat_entry.is_streaming,
            "34.c register_from_ir MUST auto-derive is_streaming=true \
             for tools declaring effects: <stream:<policy>>"
        );
        let plain_entry = reg.get("PlainScanner").unwrap();
        assert!(
            !plain_entry.is_streaming,
            "34.c register_from_ir MUST auto-derive is_streaming=false \
             for tools without `stream:` in effect_row"
        );
    }

    #[test]
    fn fase34_c_builtins_are_not_streaming() {
        let reg = ToolRegistry::new();
        // Built-in Calculator + DateTimeTool have no stream effect.
        assert!(!reg.get("Calculator").unwrap().is_streaming);
        assert!(!reg.get("DateTimeTool").unwrap().is_streaming);
    }

    #[test]
    fn new_registry_has_builtins() {
        let reg = ToolRegistry::new();
        assert!(reg.contains("Calculator"));
        assert!(reg.contains("DateTimeTool"));
        assert_eq!(reg.len(), 2);
        assert_eq!(reg.builtin_names(), vec!["Calculator", "DateTimeTool"]);
        assert!(reg.program_names().is_empty());
    }

    #[test]
    fn register_program_tool() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "WebSearch".to_string(),
            provider: "brave".to_string(),
            timeout: "10s".to_string(),
            runtime: String::new(),
            sandbox: None,
            max_results: Some(5),
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        assert!(reg.contains("WebSearch"));
        assert_eq!(reg.len(), 3);
        assert_eq!(reg.program_names(), vec!["WebSearch"]);

        let entry = reg.get("WebSearch").unwrap();
        assert_eq!(entry.provider, "brave");
        assert_eq!(entry.max_results, Some(5));
    }

    #[test]
    fn register_from_ir_specs() {
        let mut reg = ToolRegistry::new();
        let specs = vec![
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 1,
                source_column: 1,
                name: "WebSearch".to_string(),
                provider: "brave".to_string(),
                max_results: Some(5),
                filter_expr: String::new(),
                timeout: "10s".to_string(),
                runtime: String::new(),
                sandbox: None,
                input_schema: Vec::new(),
                output_schema: String::new(),
                parameters: Vec::new(),
                output_type: None,
                secret: String::new(),
                secret_partition: String::new(),
                effect_row: Vec::new(),
                target: None,
                risk: None,
                argv: Vec::new(),
                cache: String::new(),
                scrape: None,
            },
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 5,
                source_column: 1,
                name: "DataAnalyzer".to_string(),
                provider: "stub".to_string(),
                max_results: None,
                filter_expr: String::new(),
                timeout: String::new(),
                runtime: "python".to_string(),
                sandbox: Some(true),
                input_schema: Vec::new(),
                output_schema: String::new(),
                parameters: Vec::new(),
                output_type: None,
                secret: String::new(),
                secret_partition: String::new(),
                effect_row: Vec::new(),
                target: None,
                risk: None,
                argv: Vec::new(),
                cache: String::new(),
                scrape: None,
            },
        ];

        reg.register_from_ir(&specs);

        assert_eq!(reg.len(), 4); // 2 builtins + 2 program
        assert!(reg.contains("WebSearch"));
        assert!(reg.contains("DataAnalyzer"));
        assert_eq!(reg.program_names(), vec!["DataAnalyzer", "WebSearch"]);
    }

    #[test]
    fn dispatch_builtin_calculator() {
        let reg = ToolRegistry::new();
        let result = reg.dispatch("Calculator", "2 + 3").unwrap();
        assert!(result.success);
        assert_eq!(result.output, "5");
    }

    #[test]
    fn dispatch_builtin_datetime() {
        let reg = ToolRegistry::new();
        let result = reg.dispatch("DateTimeTool", "year").unwrap();
        assert!(result.success);
        let year: i32 = result.output.parse().unwrap();
        assert!(year >= 2024);
    }

    #[test]
    fn dispatch_stub_provider() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "TestTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        let result = reg.dispatch("TestTool", "hello world").unwrap();
        assert!(result.success);
        assert_eq!(result.output, "[stub] TestTool(hello world)");
    }

    #[test]
    fn dispatch_unknown_provider_falls_through() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "WebSearch".to_string(),
            provider: "brave".to_string(),
            timeout: "10s".to_string(),
            runtime: String::new(),
            sandbox: None,
            max_results: Some(5),
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        // brave provider not handled locally → falls through to LLM
        assert!(reg.dispatch("WebSearch", "query").is_none());
    }

    #[test]
    fn dispatch_unregistered_tool_returns_none() {
        let reg = ToolRegistry::new();
        assert!(reg.dispatch("NonExistent", "arg").is_none());
    }

    #[test]
    fn program_tool_overrides_builtin() {
        let mut reg = ToolRegistry::new();
        // Override Calculator with a stub provider
        reg.register(ToolEntry {
            name: "Calculator".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        let entry = reg.get("Calculator").unwrap();
        assert_eq!(entry.source, ToolSource::Program);
        assert_eq!(entry.provider, "stub");

        // Now dispatches via stub, not native
        let result = reg.dispatch("Calculator", "2+3").unwrap();
        assert_eq!(result.output, "[stub] Calculator(2+3)");
    }

    // §Fase 58.g — endpoint resolution (D7).

    #[test]
    fn resolve_tool_endpoint_absolute_passthrough() {
        // Already-absolute runtimes are pinned by the program (D5).
        assert_eq!(
            resolve_tool_endpoint("https://api.example.com/x", "T", "https://base"),
            "https://api.example.com/x"
        );
        assert_eq!(
            resolve_tool_endpoint("http://h/x", "T", "https://base"),
            "http://h/x"
        );
    }

    #[test]
    fn resolve_tool_endpoint_relative_joined_to_base() {
        assert_eq!(
            resolve_tool_endpoint("/crm/search", "CrmRadar", "https://tools.acme.io"),
            "https://tools.acme.io/crm/search"
        );
        // No leading slash on the slug works too.
        assert_eq!(
            resolve_tool_endpoint("crm/search", "CrmRadar", "https://tools.acme.io/"),
            "https://tools.acme.io/crm/search"
        );
    }

    #[test]
    fn resolve_tool_endpoint_empty_runtime_uses_tool_name() {
        assert_eq!(
            resolve_tool_endpoint("", "CrmRadar", "https://tools.acme.io"),
            "https://tools.acme.io/CrmRadar"
        );
    }

    #[test]
    fn resolve_tool_endpoint_empty_base_is_noop() {
        // No base wired → relative runtime stays relative (the
        // dispatcher then surfaces the actionable diagnostic).
        assert_eq!(resolve_tool_endpoint("/crm", "T", ""), "/crm");
        assert_eq!(resolve_tool_endpoint("", "T", "   "), "");
    }

    #[test]
    fn resolve_relative_endpoints_only_rewrites_http_mcp_program_tools() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "CrmRadar".to_string(),
            provider: "http".to_string(),
            timeout: String::new(),
            runtime: "/crm/search".to_string(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });
        reg.register(ToolEntry {
            name: "FhirMcp".to_string(),
            provider: "mcp".to_string(),
            timeout: String::new(),
            runtime: "fhir".to_string(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });
        reg.register(ToolEntry {
            name: "Pinned".to_string(),
            provider: "http".to_string(),
            timeout: String::new(),
            runtime: "https://pinned.example.com/api".to_string(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        reg.resolve_relative_endpoints("https://tenant-acme.tools.internal");

        assert_eq!(
            reg.get("CrmRadar").unwrap().runtime,
            "https://tenant-acme.tools.internal/crm/search"
        );
        assert_eq!(
            reg.get("FhirMcp").unwrap().runtime,
            "https://tenant-acme.tools.internal/fhir"
        );
        // Absolute runtime untouched (D5).
        assert_eq!(
            reg.get("Pinned").unwrap().runtime,
            "https://pinned.example.com/api"
        );
        // Built-ins (native) never carry a URL → untouched.
        assert_eq!(reg.get("Calculator").unwrap().runtime, "");
    }

    #[test]
    fn resolve_relative_endpoints_blank_base_is_noop() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "T".to_string(),
            provider: "http".to_string(),
            timeout: String::new(),
            runtime: "/x".to_string(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });
        reg.resolve_relative_endpoints("   ");
        assert_eq!(reg.get("T").unwrap().runtime, "/x");
    }

    #[test]
    fn tool_names_sorted() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "ZetaTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });
        reg.register(ToolEntry {
            name: "AlphaTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            parameters: Vec::new(),
            secret: String::new(),
            secret_partition: String::new(),
            source: ToolSource::Program,
            is_streaming: false,
            scrape: None,
        });

        let names = reg.tool_names();
        assert_eq!(
            names,
            vec!["AlphaTool", "Calculator", "DateTimeTool", "ZetaTool"]
        );
    }
}
