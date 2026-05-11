"""§Fase 31.g — Robustness fuzz for the implicit_transport inference.

D12-style budget extended to Fase 31 (originally ratified by Fase 28):
the inference pass `_compute_implicit_transports` MUST never crash
(uncaught exception, infinite loop, stack overflow, etc.) when an
adversarial source mutates the `axonendpoint` / `flow` / `tool`
declarations that the inference predicate walks.

The 31.b inference pack covers exact positive + negative space for
the D1 rule. This pack complements it with 1000 deterministic-seeded
mutations to surface unhandled exceptions that the positive space
tests would not reach. The recovery contract is:

  * Input that lexes + parses cleanly → the type-checker pass
    completes; every AxonEndpointDefinition in the program has
    `implicit_transport ∈ {"sse", "json"}` (closed set per D2).
  * Input that fails to lex / parse → exception raised at the
    parser layer; the type-checker never runs on it; out of scope
    for this pack.
  * NEVER: an uncaught exception from `_compute_implicit_transports`
    on a lex+parse-clean input. The pass must be total.

Pillar trace per D10:
  - MATHEMATICS — the inference function is total + deterministic.
  - LOGIC      — output is always in the closed set {"sse", "json"}.
  - COMPUTING  — defensive; no input shape crashes the pass.

The seed is fixed so any regression reproduces verbatim. The
parametrization shape (`seed` ∈ [0,100)) is identical to the
Fase 28 + Fase 30 packs so CI reporters render them as siblings.
"""
from __future__ import annotations

import random
from typing import Any

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.errors import AxonLexerError, AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker


# Seed templates — each exercises a different shape of the
# inference predicate:
#   (a) implicit-sse via tool with stream effect (Kivi-shape)
#   (b) implicit-sse via Stream<T> output (disjunct a)
#   (c) explicit transport: json (D3 opt-out)
#   (d) explicit transport: sse (declared)
#   (e) non-stream flow (no inference)
SEED_PROGRAMS: list[str] = [
    "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
    "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
    "axonendpoint E { method: POST path: \"/f\" execute: F }",

    "flow F() -> Unit { step S { ask: \"x\" output: Stream<Token> } }\n"
    "axonendpoint E { method: POST path: \"/f\" execute: F }",

    "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
    "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
    "axonendpoint E { method: POST path: \"/f\" execute: F transport: json }",

    "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
    "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
    "axonendpoint E { method: POST path: \"/f\" execute: F transport: sse }",

    "flow F() -> Int { step S { ask: \"x\" output: Int } }\n"
    "axonendpoint E { method: POST path: \"/f\" execute: F }",
]


# Bytes the byte-mutator may insert. Tight alphabet so most inputs
# survive the lexer to actually reach the type-checker.
ALPHABET = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " :{}()[]<>,\"\n_"
)


def _mutate(source: str, rng: random.Random) -> str:
    """Apply 0-3 byte mutations: delete, insert, swap, replace.

    Designed to produce adversarial inputs that still lex but stress
    the parser + type-checker boundaries. Mirrors the Fase 28 D12
    mutator alphabet.
    """
    chars = list(source)
    n_mutations = rng.randint(0, 3)
    for _ in range(n_mutations):
        if not chars:
            break
        op = rng.choice(["delete", "insert", "swap", "replace"])
        i = rng.randint(0, len(chars) - 1)
        if op == "delete":
            del chars[i]
        elif op == "insert":
            chars.insert(i, rng.choice(ALPHABET))
        elif op == "swap" and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif op == "replace":
            chars[i] = rng.choice(ALPHABET)
    return "".join(chars)


# ─── §1 — Inference pass never panics on lex+parse-clean input ─────


class TestImplicitTransportFuzzNeverPanics:
    """1000 deterministic iterations × 5 seed shapes. For each
    mutated source that survives both the lexer AND the parser, the
    type-checker pass (which runs `_compute_implicit_transports`)
    MUST complete without an uncaught exception.

    Inputs that fail to lex or parse are skipped — the inference
    pass never sees them; they're out of scope for this contract.
    """

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_mutation_never_crashes_inference(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iteration in range(10):
            base = rng.choice(SEED_PROGRAMS)
            mutated = _mutate(base, rng)
            # Lex + parse — if either fails, skip; that's out of scope.
            try:
                tokens = Lexer(mutated).tokenize()
            except AxonLexerError:
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"Lexer raised uncaught {type(exc).__name__} (seed={seed}, "
                    f"iter={_iteration}): {mutated!r}\n  → {exc}"
                )
            try:
                program = Parser(tokens).parse()
            except AxonParseError:
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"Parser raised uncaught {type(exc).__name__} (seed={seed}, "
                    f"iter={_iteration}): {mutated!r}\n  → {exc}"
                )

            # Type-checker pass MUST not raise. Errors are returned;
            # never thrown.
            try:
                tc = TypeChecker(program)
                _ = tc.check()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"TypeChecker.check raised uncaught {type(exc).__name__} "
                    f"on lex+parse-clean input (seed={seed}, iter={_iteration}): "
                    f"{mutated!r}\n  → {exc}"
                )


# ─── §2 — Output is always in the closed set {"sse", "json"} ───────


class TestImplicitTransportFuzzClosedOutputSet:
    """After `_compute_implicit_transports` runs, every
    `AxonEndpointDefinition.implicit_transport` MUST be one of
    `"sse"` or `"json"` — never empty, never any other value.
    D2 closed set + D1 inference contract.
    """

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_output_always_in_closed_set(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iteration in range(10):
            base = rng.choice(SEED_PROGRAMS)
            mutated = _mutate(base, rng)
            try:
                tokens = Lexer(mutated).tokenize()
                program = Parser(tokens).parse()
            except (AxonLexerError, AxonParseError):
                continue
            TypeChecker(program).check()
            for decl in program.declarations:
                if isinstance(decl, AxonEndpointDefinition):
                    assert decl.implicit_transport in ("sse", "json"), (
                        f"implicit_transport drifted from closed set "
                        f"(seed={seed}, iter={_iteration}): "
                        f"{decl.implicit_transport!r}; source: {mutated!r}"
                    )


# ─── §3 — Idempotence under fuzz ───────────────────────────────────


class TestImplicitTransportFuzzIdempotence:
    """Re-running the type-checker pass on the same program MUST
    not change `implicit_transport` (mathematical idempotence).
    This pack stresses the property across adversarial inputs."""

    @pytest.mark.parametrize("seed", list(range(0, 25)))  # Smaller — 25×10=250 iters
    def test_double_check_pass_stable_under_fuzz(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iteration in range(10):
            base = rng.choice(SEED_PROGRAMS)
            mutated = _mutate(base, rng)
            try:
                tokens = Lexer(mutated).tokenize()
                program = Parser(tokens).parse()
            except (AxonLexerError, AxonParseError):
                continue

            # Pass 1.
            TypeChecker(program).check()
            first: dict[str, str] = {
                d.name: d.implicit_transport
                for d in program.declarations
                if isinstance(d, AxonEndpointDefinition)
            }
            # Pass 2 — must produce the same map.
            TypeChecker(program).check()
            second: dict[str, str] = {
                d.name: d.implicit_transport
                for d in program.declarations
                if isinstance(d, AxonEndpointDefinition)
            }
            assert first == second, (
                f"idempotence violated (seed={seed}, iter={_iteration}): "
                f"first={first}, second={second}, source={mutated!r}"
            )
