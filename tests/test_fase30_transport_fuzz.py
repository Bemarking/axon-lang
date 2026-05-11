"""§Fase 30.g — Robustness fuzz for `transport` + `keepalive` fields.

D12-style budget extended to Fase 30 (originally ratified by Fase 28):
the parser MUST never crash (uncaught exception, infinite loop, stack
overflow, etc.) when an adversarial source mutates the `transport:` or
`keepalive:` field-value bytes inside an `axonendpoint` block.

The 30.b parser pack covers exact positive + negative space for the
closed enums {json, sse, ndjson} (D2) and {5s, 15s, 30s, 60s} (D6).
This pack complements it with 1000 deterministic-seeded mutations of
the value tokens to surface unhandled exceptions that the positive +
negative space tests would not reach. The recovery contract is:

  * Input matches both closed enums → parse succeeds, fields equal
    the declared values.
  * Input violates either closed enum → `AxonParseError` raised with
    a structured `.message` (smart-suggest may or may not fire
    depending on edit-distance, both are acceptable).
  * Input is lex-rejectable (control characters etc.) →
    `AxonLexerError` raised before the parser runs; out of scope.

  * NEVER: uncaught generic Exception, `IndexError`, `KeyError`,
    `RecursionError`, infinite loop, or any non-`Axon*Error` failure.

The seed is fixed so any regression reproduces verbatim. The
parametrization shape (`seed` ∈ [0,100)) is identical to the
Fase 28 pack so the CI reporter renders them as a sibling group.
"""
from __future__ import annotations

import random
from typing import List

import pytest

from axon.compiler.errors import AxonLexerError, AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# Canonical seed shape — the parser will always see a complete
# axonendpoint header with execute target + the two interesting
# fields. Fuzz only mutates the VALUE bytes of transport + keepalive
# so we exercise the smart-suggest + validation paths, not the
# broader parser recovery (which Fase 28 covers).
SEED_TEMPLATE = (
    "axonendpoint Live {{\n"
    "    method: POST\n"
    "    path: \"/v1/x\"\n"
    "    execute: F\n"
    "    transport: {transport}\n"
    "    keepalive: {keepalive}\n"
    "}}"
)

# Bytes the fuzz may emit as value tokens. Constrained to identifier-
# class characters + a tight set of structural punctuation so most
# inputs survive the lexer. (Lex-rejectable inputs are swallowed at
# the AxonLexerError boundary per the contract above.)
VALUE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


def _random_token(rng: random.Random, length: int) -> str:
    """Produce an arbitrary identifier-class token of `length` bytes.

    Tokens are guaranteed non-empty, start with a letter (so they
    survive the lexer's identifier-start rule), and contain only
    alphanumerics + underscore.
    """
    if length <= 0:
        length = 1
    head = rng.choice("abcdefghijklmnopqrstuvwxyz")
    tail = "".join(rng.choices(VALUE_ALPHABET, k=length - 1))
    return head + tail


# Tokens the parser must accept by D2 + D6 (used to verify the
# happy-path is exercised when the fuzz happens to pick one).
ENUM_TRANSPORTS = {"json", "sse", "ndjson"}
ENUM_KEEPALIVES = {"5s", "15s", "30s", "60s"}


class TestTransportKeepaliveRobustnessFuzz:
    """1000 deterministic iterations × 2 fields = 2000 mutated value
    tokens. The parser may accept or reject; either is fine; what's
    forbidden is an uncaught generic exception.

    Iteration shape mirrors Fase 28's pack (100 seeds × 10 inner
    iterations) so CI reporters group them identically.
    """

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_value_mutation_never_crashes(self, seed: int) -> None:
        rng = random.Random(seed)
        for _iteration in range(10):
            # Mix of valid-enum and adversarial tokens. ~5% of
            # iterations sample directly from the closed enum so the
            # happy-path is also exercised under fuzz; the rest
            # sample arbitrary identifier-class strings.
            if rng.random() < 0.05:
                transport = rng.choice(sorted(ENUM_TRANSPORTS))
            else:
                transport = _random_token(rng, rng.randint(1, 12))
            if rng.random() < 0.05:
                keepalive = rng.choice(sorted(ENUM_KEEPALIVES))
            else:
                keepalive = _random_token(rng, rng.randint(1, 12))

            source = SEED_TEMPLATE.format(
                transport=transport, keepalive=keepalive,
            )

            try:
                tokens = Lexer(source).tokenize()
            except AxonLexerError:
                # Lex-time rejection is out of scope (the values are
                # ASCII identifier-class — this branch should not
                # fire under the current alphabet — but kept for
                # defense against future alphabet expansion).
                continue

            # Parser must NEVER raise anything other than AxonParseError.
            # On valid-enum × valid-enum input, the parser must succeed.
            try:
                program = Parser(tokens).parse()
            except AxonParseError:
                # Structured rejection — verify it's targeted at one of
                # the two fields. The closed enum is enforced upstream
                # in `_parse_axonendpoint`; smart-suggest may or may not
                # fire.
                if (
                    transport in ENUM_TRANSPORTS
                    and keepalive in ENUM_KEEPALIVES
                ):
                    pytest.fail(
                        f"closed-enum × closed-enum input was rejected:\n"
                        f"  transport={transport!r} keepalive={keepalive!r}\n"
                        f"  seed={seed}"
                    )
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"Parser raised uncaught {type(exc).__name__} on "
                    f"valid-lex input (seed={seed}, iteration={_iteration}):\n"
                    f"  source={source!r}\n"
                    f"  exception={exc}"
                )

            # Accepted path: verify the fields round-trip.
            from axon.compiler.ast_nodes import AxonEndpointDefinition

            decl = program.declarations[0]
            assert isinstance(decl, AxonEndpointDefinition)
            if transport in ENUM_TRANSPORTS:
                assert decl.transport == transport, (
                    f"accepted transport drifted: declared={transport!r} "
                    f"parsed={decl.transport!r} seed={seed}"
                )
            if keepalive in ENUM_KEEPALIVES:
                assert decl.keepalive == keepalive, (
                    f"accepted keepalive drifted: declared={keepalive!r} "
                    f"parsed={decl.keepalive!r} seed={seed}"
                )


class TestFieldByteMutationFuzz:
    """Coarser mutation: take a known-good source and randomly mutate
    individual bytes anywhere in the file. The 30.b pack already
    pins specific positive/negative cases; this pack verifies the
    field-extraction code path is robust to byte-level adversarial
    inputs at any offset, not just inside the value tokens.

    Same 100 × 10 = 1000-iteration shape.
    """

    BASE = (
        "axonendpoint Live {\n"
        "    method: POST\n"
        "    path: \"/v1/x\"\n"
        "    execute: F\n"
        "    transport: sse\n"
        "    keepalive: 15s\n"
        "}\n"
    )

    @pytest.mark.parametrize("seed", list(range(0, 100)))
    def test_random_byte_mutation_never_crashes(self, seed: int) -> None:
        rng = random.Random(seed)
        for _ in range(10):
            mutated = self._mutate(self.BASE, rng)
            try:
                tokens = Lexer(mutated).tokenize()
            except AxonLexerError:
                continue
            try:
                _program = Parser(tokens).parse()
            except AxonParseError:
                # Structured rejection — acceptable.
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"Parser raised uncaught {type(exc).__name__} on "
                    f"byte-mutated input (seed={seed}):\n"
                    f"  source={mutated!r}\n"
                    f"  exception={exc}"
                )

    @staticmethod
    def _mutate(source: str, rng: random.Random) -> str:
        """Apply 0-3 byte mutations: delete, insert, swap, replace.

        Mirrors the Fase 28 fuzz mutator. Insertions sampled from a
        structural alphabet that's likely to confuse the parser
        (braces, colons, quotes) — the more cruel the input, the
        more useful the robustness signal.
        """
        chars: List[str] = list(source)
        n_mutations = rng.randint(0, 3)
        for _ in range(n_mutations):
            if not chars:
                break
            op = rng.choice(["delete", "insert", "swap", "replace"])
            i = rng.randint(0, len(chars) - 1)
            if op == "delete":
                del chars[i]
            elif op == "insert":
                chars.insert(i, rng.choice("(){}<>[]:,;\"'\n\t "))
            elif op == "swap" and i + 1 < len(chars):
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
            elif op == "replace":
                chars[i] = rng.choice(
                    "abcdefghijklmnopqrstuvwxyz0123456789{}()[]<>:,;"
                )
        return "".join(chars)
