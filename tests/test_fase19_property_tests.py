"""
Fase 19.j — Hypothesis property tests for the Fase 19 dispatchers.

Sample-based tests verify specific scenarios; property tests assert
INVARIANTS that must hold for ALL valid inputs. The plan promises
≥100 examples per primitive — Hypothesis defaults to ~100 trials per
property which we accept.

Properties verified:

  * **HibernationStore round-trip**: for any session_id + variables,
    save → load returns the same snapshot.
  * **ContinuityTokenSigner symmetric integrity**: every token signed
    by a key verifies under the same key and produces back the
    original session_id.
  * **ParMergeStrategy idempotence**: applying the same strategy
    twice in sequence produces the same merged state.
  * **ContextView write isolation**: branches mutating their views
    never leak writes into the parent until merge.
  * **parse_timeout monotonicity**: increasing the duration spec
    yields a non-decreasing TTL.
  * **Hibernation token unforgeability**: a token signed under key A
    NEVER verifies under a different key B (cryptographic invariant).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from axon.runtime.context_mgr import ContextManager
from axon.runtime.par_context import (
    ContextView,
    ParMergeStrategy,
    merge_par_views,
)
from axon.runtime.pem import (
    ContinuityToken,
    ContinuityTokenSigner,
    HibernationSnapshot,
    InMemoryHibernationStore,
    TokenForgedOrRotated,
    new_token,
    parse_timeout,
)


# ═══════════════════════════════════════════════════════════════════
#  HIBERNATION STORE — round-trip property
# ═══════════════════════════════════════════════════════════════════


_safe_keys = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=20,
)
_safe_values = st.one_of(
    st.text(max_size=50),
    st.integers(),
    st.booleans(),
    st.lists(st.integers(), max_size=5),
)


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    session_id=st.text(min_size=1, max_size=40),
    variables=st.dictionaries(_safe_keys, _safe_values, max_size=8),
)
def test_hibernation_store_save_load_roundtrip(session_id, variables):
    """For any valid (session_id, variables), save followed by load
    returns the exact snapshot we stored. No data drift, no key
    collision."""
    store = InMemoryHibernationStore()
    snapshot = HibernationSnapshot(
        session_id=session_id,
        flow_name="flow",
        variables=variables,
    )
    store.save(session_id, snapshot)
    loaded = store.load(session_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.variables == variables


# ═══════════════════════════════════════════════════════════════════
#  CONTINUITY TOKEN — symmetric integrity
# ═══════════════════════════════════════════════════════════════════


@settings(deadline=None)
@given(
    session_id=st.text(min_size=1, max_size=80).filter(
        lambda s: "\x1e" not in s  # field separator must not appear in payload
    ),
    ttl_seconds=st.integers(min_value=10, max_value=86400),
)
def test_continuity_token_sign_verify_round_trip(session_id, ttl_seconds):
    """Every token signed by a key verifies under that key and
    recovers the original session_id."""
    signer = ContinuityTokenSigner(secrets.token_bytes(32))
    token = new_token(session_id, ttl=timedelta(seconds=ttl_seconds))
    raw = signer.sign(token)
    decoded = signer.verify(raw)
    assert decoded.session_id == session_id


@settings(deadline=None)
@given(
    session_id=st.text(min_size=1, max_size=40).filter(
        lambda s: "\x1e" not in s
    ),
)
def test_continuity_token_unforgeable_under_different_key(session_id):
    """A token signed by key A never verifies under a different key
    B. Cryptographic invariant — the test enforces it under arbitrary
    session_ids."""
    key_a = secrets.token_bytes(32)
    key_b = secrets.token_bytes(32)
    # Defensive: extremely unlikely but keys could coincide; reject.
    if key_a == key_b:
        return
    signer_a = ContinuityTokenSigner(key_a)
    signer_b = ContinuityTokenSigner(key_b)
    raw = signer_a.sign(new_token(session_id, timedelta(hours=1)))
    with pytest.raises(TokenForgedOrRotated):
        signer_b.verify(raw)


# ═══════════════════════════════════════════════════════════════════
#  PARSE TIMEOUT — monotonicity
# ═══════════════════════════════════════════════════════════════════


@given(seconds=st.integers(min_value=0, max_value=86400 * 7))
def test_parse_timeout_seconds_monotonicity(seconds):
    """parse_timeout with `Ns` produces exactly N seconds for valid N."""
    result = parse_timeout(f"{seconds}s")
    assert result == timedelta(seconds=seconds)


@given(
    a=st.integers(min_value=1, max_value=3600),
    b=st.integers(min_value=1, max_value=3600),
)
def test_parse_timeout_ordering_preserved(a, b):
    """If a < b, parse_timeout(`as`) <= parse_timeout(`bs`)."""
    if a < b:
        assert parse_timeout(f"{a}s") < parse_timeout(f"{b}s")
    elif a == b:
        assert parse_timeout(f"{a}s") == parse_timeout(f"{b}s")


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT VIEW — write isolation
# ═══════════════════════════════════════════════════════════════════


@given(
    parent_vars=st.dictionaries(_safe_keys, _safe_values, max_size=5),
    branch_writes=st.dictionaries(_safe_keys, _safe_values, max_size=5),
)
def test_context_view_writes_do_not_leak_to_parent(
    parent_vars, branch_writes,
):
    """For any parent variable set + any branch write set, the
    branch's writes must NOT be observable on the parent before
    merge. Pre-merge, parent retains its original state exactly."""
    parent = ContextManager(system_prompt="")
    for k, v in parent_vars.items():
        parent.set_variable(k, v)
    parent_snapshot = dict(parent.get_variables())

    view = ContextView(parent)
    for k, v in branch_writes.items():
        view.set_variable(k, v)

    # Parent untouched.
    assert parent.get_variables() == parent_snapshot


# ═══════════════════════════════════════════════════════════════════
#  PAR MERGE — strategy invariants
# ═══════════════════════════════════════════════════════════════════


@given(
    keys=st.lists(_safe_keys, min_size=1, max_size=5, unique=True),
    values=st.lists(_safe_values, min_size=1, max_size=5),
)
def test_last_writer_wins_picks_higher_branch(keys, values):
    """For any two branches writing the same keys, LAST_WRITER_WINS
    picks branch 1's value when both branches write."""
    parent = ContextManager(system_prompt="")
    views = [ContextView(parent), ContextView(parent)]
    # Branch 0 writes key=values[0]; branch 1 writes key=values[-1].
    target_key = keys[0]
    early_value = values[0]
    late_value = values[-1]
    views[0].set_variable(target_key, early_value)
    views[1].set_variable(target_key, late_value)
    merge_par_views(parent, views, strategy=ParMergeStrategy.LAST_WRITER_WINS)
    assert parent.get_variable(target_key) == late_value


@given(
    keys=st.lists(_safe_keys, min_size=1, max_size=5, unique=True),
    values=st.lists(_safe_values, min_size=1, max_size=5),
)
def test_first_writer_wins_picks_lower_branch(keys, values):
    """Symmetric to LAST_WRITER_WINS — FIRST_WRITER_WINS picks
    branch 0's value."""
    parent = ContextManager(system_prompt="")
    views = [ContextView(parent), ContextView(parent)]
    target_key = keys[0]
    early_value = values[0]
    late_value = values[-1]
    views[0].set_variable(target_key, early_value)
    views[1].set_variable(target_key, late_value)
    merge_par_views(parent, views, strategy=ParMergeStrategy.FIRST_WRITER_WINS)
    assert parent.get_variable(target_key) == early_value


@given(
    disjoint_keys=st.lists(
        _safe_keys, min_size=2, max_size=6, unique=True,
    ),
)
def test_merge_disjoint_writes_unaffected_by_strategy(disjoint_keys):
    """When two branches write to NON-overlapping keys, every merge
    strategy yields the same final state — the union of writes."""
    if len(disjoint_keys) < 2:
        return
    half = len(disjoint_keys) // 2
    keys_a = disjoint_keys[:half]
    keys_b = disjoint_keys[half:]

    expected = {}
    for k in keys_a:
        expected[k] = "from-branch-0"
    for k in keys_b:
        expected[k] = "from-branch-1"

    for strategy in ParMergeStrategy:
        parent = ContextManager(system_prompt="")
        views = [ContextView(parent), ContextView(parent)]
        for k in keys_a:
            views[0].set_variable(k, "from-branch-0")
        for k in keys_b:
            views[1].set_variable(k, "from-branch-1")
        merge_par_views(parent, views, strategy=strategy)
        actual = parent.get_variables()
        for k, v in expected.items():
            assert actual[k] == v, (
                f"strategy={strategy.value}: key {k!r} = {actual[k]!r}, "
                f"expected {v!r}"
            )


@given(
    seed_value=_safe_values,
    branch_writes=st.lists(_safe_values, min_size=1, max_size=4),
)
def test_par_merge_idempotent_on_re_merge(seed_value, branch_writes):
    """Merging an already-merged state into itself must be a no-op
    (the parent's state after the second merge equals the state
    after the first). Idempotence under repeated merge."""
    parent = ContextManager(system_prompt="")
    parent.set_variable("seed", seed_value)
    views = [ContextView(parent) for _ in branch_writes]
    for i, v in enumerate(branch_writes):
        views[i].set_variable("seed", v)
    merge_par_views(parent, views, strategy=ParMergeStrategy.LAST_WRITER_WINS)
    state_after_first = dict(parent.get_variables())

    # Re-merge with NEW views constructed from the post-merge parent.
    # Empty diffs → nothing to apply → parent state unchanged.
    new_views = [ContextView(parent), ContextView(parent)]
    merge_par_views(parent, new_views, strategy=ParMergeStrategy.LAST_WRITER_WINS)
    assert parent.get_variables() == state_after_first
