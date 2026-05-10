#!/usr/bin/env python
"""§Fase 28.i — Regenerate the drift-gate corpus expected counts.

Run from the repo root::

    python scripts/fase28_regen_drift_corpus.py

This rebuilds `tests/fixtures/fase28_drift_gate/corpus.json` from
the canonical INPUTS list defined here. The expected_* counts are
computed from the Python parser. After regeneration, run the Rust
drift-gate test to confirm Rust still agrees::

    cargo test --manifest-path axon-frontend/Cargo.toml --test fase28_drift_gate

If Rust disagrees with the freshly-regenerated Python counts on
any entry, the Rust test fails and the regression has been caught
at PR-time — that is the cross-stack drift gate working as
intended (D7 ratified 2026-05-10).

Adding a new entry: append `(name, source)` to INPUTS below, run
this script, run BOTH stack tests. If both pass, commit the
updated corpus.json + this script change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root is the parent of `scripts/`.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from axon.compiler.lexer import Lexer  # noqa: E402
from axon.compiler.parser import Parser  # noqa: E402


# ── canonical drift-gate inputs ────────────────────────────────
#
# Each tuple is (name, source). Names must be unique. Sources
# should cover:
#   * clean inputs of various sizes
#   * top-level keyword typos (smart-suggest fires)
#   * flow-body keyword typos
#   * recovery-then-clean transitions
#   * empty / whitespace
#   * brace-imbalance edge cases
#   * nested-error blocks

INPUTS: list[tuple[str, str]] = [
    ("clean_flow", "flow F() { }"),
    ("clean_intent", "intent I {}"),
    ("clean_two_decls", "flow F() { } intent I {}"),
    ("typo_top_level_flwo", "flwo F() { }"),
    ("typo_top_level_intnt", "intnt I {}"),
    ("typo_far_no_suggest", "qwerty F() { }"),
    ("two_typos", "flwo F() { } intnt J {}"),
    ("garbage_then_clean", "garbage flow F() { }"),
    ("only_garbage", "foo bar baz"),
    ("empty", ""),
    ("ws_only", "   \n  \n"),
    ("typo_flow_body", "flow F() { stepp S {} }"),
    ("typo_flow_body_reasn", "flow F() { reasn R {} }"),
    ("brace_imbalance", "} flow F() {}"),
    (
        "nested_error_then_clean",
        "flow F() { not_a_step { inner } } flow G() {}",
    ),
]


CORPUS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "fase28_drift_gate" / "corpus.json"
)


def _compute(source: str) -> tuple[int, int, int]:
    """Return ``(error_count, suggest_count, decl_count)`` for ``source``.

    The triple is the cross-stack contract: if Rust produces the
    same triple on the same source, the stacks are byte-identical
    at the count level.
    """
    tokens = Lexer(source).tokenize()
    result = Parser(tokens).parse_with_recovery()
    n_err = len(result.errors)
    n_suggest = sum(1 for e in result.errors if "Did you mean" in str(e))
    n_decl = len(result.program.declarations)
    return n_err, n_suggest, n_decl


def main() -> int:
    """Regenerate the corpus.json from INPUTS + Python parser output."""
    seen_names: set[str] = set()
    corpus: list[dict] = []
    for name, source in INPUTS:
        if name in seen_names:
            print(f"error: duplicate name {name!r}", file=sys.stderr)
            return 1
        seen_names.add(name)
        n_err, n_suggest, n_decl = _compute(source)
        corpus.append(
            {
                "name": name,
                "source": source,
                "expected_error_count": n_err,
                "expected_suggest_count": n_suggest,
                "expected_decl_count": n_decl,
            }
        )

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(
        json.dumps(corpus, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {CORPUS_PATH} with {len(corpus)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
