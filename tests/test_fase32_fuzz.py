"""§Fase 32.i — D12 robustness fuzz for the Fase 32 REST surface.

D12 budget (originally ratified Fase 28, extended through Fase 30,
Fase 31, now Fase 32): every public predicate the runtime exposes on
the dynamic-route surface MUST be **total + non-panicking** over its
documented input domain. The positive-space test packs (32.b–32.h)
cover the canonical behaviors; this pack closes the negative space by
randomly mutating inputs to surface uncaught exceptions.

Surfaces under fuzz:

  1. `collect_axonendpoint_routes` (32.b) — route table derivation from
     arbitrary parsed Program ASTs.
  2. `validate_body` (32.c + 32.d response side) — JSON value × type
     name × type table → Result.
  3. `_is_valid_capability_slug` (32.g) — slug grammar predicate.
  4. `resolve_replay_enabled` (32.h) — equivalent in Python via direct
     boolean computation (Rust-only surface; this lane just locks the
     method-default heuristic).

The invariant is uniform: **the function returns a value (Ok/Err for
validators, list for collectors, bool for predicates) or raises a
documented exception type. It MUST NEVER panic with an uncaught
exception, infinite-loop, or stack-overflow.**

Pillar trace per D12:
  - MATHEMATICS — each function is total over its documented domain.
  - LOGIC      — output is always in the closed set the contract
                  declares (e.g. validate_body returns
                  `None | BodyValidationError`).
  - COMPUTING  — defensive; no adversarial input shape crashes the
                  predicate (the language never crashes on adopters'
                  ill-formed source — diagnostics are the right shape).

Seed = pytest parametrize over 100 deterministic integer seeds × 10
iterations per seed. Identical shape to the Fase 28 + Fase 30 + Fase 31
D12 packs so CI reporters render them as siblings in one timeline.
"""
from __future__ import annotations

import random
import string
from typing import Any

import pytest

from axon.compiler.ast_nodes import (
    AxonEndpointDefinition,
    ProgramNode,
)
from axon.runtime.route_registry import (
    AXONENDPOINT_METHODS,
    RouteCollisionError,
    collect_axonendpoint_routes,
)
from axon.runtime.route_schema import (
    BUILTIN_PRIMITIVES,
    BodyValidationError,
    FieldSchema,
    TypeSchema,
    validate_body,
)
from axon.compiler.parser import _is_valid_capability_slug


# Type names the validator should see in random fuzzing — a mix of
# built-in primitives, ranged types, and a fabricated unknown.
TYPE_NAMES = list(BUILTIN_PRIMITIVES) + [
    "RiskScore", "ConfidenceScore", "SentimentScore", "List", "NotDeclared",
]

# Random JSON value shapes the validator may encounter.
JSON_GENERATORS = [
    lambda r: None,
    lambda r: r.choice([True, False]),
    lambda r: r.randint(-1000, 1000),
    lambda r: r.uniform(-10.0, 10.0),
    lambda r: "".join(r.choices(string.ascii_letters, k=r.randint(0, 8))),
    lambda r: [r.randint(0, 10) for _ in range(r.randint(0, 4))],
    lambda r: {"k": r.randint(0, 100)} if r.random() < 0.5 else {},
]


def _gen_json(rng: random.Random) -> Any:
    return rng.choice(JSON_GENERATORS)(rng)


def _gen_slug(rng: random.Random) -> str:
    """Generate a random slug-shaped string — sometimes valid, often
    invalid (uppercase, digits, hyphens, empty segments)."""
    alphabet = string.ascii_letters + string.digits + "._-@/ "
    return "".join(rng.choices(alphabet, k=rng.randint(0, 20)))


def _gen_method(rng: random.Random) -> str:
    """Random HTTP-method-shaped string — often canonical, sometimes
    garbage. The resolve_replay_enabled function must handle all inputs."""
    canonical = list(AXONENDPOINT_METHODS) + ["HEAD", "OPTIONS", "CONNECT", "TRACE"]
    if rng.random() < 0.7:
        return rng.choice(canonical)
    return "".join(rng.choices(string.ascii_letters + string.digits, k=rng.randint(0, 10)))


def _make_program_with_endpoints(rng: random.Random) -> ProgramNode:
    """Fabricate a ProgramNode with random axonendpoints. Bypasses the
    parser so we can stress collect_axonendpoint_routes directly with
    inputs that would never lex cleanly."""
    program = ProgramNode()
    program.declarations = []
    n_endpoints = rng.randint(0, 5)
    for _ in range(n_endpoints):
        method_pool = list(AXONENDPOINT_METHODS) + ["bogus", "", "GET", "head"]
        ep = AxonEndpointDefinition()
        ep.name = "".join(rng.choices(string.ascii_letters, k=rng.randint(1, 8)))
        ep.method = rng.choice(method_pool)
        ep.path = rng.choice(["/a", "/b/{id}", "", "no-slash", "/" + "x" * rng.randint(1, 20)])
        ep.execute_flow = "F"
        program.declarations.append(ep)
    return program


def _resolve_replay_enabled(method: str, replay_explicit: bool, replay: bool) -> bool:
    """Python mirror of Rust `axonendpoint_replay::resolve_replay_enabled`.
    Pure + total over (method, replay_explicit, replay). When explicit,
    declared value wins; otherwise POST/PUT → True, else False."""
    if replay_explicit:
        return replay
    return method in ("POST", "PUT")


# ─── §1 — validate_body (32.c + 32.d) never panics ────────────────────


class TestValidateBodyNeverPanics:
    """100 seeds × 10 iters × random JSON × random type name. The
    function returns `None | BodyValidationError`; it must NEVER panic
    with an uncaught exception, regardless of input shape."""

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_input_never_panics(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iter in range(10):
            body = _gen_json(rng)
            type_name = rng.choice(TYPE_NAMES + [""])  # empty = D9 path
            # Random type table — may contain bogus shapes.
            table: dict[str, TypeSchema] = {}
            if rng.random() < 0.5:
                table["Custom"] = TypeSchema(
                    name="Custom",
                    fields=[
                        FieldSchema(
                            name="x",
                            type_name=rng.choice(TYPE_NAMES),
                            generic_param="String" if rng.random() < 0.3 else "",
                            optional=rng.random() < 0.4,
                        ),
                    ],
                )
            try:
                result = validate_body(body, type_name, table)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"validate_body raised uncaught {type(exc).__name__} "
                    f"(seed={seed}, iter={_iter}, body={body!r}, "
                    f"type_name={type_name!r}): {exc}"
                )
            # Output must be None OR BodyValidationError instance.
            assert result is None or isinstance(result, BodyValidationError), (
                f"validate_body returned unexpected type {type(result).__name__}"
            )


# ─── §2 — collect_axonendpoint_routes never panics ───────────────────


class TestCollectRoutesNeverPanics:
    """Random ProgramNode fabrications including malformed methods/paths.
    `collect_axonendpoint_routes` must return a dict OR raise
    `RouteCollisionError` (documented). Any other exception is a defect."""

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_program_never_panics(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iter in range(10):
            program = _make_program_with_endpoints(rng)
            try:
                _ = collect_axonendpoint_routes(program, "<fuzz>", "fuzz.axon")
            except RouteCollisionError:
                continue  # documented error path
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"collect_axonendpoint_routes raised uncaught "
                    f"{type(exc).__name__} (seed={seed}, iter={_iter}): {exc}"
                )


# ─── §3 — _is_valid_capability_slug is total + returns bool ─────────


class TestSlugValidatorNeverPanics:
    """Slug validator must return a bool for ANY string input.
    Special chars, unicode, empty, very long — all return True or False."""

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_string_returns_bool(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iter in range(10):
            slug = _gen_slug(rng)
            try:
                result = _is_valid_capability_slug(slug)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"_is_valid_capability_slug raised uncaught "
                    f"{type(exc).__name__} on slug={slug!r}: {exc}"
                )
            assert isinstance(result, bool), (
                f"_is_valid_capability_slug returned non-bool {result!r}"
            )


# ─── §4 — resolve_replay_enabled is total + returns bool ─────────────


class TestResolveReplayEnabledTotalFunction:
    """Method-default heuristic is total over the (method, explicit,
    replay) tuple. Random method strings (including non-canonical)
    must yield a bool."""

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_inputs_total(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iter in range(10):
            method = _gen_method(rng)
            replay_explicit = rng.choice([True, False])
            replay = rng.choice([True, False])
            try:
                result = _resolve_replay_enabled(method, replay_explicit, replay)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"resolve_replay_enabled raised uncaught "
                    f"{type(exc).__name__}: {exc}"
                )
            assert isinstance(result, bool)
            # When explicit, declared value MUST win regardless of method.
            if replay_explicit:
                assert result == replay


# ─── §5 — Cross-surface invariants ───────────────────────────────────


class TestCrossSurfaceInvariants:
    """A handful of cross-surface invariants exercised across random
    inputs to catch interaction bugs that single-surface fuzz misses."""

    @pytest.mark.parametrize("seed", list(range(0, 50)))
    def test_empty_body_type_always_passes(self, seed: int) -> None:
        """D9: empty body_type short-circuits to Ok for ANY body."""
        rng = random.Random(seed)
        for _iter in range(10):
            body = _gen_json(rng)
            assert validate_body(body, "", {}) is None

    @pytest.mark.parametrize("seed", list(range(0, 50)))
    def test_any_type_always_passes(self, seed: int) -> None:
        """`output: Any` is the universal accept — same on validate side."""
        rng = random.Random(seed)
        for _iter in range(10):
            body = _gen_json(rng)
            assert validate_body(body, "Any", {}) is None

    @pytest.mark.parametrize("seed", list(range(0, 50)))
    def test_slug_validator_idempotent(self, seed: int) -> None:
        """Calling the slug validator twice on the same input returns
        the same value (pure function)."""
        rng = random.Random(seed)
        for _iter in range(10):
            slug = _gen_slug(rng)
            assert _is_valid_capability_slug(slug) == _is_valid_capability_slug(slug)
