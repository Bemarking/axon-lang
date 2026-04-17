//! `axon inspect` native implementation — introspect the AXON standard library.
//!
//! Lists and details stdlib components across 4 namespaces:
//!   - personas, anchors, flows, tools
//!
//! Usage:
//!   axon inspect anchors       — list all anchors
//!   axon inspect personas      — list all personas
//!   axon inspect --all         — list all namespaces
//!   axon inspect NoHallucination — show detail for a specific entry
//!
//! Exit codes:
//!   0 — success
//!   1 — entry not found

use std::io::{self, IsTerminal};

use crate::stdlib::{self, StdlibEntry, StdlibAnchor, StdlibFlow, StdlibPersona, StdlibTool};

// ── ANSI colors ─────────────────────────────────────────────────────────────

const CYAN: &str = "\x1b[36m";
const GREEN: &str = "\x1b[32m";
const RED: &str = "\x1b[31m";
const YELLOW: &str = "\x1b[33m";
const BOLD: &str = "\x1b[1m";
const DIM: &str = "\x1b[2m";
const RESET: &str = "\x1b[0m";

fn c(text: &str, code: &str, use_color: bool) -> String {
    if use_color {
        format!("{code}{text}{RESET}")
    } else {
        text.to_string()
    }
}

// ── Namespace listing ───────────────────────────────────────────────────────

fn print_namespace(namespace: &str, use_color: bool) {
    let entries = stdlib::list_namespace(namespace);
    if entries.is_empty() {
        println!("  {}", c(&format!("No {namespace} registered."), DIM, use_color));
        return;
    }

    println!(
        "\n  {}\n",
        c(&format!("{} ({})", namespace.to_uppercase(), entries.len()), &format!("{BOLD}{CYAN}"), use_color)
    );

    for entry in &entries {
        let suffix = match entry {
            StdlibEntry::Anchor(a) => format!("  [{}]", a.severity),
            StdlibEntry::Tool(t) if t.requires_api_key => "  [api-key]".to_string(),
            _ => String::new(),
        };
        println!(
            "    {}{}",
            c(entry.name(), GREEN, use_color),
            c(&suffix, DIM, use_color),
        );
        if !entry.description().is_empty() {
            println!("      {}", c(entry.description(), DIM, use_color));
        }
    }
    println!();
}

// ── Detail view ─────────────────────────────────────────────────────────────

fn print_detail(entry: &StdlibEntry, use_color: bool) {
    println!();
    match entry {
        StdlibEntry::Persona(p) => print_persona_detail(p, use_color),
        StdlibEntry::Anchor(a) => print_anchor_detail(a, use_color),
        StdlibEntry::Flow(f) => print_flow_detail(f, use_color),
        StdlibEntry::Tool(t) => print_tool_detail(t, use_color),
    }
    println!();
}

fn print_persona_detail(p: &StdlibPersona, uc: bool) {
    println!("  {} {}", c("persona", &format!("{BOLD}{CYAN}"), uc), c(p.name, &format!("{BOLD}{GREEN}"), uc));
    println!("  {}", c(p.description, DIM, uc));
    println!();
    println!("    {}  {}", c("tone:", YELLOW, uc), p.tone);
    println!("    {}  {}", c("domain:", YELLOW, uc), p.domain.join(", "));
    println!("    {}  {}", c("confidence:", YELLOW, uc), p.confidence_threshold);
    println!("    {}  {}", c("cite_sources:", YELLOW, uc), p.cite_sources);
    println!("    {}  {}", c("category:", YELLOW, uc), p.category);
    println!("    {}  {}", c("version:", YELLOW, uc), p.version);
}

fn print_anchor_detail(a: &StdlibAnchor, uc: bool) {
    println!("  {} {}", c("anchor", &format!("{BOLD}{CYAN}"), uc), c(a.name, &format!("{BOLD}{GREEN}"), uc));
    println!("  {}", c(a.description, DIM, uc));
    println!();
    println!("    {}  {}", c("severity:", YELLOW, uc), a.severity);
    if !a.require.is_empty() {
        println!("    {}  {}", c("require:", YELLOW, uc), a.require.join(", "));
    }
    if !a.reject.is_empty() {
        println!("    {}  {}", c("reject:", YELLOW, uc), a.reject.join(", "));
    }
    if let Some(floor) = a.confidence_floor {
        println!("    {}  {}", c("confidence_floor:", YELLOW, uc), floor);
    }
    println!("    {}  {}", c("version:", YELLOW, uc), a.version);
}

fn print_flow_detail(f: &StdlibFlow, uc: bool) {
    let params: Vec<String> = f.parameters.iter().map(|(n, t)| format!("{n}: {t}")).collect();
    println!(
        "  {} {}({}) -> {}",
        c("flow", &format!("{BOLD}{CYAN}"), uc),
        c(f.name, &format!("{BOLD}{GREEN}"), uc),
        params.join(", "),
        f.return_type
    );
    println!("  {}", c(f.description, DIM, uc));
    println!();
    println!("    {}  {}", c("category:", YELLOW, uc), f.category);
    println!("    {}  {}", c("version:", YELLOW, uc), f.version);
}

fn print_tool_detail(t: &StdlibTool, uc: bool) {
    println!("  {} {}", c("tool", &format!("{BOLD}{CYAN}"), uc), c(t.name, &format!("{BOLD}{GREEN}"), uc));
    println!("  {}", c(t.description, DIM, uc));
    println!();
    if !t.provider.is_empty() {
        println!("    {}  {}", c("provider:", YELLOW, uc), t.provider);
    }
    println!("    {}  {}s", c("timeout:", YELLOW, uc), t.timeout);
    println!("    {}  {}", c("sandbox:", YELLOW, uc), t.sandbox);
    println!("    {}  {}", c("requires_api_key:", YELLOW, uc), t.requires_api_key);
    println!("    {}  {}", c("version:", YELLOW, uc), t.version);
}

// ── Public entry point ──────────────────────────────────────────────────────

pub fn run_inspect(target: &str, all: bool) -> i32 {
    let use_color = io::stdout().is_terminal();

    if all {
        for ns in stdlib::VALID_NAMESPACES {
            print_namespace(ns, use_color);
        }
        return 0;
    }

    // Check if target is a namespace
    if stdlib::VALID_NAMESPACES.contains(&target) {
        print_namespace(target, use_color);
        return 0;
    }

    // Try to resolve as a specific entry name
    if let Some(entry) = stdlib::resolve(target) {
        print_detail(&entry, use_color);
        return 0;
    }

    eprintln!(
        "{}",
        c(
            &format!("Not found: '{target}'. Use a namespace (anchors, personas, flows, tools) or a component name."),
            &format!("{BOLD}{RED}"),
            use_color,
        )
    );
    1
}
