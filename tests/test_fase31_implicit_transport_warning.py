"""§Fase 31.c — Test pack for the `axon-W001` compile-time warning.

D4 ratified 2026-05-11 verbatim. Covers:

  * Warning FIRES when conditions hold (implicit sse + no explicit
    transport + flow resolves).
  * Warning DOES NOT FIRE when any condition is violated:
      - explicit `transport: sse` declared
      - explicit `transport: json` declared (D3 opt-out)
      - flow has no stream effects (no inference)
      - execute_flow is orphan (separate error)
  * Rate-limit: one warning per axonendpoint per check pass.
  * Message shape — canonical W001 prefix + endpoint name + flow
    name + disjunct-specific origin text.
  * Suppression matrix is exhaustive.

Four-pillar trace per D10:
  - PHILOSOPHY — the language must be honest about its inferences.
  - LOGIC      — the warning fires iff a precise predicate holds.
  - COMPUTING  — rate-limited per-endpoint; suppression explicit.
"""
from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker


W001_CODE = "axon-W001"


def _check(src: str) -> tuple[list, list, dict]:
    """Parse + type-check; return (errors, warnings, endpoints_by_name)."""
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    tc = TypeChecker(program)
    errs = tc.check()
    warnings = tc.warnings
    endpoints = {
        d.name: d for d in program.declarations
        if isinstance(d, AxonEndpointDefinition)
    }
    return errs, warnings, endpoints


def _w001_warnings(warnings) -> list:
    return [w for w in warnings if W001_CODE in w.message]


# ─── 1. Positive — warning fires on every implicit-sse site ────────────


class TestW001FiresOnImplicitSse:

    def test_kivi_shape_fires(self):
        # The canonical Kivi pattern 2026-05-11 — apply: tool_name.
        src = (
            "tool chat_token_stream { description: \"streaming\" effects: <stream:drop_oldest> }\n"
            "flow Chat() -> String { step Generate { ask: \"hi\" apply: chat_token_stream } }\n"
            "axonendpoint ChatEndpoint { method: POST path: \"/chat\" execute: Chat }"
        )
        _, warnings, endpoints = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 1
        assert "ChatEndpoint" in w1s[0].message
        assert "Chat" in w1s[0].message
        assert "chat_token_stream" in w1s[0].message
        assert "stream:drop_oldest" in w1s[0].message
        assert endpoints["ChatEndpoint"].implicit_transport == "sse"

    def test_stream_output_disjunct_a_fires(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" output: Stream<Token> } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 1
        # Origin should reference the step + the output type.
        assert "step 'S'" in w1s[0].message
        assert "Stream<Token>" in w1s[0].message

    @pytest.mark.parametrize(
        "policy", ["drop_oldest", "degrade_quality", "pause_upstream", "fail"]
    )
    def test_each_backpressure_policy_fires(self, policy):
        src = (
            f"tool t {{ description: \"t\" effects: <stream:{policy}> }}\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 1
        assert f"stream:{policy}" in w1s[0].message


# ─── 2. Negative — suppression conditions ──────────────────────────────


class TestW001SuppressionRules:

    def test_explicit_sse_suppresses_warning(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: sse }"
        )
        _, warnings, _ = _check(src)
        assert len(_w001_warnings(warnings)) == 0

    def test_explicit_json_suppresses_warning(self):
        # D3 — adopter explicitly opted out.
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: json }"
        )
        _, warnings, _ = _check(src)
        assert len(_w001_warnings(warnings)) == 0

    def test_explicit_ndjson_suppresses_warning(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: ndjson }"
        )
        _, warnings, _ = _check(src)
        assert len(_w001_warnings(warnings)) == 0

    def test_no_stream_effect_no_warning(self):
        src = (
            "flow F() -> Int { step S { ask: \"x\" output: Int } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        assert len(_w001_warnings(warnings)) == 0

    def test_orphan_execute_flow_no_warning(self):
        # The endpoint references a flow that doesn't exist; that's a
        # separate error. Attaching W001 here would be noise.
        src = "axonendpoint Orphan { method: POST path: \"/o\" execute: Ghost }"
        _, warnings, _ = _check(src)
        assert len(_w001_warnings(warnings)) == 0


# ─── 3. Rate-limiting — one warning per axonendpoint ───────────────────


class TestW001RateLimiting:

    def test_single_warning_per_endpoint(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 1, f"expected exactly 1 W001, got {len(w1s)}"

    def test_multiple_endpoints_same_flow_each_fires_once(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint E1 { method: POST path: \"/e1\" execute: F }\n"
            "axonendpoint E2 { method: POST path: \"/e2\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 2
        msgs = [w.message for w in w1s]
        assert any("E1" in m for m in msgs)
        assert any("E2" in m for m in msgs)

    def test_mixed_endpoints_only_implicit_fires(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint Implicit { method: POST path: \"/i\" execute: F }\n"
            "axonendpoint ExplicitSse { method: POST path: \"/s\" execute: F transport: sse }\n"
            "axonendpoint ExplicitJson { method: POST path: \"/j\" execute: F transport: json }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert len(w1s) == 1
        assert "Implicit" in w1s[0].message


# ─── 4. Message shape ──────────────────────────────────────────────────


class TestW001MessageShape:

    def test_message_starts_with_canonical_prefix(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1s = _w001_warnings(warnings)
        assert w1s[0].message.startswith(f"warning[{W001_CODE}]:")

    def test_message_mentions_both_remediation_options(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        msg = _w001_warnings(warnings)[0].message
        assert "transport: sse" in msg, "must mention SSE opt-in"
        assert "transport: json" in msg, "must mention json opt-out (D3)"

    def test_message_mentions_strict_flag(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        msg = _w001_warnings(warnings)[0].message
        assert "strict_type_driven_transport" in msg, (
            "must reference the D6 runtime flag so adopters know where the future default sits"
        )

    def test_line_column_point_at_axonendpoint(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint Live { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        w1 = _w001_warnings(warnings)[0]
        # The axonendpoint starts on line 3 in this source.
        assert w1.line == 3, f"expected line 3, got {w1.line}"
        assert w1.column > 0


# ─── 5. Idempotence ────────────────────────────────────────────────────


class TestW001Idempotence:

    def test_double_check_pass_emits_same_count(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        tokens = Lexer(src).tokenize()
        program = Parser(tokens).parse()
        tc1 = TypeChecker(program)
        tc1.check()
        first = len(_w001_warnings(tc1.warnings))
        tc2 = TypeChecker(program)
        tc2.check()
        second = len(_w001_warnings(tc2.warnings))
        assert first == second == 1


# ─── 6. Origin description — disjunct-specific text ────────────────────


class TestW001OriginDescription:
    """The message embeds a description of WHY the inference fired
    — disjunct-specific text so the adopter can paste the fix
    without re-reading the source."""

    def test_apply_ref_describes_step_and_tool(self):
        src = (
            "tool brew { description: \"brew\" effects: <stream:fail> }\n"
            "flow F() -> Unit { step Pour { ask: \"x\" apply: brew } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        msg = _w001_warnings(warnings)[0].message
        assert "step 'Pour'" in msg
        assert "tool 'brew'" in msg
        assert "stream:fail" in msg

    def test_stream_output_describes_step_and_output(self):
        src = (
            "flow F() -> Unit { step Emit { ask: \"x\" output: Stream<Char> } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        _, warnings, _ = _check(src)
        msg = _w001_warnings(warnings)[0].message
        assert "step 'Emit'" in msg
        assert "Stream<Char>" in msg
