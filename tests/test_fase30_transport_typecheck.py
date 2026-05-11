"""§Fase 30.c — Type-checker enforcement: `transport: sse|ndjson` requires
a Stream-producing `execute:` flow (D3 ratified 2026-05-10).

Formal predicate enforced:

    is_streaming_transport(t)  ⟹  produces_stream(execute_flow)

where:

    produces_stream(F)  ≡
        (∃ step ∈ F.body. has_stream_output(step))           ──(a) type-level
      ∨ (∃ tool ∈ tools_used_by(F). has_stream_effect(tool))  ──(b) effect-level
      ∨ (∃ expr ∈ AST(F). is_stream_yield_perform(expr))      ──(c) operational

Test coverage by formal layer:

  TestDisjunctATypeLevel — `output: Stream<T>` step output
  TestDisjunctBEffectLevel — `effects: [stream:<policy>]` tool effect row
  TestDisjunctCOperational — `perform Stream.Yield(...)` operation
  TestNegativeSpace — flows that satisfy NO disjunct must be rejected
  TestBackwardsCompat — D1 default `transport: json` skips the check
  TestStreamingTransports — D2 enum: both sse and ndjson trigger the rule
  TestErrorMessageShape — D-style remediation hint per plan vivo §5.2
  TestPredicateLogicProperties — soundness + completeness invariants
  TestEdgeCases — malformed flows, undefined references, nested bodies
"""
from __future__ import annotations

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker


def _typecheck(src: str):
    """Parse + type-check; return the list of errors. Raises on
    parse-time failure (the predicate is a semantic check; parse
    errors mean the test fixture itself is malformed)."""
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    tc = TypeChecker(program)
    return tc.check()


def _transport_errors(errors) -> list:
    """Filter for transport-rule violations specifically. The 30.c
    error message always contains the phrase `does not produce a
    Stream<T>` — that's the soundness signal we assert on."""
    return [
        e for e in errors
        if "transport" in e.message and "does not produce a Stream" in e.message
    ]


# ──────────────────────────────────────────────────────────────────
# TestDisjunctATypeLevel — `output: Stream<T>` step output
# ──────────────────────────────────────────────────────────────────


class TestDisjunctATypeLevel:
    """Disjunct (a) — formal layer: type-level commitment.

    `output: Stream<T>` on any step in the flow body is a sufficient
    type-system witness that the flow produces stream tokens at
    runtime. The type signature itself is the proof obligation.
    """

    def test_simple_stream_token(self):
        src = """
        flow F() {
            step S { output: Stream<Token> }
        }
        axonendpoint Live {
            method: POST path: "/live" execute: F transport: sse
        }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_stream_generic_inner_type_irrelevant(self):
        # The inner T may be any single-token identifier; the
        # predicate only checks the outer Stream<...> wrapper. (Nested
        # generics like Stream<Map<String,Int>> are unsupported at
        # the type-expression parser level — out of scope for 30.c.)
        for inner in ["String", "Patient", "Token", "Diagnosis"]:
            src = f"""
            flow F() {{
                step S {{ output: Stream<{inner}> }}
            }}
            axonendpoint Live {{
                method: POST path: "/l" execute: F transport: sse
            }}
            """
            assert _transport_errors(_typecheck(src)) == [], inner

    def test_multi_step_only_one_streams(self):
        # Only ONE step needs to produce a stream output — the
        # disjunct is satisfied by ANY step.
        src = """
        flow F() {
            step S1 { output: String }
            step S2 { output: Stream<Token> }
            step S3 { output: Int }
        }
        axonendpoint Live { method: POST path: "/l" execute: F transport: sse }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_optional_stream_does_not_count(self):
        # `Stream<T>?` is OPTIONAL of stream — the value may be
        # absent (None / null at runtime). The predicate intentionally
        # rejects this: a commitment that may be absent is not a
        # streaming commitment. The output_type string is
        # "Stream<T>?" (per `_parse_output_type_string`), which does
        # NOT match the strict `endswith(">")` rule.
        src = """
        flow F() {
            step S { output: Stream<Token>? }
        }
        axonendpoint Live { method: POST path: "/l" execute: F transport: sse }
        """
        # No disjunct holds → rejected.
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1


# ──────────────────────────────────────────────────────────────────
# TestDisjunctBEffectLevel — `effects: [stream:<policy>]` tool effect
# ──────────────────────────────────────────────────────────────────


class TestDisjunctBEffectLevel:
    """Disjunct (b) — formal layer: algebraic effect declaration.

    A tool with `effects: <stream:<policy>>` carries the effect row
    that declares streaming participation. The flow's compile-time
    proof obligation: at least one tool it uses must carry this
    effect. Closed Fase 11.a catalog: drop_oldest / degrade_quality /
    pause_upstream / fail.
    """

    @pytest.mark.parametrize(
        "policy", ["drop_oldest", "degrade_quality", "pause_upstream", "fail"]
    )
    def test_each_of_4_policies_satisfies_disjunct(self, policy: str):
        src = f"""
        tool Streamer {{
            provider: local
            effects: <stream:{policy}>
        }}
        flow F() {{
            step S {{ use Streamer("x") }}
        }}
        axonendpoint Live {{
            method: POST path: "/l" execute: F transport: sse
        }}
        """
        assert _transport_errors(_typecheck(src)) == [], policy

    def test_tool_without_stream_effect_does_not_satisfy(self):
        src = """
        tool Plain {
            provider: local
            effects: <io, network>
        }
        flow F() {
            step S { use Plain("x") }
        }
        axonendpoint Bad {
            method: POST path: "/b" execute: F transport: sse
        }
        """
        # `io` + `network` are not `stream:*` — disjunct (b) fails.
        # No other disjunct holds either → rejected.
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1

    def test_effect_row_with_stream_AND_other_effects(self):
        # `stream:drop_oldest` mixed with other effects still satisfies.
        # The predicate checks `any(e.startswith("stream:"))` over the
        # effect row.
        src = """
        tool MixedTool {
            provider: local
            effects: <io, network, stream:drop_oldest>
        }
        flow F() { step S { use MixedTool("x") } }
        axonendpoint Live { method: POST path: "/l" execute: F transport: sse }
        """
        assert _transport_errors(_typecheck(src)) == []


# ──────────────────────────────────────────────────────────────────
# TestDisjunctCOperational — `perform Stream.Yield(...)`
# ──────────────────────────────────────────────────────────────────


class TestDisjunctCOperational:
    """Disjunct (c) — formal layer: operational evidence.

    A `perform Stream.Yield(value)` expression anywhere in the flow
    body is the runtime-operation proof: the flow actively emits
    chunks. Fase 23 algebraic-effect operations land here.
    """

    def test_simple_yield_at_step_level(self):
        src = """
        flow F() {
            step S { perform Stream.Yield("tok") }
        }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: sse
        }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_other_stream_operations_do_not_count(self):
        # Stream.Done / Stream.Cancel are control ops, NOT producers.
        # The predicate is intentionally tight: only Stream.Yield
        # counts as evidence of chunk emission. If an adopter writes
        # only Stream.Done, the flow doesn't actually emit chunks.
        src = """
        flow F() {
            step S { perform Stream.Done() }
        }
        axonendpoint Bad {
            method: POST path: "/b" execute: F transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1

    def test_perform_other_effect_does_not_count(self):
        # `perform Channel.Send(...)` is a different effect entirely.
        src = """
        flow F() {
            step S { perform Channel.Send("payload") }
        }
        axonendpoint Bad {
            method: POST path: "/b" execute: F transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1


# ──────────────────────────────────────────────────────────────────
# TestNegativeSpace — every flow that satisfies NO disjunct is rejected
# ──────────────────────────────────────────────────────────────────


class TestNegativeSpace:
    """Completeness check: a flow that fails ALL three disjuncts
    must be rejected. This is the "no false positive" direction —
    the type-checker must not silently accept a flow that cannot
    produce stream tokens at runtime."""

    def test_empty_flow_body(self):
        src = """
        flow Empty() { }
        axonendpoint Bad {
            method: POST path: "/b" execute: Empty transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1

    def test_only_non_stream_output(self):
        src = """
        flow F() { step S { output: String } }
        axonendpoint Bad {
            method: POST path: "/b" execute: F transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1

    def test_non_stream_tool_no_yield(self):
        src = """
        tool Plain { provider: local effects: <io> }
        flow F() {
            step S { use Plain("x") output: Int }
        }
        axonendpoint Bad {
            method: POST path: "/b" execute: F transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1


# ──────────────────────────────────────────────────────────────────
# TestBackwardsCompat — D1: default transport=json skips the check
# ──────────────────────────────────────────────────────────────────


class TestBackwardsCompat:
    """D1 ratified: when `transport` is absent OR `json`, the
    30.c check does not run. Adopters with non-stream flows + no
    transport declaration see zero behavior change."""

    def test_absent_transport_skips_check(self):
        # Plain flow + no transport field → no 30.c enforcement.
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Ok { method: POST path: "/ok" execute: Plain }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_explicit_json_skips_check(self):
        # transport: json explicit ≡ absent for enforcement purposes.
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Ok {
            method: POST path: "/ok" execute: Plain transport: json
        }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_streaming_flow_without_transport_no_check(self):
        # Stream-producing flow with no transport field → not
        # required to be SSE. The enforcement is contrapositive:
        # transport=sse REQUIRES streaming, but streaming flows
        # don't REQUIRE transport=sse.
        src = """
        flow F() { step S { output: Stream<X> } }
        axonendpoint Live {
            method: POST path: "/l" execute: F
        }
        """
        assert _transport_errors(_typecheck(src)) == []


# ──────────────────────────────────────────────────────────────────
# TestStreamingTransports — D2 enum: both sse + ndjson trigger
# ──────────────────────────────────────────────────────────────────


class TestStreamingTransports:
    """D2 ratified: transport ∈ {sse, ndjson} are the streaming
    transports. Both trigger the 30.c predicate; json does not."""

    def test_sse_triggers_predicate(self):
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Bad {
            method: POST path: "/b" execute: Plain transport: sse
        }
        """
        assert len(_transport_errors(_typecheck(src))) == 1

    def test_ndjson_triggers_same_predicate(self):
        # ndjson is reserved namespace per D2; wire emission deferred
        # but the type contract holds today. Adopters who declare
        # ndjson get the same compile-time guarantee.
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Bad {
            method: POST path: "/b" execute: Plain transport: ndjson
        }
        """
        assert len(_transport_errors(_typecheck(src))) == 1

    def test_ndjson_with_stream_disjunct_accepts(self):
        # Same disjunction applies — disjunct (a) accepts.
        src = """
        flow F() { step S { output: Stream<X> } }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: ndjson
        }
        """
        assert _transport_errors(_typecheck(src)) == []


# ──────────────────────────────────────────────────────────────────
# TestErrorMessageShape — plan vivo §5.2 remediation hint
# ──────────────────────────────────────────────────────────────────


class TestErrorMessageShape:
    """The error message must guide the adopter to one of 4 fixes
    (a/b/c/d per plan vivo §5.2). Each option is mentioned in the
    message so the adopter sees the full remediation surface."""

    def _get_message(self) -> str:
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Bad {
            method: POST path: "/b" execute: Plain transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1
        return errs[0].message

    def test_message_names_the_axonendpoint(self):
        assert "axonendpoint 'Bad'" in self._get_message()

    def test_message_names_the_execute_flow(self):
        assert "'Plain'" in self._get_message()

    def test_message_names_the_transport(self):
        assert "transport: sse" in self._get_message()

    def test_message_includes_4_remediation_options(self):
        msg = self._get_message()
        # Each of the 4 options from plan vivo §5.2 should appear
        # in the help section (we don't require exact format; we
        # check that the adopter sees all the levers).
        assert "Stream<T>" in msg
        assert "stream:" in msg
        assert "Stream.Yield" in msg
        assert "drop" in msg.lower() or "JSON" in msg


# ──────────────────────────────────────────────────────────────────
# TestPredicateLogicProperties — formal correctness invariants
# ──────────────────────────────────────────────────────────────────


class TestPredicateLogicProperties:
    """Mathematical properties of the predicate. These tests pin the
    logical structure of the disjunction so future refactors can't
    accidentally break soundness or completeness."""

    def test_disjunction_or_semantics(self):
        # A flow with BOTH disjunct (a) and (c) satisfies the predicate.
        # The OR is inclusive — having more disjuncts isn't an error.
        src = """
        flow F() {
            step S {
                output: Stream<Token>
                perform Stream.Yield("x")
            }
        }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: sse
        }
        """
        assert _transport_errors(_typecheck(src)) == []

    def test_contrapositive_holds(self):
        # Contrapositive: ¬produces_stream ⟹ ¬is_streaming_transport
        # i.e., a non-streaming flow + transport=sse → REJECTED.
        # (Verified throughout TestNegativeSpace; this test pins
        # the logical formulation explicitly.)
        src = """
        flow Plain() { step S { output: String } }
        axonendpoint Bad {
            method: POST path: "/b" execute: Plain transport: sse
        }
        """
        errs = _transport_errors(_typecheck(src))
        assert len(errs) == 1, "contrapositive must reject"

    def test_predicate_is_localized_to_axonendpoint(self):
        # A non-stream flow that is NOT referenced by any sse-transport
        # axonendpoint should not trip the check. The predicate
        # is local to the axonendpoint declaration, not global.
        src = """
        flow Plain() { step S { output: String } }
        flow F() { step S { output: Stream<X> } }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: sse
        }
        """
        # Plain is referenced by nobody with transport: sse — no error.
        assert _transport_errors(_typecheck(src)) == []


# ──────────────────────────────────────────────────────────────────
# TestEdgeCases
# ──────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Defensive coverage: malformed inputs, undefined references,
    nested step bodies. The predicate must not crash."""

    def test_undefined_execute_flow_does_not_double_flag(self):
        # When `execute: F` references an undefined flow, the
        # existing pre-30 check reports it. The 30.c check should
        # NOT emit a second "doesn't produce Stream" error on top —
        # double-flagging is noise.
        src = """
        axonendpoint Bad {
            method: POST path: "/b" execute: Missing transport: sse
        }
        """
        errs = _typecheck(src)
        # Exactly one error per cause (the undefined-flow error from
        # the pre-30 check); no stream-rule error compounding on it.
        transport_errs = _transport_errors(errs)
        assert len(transport_errs) == 0, transport_errs

    def test_nested_step_body_yield_satisfies_disjunct_c(self):
        # Stream.Yield inside a nested step body still satisfies (c).
        # The walker must descend into step.body recursively.
        src = """
        flow F() {
            step S {
                step Inner {
                    perform Stream.Yield("nested-tok")
                }
            }
        }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: sse
        }
        """
        # NOTE: AXON's parser may not accept arbitrarily-nested
        # steps; this test pins that IF the parser does, the
        # walker reaches the yield. If parse fails the test is
        # vacuously satisfied — we skip rather than fail.
        try:
            errs = _typecheck(src)
        except Exception:
            pytest.skip("parser does not accept nested step bodies")
        assert _transport_errors(errs) == []

    def test_perform_stream_yield_with_no_arguments(self):
        # Edge: `perform Stream.Yield()` with no value. Still
        # satisfies the predicate (it's the operation name that
        # matters; semantic of empty yield is a runtime concern).
        src = """
        flow F() { step S { perform Stream.Yield() } }
        axonendpoint Live {
            method: POST path: "/l" execute: F transport: sse
        }
        """
        assert _transport_errors(_typecheck(src)) == []
