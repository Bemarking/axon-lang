"""
Par per-branch context isolation + merge strategies (Fase 19.d).

Fase 18.e shipped Par with shared-context concurrency: all branches
wrote into the same ``ContextManager``. Under high write contention
two concurrent branches could clobber each other in non-deterministic
ways, with the surviving value depending on asyncio interleaving.

Fase 19.d closes that race risk:

  * Each branch runs against a :class:`ContextView` — a deep-copied
    seed of the parent context. Reads see the snapshot; writes are
    captured locally without touching the parent.
  * After all branches complete, the executor merges the per-branch
    diffs back into the parent context via a configurable
    :class:`ParMergeStrategy`. Conflicts are resolved per the chosen
    policy.

Four built-in strategies:

  * ``LAST_WRITER_WINS`` — branch order in source code is the
    tiebreaker; later branches overwrite earlier ones. Default
    (matches Fase 18.e MVP behavior).
  * ``FIRST_WRITER_WINS`` — first branch (source order) to write a
    given key wins; subsequent writes are dropped.
  * ``REJECT_CONFLICTS`` — any disagreement raises
    :class:`ParMergeConflict`. Use when adopters require zero
    silent overwrites (e.g. financial or safety-critical flows).
  * ``MERGE_DICTS`` — for keys whose all-branch values are dicts,
    deep-merge them via union of keys (per-key
    last-writer-wins on scalars). For non-dict values, falls back
    to ``LAST_WRITER_WINS``.

Out-of-scope per plan §Fase 19: custom strategies beyond the four
built-ins; cross-process Par (the views are in-process snapshots).
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Any

from axon.runtime.context_mgr import ContextManager
from axon.runtime.runtime_errors import AxonRuntimeError


# ═══════════════════════════════════════════════════════════════════
#  MERGE STRATEGY ENUM + ERROR
# ═══════════════════════════════════════════════════════════════════


class ParMergeStrategy(str, Enum):
    """Policy for merging per-branch context diffs back into the
    parent at the end of a Par block.

    Stored as ``str`` so the IR's ``consolidation`` field (already a
    free-form string) can carry the strategy name without an IR
    schema bump. Unknown / empty strings resolve to
    :data:`LAST_WRITER_WINS`.
    """

    LAST_WRITER_WINS = "last_writer_wins"
    FIRST_WRITER_WINS = "first_writer_wins"
    REJECT_CONFLICTS = "reject_conflicts"
    MERGE_DICTS = "merge_dicts"


def parse_merge_strategy(spec: str) -> ParMergeStrategy:
    """Coerce a free-form ``consolidation`` string into a strategy.

    Empty / unknown strings default to ``LAST_WRITER_WINS`` (the
    Fase 18.e behavior). Adopters who typo a strategy name still
    get well-defined semantics; they can verify the resolved
    strategy via the ``par`` step's STEP_END trace event.
    """
    if not spec:
        return ParMergeStrategy.LAST_WRITER_WINS
    try:
        return ParMergeStrategy(spec.strip().lower())
    except ValueError:
        return ParMergeStrategy.LAST_WRITER_WINS


class ParMergeConflict(AxonRuntimeError):
    """Raised by ``REJECT_CONFLICTS`` when two branches write
    different values to the same key.

    Carries the conflicting key + the per-branch values for adopter
    diagnosis."""


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT VIEW — per-branch shielded snapshot
# ═══════════════════════════════════════════════════════════════════


class ContextView(ContextManager):
    """Per-branch shielded view of a parent ``ContextManager``.

    On construction, deep-copies the parent's variables + step results
    into the view's own dicts. Subsequent ``set_variable`` /
    ``set_step_result`` calls inside the branch mutate the view's
    state only — the parent is untouched until the explicit merge
    step.

    Typed-channel state (``typed_bus``, capabilities, discovered
    handles) is **shared** with the parent, intentionally:

      * Capabilities have one-shot semantics by design (publish-once,
        discover-once); duplicating them per-branch would break the
        affine type guarantees.
      * The TypedEventBus carries pending broadcasts that must reach
        all listeners regardless of which branch they live in.

    Adopters whose Par branches publish capabilities should be aware
    that a discover from a sibling branch can race; this is the
    correct semantics for π-calc mobility (capabilities are mobile
    and one-shot), not a regression.
    """

    def __init__(self, parent: ContextManager) -> None:
        # Deliberately do NOT call super().__init__ from the parent's
        # arguments — we want to own the message list / current_step,
        # but seed variables + step_results from the parent snapshot.
        super().__init__(
            system_prompt=parent.system_prompt,
            tracer=parent._tracer,
        )
        self._parent = parent
        self._variables = copy.deepcopy(parent._variables)
        self._step_results = copy.deepcopy(parent._step_results)
        # Snapshot the seed for diff computation at merge time.
        self._seed_variables = copy.deepcopy(self._variables)
        self._seed_step_results = copy.deepcopy(self._step_results)
        # Share typed-channel state with the parent (see class docstring).
        self._typed_bus = parent._typed_bus
        self._capabilities = parent._capabilities
        self._discovered_handles = parent._discovered_handles
        # Branches share message history reads but write into their own
        # buffer — merging messages back is left to the strategy
        # (current strategies do not merge conversation history).
        self._messages = list(parent._messages)

    @property
    def parent(self) -> ContextManager:
        """The underlying parent context that produced this view."""
        return self._parent

    def diff_variables(self) -> dict[str, Any]:
        """Variables added or mutated in this view relative to the
        seed taken at construction. Insertion order is preserved."""
        return {
            key: value
            for key, value in self._variables.items()
            if key not in self._seed_variables
            or self._seed_variables[key] != value
        }

    def diff_step_results(self) -> dict[str, Any]:
        """Step results added or mutated in this view relative to the
        seed taken at construction. Insertion order is preserved."""
        return {
            key: value
            for key, value in self._step_results.items()
            if key not in self._seed_step_results
            or self._seed_step_results[key] != value
        }


# ═══════════════════════════════════════════════════════════════════
#  MERGE
# ═══════════════════════════════════════════════════════════════════


def _deep_merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict union; for overlapping keys whose values are
    both dicts, recurse; otherwise b wins (per-call last-writer)."""
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dicts(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_writes(
    writes: list[tuple[int, Any]],
    *,
    strategy: ParMergeStrategy,
    key: str,
    kind: str,
) -> Any:
    """Pick the winning value for a key given the per-branch writes.

    ``writes`` is a list of ``(branch_idx, value)`` in source order.
    Caller has already grouped writes by key.
    """
    # Single write → unambiguous regardless of strategy.
    if len(writes) == 1:
        return writes[0][1]

    if strategy is ParMergeStrategy.FIRST_WRITER_WINS:
        return writes[0][1]

    if strategy is ParMergeStrategy.LAST_WRITER_WINS:
        return writes[-1][1]

    if strategy is ParMergeStrategy.REJECT_CONFLICTS:
        # All writes must agree by value for the merge to succeed.
        seed = writes[0][1]
        for branch_idx, value in writes[1:]:
            if value != seed:
                raise ParMergeConflict(
                    f"par merge conflict on {kind} '{key}': "
                    f"branch 0 wrote {seed!r}, branch {branch_idx} "
                    f"wrote {value!r}. Strategy=reject_conflicts."
                )
        return seed

    if strategy is ParMergeStrategy.MERGE_DICTS:
        # If all values are dicts, deep-merge in source order. If any
        # is non-dict, fall back to last-writer-wins (documented
        # behavior).
        if all(isinstance(v, dict) for _, v in writes):
            merged: dict[str, Any] = {}
            for _, v in writes:
                merged = _deep_merge_dicts(merged, v)
            return merged
        return writes[-1][1]

    # Defensive — unknown enum member would mean a code change went
    # untested; surface explicitly rather than silently mis-merging.
    raise AxonRuntimeError(  # pragma: no cover
        f"par merge: unknown strategy {strategy!r}"
    )


def merge_par_views(
    parent: ContextManager,
    views: list[ContextView],
    *,
    strategy: ParMergeStrategy,
) -> dict[str, Any]:
    """Merge per-branch view diffs back into the parent context.

    Returns a structured summary of the merge — useful for the
    STEP_END trace event so adopters can see which keys were touched
    by which branches.

    Raises :class:`ParMergeConflict` under ``REJECT_CONFLICTS`` when
    two branches disagree on a value. Mutates ``parent`` in place
    on the success path.
    """
    # key → [(branch_idx, value), ...] in branch source order.
    var_writes: dict[str, list[tuple[int, Any]]] = {}
    step_writes: dict[str, list[tuple[int, Any]]] = {}
    for idx, view in enumerate(views):
        for k, v in view.diff_variables().items():
            var_writes.setdefault(k, []).append((idx, v))
        for k, v in view.diff_step_results().items():
            step_writes.setdefault(k, []).append((idx, v))

    var_resolved: dict[str, Any] = {}
    for key, writes in var_writes.items():
        var_resolved[key] = _resolve_writes(
            writes, strategy=strategy, key=key, kind="variable",
        )

    step_resolved: dict[str, Any] = {}
    for key, writes in step_writes.items():
        step_resolved[key] = _resolve_writes(
            writes, strategy=strategy, key=key, kind="step_result",
        )

    # Apply.
    for key, value in var_resolved.items():
        parent.set_variable(key, value)
    for key, value in step_resolved.items():
        parent.set_step_result(key, value)

    def _has_value_disagreement(writes: list[tuple[int, Any]]) -> bool:
        """True iff at least two writes disagree by ``==``. Hashability-
        safe — does not put values in a set (dicts/lists are common
        write payloads and are unhashable)."""
        if len(writes) < 2:
            return False
        first = writes[0][1]
        return any(v != first for _, v in writes[1:])

    return {
        "strategy": strategy.value,
        "variables_written": sorted(var_resolved.keys()),
        "step_results_written": sorted(step_resolved.keys()),
        "conflict_keys": sorted(
            k for k, w in var_writes.items() if _has_value_disagreement(w)
        ),
    }


__all__ = [
    "ContextView",
    "ParMergeConflict",
    "ParMergeStrategy",
    "merge_par_views",
    "parse_merge_strategy",
]
