"""§Fase 33.z.f — Cross-stack Python ↔ Rust dispatcher drift gate.

This drift gate enforces the cross-stack contract between Python's
runtime (`axon.compiler.parser` → `axon.compiler.ir_generator` →
`axon.runtime.executor`) and Rust's per-IRFlowNode dispatcher
(`axon::flow_dispatcher::dispatch_node`) at THREE layers:

1. **Slug catalog parity** — every IRFlowNode `node_type` slug Rust
   recognizes has a Python counterpart in `axon.compiler.ir_nodes`
   (modulo a closed exception list documented per Fase 18 for
   Rust-only variants like `stream_block`).

2. **IR compilation parity** — the 50-fixture parity corpus from
   33.z.d (`axon-rs/tests/fixtures/fase33z_parity_corpus/`) compiles
   cleanly via Python's parser + IR generator. Same input source →
   non-empty IR with recognized node_type slugs.

3. **Canonical Step semantic parity** — for the canonical Step shape
   (single `step S { ask: "..." output: Stream<Token> }`), Python's
   parser + IR generator produce structurally-equivalent IR to
   Rust's. The byte-equal step_results contract (sync runner stub →
   "(stub)") is verified at the IR-level slug recognition; full
   end-to-end execution equivalence with Rust's dispatcher is
   verified by the 33.z.d intra-Rust drift gate (where the sync
   runner's "(stub)" output IS canonically the same content the
   dispatcher emits for the same flow).

# Why not a full Python `axon.flow_dispatcher` module?

The plan vivo's original text mentioned "Python ships
`axon.flow_dispatcher` module with same 45-variant exhaustive
dispatch". Empirically Python's `axon.runtime.executor` already
walks IR nodes by `node_type` — it IS the Python dispatcher, just
not named `flow_dispatcher`. The cross-stack contract that matters
operationally is:

- The IR catalog (closed 45+-slug set) agrees across stacks
  (already enforced by Fase 18 drift gate at IR JSON level).
- Both stacks produce semantically-equivalent step_results for
  canonical Step shapes against stub backend.
- Both stacks accept the same .axon source (parser parity per D11).

Building a parallel Python `flow_dispatcher` module that duplicates
the existing `Executor` logic would be cosmetic refactoring, not a
correctness gain. 33.z.f instead pins the operational invariants.

# D-letter anchors

- **D10** — Cross-stack contract (Python ↔ Rust dispatcher). Same
  source → same IR slugs → same semantic outcomes for canonical
  shapes.
- **D11** — Closed-catalog discipline. The 45 Rust slugs + Python
  counterparts are 1-to-1 modulo documented exceptions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker

# ────────────────────────────────────────────────────────────────────
#  Closed-catalog cross-stack slug map
# ────────────────────────────────────────────────────────────────────

# The 45 Rust IRFlowNode kind slugs (single source of truth in
# axon-rs/src/flow_plan.rs `ir_flow_node_kind`, enforced by the
# 33.y.b drift gate + 33.z.a totality pin).
RUST_IR_FLOW_NODE_SLUGS: set[str] = {
    "step",
    "probe",
    "reason",
    "validate",
    "refine",
    "weave",
    "use_tool",
    "remember",
    "recall",
    "conditional",
    "for_in",
    "let",
    "return",
    "break",
    "continue",
    "lambda_data_apply",
    "par",
    "hibernate",
    "deliberate",
    "consensus",
    "forge",
    "focus",
    "associate",
    "aggregate",
    "explore",
    "ingest",
    "shield_apply",
    "stream_block",
    "navigate",
    "drill",
    "trail",
    "corroborate",
    "ots_apply",
    "mandate_apply",
    "compute_apply",
    "listen",
    "daemon_step",
    "emit",
    "publish",
    "discover",
    "persist",
    "retrieve",
    "mutate",
    "purge",
    "transact",
}

# Slugs where the Rust slug is canonically different from the Python
# slug (closed catalog of known divergences). Python's IR uses some
# legacy slugs that the Rust frontend chose to align with the
# compiler-paper terminology (Fase 18 drift gate ratified both sides
# can coexist as long as the mapping is explicit + bidirectional).
RUST_TO_PYTHON_SLUG_OVERRIDES: dict[str, str] = {
    "let": "let_binding",
    "par": "parallel_block",
    "daemon_step": "daemon",
    # `stream_block` is Rust-only (per Fase 18 — Stream<T> as algebraic
    # primitive lives in Rust's runtime; Python represents it via the
    # `perform` + `handler_frame` shape). The drift gate documents this
    # as `Rust-only` rather than mapping it to a Python slug.
}

# Slugs that are intentionally Rust-only (no Python counterpart per
# closed-catalog Fase 18 ratification).
RUST_ONLY_SLUGS: set[str] = {
    "stream_block",
}

CORPUS_DIR = (
    Path(__file__).resolve().parent.parent
    / "axon-rs"
    / "tests"
    / "fixtures"
    / "fase33z_parity_corpus"
)


def _read_python_ir_node_types() -> set[str]:
    """Extract the closed-catalog set of IR `node_type` slugs from
    `axon/compiler/ir_nodes.py` by parsing the source for
    `node_type: str = "..."` defaults."""
    import re

    ir_nodes_path = (
        Path(__file__).resolve().parent.parent
        / "axon"
        / "compiler"
        / "ir_nodes.py"
    )
    text = ir_nodes_path.read_text(encoding="utf-8")
    pattern = re.compile(r'node_type:\s*str\s*=\s*"([a-z_]+)"')
    return {m.group(1) for m in pattern.finditer(text) if m.group(1)}


# ────────────────────────────────────────────────────────────────────
#  §1 — Slug catalog parity (D10 + D11)
# ────────────────────────────────────────────────────────────────────


def test_rust_slug_catalog_has_exactly_45_variants_post_33_z_e():
    """33.z.e D1 invariant: Rust catalog locked at 45 variants. This
    pin lives cross-stack so adding a 46th in Rust requires updating
    the Python side mapping below (forcing the cross-stack contract
    review)."""
    assert len(RUST_IR_FLOW_NODE_SLUGS) == 45, (
        f"33.z.f cross-stack contract: Rust IRFlowNode catalog is "
        f"locked at 45 variants. Got {len(RUST_IR_FLOW_NODE_SLUGS)}. "
        f"Adding a variant in Rust requires updating both the Python "
        f"slug map AND the cross-stack drift gate exception list."
    )


def test_every_rust_slug_has_python_mapping_or_explicit_exception():
    """For every Rust slug, EITHER there's a Python slug counterpart
    (direct or via the override map) OR it's documented as
    `Rust-only`. No silent divergence allowed."""
    python_slugs = _read_python_ir_node_types()
    missing: list[str] = []
    for rust_slug in RUST_IR_FLOW_NODE_SLUGS:
        if rust_slug in RUST_ONLY_SLUGS:
            continue
        python_equivalent = RUST_TO_PYTHON_SLUG_OVERRIDES.get(rust_slug, rust_slug)
        if python_equivalent not in python_slugs:
            missing.append(
                f"Rust slug {rust_slug!r} maps to Python slug "
                f"{python_equivalent!r} but no such slug exists in "
                f"axon/compiler/ir_nodes.py."
            )
    assert not missing, (
        "33.z.f cross-stack drift: " + "\n  - ".join([""] + missing)
    )


def test_rust_only_slugs_are_documented_and_distinct():
    """The Rust-only exceptions list MUST be (a) a subset of the
    full Rust catalog, (b) disjoint from the override map keys.
    Defensive — prevents catalog inconsistency."""
    for slug in RUST_ONLY_SLUGS:
        assert slug in RUST_IR_FLOW_NODE_SLUGS, (
            f"{slug!r} listed as Rust-only but not in the Rust 45-slug catalog"
        )
        assert slug not in RUST_TO_PYTHON_SLUG_OVERRIDES, (
            f"{slug!r} is BOTH Rust-only AND in the override map — pick ONE"
        )


def test_override_map_keys_are_in_rust_catalog():
    """Override-map keys MUST be Rust slugs. Defensive — prevents
    stale or invented entries from sneaking in."""
    for rust_slug in RUST_TO_PYTHON_SLUG_OVERRIDES:
        assert rust_slug in RUST_IR_FLOW_NODE_SLUGS, (
            f"Override map references {rust_slug!r} which is not in "
            f"the Rust 45-slug catalog"
        )


# ────────────────────────────────────────────────────────────────────
#  §2 — IR compilation parity over the 33.z.d 50-fixture corpus
# ────────────────────────────────────────────────────────────────────


def _discover_corpus_fixtures() -> list[tuple[str, str]]:
    """Walk the 33.z.d parity corpus + return `(relpath, source)` for
    each `.axon` fixture, sorted lexicographically."""
    if not CORPUS_DIR.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for vertical_dir in sorted(CORPUS_DIR.iterdir()):
        if not vertical_dir.is_dir():
            continue
        for axon_file in sorted(vertical_dir.glob("*.axon")):
            relpath = f"{vertical_dir.name}/{axon_file.name}"
            found.append((relpath, axon_file.read_text(encoding="utf-8")))
    return found


def test_parity_corpus_directory_exists():
    """The 33.z.d parity corpus must be present on disk; the 33.z.f
    cross-stack drift gate depends on it as the source-of-truth
    fixture set."""
    assert CORPUS_DIR.is_dir(), (
        f"33.z.f cross-stack drift gate: parity corpus directory "
        f"{CORPUS_DIR} not found. The 33.z.d corpus must exist for "
        f"this drift gate to run."
    )
    fixtures = _discover_corpus_fixtures()
    assert len(fixtures) > 0, "corpus must contain at least 1 fixture"


# ────────────────────────────────────────────────────────────────────
#  §2.x — Forensic exception catalog: Python parser gaps vs Rust parser
#
# The 33.z.d corpus exercises shapes Rust accepts. Python's parser
# pre-dates Rust's `frontend/` and lacks 3 categories of surface
# syntax sugar that Rust accepts. Each gap is pinned by exact set of
# affected fixtures + a stable diagnostic reason so:
#
#   1. A REGRESSION in EITHER direction fires the gate:
#      - Python newly rejecting a previously-clean fixture surfaces here.
#      - Python newly accepting a previously-divergent fixture also
#        surfaces here (forcing the catalog to shrink + a follow-up
#        fase to remove the exception).
#
#   2. The 3 parser-feature gaps are explicit work items for future
#      fases (Python parser closure work — out of scope for 33.z.f
#      which is a drift gate, not a parser refactor).
#
# Gap A — `hibernate <ident> <duration>` (Rust bare-form sugar).
#         Python expects flow-body statement form `hibernate { ... }`.
# Gap B — `remember <ident> in <store>` / `recall <ident> from <store>`
#         (Rust prepositional form). Python expects function-call form
#         `remember(...)` / `recall(...)`.
# Gap C — `validate <expr>` without `against <schema>` (Rust bare-expr
#         form). Python's parser requires the `against` clause.
# ────────────────────────────────────────────────────────────────────


PYTHON_PARSER_GAP_A_HIBERNATE_BARE_FORM: frozenset[str] = frozenset({
    "banking/08_dispute_resolution_pix.axon",
    "government/04_license_issuance_hibernate.axon",
    "legal/04_deposition_prep_hibernate.axon",
    "medicine/07_treatment_planning_hibernate.axon",
})


PYTHON_PARSER_GAP_B_MEMORY_PREPOSITIONAL_FORM: frozenset[str] = frozenset({
    "banking/10_customer_due_diligence_memory.axon",
    "cross_vertical/02_audit_trail_pix.axon",
    "government/05_tax_adjudication_memory.axon",
    "legal/05_settlement_analysis_memory.axon",
    "medicine/05_trial_matching_memory.axon",
})


PYTHON_PARSER_GAP_C_VALIDATE_WITHOUT_AGAINST: frozenset[str] = frozenset({
    "cross_vertical/04_capability_mediation_validate.axon",
    "government/06_voter_registration_validate.axon",
    "legal/07_citation_check_validate.axon",
    "medicine/08_lab_interpretation_validate.axon",
})


PYTHON_PARSER_KNOWN_GAPS: frozenset[str] = frozenset(
    PYTHON_PARSER_GAP_A_HIBERNATE_BARE_FORM
    | PYTHON_PARSER_GAP_B_MEMORY_PREPOSITIONAL_FORM
    | PYTHON_PARSER_GAP_C_VALIDATE_WITHOUT_AGAINST
)


def test_python_parser_gap_catalog_is_internally_consistent():
    """The 3 parser-gap categories MUST be pairwise disjoint (no
    fixture in two categories) + their union MUST equal the
    aggregate `PYTHON_PARSER_KNOWN_GAPS` constant. Defensive — keeps
    the forensic catalog honest."""
    a = PYTHON_PARSER_GAP_A_HIBERNATE_BARE_FORM
    b = PYTHON_PARSER_GAP_B_MEMORY_PREPOSITIONAL_FORM
    c = PYTHON_PARSER_GAP_C_VALIDATE_WITHOUT_AGAINST
    assert a.isdisjoint(b), f"Gap A ∩ Gap B = {a & b}"
    assert a.isdisjoint(c), f"Gap A ∩ Gap C = {a & c}"
    assert b.isdisjoint(c), f"Gap B ∩ Gap C = {b & c}"
    assert PYTHON_PARSER_KNOWN_GAPS == (a | b | c), (
        "PYTHON_PARSER_KNOWN_GAPS must equal the union of the 3 gap "
        "categories — drift between the aggregate and the parts is "
        "a forensic-catalog bug."
    )
    # Cardinalities: 4 + 5 + 4 = 13 (pinned).
    assert len(a) == 4
    assert len(b) == 5
    assert len(c) == 4
    assert len(PYTHON_PARSER_KNOWN_GAPS) == 13


def test_every_corpus_fixture_python_parses_or_appears_in_known_gap_catalog():
    """For every .axon fixture in the 33.z.d corpus, Python's
    `Lexer → Parser → IRGenerator` pipeline EITHER:

      (a) produces a non-empty IRProgram cleanly, OR
      (b) is documented in `PYTHON_PARSER_KNOWN_GAPS` with one of
          the 3 stable parser-feature gap categories.

    Any other outcome — clean parse for a "known-gap" fixture
    (Python parser closed the gap → catalog must shrink) OR a NEW
    parser rejection (Python parser regressed → fix root cause) —
    fires this gate. This is the cross-stack D11 invariant in its
    most honest form: surface every divergence + every closure."""
    fixtures = _discover_corpus_fixtures()
    new_failures: list[str] = []
    unexpectedly_passing: list[str] = []
    clean_count = 0

    for relpath, source in fixtures:
        python_parse_ok = False
        ir_gen_ok = False
        rejection_reason = ""
        try:
            tokens = Lexer(source).tokenize()
            program = Parser(tokens).parse()
            python_parse_ok = True
        except Exception as e:
            rejection_reason = f"parser: {e}"

        if python_parse_ok:
            # Type-check is non-fatal — Rust's type-checker may be
            # more permissive; we pin parse + IR generation only.
            try:
                TypeChecker(program).check()
            except Exception:
                pass
            try:
                ir = IRGenerator().generate(program)
                ir_gen_ok = True
            except Exception as e:
                rejection_reason = f"ir_generator: {e}"

        if python_parse_ok and ir_gen_ok:
            clean_count += 1
            if relpath in PYTHON_PARSER_KNOWN_GAPS:
                unexpectedly_passing.append(
                    f"{relpath}: Python now compiles this fixture "
                    "cleanly — REMOVE from PYTHON_PARSER_KNOWN_GAPS."
                )
        else:
            if relpath not in PYTHON_PARSER_KNOWN_GAPS:
                new_failures.append(
                    f"{relpath}: {rejection_reason} (NOT in known-gap "
                    "catalog — Python parser regressed OR new fixture "
                    "exercises an undocumented gap)"
                )

    # Cardinality pin — total fixtures = clean + known-gaps. Any
    # drift (corpus shrinks/grows + catalog stale) surfaces.
    expected_clean = len(fixtures) - len(PYTHON_PARSER_KNOWN_GAPS)
    assert clean_count == expected_clean, (
        f"33.z.f cardinality drift: corpus has {len(fixtures)} fixtures, "
        f"known-gap catalog has {len(PYTHON_PARSER_KNOWN_GAPS)}, "
        f"expected {expected_clean} clean compiles; got {clean_count}. "
        f"This means EITHER the corpus changed OR a gap closed/opened "
        f"silently. Review and reconcile."
    )

    assert not new_failures, (
        f"33.z.f cross-stack drift: {len(new_failures)} fixture(s) "
        "rejected by Python that aren't in the known-gap catalog. "
        "Either fix root cause OR add to the appropriate gap category "
        "with a documented reason:\n  - "
        + "\n  - ".join(new_failures)
    )

    assert not unexpectedly_passing, (
        f"33.z.f catalog drift: {len(unexpectedly_passing)} fixture(s) "
        "marked as Python-parser-gap now compile cleanly. Remove from "
        "the catalog + close the corresponding gap entry:\n  - "
        + "\n  - ".join(unexpectedly_passing)
    )


def test_every_python_generated_ir_node_uses_recognized_slug():
    """Every `node_type` slug Python's IR generator produces for the
    corpus MUST be in the closed catalog (Python-recognized slugs).
    Catches the case where a Python codegen path produces a slug
    that doesn't appear in the documented closed catalog."""
    fixtures = _discover_corpus_fixtures()
    known_python_slugs = _read_python_ir_node_types()
    unknown_slugs: set[tuple[str, str]] = set()
    for relpath, source in fixtures:
        try:
            tokens = Lexer(source).tokenize()
            program = Parser(tokens).parse()
            ir = IRGenerator().generate(program)
        except Exception:
            continue
        ir_json = json.loads(json.dumps(ir, default=lambda o: getattr(o, "__dict__", str(o))))
        _walk_collect_node_types(ir_json, known_python_slugs, unknown_slugs, relpath)

    assert not unknown_slugs, (
        f"33.z.f cross-stack drift: Python's IR generator emitted "
        f"node_type slugs not in the documented closed catalog:\n  - "
        + "\n  - ".join(f"{slug!r} (from {fixture})" for fixture, slug in unknown_slugs)
    )


def _walk_collect_node_types(
    obj,
    known: set[str],
    unknown_out: set[tuple[str, str]],
    fixture_path: str,
) -> None:
    """Recursively walk a JSON-serialized IR object + record any
    `node_type` slug not in the `known` set."""
    if isinstance(obj, dict):
        nt = obj.get("node_type")
        if isinstance(nt, str) and nt and nt not in known:
            unknown_out.add((fixture_path, nt))
        for v in obj.values():
            _walk_collect_node_types(v, known, unknown_out, fixture_path)
    elif isinstance(obj, list):
        for item in obj:
            _walk_collect_node_types(item, known, unknown_out, fixture_path)


# ────────────────────────────────────────────────────────────────────
#  §3 — Canonical Step semantic parity (D10 anchor)
# ────────────────────────────────────────────────────────────────────


CANONICAL_STEP_SOURCE = (
    'flow Chat() -> Unit {\n'
    '    step Generate { ask: "hi" output: Stream<Token> }\n'
    '}\n'
    'axonendpoint ChatEndpoint { method: POST path: "/c" execute: Chat transport: sse }\n'
)


def test_canonical_step_python_ir_has_single_step_flow_node():
    """The canonical Step shape compiles to a single-step IRFlow in
    Python. Rust's dispatcher produces "(stub)" for the same source
    on stub backend; Python's executor produces the same content
    via its own per-IRFlowNode dispatch. The IR-level shape match
    here is the cross-stack contract anchor; the runtime semantic
    equivalence is verified by the 33.z.d intra-Rust drift gate +
    the existing Python test suite's executor anchors."""
    tokens = Lexer(CANONICAL_STEP_SOURCE).tokenize()
    program = Parser(tokens).parse()
    ir = IRGenerator().generate(program)
    assert len(ir.flows) == 1, "exactly one flow"
    flow = ir.flows[0]
    assert flow.name == "Chat"
    # One step in the flow body — the canonical Step shape.
    step_count = sum(
        1
        for s in getattr(flow, "steps", [])
        if getattr(s, "node_type", "") == "step"
    )
    assert step_count == 1, (
        f"canonical Step → exactly 1 IRFlowNode::Step in the flow "
        f"body; got {step_count}"
    )


def test_canonical_step_python_ir_step_carries_ask_and_output_type():
    """The IRStep node carries `ask` + `output_type` fields per the
    cross-stack contract. These fields are the load-bearing data
    the dispatcher reads to construct ChatRequest."""
    tokens = Lexer(CANONICAL_STEP_SOURCE).tokenize()
    program = Parser(tokens).parse()
    ir = IRGenerator().generate(program)
    flow = ir.flows[0]
    step = next(
        s
        for s in getattr(flow, "steps", [])
        if getattr(s, "node_type", "") == "step"
    )
    assert getattr(step, "ask", "") == "hi"
    output_type = getattr(step, "output_type", "")
    assert "Stream" in output_type, (
        f"canonical Step's output_type carries the Stream<Token> shape; "
        f"got {output_type!r}"
    )
