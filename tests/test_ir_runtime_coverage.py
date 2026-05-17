"""
Fase 18.l — Drift gate: every IRFlowNode variant must have a classified
runtime status in docs/fase/fase_18_ir_runtime_audit.md §3.

This test parses the canonical IRFlowNode variant list from
axon-frontend/src/ir_nodes.rs and the matrix table from the Fase 18
plan doc; asserts every variant has a row with a valid status.

Adding a new IR node type without classifying it fails this test → CI
red → forces the contributor to decide:
  * is this WIRED at runtime?
  * is this LLM-CORRECT?
  * is this a known GAP (and if so, severity)?

This is the structural defense against the same compile-only/runtime-stub
gap pattern that Fases 15, 16, 17 closed reactively. After Fase 18,
silent fall-through to the LLM is impossible by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_VALID_STATUSES = {
    "✅ WIRED",
    "🔵 LLM-CORRECT",
    "🔴 GAP-CRITICAL",
    "🟠 GAP-HIGH",
    "🟡 GAP-MEDIUM",
}


def _project_root() -> Path:
    """Walk up from this test file until we find the project root."""
    return Path(__file__).resolve().parent.parent


def _enum_variants_from_rust() -> list[str]:
    """Parse the IRFlowNode enum variants from the canonical Rust file.

    The enum is defined inside `pub enum IRFlowNode { ... }` with each
    variant on its own line as `Variant(IRStruct),`. We extract the
    variant identifier (left of the parenthesis).
    """
    src = (_project_root() / "axon-frontend" / "src" / "ir_nodes.rs").read_text(encoding="utf-8")
    match = re.search(r"pub enum IRFlowNode \{(.*?)\n\}", src, re.DOTALL)
    if match is None:
        raise AssertionError(
            "Could not locate `pub enum IRFlowNode { ... }` in "
            "axon-frontend/src/ir_nodes.rs — has the canonical IR enum "
            "moved? The drift gate parses it directly to stay in sync."
        )
    body = match.group(1)
    variants = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        # Match `Variant(IRType),` — capture the identifier before `(`.
        m = re.match(r"^([A-Z]\w*)\(", line)
        if m is not None:
            variants.append(m.group(1))
    return variants


def _matrix_rows_from_plan() -> dict[str, str]:
    """Parse the Fase 18 matrix table (markdown) and return
    `{variant_name: status}`.

    The table lives under §3 of docs/fase/fase_18_ir_runtime_audit.md with
    rows shaped:
      | N | `VariantName` | <status emoji + text> | <evidence> |
    """
    src = (_project_root() / "docs" / "fase_18_ir_runtime_audit.md").read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    # Locate §3 header and read until the next ## heading.
    section_match = re.search(
        r"## 3\. The matrix.*?\n(.+?)\n## ",
        src,
        re.DOTALL,
    )
    if section_match is None:
        raise AssertionError(
            "Could not locate `## 3. The matrix ...` in "
            "docs/fase/fase_18_ir_runtime_audit.md — the drift gate parses "
            "this section to enforce coverage."
        )
    section = section_match.group(1)
    # Match each row: pipe + index + pipe + `Variant` + pipe + status + ...
    row_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|",
        re.MULTILINE,
    )
    for variant, status_raw in row_pattern.findall(section):
        # Status text is one of: "✅ WIRED", "🔵 LLM-CORRECT",
        # "🔴 **GAP-CRITICAL**" (markdown bold strips), etc.
        # Normalise by stripping markdown bold + collapsing whitespace.
        status = status_raw.replace("**", "").strip()
        rows[variant] = status
    return rows


# ── Tests ──────────────────────────────────────────────────────────────


def test_canonical_enum_parsed():
    """Sanity: the Rust IRFlowNode enum yields a non-empty variant list."""
    variants = _enum_variants_from_rust()
    assert len(variants) >= 30, (
        f"Expected ≥30 IRFlowNode variants; got {len(variants)}. "
        f"The parser may have changed shape."
    )


def test_matrix_parsed():
    """Sanity: the Fase 18 matrix yields a non-empty row dict."""
    rows = _matrix_rows_from_plan()
    assert len(rows) >= 30, (
        f"Expected ≥30 matrix rows; got {len(rows)}. "
        f"Has the §3 table layout drifted from the parser regex?"
    )


def test_every_variant_has_classification():
    """Every IRFlowNode variant must appear in the matrix with a
    valid status. This is the central drift gate."""
    variants = set(_enum_variants_from_rust())
    rows = _matrix_rows_from_plan()
    missing = variants - set(rows)
    assert not missing, (
        f"IRFlowNode variants without a status row in "
        f"docs/fase/fase_18_ir_runtime_audit.md §3:\n  {sorted(missing)}\n\n"
        f"Add a row for each one with one of the valid statuses: "
        f"{sorted(_VALID_STATUSES)}.\n"
        f"This gate exists to prevent silent compile-only/runtime-stub "
        f"gaps (the bug pattern that took Fases 15/16/17 to close one "
        f"primitive at a time)."
    )


def test_every_status_is_valid():
    """Every status in the matrix must be one of the closed set."""
    rows = _matrix_rows_from_plan()
    invalid = {
        variant: status
        for variant, status in rows.items()
        if status not in _VALID_STATUSES
    }
    assert not invalid, (
        f"Matrix rows with invalid status:\n"
        f"{[(v, s) for v, s in invalid.items()]}\n\n"
        f"Valid statuses: {sorted(_VALID_STATUSES)}"
    )


@pytest.mark.parametrize("variant_name", [
    # WIRED primitives — every flow variant that has a runtime
    # dispatcher. The drift gate fails if any regresses.
    # Original 27 WIRED (pre-Fase-18):
    "UseTool", "Let", "LambdaDataApply", "Deliberate", "Consensus",
    "Forge", "ShieldApply", "Navigate", "Corroborate", "OtsApply",
    "MandateApply", "ComputeApply", "Listen", "DaemonStep",
    "Emit", "Publish", "Discover", "Persist", "Retrieve", "Mutate",
    "Purge", "Transact", "Focus", "Associate", "Aggregate",
    "Explore", "Ingest",
    # 9 newly WIRED in Fase 18 (the gaps closed):
    "Conditional", "ForIn", "Par", "Return",     # 18.b/c/e/d — control flow
    "Remember", "Recall",                          # 18.f/g — memory subsystem
    "Hibernate",                                   # 18.h — CPS checkpoint
    "Drill", "Trail",                              # 18.j/k — PIX domain primitives
])
def test_known_wired_primitives_remain_wired(variant_name: str):
    """If any of these regresses to a GAP status, something broke."""
    rows = _matrix_rows_from_plan()
    status = rows.get(variant_name)
    assert status == "✅ WIRED", (
        f"Variant `{variant_name}` was previously WIRED but matrix "
        f"now says {status!r}. Regression?"
    )


@pytest.mark.parametrize("variant_name", [
    # Original 6 LLM-bound cognitive primitives:
    "Step", "Probe", "Reason", "Validate", "Refine", "Weave",
    # Stream re-classified post-Fase-18 audit: it's a Rust-only
    # flow-step variant; Python flows do not contain `Stream` at
    # the flow level (only `IRStreamSpec` at program level).
    "Stream",
])
def test_known_llm_correct_remain_llm_correct(variant_name: str):
    """LLM-bound primitives stay LLM-bound."""
    rows = _matrix_rows_from_plan()
    status = rows.get(variant_name)
    assert status == "🔵 LLM-CORRECT", (
        f"Variant `{variant_name}` was previously LLM-CORRECT but "
        f"matrix now says {status!r}."
    )


def test_no_remaining_gap_statuses():
    """Acceptance gate for Fase 18: zero rows with GAP status."""
    rows = _matrix_rows_from_plan()
    gaps = {
        v: s for v, s in rows.items()
        if "GAP" in s.upper()
    }
    assert not gaps, (
        f"Fase 18 acceptance violated — matrix still has {len(gaps)} "
        f"unwired GAP entries:\n{sorted(gaps.items())}\n\n"
        f"All 10 gaps must be closed before v1.13.0 ships."
    )
