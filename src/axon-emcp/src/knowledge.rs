//! The knowledge base catalogue.
//!
//! All documentation lives as markdown with YAML frontmatter under
//! `src/knowledge/` at the repo root. This module:
//!
//! 1. Discovers the corpus root (dev mode, installed binary, or
//!    `AXON_EMCP_KNOWLEDGE_DIR` override — in this order).
//! 2. Parses every `primitives/*.md` into a [`Primitive`] entry.
//! 3. Indexes them by name so [`Catalog::primitive(name)`] is O(1).
//!
//! The corpus is **the source of truth**: edits land as markdown
//! diffs, the server reloads them at startup. There is no compiled
//! catalog and no generation step. A primitive added to
//! `src/knowledge/primitives/foo.md` is automatically visible to the
//! MCP layer the next time the server starts.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use gray_matter::engine::YAML;
use gray_matter::Matter;
use include_dir::{include_dir, Dir};
use serde::Deserialize;

/// The knowledge corpus compiled into the binary at build time.
///
/// `cargo install --path src/axon-emcp` ships this baked-in copy so
/// the installed server runs without any filesystem dependency. At
/// runtime [`Catalog::load_default`] still prefers (a) the
/// `AXON_EMCP_KNOWLEDGE_DIR` env override or (b) the in-tree dev path
/// (both let operators hot-edit `.md` files without rebuilding); the
/// embedded copy is the (c) fallback that always works.
static EMBEDDED_KNOWLEDGE: Dir<'_> =
    include_dir!("$CARGO_MANIFEST_DIR/../knowledge");

/// One primitive's full documentation, parsed from its markdown source.
///
/// The markdown frontmatter carries the structured fields the MCP layer
/// projects directly (`top_level`, `category`, `grammar`); the body
/// after the frontmatter is the prose reference the agent reads when
/// it asks for the full doc.
#[derive(Debug, Clone)]
pub struct Primitive {
    /// Canonical name as it appears in source (`persona`, `flow`,
    /// `socket`, `axonendpoint`, …). Used as the dictionary key.
    pub name: String,
    /// One-line summary the agent sees in the listing.
    pub summary: String,
    /// Which family the primitive belongs to. Drives the
    /// `axon.primitives(filter)` category facet.
    pub category: Category,
    /// `true` ⇒ this primitive is a top-level declaration (it stands
    /// alone at the program root). `false` ⇒ it only appears nested
    /// inside another construct (e.g. `step` inside a `flow`).
    pub top_level: bool,
    /// The EBNF fragment for this primitive (extract from the official
    /// grammar). Empty string is allowed for primitives whose grammar
    /// is delegated to a parent construct.
    pub grammar: String,
    /// The cycle that introduced this primitive (e.g. `"Fase 4"`,
    /// `"Fase 41.b"`). Lets the agent answer "since when has this
    /// existed?" honestly.
    pub since: String,
    /// The prose body — the full markdown that follows the frontmatter.
    /// Returned verbatim by `axon.primitive_doc(name)`.
    pub body: String,
}

/// The primitive families an agent can filter by.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Category {
    /// `persona`, `flow`, `reason`, `anchor`, `tool`, `probe`, `weave`,
    /// `validate`, `context`, `memory`, `intent`, `refine`. The
    /// "what an LLM does" layer.
    Cognition,
    /// Cognitive I/O — `resource`, `fabric`, `manifest`, `observe`,
    /// `reconcile`, `lease`, `ensemble`, `topology`, `session`,
    /// `immune`, `reflex`, `heal`, `compliance`, `component`, `view`.
    CognitiveIo,
    /// `axonstore`, `dataspace`, `corpus`, `pix`, the four-pillar
    /// persistence layer.
    DataPlane,
    /// `socket`, `session` choice grammar, the §Fase 41 session-type
    /// algebra surface (post-v2.3.0).
    SessionTypes,
    /// `daemon`, `listen`, `axonendpoint`, `axpoint`, `mcp`, `taint`,
    /// the actor / wire surface.
    Wire,
    /// `shield`, `mandate`, `lambda`, `forge`, `agent`, `ots`, `psyche`,
    /// `compute`, `logic`. Specialised cognitive operators.
    Operators,
}

impl Category {
    pub fn as_str(self) -> &'static str {
        match self {
            Category::Cognition => "cognition",
            Category::CognitiveIo => "cognitive_io",
            Category::DataPlane => "data_plane",
            Category::SessionTypes => "session_types",
            Category::Wire => "wire",
            Category::Operators => "operators",
        }
    }
}

/// The frontmatter shape we expect on every `primitives/*.md`. A file
/// missing a required field is a hard error (the loader refuses to
/// start the server) — the agent should never see partial entries.
#[derive(Debug, Deserialize)]
struct Frontmatter {
    name: String,
    summary: String,
    category: Category,
    top_level: bool,
    #[serde(default)]
    grammar: String,
    #[serde(default)]
    since: String,
}

/// The in-process knowledge catalogue. Built once at startup and held
/// behind an `Arc` for cheap clone across the async dispatcher.
#[derive(Debug, Clone, Default)]
pub struct Catalog {
    primitives: BTreeMap<String, Primitive>,
}

impl Catalog {
    /// Discover + load the corpus. Resolution order (first hit wins):
    ///
    /// 1. **`AXON_EMCP_KNOWLEDGE_DIR`** env var — operator override
    ///    (lets ops pin the corpus to an explicit path, e.g. for a
    ///    custom on-prem distribution).
    /// 2. **In-tree dev path** (`<crate>/../knowledge`) — present when
    ///    running `cargo run` from inside the repo; lets contributors
    ///    hot-edit `.md` files without rebuilding the binary.
    /// 3. **Embedded corpus** ([`EMBEDDED_KNOWLEDGE`]) — baked into the
    ///    binary at compile time by `include_dir!`. Always present.
    ///    This is what a `cargo install`-ed user gets.
    ///
    /// The function only fails if a higher-priority location was
    /// requested explicitly (via the env var) and turned out to be
    /// invalid — in that case we surface the problem rather than
    /// silently falling through to the embedded copy. An unset env
    /// var + missing dev path just transparently uses the embedded
    /// copy.
    pub fn load_default() -> Result<Self, LoadError> {
        // (1) explicit env override — always wins, and if it points
        // somewhere that does not parse, that's a hard error: the
        // operator asked us to use that corpus.
        if let Ok(env) = std::env::var("AXON_EMCP_KNOWLEDGE_DIR") {
            let path = PathBuf::from(env);
            if !path.is_dir() {
                return Err(LoadError::MissingDir(path));
            }
            return Self::load_from(&path);
        }
        // (2) in-tree dev path — only when we're sitting inside the
        // source repo (CARGO_MANIFEST_DIR resolves the crate's source
        // root; the sibling `knowledge` only exists when the binary
        // is being run from that tree, not after `cargo install`).
        let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(|p| p.join("knowledge"));
        if let Some(p) = dev_path {
            if p.is_dir() {
                return Self::load_from(&p);
            }
        }
        // (3) embedded fallback — the corpus baked into the binary by
        // `include_dir!` at compile time. This is what users of a
        // `cargo install`-ed binary will hit by default.
        Self::load_embedded()
    }

    /// Load the catalog from the compile-time-embedded corpus. Used by
    /// `load_default` as the final fallback; also exposed directly so
    /// tests can exercise the embedded path without the env-var dance.
    pub fn load_embedded() -> Result<Self, LoadError> {
        let prims_dir = EMBEDDED_KNOWLEDGE.get_dir("primitives").ok_or_else(|| {
            LoadError::MissingDir(PathBuf::from("(embedded)/primitives"))
        })?;
        let mut primitives = BTreeMap::new();
        for file in prims_dir.files() {
            // Match the FS loader's filter — only `.md` files count.
            let is_md = file
                .path()
                .extension()
                .and_then(|s| s.to_str())
                .map(|s| s.eq_ignore_ascii_case("md"))
                .unwrap_or(false);
            if !is_md {
                continue;
            }
            let raw = file.contents_utf8().ok_or_else(|| {
                LoadError::BadFrontmatter(
                    PathBuf::from(file.path()),
                    "embedded file is not valid UTF-8".into(),
                )
            })?;
            let prim = parse_primitive(raw, file.path())?;
            if primitives.insert(prim.name.clone(), prim.clone()).is_some() {
                return Err(LoadError::DuplicateName(
                    prim.name,
                    PathBuf::from(file.path()),
                ));
            }
        }
        Ok(Catalog { primitives })
    }

    /// Load from an explicit path. Public so tests + tools can drive
    /// the loader without touching the filesystem env.
    pub fn load_from(root: &Path) -> Result<Self, LoadError> {
        let primitives_dir = root.join("primitives");
        if !primitives_dir.is_dir() {
            return Err(LoadError::MissingDir(primitives_dir));
        }
        let mut primitives = BTreeMap::new();
        for entry in std::fs::read_dir(&primitives_dir)
            .map_err(|e| LoadError::Io(primitives_dir.clone(), e))?
        {
            let entry = entry.map_err(|e| LoadError::Io(primitives_dir.clone(), e))?;
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("md") {
                continue;
            }
            let raw = std::fs::read_to_string(&path)
                .map_err(|e| LoadError::Io(path.clone(), e))?;
            let prim = parse_primitive(&raw, &path)?;
            if primitives.insert(prim.name.clone(), prim.clone()).is_some() {
                return Err(LoadError::DuplicateName(prim.name, path));
            }
        }
        Ok(Catalog { primitives })
    }

    /// Empty catalog — used only by unit tests that exercise the
    /// server's wire shape without needing the corpus.
    pub fn empty_for_tests() -> Self {
        Catalog::default()
    }

    pub fn primitive_count(&self) -> usize {
        self.primitives.len()
    }

    /// Lookup one primitive by canonical name. `None` if absent.
    pub fn primitive(&self, name: &str) -> Option<&Primitive> {
        self.primitives.get(name)
    }

    /// Iterate every primitive (in BTreeMap order — alphabetical, stable).
    pub fn primitives(&self) -> impl Iterator<Item = &Primitive> {
        self.primitives.values()
    }
}

/// What can go wrong loading the corpus. Surfaced as a fatal startup
/// error — the server refuses to run on a malformed knowledge base.
#[derive(Debug)]
pub enum LoadError {
    /// The corpus root exists but is missing the expected subdir
    /// (`primitives/`), or the operator-supplied
    /// `AXON_EMCP_KNOWLEDGE_DIR` does not name an existing directory.
    MissingDir(PathBuf),
    /// A filesystem error happened while reading a path.
    Io(PathBuf, std::io::Error),
    /// A markdown file failed frontmatter parsing.
    BadFrontmatter(PathBuf, String),
    /// A file is missing the `---\n…\n---` frontmatter block entirely.
    NoFrontmatter(PathBuf),
    /// Two primitives declare the same `name` field — ambiguous.
    DuplicateName(String, PathBuf),
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoadError::MissingDir(p) => write!(f, "expected directory not found: {}", p.display()),
            LoadError::Io(p, e) => write!(f, "I/O error reading {}: {}", p.display(), e),
            LoadError::BadFrontmatter(p, msg) => {
                write!(f, "frontmatter error in {}: {}", p.display(), msg)
            }
            LoadError::NoFrontmatter(p) => {
                write!(f, "missing YAML frontmatter block in {}", p.display())
            }
            LoadError::DuplicateName(n, p) => {
                write!(f, "primitive `{n}` already exists (second definition at {})", p.display())
            }
        }
    }
}

impl std::error::Error for LoadError {}

fn parse_primitive(raw: &str, path: &Path) -> Result<Primitive, LoadError> {
    let matter = Matter::<YAML>::new();
    let parsed = matter.parse(raw);
    let fm: Frontmatter = parsed
        .data
        .ok_or_else(|| LoadError::NoFrontmatter(path.to_path_buf()))?
        .deserialize()
        .map_err(|e| LoadError::BadFrontmatter(path.to_path_buf(), e.to_string()))?;
    Ok(Primitive {
        name: fm.name,
        summary: fm.summary,
        category: fm.category,
        top_level: fm.top_level,
        grammar: fm.grammar,
        since: fm.since,
        body: parsed.content,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;

    fn write_primitive(dir: &Path, name: &str, content: &str) {
        let path = dir.join(format!("{name}.md"));
        let mut f = fs::File::create(path).unwrap();
        f.write_all(content.as_bytes()).unwrap();
    }

    #[test]
    fn loader_parses_a_well_formed_primitive() {
        let tmp = tempdir();
        let prim_dir = tmp.join("primitives");
        fs::create_dir_all(&prim_dir).unwrap();
        write_primitive(
            &prim_dir,
            "socket",
            r#"---
name: socket
summary: typed WebSocket transport (Fase 41)
category: session_types
top_level: true
grammar: |
  socket Name { protocol: SessionRef, ... }
since: Fase 41.b
---

# `socket`

Body prose.
"#,
        );
        let cat = Catalog::load_from(&tmp).unwrap();
        assert_eq!(cat.primitive_count(), 1);
        let p = cat.primitive("socket").unwrap();
        assert_eq!(p.summary, "typed WebSocket transport (Fase 41)");
        assert!(p.top_level);
        assert_eq!(p.category, Category::SessionTypes);
        assert!(p.body.contains("Body prose"));
    }

    #[test]
    fn loader_rejects_missing_frontmatter() {
        let tmp = tempdir();
        let prim_dir = tmp.join("primitives");
        fs::create_dir_all(&prim_dir).unwrap();
        write_primitive(&prim_dir, "bad", "# no frontmatter\n");
        let err = Catalog::load_from(&tmp).expect_err("must reject");
        assert!(matches!(err, LoadError::NoFrontmatter(_)));
    }

    #[test]
    fn loader_rejects_duplicate_names() {
        let tmp = tempdir();
        let prim_dir = tmp.join("primitives");
        fs::create_dir_all(&prim_dir).unwrap();
        let body = |n| {
            format!(
                "---\nname: {n}\nsummary: x\ncategory: cognition\ntop_level: true\n---\n"
            )
        };
        write_primitive(&prim_dir, "a", &body("dup"));
        write_primitive(&prim_dir, "b", &body("dup"));
        let err = Catalog::load_from(&tmp).expect_err("dup name must fail");
        assert!(matches!(err, LoadError::DuplicateName(name, _) if name == "dup"));
    }

    #[test]
    fn embedded_corpus_loads_and_contains_at_least_the_socket_primitive() {
        // §Phase 1 — the `include_dir!` macro bakes `src/knowledge/`
        // into the binary at compile time. `load_embedded` must
        // round-trip every entry through the same frontmatter parser
        // the FS loader uses, so the wire shape an MCP client sees
        // does not depend on whether the corpus was disk-served or
        // baked-in.
        let cat = Catalog::load_embedded().expect("embedded corpus must load");
        assert!(
            cat.primitive_count() >= 1,
            "embedded corpus is empty — include_dir! resolved no files"
        );
        let socket = cat
            .primitive("socket")
            .expect("Phase 0 ships the socket primitive — must be embedded");
        assert!(socket.top_level);
        assert_eq!(socket.category, Category::SessionTypes);
        // The embedded body must include the canonical opening — the
        // markdown was authored as `# \`socket\`` followed by the
        // primitive's introductory paragraph.
        assert!(socket.body.contains("socket"));
        assert!(socket.body.contains("WebSocket"));
    }

    /// A throwaway temp dir, no `tempfile` dep — keeps the dependency
    /// surface minimal. We use process-id + a monotonic counter so
    /// concurrent test runs don't collide.
    fn tempdir() -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let n = N.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "axon-emcp-test-{}-{n}",
            std::process::id()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }
}
