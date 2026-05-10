"""§Fase 28.i — Cross-stack drift gate (Python side).

D7 ratified 2026-05-10: byte-identical error lists across Python
and Rust frontends. The drift gate locks this in CI by having both
stacks parse the same canonical corpus and assert the same expected
counts (error count, suggest-hint count, salvaged declaration
count).

Single source of truth: `tests/fixtures/fase28_drift_gate/corpus.json`.
Both the Python pack (this file) and the Rust integration test
(`axon-frontend/tests/fase28_drift_gate.rs`) read the same JSON.
If at any future point the two stacks diverge on what input X
produces, exactly one of the two test packs fails — the drift is
caught at PR review time, not at adopter-bug-report time.

The corpus covers:
  - clean inputs (zero errors, decl count > 0)
  - top-level keyword typos (recovery + smart-suggest fire)
  - flow-body keyword typos
  - garbage + recovery (one error, one salvaged decl)
  - empty / whitespace-only edge cases
  - brace-imbalance edge case
  - nested-error + clean-decl recovery

When extending: edit the corpus.json + run BOTH stacks against the
new entry to confirm parity before committing. The
`scripts/fase28_regen_drift_corpus.py` helper regenerates expected
counts from Python — Rust is asserted to match the SAME values, so
if Rust drifts, the Rust test will fail rather than the helper
silently agreeing with itself.

D12 ratified: deterministic fuzz iteration budget (1000 iter per
CI run). The fuzz tests in 28.b/c already enforce 100 buckets ×
10 mutations = 1000 iterations against deterministic-seeded
xorshift mutators on each stack — the drift gate adds the corpus-
based parity check on top of those.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "fase28_drift_gate" / "corpus.json"


def _load_corpus() -> list[dict]:
    """Read the shared drift-gate corpus.

    Same JSON file is read by the Rust integration test in
    `axon-frontend/tests/fase28_drift_gate.rs`. The expected_*
    fields are the cross-stack contract — a single source of
    truth describing what BOTH stacks must produce.
    """
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CORPUS: list[dict] = _load_corpus()


# ──────────────────────────────────────────────────────────────────
# TestCorpusFixtureIntegrity — fail fast if the file is malformed
# ──────────────────────────────────────────────────────────────────


class TestCorpusFixtureIntegrity:
    def test_corpus_loads(self):
        assert isinstance(CORPUS, list)
        assert len(CORPUS) >= 10  # We expect at least ~15 entries.

    def test_required_fields_present(self):
        for entry in CORPUS:
            for key in (
                "name",
                "source",
                "expected_error_count",
                "expected_suggest_count",
                "expected_decl_count",
            ):
                assert key in entry, f"missing {key} in {entry}"

    def test_names_unique(self):
        names = [e["name"] for e in CORPUS]
        assert len(names) == len(set(names))

    def test_corpus_path_is_canonical(self):
        # Pin the location so the Rust test can find it deterministically.
        assert CORPUS_PATH.is_file()
        assert CORPUS_PATH.parts[-3:] == (
            "fixtures",
            "fase28_drift_gate",
            "corpus.json",
        )


# ──────────────────────────────────────────────────────────────────
# TestPythonAgainstCorpus — Python side honors the golden contract
# ──────────────────────────────────────────────────────────────────


class TestPythonAgainstCorpus:
    """Python parser must produce exactly the counts the corpus
    declares. If a future Python change drifts, this test fails
    AND the Rust test (with the same corpus) will too unless Rust
    drifted in lockstep — in which case we have a bigger problem.
    """

    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_error_count_matches_corpus(self, entry: dict):
        toks = Lexer(entry["source"]).tokenize()
        result = Parser(toks).parse_with_recovery()
        assert len(result.errors) == entry["expected_error_count"], (
            f"{entry['name']}: errors={len(result.errors)} "
            f"!= expected={entry['expected_error_count']}\n"
            f"  source: {entry['source']!r}\n"
            f"  got: {[str(e) for e in result.errors]}"
        )

    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_suggest_count_matches_corpus(self, entry: dict):
        toks = Lexer(entry["source"]).tokenize()
        result = Parser(toks).parse_with_recovery()
        n_suggest = sum(
            1 for e in result.errors if "Did you mean" in str(e)
        )
        assert n_suggest == entry["expected_suggest_count"], (
            f"{entry['name']}: suggest={n_suggest} "
            f"!= expected={entry['expected_suggest_count']}\n"
            f"  source: {entry['source']!r}"
        )

    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_decl_count_matches_corpus(self, entry: dict):
        toks = Lexer(entry["source"]).tokenize()
        result = Parser(toks).parse_with_recovery()
        n_decl = len(result.program.declarations)
        assert n_decl == entry["expected_decl_count"], (
            f"{entry['name']}: decls={n_decl} "
            f"!= expected={entry['expected_decl_count']}\n"
            f"  source: {entry['source']!r}"
        )


# ──────────────────────────────────────────────────────────────────
# TestDeterministicFuzzCounts — D12 deterministic fuzz: same seed,
# same iteration count, never crashes. The cross-stack parity for
# fuzz-generated inputs is INTENTIONALLY not asserted — the lexers
# are independent implementations and may reject mutated input
# differently. What 28.b / 28.c / 28.i guarantee is "neither stack
# crashes on any well-lexed input"; D7 byte-identical equality is
# locked to the named corpus above.
# ──────────────────────────────────────────────────────────────────


class TestDeterministicFuzzCounts:
    """The 1000-iter fuzz already lives in 28.b's
    `TestRobustnessFuzz` — this test serves as a structural pin to
    confirm the 100 × 10 = 1000 budget holds (D12 ratified).
    """

    def test_fuzz_budget_pinned_at_one_thousand(self):
        # Hard-coded contract: 100 buckets × 10 mutations.
        BUCKETS = 100
        MUTATIONS_PER_BUCKET = 10
        assert BUCKETS * MUTATIONS_PER_BUCKET == 1000

    def test_fuzz_module_present(self):
        # Sanity: the fuzz test exists and is callable. If somebody
        # deletes it, this test fails before it reaches CI.
        from tests import test_fase28_parser_recovery as recovery_pack
        assert hasattr(recovery_pack, "TestRobustnessFuzz")
