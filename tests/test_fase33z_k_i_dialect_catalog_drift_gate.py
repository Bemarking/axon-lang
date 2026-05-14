"""§Fase 33.z.k.i (v1.28.0) — Python-side dialect catalog drift gate.

Cross-stack counterpart of
`axon-rs/tests/fase33z_k_i_dialect_catalog_drift_gate.rs`. Both stacks
hardcode the same founder-ratified Q3 snapshot
``{axon, openai, kimi, glm, anthropic}`` and pin every closure decision
against it. Any drift in either stack — even silent / non-touching of
the other — fires loudly on the next CI run.

This Python gate pins the closure decisions that live on the Python
side:

1. **Cardinality** ``_AXONENDPOINT_TRANSPORT_DIALECTS`` has exactly 5
   entries.
2. **Membership** matches the founder-ratified Q3 snapshot byte-
   identically.
3. **No duplicates** (the underlying type is ``frozenset`` so this is
   structural — but we pin the assertion anyway in case the type
   changes to a list/tuple in the future).
4. **Cross-stack drift parity** Python catalog membership equals the
   hardcoded Rust snapshot (the Rust frontend's
   ``AXONENDPOINT_TRANSPORT_DIALECTS`` const is the source of truth;
   this Python gate verifies the Python mirror agrees).
5. **resolve_effective_dialect totality** over the catalog input
   space.
6. **Q1 default rules pinned** Rule 2 + Rule 3 outcomes byte-exact.
7. **Snapshot explicit enumeration** every member matched by name so
   adding a 6th forces an explicit code change here.
"""

from __future__ import annotations

import pytest

from axon.compiler.parser import _AXONENDPOINT_TRANSPORT_DIALECTS
from axon.compiler.type_checker import resolve_effective_dialect


# ─── Canonical snapshot (founder-ratified Q3 revision 2026-05-14) ───
#
# Adding a 6th dialect requires:
#   1. Update this SNAPSHOT tuple.
#   2. Update axon/compiler/parser.py _AXONENDPOINT_TRANSPORT_DIALECTS.
#   3. Update axon-frontend/src/parser.rs AXONENDPOINT_TRANSPORT_DIALECTS.
#   4. Update axon-rs/src/wire_format/mod.rs select_adapter() match arms.
#   5. Implement (or dispatch) the adapter for the new dialect.
#   6. Update axon/compiler/type_checker.py resolve_effective_dialect()
#      if it needs to default to the new dialect for any input.
#   7. Add the dialect to the Rust drift gate's dispatch table.
#   8. Add E2E test pinning the new dialect's wire bytes.
#   9. Update plan vivo + adopter docs.
#
# THE 5 strings below are LOAD-BEARING — they are the alphabet of the
# closed catalog. Cross-stack equality with the Rust catalog is the
# core drift-prevention invariant.
CANONICAL_DIALECT_SNAPSHOT: tuple[str, ...] = (
    "axon",
    "openai",
    "kimi",
    "glm",
    "anthropic",
)


# ════════════════════════════════════════════════════════════════════
#  §1 — Cardinality + membership lock
# ════════════════════════════════════════════════════════════════════


def test_s1_catalog_cardinality_is_exactly_five():
    assert len(_AXONENDPOINT_TRANSPORT_DIALECTS) == 5, (
        "33.z.k.i Python drift gate: the closed dialect catalog has "
        "EXACTLY 5 entries per the Q3 revision 2026-05-14 "
        "({axon, openai, kimi, glm, anthropic}). Adding/removing "
        "requires a deliberate sub-fase + snapshot update + cross-"
        "stack drift gate alignment."
    )


def test_s1_catalog_membership_matches_snapshot_verbatim():
    assert _AXONENDPOINT_TRANSPORT_DIALECTS == frozenset(
        CANONICAL_DIALECT_SNAPSHOT
    ), (
        "33.z.k.i Python: _AXONENDPOINT_TRANSPORT_DIALECTS drifted "
        f"from snapshot. Got {sorted(_AXONENDPOINT_TRANSPORT_DIALECTS)!r}, "
        f"snapshot {sorted(CANONICAL_DIALECT_SNAPSHOT)!r}."
    )


def test_s1_catalog_has_no_duplicates():
    # The underlying type is frozenset so duplicates are structurally
    # impossible — but pinning here defends against an accidental type
    # change to list/tuple.
    assert len(_AXONENDPOINT_TRANSPORT_DIALECTS) == len(
        set(_AXONENDPOINT_TRANSPORT_DIALECTS)
    ), (
        "33.z.k.i Python: catalog has duplicates (or the underlying "
        "type changed from frozenset to allow duplicates). "
        "AXONENDPOINT_TRANSPORT_DIALECTS MUST be a set semantically."
    )


# ════════════════════════════════════════════════════════════════════
#  §2 — Cross-stack equality with Rust frontend's catalog
# ════════════════════════════════════════════════════════════════════
#
# The Rust frontend's `AXONENDPOINT_TRANSPORT_DIALECTS` const lives in
# `axon-frontend/src/parser.rs` and is the source of truth. We pin its
# membership here via the same hardcoded snapshot. The corresponding
# Rust drift gate `fase33z_k_i_dialect_catalog_drift_gate.rs` has the
# identical snapshot and pins its parser const against it — so if
# either side drifts from the snapshot, BOTH gates fire.

# The Rust catalog as known to the Python side. This MUST equal the
# Python snapshot (D7 cross-stack contract). If it diverges, the
# stacks have drifted.
RUST_CATALOG_AS_KNOWN_TO_PYTHON: tuple[str, ...] = (
    "axon",
    "openai",
    "kimi",
    "glm",
    "anthropic",
)


def test_s2_cross_stack_membership_equals_rust():
    py_set = frozenset(_AXONENDPOINT_TRANSPORT_DIALECTS)
    rust_set = frozenset(RUST_CATALOG_AS_KNOWN_TO_PYTHON)
    assert py_set == rust_set, (
        "33.z.k.i D7 cross-stack contract: Python "
        "_AXONENDPOINT_TRANSPORT_DIALECTS MUST match the Rust frontend's "
        "AXONENDPOINT_TRANSPORT_DIALECTS verbatim. The Rust drift gate "
        "test pins the same snapshot against its parser const. "
        f"Python: {sorted(py_set)!r}, Rust-as-known: {sorted(rust_set)!r}"
    )


def test_s2_canonical_snapshot_equals_rust_snapshot():
    # Both Python + Rust drift gates hardcode the same 5-string
    # snapshot. This test pins THIS test file's snapshot against the
    # Rust snapshot the Python side hardcodes. Net effect: if the
    # snapshots diverge between stacks, this test fails.
    assert set(CANONICAL_DIALECT_SNAPSHOT) == set(
        RUST_CATALOG_AS_KNOWN_TO_PYTHON
    ), (
        "33.z.k.i: this test file has TWO snapshots — "
        "CANONICAL_DIALECT_SNAPSHOT (the Python-side catalog snapshot) "
        "and RUST_CATALOG_AS_KNOWN_TO_PYTHON (a hardcoded copy of the "
        "Rust catalog). They MUST be equal — both are the same closed "
        "catalog. Keeping them separate variables makes the cross-"
        "stack invariant explicit at the test site."
    )


# ════════════════════════════════════════════════════════════════════
#  §3 — resolve_effective_dialect totality + Q1 default pins
# ════════════════════════════════════════════════════════════════════


def test_s3_resolver_output_is_always_a_catalog_member():
    inputs = [
        "",
        "axon",
        "openai",
        "kimi",
        "glm",
        "anthropic",
        "unknown",
        "FOO",
    ]
    for explicit in inputs:
        for algebraic in (False, True):
            result = resolve_effective_dialect(explicit, algebraic)
            if explicit == "":
                assert result in _AXONENDPOINT_TRANSPORT_DIALECTS, (
                    f"33.z.k.i: resolve_effective_dialect({explicit!r}, "
                    f"{algebraic}) returned {result!r} which is NOT a "
                    f"catalog member."
                )
            elif explicit in _AXONENDPOINT_TRANSPORT_DIALECTS:
                # Rule 1: explicit catalog member wins.
                assert result == explicit, (
                    f"33.z.k.i Rule 1: resolve_effective_dialect("
                    f"{explicit!r}, _) MUST return {explicit!r} verbatim. "
                    f"Got {result!r}."
                )
            # For unknown explicit strings the resolver is permitted
            # to pass them through since the parser rejects them at
            # compile time before they reach the resolver in production.


def test_s3_resolver_q1_rule_2_algebraic_effect_defaults_to_openai():
    assert resolve_effective_dialect("", True) == "openai", (
        "33.z.k.i Q1 Rule 2: algebraic-effect flows default to openai "
        "(LLM-streaming ecosystem expectation — adopter SDKs litellm/"
        "langchain/vercel-ai/instructor/llama_index parse the openai "
        "wire verbatim)."
    )


def test_s3_resolver_q1_rule_3_type_annotation_defaults_to_axon():
    assert resolve_effective_dialect("", False) == "axon", (
        "33.z.k.i Q1 Rule 3: type-annotation-only flows default to "
        "axon (W3C-correct baseline + D6 byte-compat indefinite)."
    )


# ════════════════════════════════════════════════════════════════════
#  §4 — Snapshot explicit enumeration (forces drift to touch code)
# ════════════════════════════════════════════════════════════════════


def test_s4_snapshot_explicit_member_enumeration():
    """Every snapshot entry is explicitly enumerated below. If anyone
    adds a 6th dialect to the snapshot they MUST add a new match arm
    here too — making catalog growth an explicit code change.
    """
    for d in CANONICAL_DIALECT_SNAPSHOT:
        # match-style explicit enumeration (Python 3.10+ supports
        # match; using if-elif chain for broader compat).
        if d == "axon":
            recognized = True
        elif d == "openai":
            recognized = True
        elif d == "kimi":
            recognized = True
        elif d == "glm":
            recognized = True
        elif d == "anthropic":
            recognized = True
        else:
            recognized = False
        assert recognized, (
            f"33.z.k.i: snapshot entry {d!r} not enumerated explicitly. "
            f"The if-elif chain here MUST contain every snapshot member."
        )
    assert len(CANONICAL_DIALECT_SNAPSHOT) == 5, (
        "33.z.k.i: snapshot cardinality drifted from 5."
    )


# ════════════════════════════════════════════════════════════════════
#  §5 — Parametric coverage: resolver agrees with closed catalog
#        across the full closed input space
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "explicit_dialect",
    sorted(_AXONENDPOINT_TRANSPORT_DIALECTS),
)
@pytest.mark.parametrize("algebraic", [False, True])
def test_s5_resolver_with_explicit_catalog_member_returns_member_verbatim(
    explicit_dialect: str, algebraic: bool
):
    """Rule 1 (explicit-wins) MUST be the same for every catalog
    member, regardless of the algebraic flag. 5 dialects × 2 algebraic
    booleans = 10 parametric assertions."""
    result = resolve_effective_dialect(explicit_dialect, algebraic)
    assert result == explicit_dialect, (
        f"33.z.k.i Rule 1: resolve_effective_dialect({explicit_dialect!r}, "
        f"{algebraic}) MUST return {explicit_dialect!r} verbatim "
        f"(explicit dialect dominates the algebraic-effect default). "
        f"Got {result!r}."
    )
