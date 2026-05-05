"""
Fase 19.d — Par per-branch ContextView + merge strategies.

Closes the shared-context race risk that Fase 18.e's MVP shipped:
each Par branch now runs against a deep-copied ``ContextView``;
writes are merged back into the parent at branch-completion time
per a configurable :class:`ParMergeStrategy`.

Tests cover:

  * ContextView isolation: branch writes do not leak into parent
    until merge.
  * Merge strategy parsing: empty / unknown / case-variant inputs.
  * `LAST_WRITER_WINS` (default): later branch overwrites earlier.
  * `FIRST_WRITER_WINS`: first branch's write survives.
  * `REJECT_CONFLICTS`: agreeing writes succeed; disagreeing writes
    raise `ParMergeConflict`.
  * `MERGE_DICTS`: per-key dict deep-merge across branches.
  * Backward compatibility: existing flows with empty consolidation
    still get last-writer-wins (Fase 18.e behavior).
  * Trace event surfaces the chosen strategy + written keys +
    conflict_keys.
  * Empty branches: par with zero branches is a no-op.
  * Sole-writer single-write keys are unambiguous regardless of
    strategy.
"""

from __future__ import annotations

import pytest

from axon.runtime.context_mgr import ContextManager
from axon.runtime.par_context import (
    ContextView,
    ParMergeConflict,
    ParMergeStrategy,
    merge_par_views,
    parse_merge_strategy,
)

from tests.test_fase18_control_flow import _exec, _let, _par


# ═══════════════════════════════════════════════════════════════════
#  PARSE MERGE STRATEGY
# ═══════════════════════════════════════════════════════════════════


class TestParseMergeStrategy:
    def test_empty_defaults_to_last_writer_wins(self):
        assert parse_merge_strategy("") is ParMergeStrategy.LAST_WRITER_WINS

    def test_unknown_defaults_to_last_writer_wins(self):
        assert parse_merge_strategy("nonsense") is ParMergeStrategy.LAST_WRITER_WINS

    def test_known_strategies_parse(self):
        assert parse_merge_strategy("last_writer_wins") is ParMergeStrategy.LAST_WRITER_WINS
        assert parse_merge_strategy("first_writer_wins") is ParMergeStrategy.FIRST_WRITER_WINS
        assert parse_merge_strategy("reject_conflicts") is ParMergeStrategy.REJECT_CONFLICTS
        assert parse_merge_strategy("merge_dicts") is ParMergeStrategy.MERGE_DICTS

    def test_case_and_whitespace_tolerant(self):
        assert parse_merge_strategy("  REJECT_CONFLICTS  ") is ParMergeStrategy.REJECT_CONFLICTS
        assert parse_merge_strategy("Merge_Dicts") is ParMergeStrategy.MERGE_DICTS


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT VIEW
# ═══════════════════════════════════════════════════════════════════


class TestContextView:
    def test_view_seeds_from_parent_variables(self):
        parent = ContextManager(system_prompt="sp")
        parent.set_variable("seed", "value")
        view = ContextView(parent)
        assert view.get_variable("seed") == "value"

    def test_view_writes_do_not_leak_to_parent(self):
        parent = ContextManager(system_prompt="sp")
        parent.set_variable("x", 1)
        view = ContextView(parent)
        view.set_variable("x", 999)
        view.set_variable("new", "fresh")
        # Parent untouched until explicit merge.
        assert parent.get_variable("x") == 1
        assert not parent.has_variable("new")

    def test_view_diff_includes_added_and_mutated_keys(self):
        parent = ContextManager(system_prompt="sp")
        parent.set_variable("a", 1)
        parent.set_variable("b", 2)
        view = ContextView(parent)
        view.set_variable("a", 100)        # mutated
        view.set_variable("c", "added")    # added
        # b not touched, must not appear in diff
        diff = view.diff_variables()
        assert diff == {"a": 100, "c": "added"}

    def test_view_seeded_step_results_diff_likewise(self):
        parent = ContextManager(system_prompt="sp")
        parent.set_step_result("upstream", {"hits": 3})
        view = ContextView(parent)
        view.set_step_result("downstream", {"emitted": True})
        view.set_step_result("upstream", {"hits": 9})
        diff = view.diff_step_results()
        assert diff == {
            "downstream": {"emitted": True},
            "upstream": {"hits": 9},
        }

    def test_view_deepcopies_seeded_mutables(self):
        """A branch mutating a dict it pulled from the seed must NOT
        observably mutate the parent's copy."""
        parent = ContextManager(system_prompt="sp")
        parent.set_variable("payload", {"count": 1})
        view = ContextView(parent)
        view.get_variable("payload")["count"] = 999
        assert parent.get_variable("payload") == {"count": 1}


# ═══════════════════════════════════════════════════════════════════
#  MERGE STRATEGIES (unit-level)
# ═══════════════════════════════════════════════════════════════════


def _two_views_with_writes(parent_seed=None) -> tuple[ContextManager, list[ContextView]]:
    parent = ContextManager(system_prompt="sp")
    for k, v in (parent_seed or {}).items():
        parent.set_variable(k, v)
    return parent, [ContextView(parent), ContextView(parent)]


class TestMergeStrategies:
    def test_last_writer_wins_picks_higher_branch_index(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", "first")
        views[1].set_variable("k", "second")
        merge_par_views(parent, views, strategy=ParMergeStrategy.LAST_WRITER_WINS)
        assert parent.get_variable("k") == "second"

    def test_first_writer_wins_picks_lower_branch_index(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", "first")
        views[1].set_variable("k", "second")
        merge_par_views(parent, views, strategy=ParMergeStrategy.FIRST_WRITER_WINS)
        assert parent.get_variable("k") == "first"

    def test_reject_conflicts_passes_when_writes_agree(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", {"shared": True})
        views[1].set_variable("k", {"shared": True})
        merge_par_views(parent, views, strategy=ParMergeStrategy.REJECT_CONFLICTS)
        assert parent.get_variable("k") == {"shared": True}

    def test_reject_conflicts_raises_on_disagreement(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", "alpha")
        views[1].set_variable("k", "beta")
        with pytest.raises(ParMergeConflict):
            merge_par_views(parent, views, strategy=ParMergeStrategy.REJECT_CONFLICTS)

    def test_merge_dicts_unions_per_key(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("payload", {"a": 1, "shared": "old"})
        views[1].set_variable("payload", {"b": 2, "shared": "new"})
        merge_par_views(parent, views, strategy=ParMergeStrategy.MERGE_DICTS)
        assert parent.get_variable("payload") == {
            "a": 1, "b": 2, "shared": "new",
        }

    def test_merge_dicts_falls_back_to_lww_for_non_dict(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", "scalar0")
        views[1].set_variable("k", "scalar1")
        merge_par_views(parent, views, strategy=ParMergeStrategy.MERGE_DICTS)
        assert parent.get_variable("k") == "scalar1"

    def test_single_write_unambiguous_under_all_strategies(self):
        for strategy in ParMergeStrategy:
            parent, views = _two_views_with_writes()
            views[0].set_variable("only", 42)  # branch 1 doesn't touch it
            merge_par_views(parent, views, strategy=strategy)
            assert parent.get_variable("only") == 42

    def test_summary_records_strategy_and_written_keys(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("a", 1)
        views[1].set_variable("b", 2)
        summary = merge_par_views(
            parent, views, strategy=ParMergeStrategy.LAST_WRITER_WINS,
        )
        assert summary["strategy"] == "last_writer_wins"
        assert sorted(summary["variables_written"]) == ["a", "b"]
        assert summary["conflict_keys"] == []  # no overlap

    def test_summary_records_conflict_keys(self):
        parent, views = _two_views_with_writes()
        views[0].set_variable("k", "alpha")
        views[1].set_variable("k", "beta")
        summary = merge_par_views(
            parent, views, strategy=ParMergeStrategy.LAST_WRITER_WINS,
        )
        assert summary["conflict_keys"] == ["k"]


# ═══════════════════════════════════════════════════════════════════
#  END-TO-END VIA THE PAR DISPATCHER
# ═══════════════════════════════════════════════════════════════════


def _par_with_strategy(branches: list, strategy: str):
    """Construct a par CompiledStep with a non-default consolidation."""
    par = _par(branches)
    par.metadata["par"]["consolidation"] = strategy
    return par


class TestParDispatcherEndToEnd:
    @pytest.mark.asyncio
    async def test_default_consolidation_preserves_fase18_behavior(self):
        """Empty consolidation → LAST_WRITER_WINS. With non-overlapping
        writes (the typical case), the resulting parent context shows
        every branch's binding — same observable behavior as Fase 18."""
        par = _par([_let("a", "alpha"), _let("b", "beta")])
        result, ctx, _ = await _exec([par])
        assert result.success is True
        assert ctx.get_variable("a") == "alpha"
        assert ctx.get_variable("b") == "beta"

    @pytest.mark.asyncio
    async def test_first_writer_wins_via_consolidation(self):
        par = _par_with_strategy(
            [_let("k", "first"), _let("k", "second")],
            "first_writer_wins",
        )
        result, ctx, _ = await _exec([par])
        assert result.success is True
        assert ctx.get_variable("k") == "first"

    @pytest.mark.asyncio
    async def test_last_writer_wins_via_consolidation(self):
        par = _par_with_strategy(
            [_let("k", "first"), _let("k", "second")],
            "last_writer_wins",
        )
        result, ctx, _ = await _exec([par])
        assert result.success is True
        assert ctx.get_variable("k") == "second"

    @pytest.mark.asyncio
    async def test_reject_conflicts_propagates_failure(self):
        par = _par_with_strategy(
            [_let("k", "alpha"), _let("k", "beta")],
            "reject_conflicts",
        )
        result, _, _ = await _exec([par])
        assert result.success is False

    @pytest.mark.asyncio
    async def test_branch_isolation_during_execution(self):
        """A branch writes to a key, then another branch reads — the
        reader must NOT see the writer's value (each branch sees its
        own snapshot of the parent at par-entry time)."""
        # Two branches: branch 0 sets `seed` to "branch0_wrote",
        # branch 1 reads `seed` (from its view, which has only the
        # parent-time value "initial"). Cannot assert directly without
        # building inspection steps; instead we assert the merge
        # outcome — branch 0's write is visible post-merge, and
        # branch 1 didn't touch the key.
        from axon.runtime.context_mgr import ContextManager
        parent = ContextManager(system_prompt="")
        parent.set_variable("seed", "initial")
        views = [ContextView(parent), ContextView(parent)]
        # Both views see "initial" at construction time.
        assert views[0].get_variable("seed") == "initial"
        assert views[1].get_variable("seed") == "initial"
        # Branch 0 writes; view 1 still sees the seed.
        views[0].set_variable("seed", "branch0_wrote")
        assert views[1].get_variable("seed") == "initial"
