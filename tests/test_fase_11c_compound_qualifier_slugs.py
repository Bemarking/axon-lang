"""
Regression test for compound qualifier slugs in effect rows
=============================================================

Closes a pre-existing parser gap that was masked because CI's failure
status did not block PyPI publishing on lang releases. The
``parse_effect_row`` (Rust) / ``_parse_effect_row`` (Python) consumer
was reading exactly one identifier after the colon, which made it
impossible to write the catalogue slugs the type checker requires:

  * dot-separated  (Fase 11.c) — ``legal:HIPAA.164_502``,
                                  ``legal:GDPR.Art6.Consent``,
                                  ``legal:PCI_DSS.v4_Req3``
  * colon-separated (Fase 11.e) — ``ots:transform:mulaw8:pcm16``,
                                   ``ots:backend:native``

The lexer fragments dotted slugs across IDENT / INTEGER tokens
(``164_502`` lexes as INTEGER ``164`` + IDENT ``_502``); the fixed
parser recombines them via source-column adjacency so the type checker
sees the catalog string verbatim.
"""

from __future__ import annotations

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ast_nodes import EffectRowNode


def _parse_first_tool_effects(src: str) -> list[str]:
    program = Parser(Lexer(src).tokenize()).parse()
    tool = program.declarations[0]
    eff: EffectRowNode | None = getattr(tool, "effects", None)
    assert eff is not None, "tool has no effect row"
    return list(eff.effects)


class TestDottedQualifierSlugs:
    def test_simple_dotted_slug(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <legal:GDPR.Art6.Consent>
        }
        """
        assert _parse_first_tool_effects(src) == ["legal:GDPR.Art6.Consent"]

    def test_segment_with_digit_underscore_mix(self) -> None:
        # `164_502` lexes as INTEGER `164` + IDENT `_502` because `_`
        # starts a fresh identifier; the parser must reassemble.
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <legal:HIPAA.164_502>
        }
        """
        assert _parse_first_tool_effects(src) == ["legal:HIPAA.164_502"]

    def test_segment_starting_with_digit_then_letter(self) -> None:
        # `501b` lexes as INTEGER `501` + IDENT `b`.
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <legal:GLBA.501b>
        }
        """
        assert _parse_first_tool_effects(src) == ["legal:GLBA.501b"]

    def test_segment_starting_with_letter_then_digit(self) -> None:
        # `v4_Req3` is a single IDENT (starts with letter).
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <legal:PCI_DSS.v4_Req3>
        }
        """
        assert _parse_first_tool_effects(src) == ["legal:PCI_DSS.v4_Req3"]

    def test_pure_integer_segment(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <legal:SOX.404>
        }
        """
        assert _parse_first_tool_effects(src) == ["legal:SOX.404"]


class TestColonSeparatedQualifierSlugs:
    def test_ots_transform_pair(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <ots:transform:mulaw8:pcm16>
        }
        """
        assert _parse_first_tool_effects(src) == ["ots:transform:mulaw8:pcm16"]

    def test_ots_backend(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <ots:backend:native>
        }
        """
        assert _parse_first_tool_effects(src) == ["ots:backend:native"]


class TestMixedAndMultipleEffects:
    def test_dotted_and_simple_in_same_row(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <sensitive:health_data, legal:HIPAA.164_502>
        }
        """
        assert _parse_first_tool_effects(src) == [
            "sensitive:health_data",
            "legal:HIPAA.164_502",
        ]

    def test_ots_pair_and_backend_in_same_row(self) -> None:
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <ots:transform:mulaw8:pcm16, ots:backend:native>
        }
        """
        assert _parse_first_tool_effects(src) == [
            "ots:transform:mulaw8:pcm16",
            "ots:backend:native",
        ]

    def test_simple_qualifiers_unaffected(self) -> None:
        # Backward-compat: single-ident qualifiers (the only kind the
        # pre-fix parser accepted) must keep working unchanged.
        src = """
        tool t {
          provider: local
          timeout: 10s
          effects: <stream:DropOldest, trust:cryptographic>
        }
        """
        assert _parse_first_tool_effects(src) == [
            "stream:DropOldest",
            "trust:cryptographic",
        ]
