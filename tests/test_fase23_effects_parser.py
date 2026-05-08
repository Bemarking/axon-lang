"""Fase 23 — Lexer + Parser + AST tests for algebraic effects.

Operationalises paper docs/algebraic_effects_streaming.md §1-§6 at the
syntactic surface. Covers:

- Lexer: 6 new keywords (`effect`, `perform`, `handle`, `resume`,
  `abort`, `forward`) + `BANG` (!) symbol for type-level effect rows.
- AST: 7 new dataclasses (EffectDeclaration, EffectOperation,
  PerformExpression, HandleExpression, HandlerClause, ResumeStatement,
  AbortStatement, ForwardExpression, AlgebraicEffectRowNode).
- Parser: top-level effect declaration + step-body productions for
  perform/handle/resume/abort/forward + helper for type-level effect
  rows (D11 row polymorphism — closed vs open).

Decisions exercised here:
  D1  — operation polymorphism: `Send<T>(value: T) -> Unit` parses.
  D2  — one-shot resume: parser permits any count; constraint enforced
        by typechecker (23.c). Tests verify the AST shape only.
  D3  — handle scope delimited via `in` block.
  D11 — row polymorphism via row variable inside `!{...}`.
  D12 — `forward` keyword for transparent decorators.

This is the syntactic surface only; semantics (typechecker rules,
exhaustiveness, linear-resume) live in 23.c. Runtime semantics live
in 23.f (Rust).
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import (
    AbortStatement,
    AlgebraicEffectRowNode,
    EffectDeclaration,
    EffectOperation,
    FlowDefinition,
    ForwardExpression,
    HandleExpression,
    HandlerClause,
    PerformExpression,
    ProgramNode,
    ResumeStatement,
    StepNode,
)
from axon.compiler.errors import AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.tokens import KEYWORDS, Token, TokenType


# ──────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────


def _tokenize(source: str) -> list[Token]:
    return Lexer(source).tokenize()


def _parse(source: str) -> ProgramNode:
    return Parser(_tokenize(source)).parse()


def _wrap_in_step(body: str) -> str:
    """Wrap a fragment of step body in a minimal flow + step skeleton.

    Used by tests that exercise step-body productions
    (perform / handle / resume / abort / forward) which only run
    inside ``_parse_flow_step``.
    """
    return (
        "flow F() -> Unit {\n"
        "  step S {\n"
        f"    {body}\n"
        "  }\n"
        "}\n"
    )


def _step_body(prog: ProgramNode) -> list:
    """Extract the step body of the first flow's first step."""
    flow = prog.declarations[0]
    assert isinstance(flow, FlowDefinition)
    step = flow.body[0]
    assert isinstance(step, StepNode)
    return step.body


# ──────────────────────────────────────────────────────────────────────
#  TestLexerKeywords — 6 new keywords + BANG token
# ──────────────────────────────────────────────────────────────────────


class TestLexerKeywords:
    """Lexer recognises Fase 23 keywords as discriminated tokens."""

    @pytest.mark.parametrize("kw,expected", [
        ("effect", TokenType.EFFECT),
        ("perform", TokenType.PERFORM),
        ("handle", TokenType.HANDLE),
        ("resume", TokenType.RESUME),
        ("abort", TokenType.ABORT),
        ("forward", TokenType.FORWARD),
    ])
    def test_keyword_tokenises(self, kw: str, expected: TokenType) -> None:
        toks = _tokenize(kw)
        assert toks[0].type is expected
        assert toks[0].value == kw

    def test_keywords_present_in_lookup_table(self) -> None:
        for kw in ("effect", "perform", "handle", "resume", "abort", "forward"):
            assert kw in KEYWORDS, f"{kw} missing from KEYWORDS table"

    def test_bang_token_emitted_standalone(self) -> None:
        """`!` not followed by `=` emits BANG (was a lexer error pre-Fase-23)."""
        toks = _tokenize("!")
        assert toks[0].type is TokenType.BANG
        assert toks[0].value == "!"

    def test_bang_does_not_swallow_neq(self) -> None:
        """`!=` still tokenises as NEQ (BANG is the standalone fallback)."""
        toks = _tokenize("!=")
        assert toks[0].type is TokenType.NEQ

    def test_bang_in_type_row_position(self) -> None:
        """`Token!{SSE, ToolCall}` tokenises into the expected sequence."""
        toks = _tokenize("Token!{SSE, ToolCall}")
        types = [t.type for t in toks if t.type is not TokenType.EOF]
        assert types == [
            TokenType.IDENTIFIER, TokenType.BANG, TokenType.LBRACE,
            TokenType.IDENTIFIER, TokenType.COMMA, TokenType.IDENTIFIER,
            TokenType.RBRACE,
        ]

    def test_pascal_case_op_name_is_identifier(self) -> None:
        """Effect operation names (PascalCase by convention) are IDENTIFIERs.

        This is critical because lowercase `emit` is the existing
        EMIT keyword (channel emit). PascalCase `Emit` must remain an
        IDENTIFIER so it can be used as an operation name without
        clashing.
        """
        toks = _tokenize("Emit Done Send Recv Call")
        for tok in toks[:5]:
            assert tok.type is TokenType.IDENTIFIER


# ──────────────────────────────────────────────────────────────────────
#  TestEffectDeclaration — top-level `effect Name { ops... }`
# ──────────────────────────────────────────────────────────────────────


class TestEffectDeclaration:
    """`effect Name { ops... }` parses as EffectDeclaration."""

    def test_single_operation_unit_return(self) -> None:
        prog = _parse("effect SSE { Emit(token: Token) -> Unit }")
        decl = prog.declarations[0]
        assert isinstance(decl, EffectDeclaration)
        assert decl.name == "SSE"
        assert len(decl.operations) == 1
        op = decl.operations[0]
        assert isinstance(op, EffectOperation)
        assert op.name == "Emit"
        assert op.type_parameters == []
        assert len(op.parameters) == 1
        assert op.parameters[0].name == "token"
        assert op.parameters[0].type_expr is not None
        assert op.parameters[0].type_expr.name == "Token"
        assert op.return_type is not None
        assert op.return_type.name == "Unit"

    def test_multiple_operations(self) -> None:
        prog = _parse(
            "effect SSE {\n"
            "    Emit(token: Token) -> Unit\n"
            "    Done() -> Never\n"
            "}"
        )
        decl = prog.declarations[0]
        names = [op.name for op in decl.operations]
        assert names == ["Emit", "Done"]
        assert decl.operations[1].parameters == []
        assert decl.operations[1].return_type.name == "Never"

    def test_zero_arg_operation(self) -> None:
        prog = _parse("effect Bell { Ring() -> Unit }")
        decl = prog.declarations[0]
        op = decl.operations[0]
        assert op.parameters == []
        assert op.name == "Ring"

    def test_multi_parameter_operation(self) -> None:
        prog = _parse(
            "effect ToolCall { Call(name: String, args: Args) -> Result }"
        )
        op = prog.declarations[0].operations[0]
        assert op.name == "Call"
        assert [p.name for p in op.parameters] == ["name", "args"]
        assert [p.type_expr.name for p in op.parameters] == ["String", "Args"]
        assert op.return_type.name == "Result"

    def test_operation_polymorphism_d1(self) -> None:
        """D1 — `Send<T>(value: T) -> Unit` carries a type parameter."""
        prog = _parse(
            "effect Channel { Send<T>(value: T) -> Unit\n  Recv<T>() -> T }"
        )
        decl = prog.declarations[0]
        send = decl.operations[0]
        assert send.type_parameters == ["T"]
        assert send.parameters[0].type_expr.name == "T"
        assert send.return_type.name == "Unit"
        recv = decl.operations[1]
        assert recv.type_parameters == ["T"]
        assert recv.parameters == []
        assert recv.return_type.name == "T"

    def test_multi_typevar_operation(self) -> None:
        """Multiple type parameters: `Map<A, B>(value: A, fn: F) -> B`."""
        prog = _parse(
            "effect Mapper { Map<A, B>(value: A, fn: F) -> B }"
        )
        op = prog.declarations[0].operations[0]
        assert op.type_parameters == ["A", "B"]

    def test_generic_param_in_type_position(self) -> None:
        """`List<Item>` as a parameter type parses as TypeExprNode."""
        prog = _parse(
            "effect Bulk { Push(items: List<Item>) -> Unit }"
        )
        param = prog.declarations[0].operations[0].parameters[0]
        assert param.type_expr.name == "List"
        assert param.type_expr.generic_param == "Item"

    def test_optional_return_type(self) -> None:
        """`Recv() -> Token?` parses with optional flag set."""
        prog = _parse("effect Buf { Recv() -> Token? }")
        op = prog.declarations[0].operations[0]
        assert op.return_type.name == "Token"
        assert op.return_type.optional is True

    def test_empty_effect_body(self) -> None:
        """An effect with zero operations parses (degenerate but legal)."""
        prog = _parse("effect Marker { }")
        decl = prog.declarations[0]
        assert isinstance(decl, EffectDeclaration)
        assert decl.name == "Marker"
        assert decl.operations == []

    def test_effect_at_top_level_only(self) -> None:
        """`effect` declarations appear at top level alongside personas, etc."""
        prog = _parse(
            "persona P { domain: [\"x\"] }\n"
            "effect SSE { Emit(t: Token) -> Unit }\n"
        )
        assert isinstance(prog.declarations[1], EffectDeclaration)

    def test_missing_arrow_raises(self) -> None:
        """`Op(...)` without `-> Type` is a parse error."""
        with pytest.raises(AxonParseError):
            _parse("effect Bad { Op(t: Token) Unit }")

    def test_missing_paren_raises(self) -> None:
        """`Op` without parameter parens is a parse error."""
        with pytest.raises(AxonParseError):
            _parse("effect Bad { Op -> Unit }")

    def test_effect_records_source_position(self) -> None:
        prog = _parse(
            "\n\n  effect SSE { Emit(t: Token) -> Unit }"
        )
        decl = prog.declarations[0]
        assert decl.line == 3
        assert decl.column == 3


# ──────────────────────────────────────────────────────────────────────
#  TestPerform — `perform Effect.Op(args)`
# ──────────────────────────────────────────────────────────────────────


class TestPerform:
    """`perform Effect.Op(args)` inside a step body."""

    def test_simple_perform(self) -> None:
        prog = _parse(_wrap_in_step("perform SSE.Emit(token)"))
        body = _step_body(prog)
        assert len(body) == 1
        node = body[0]
        assert isinstance(node, PerformExpression)
        assert node.effect_name == "SSE"
        assert node.operation_name == "Emit"
        assert node.arguments == ["token"]

    def test_perform_zero_args(self) -> None:
        prog = _parse(_wrap_in_step("perform SSE.Done()"))
        node = _step_body(prog)[0]
        assert isinstance(node, PerformExpression)
        assert node.operation_name == "Done"
        assert node.arguments == []

    def test_perform_multi_args(self) -> None:
        prog = _parse(_wrap_in_step("perform Tool.Call(name, args)"))
        node = _step_body(prog)[0]
        assert node.operation_name == "Call"
        assert node.arguments == ["name", "args"]

    def test_perform_string_arg(self) -> None:
        prog = _parse(_wrap_in_step('perform Log.Info("hello")'))
        node = _step_body(prog)[0]
        assert node.arguments == ["hello"]

    def test_perform_missing_dot_raises(self) -> None:
        """`perform SSE Emit(...)` without dot fails parsing."""
        with pytest.raises(AxonParseError):
            _parse(_wrap_in_step("perform SSE Emit(token)"))

    def test_perform_records_source_position(self) -> None:
        prog = _parse(_wrap_in_step("perform SSE.Emit(t)"))
        node = _step_body(prog)[0]
        assert node.line > 0
        assert node.column > 0


# ──────────────────────────────────────────────────────────────────────
#  TestHandle — `handle Effect { clauses } in { body }`
# ──────────────────────────────────────────────────────────────────────


class TestHandle:
    """`handle Effect { clauses } in { body }` shape and composition."""

    def test_simple_handle_single_clause(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(token) -> { resume }\n"
            "    } in {\n"
            "      perform SSE.Emit(t)\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        assert isinstance(node, HandleExpression)
        assert node.effect_names == ["SSE"]
        assert len(node.clauses) == 1
        clause = node.clauses[0]
        assert isinstance(clause, HandlerClause)
        assert clause.operation_name == "Emit"
        assert [p.name for p in clause.parameters] == ["token"]
        assert len(clause.body) == 1
        assert isinstance(clause.body[0], ResumeStatement)
        assert len(node.body) == 1
        assert isinstance(node.body[0], PerformExpression)

    def test_handle_multi_clause(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(token) -> { resume }\n"
            "      Done() -> { abort }\n"
            "    } in {\n"
            "      perform SSE.Done()\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        names = [c.operation_name for c in node.clauses]
        assert names == ["Emit", "Done"]
        assert isinstance(node.clauses[1].body[0], AbortStatement)

    def test_handle_multi_effect(self) -> None:
        """`handle SSE, ToolCall { ... } in { ... }` — multi-effect handler."""
        prog = _parse(_wrap_in_step(
            "handle SSE, ToolCall {\n"
            "      Emit(t) -> { resume }\n"
            "      Call(n, a) -> { resume }\n"
            "    } in {\n"
            "      perform SSE.Emit(token)\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        assert node.effect_names == ["SSE", "ToolCall"]

    def test_handle_in_block_required_d3(self) -> None:
        """D3 — handle without trailing `in { body }` is a parse error."""
        with pytest.raises(AxonParseError):
            _parse(_wrap_in_step(
                "handle SSE { Emit(t) -> { resume } }"
            ))

    def test_typed_clause_parameter(self) -> None:
        """Clause parameter may carry an explicit type annotation."""
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(token: Token) -> { resume }\n"
            "    } in {\n"
            "      perform SSE.Emit(t)\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        param = node.clauses[0].parameters[0]
        assert param.type_expr is not None
        assert param.type_expr.name == "Token"

    def test_zero_arg_clause(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Done() -> { abort }\n"
            "    } in {\n"
            "      perform SSE.Done()\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        clause = node.clauses[0]
        assert clause.parameters == []
        assert isinstance(clause.body[0], AbortStatement)

    def test_nested_handle(self) -> None:
        """A handle body may contain another handle (nested scopes)."""
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(t) -> { resume }\n"
            "    } in {\n"
            "      handle ToolCall {\n"
            "        Call(n, a) -> { resume }\n"
            "      } in {\n"
            "        perform SSE.Emit(t)\n"
            "      }\n"
            "    }"
        ))
        outer = _step_body(prog)[0]
        assert isinstance(outer, HandleExpression)
        inner = outer.body[0]
        assert isinstance(inner, HandleExpression)
        assert inner.effect_names == ["ToolCall"]

    def test_empty_handle_body(self) -> None:
        """A handle whose `in { ... }` body is empty parses (degenerate)."""
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(t) -> { resume }\n"
            "    } in {\n"
            "    }"
        ))
        node = _step_body(prog)[0]
        assert node.body == []


# ──────────────────────────────────────────────────────────────────────
#  TestResume — `resume` / `resume(value)`
# ──────────────────────────────────────────────────────────────────────


class TestResume:
    """`resume` and `resume(value)` shapes."""

    def test_bare_resume(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(t) -> { resume }\n"
            "    } in { perform SSE.Emit(t) }"
        ))
        clause = _step_body(prog)[0].clauses[0]
        node = clause.body[0]
        assert isinstance(node, ResumeStatement)
        assert node.value_expr == ""

    def test_resume_empty_parens(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(t) -> { resume() }\n"
            "    } in { perform SSE.Emit(t) }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, ResumeStatement)
        assert node.value_expr == ""

    def test_resume_with_value(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle Channel {\n"
            "      Recv() -> { resume(buffer) }\n"
            "    } in { perform Channel.Recv() }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, ResumeStatement)
        assert node.value_expr == "buffer"

    def test_resume_with_dotted_value(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle Channel {\n"
            "      Recv() -> { resume(state.last) }\n"
            "    } in { perform Channel.Recv() }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert node.value_expr == "state.last"


# ──────────────────────────────────────────────────────────────────────
#  TestAbort — `abort` / `abort(value)`
# ──────────────────────────────────────────────────────────────────────


class TestAbort:
    """`abort` and `abort(value)` shapes."""

    def test_bare_abort(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Done() -> { abort }\n"
            "    } in { perform SSE.Done() }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, AbortStatement)
        assert node.value_expr == ""

    def test_abort_with_value(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Done() -> { abort(reason) }\n"
            "    } in { perform SSE.Done() }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, AbortStatement)
        assert node.value_expr == "reason"


# ──────────────────────────────────────────────────────────────────────
#  TestForward — `forward Effect.Op(args)` (D12)
# ──────────────────────────────────────────────────────────────────────


class TestForward:
    """D12 — `forward Effect.Op(args)` propagates to outer handler."""

    def test_simple_forward(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Emit(t) -> { forward SSE.Emit(t) }\n"
            "    } in { perform SSE.Emit(token) }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, ForwardExpression)
        assert node.effect_name == "SSE"
        assert node.operation_name == "Emit"
        assert node.arguments == ["t"]

    def test_forward_zero_args(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle SSE {\n"
            "      Done() -> { forward SSE.Done() }\n"
            "    } in { perform SSE.Done() }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert isinstance(node, ForwardExpression)
        assert node.operation_name == "Done"
        assert node.arguments == []

    def test_forward_multi_args(self) -> None:
        prog = _parse(_wrap_in_step(
            "handle ToolCall {\n"
            "      Call(name, args) -> { forward ToolCall.Call(name, args) }\n"
            "    } in { perform ToolCall.Call(n, a) }"
        ))
        node = _step_body(prog)[0].clauses[0].body[0]
        assert node.arguments == ["name", "args"]


# ──────────────────────────────────────────────────────────────────────
#  TestEffectRow — `!{...}` row annotations (D11)
# ──────────────────────────────────────────────────────────────────────


class TestAlgebraicEffectRow:
    """D11 — `!{...}` row annotations (closed and open via row variable)."""

    def _parse_row(self, source: str) -> AlgebraicEffectRowNode:
        """Helper — invoke the standalone row-parsing production."""
        parser = Parser(_tokenize(source))
        return parser._parse_algebraic_effect_row()

    def test_empty_row(self) -> None:
        node = self._parse_row("!{}")
        assert node.effect_names == []
        assert node.row_variable == ""

    def test_single_effect_closed_row(self) -> None:
        node = self._parse_row("!{SSE}")
        assert node.effect_names == ["SSE"]
        assert node.row_variable == ""

    def test_multi_effect_closed_row(self) -> None:
        node = self._parse_row("!{SSE, ToolCall, Channel}")
        assert node.effect_names == ["SSE", "ToolCall", "Channel"]
        assert node.row_variable == ""

    def test_open_row_with_row_variable(self) -> None:
        """D11 — lowercase identifier is a row variable, not an effect name."""
        node = self._parse_row("!{SSE, e}")
        assert node.effect_names == ["SSE"]
        assert node.row_variable == "e"

    def test_open_row_with_underscore_var(self) -> None:
        """Identifiers starting with `_` are row variables (D11)."""
        node = self._parse_row("!{SSE, ToolCall, _rest}")
        assert node.effect_names == ["SSE", "ToolCall"]
        assert node.row_variable == "_rest"

    def test_row_records_source_position(self) -> None:
        node = self._parse_row("!{SSE}")
        assert node.line > 0
        assert node.column > 0


# ──────────────────────────────────────────────────────────────────────
#  TestIntegration — algebraic effects coexist with existing constructs
# ──────────────────────────────────────────────────────────────────────


class TestIntegration:
    """Algebraic effects compose with personas, flows, types, etc."""

    def test_effect_alongside_persona_and_flow(self) -> None:
        prog = _parse(
            "persona P { domain: [\"a\"] }\n"
            "effect SSE { Emit(t: Token) -> Unit }\n"
            "flow F() -> Unit { step S { perform SSE.Emit(t) } }\n"
        )
        kinds = [type(d).__name__ for d in prog.declarations]
        assert kinds == ["PersonaDefinition", "EffectDeclaration", "FlowDefinition"]

    def test_handle_inside_for_loop_body(self) -> None:
        """`handle ... in { ... }` inside a for-in loop body."""
        prog = _parse(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    for token in stream {\n"
            "      handle SSE { Emit(t) -> { resume } } in { perform SSE.Emit(token) }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        flow = prog.declarations[0]
        step = flow.body[0]
        for_node = step.body[0]
        handle = for_node.body[0]
        assert isinstance(handle, HandleExpression)

    def test_perform_does_not_consume_keyword_emit(self) -> None:
        """`emit` (lowercase, EMIT keyword) and `perform Effect.Emit` coexist.

        The lowercase `emit` keyword stays the existing EMIT channel-output
        keyword; the PascalCase `Emit` inside `perform Effect.Emit(...)` is
        an IDENTIFIER token. The lexer keeps them in different lanes purely
        by case sensitivity — no parser disambiguation needed.
        """
        toks = _tokenize("emit Emit perform")
        # `emit` (keyword) → EMIT, `Emit` (PascalCase) → IDENTIFIER, `perform` → PERFORM.
        types = [t.type for t in toks if t.type is not TokenType.EOF]
        assert types == [TokenType.EMIT, TokenType.IDENTIFIER, TokenType.PERFORM]
        # And the PerformExpression production succeeds when the operation
        # name is `Emit` — confirms there is no clash inside the step body.
        prog = _parse(
            "effect SSE { Emit(t: Token) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    perform SSE.Emit(t)\n"
            "  }\n"
            "}"
        )
        flow = prog.declarations[1]
        assert isinstance(flow, FlowDefinition)
        body = flow.body[0].body
        assert isinstance(body[0], PerformExpression)
        assert body[0].operation_name == "Emit"

    def test_effect_then_handle_program(self) -> None:
        """A program declaring an effect + handling it inside a flow parses."""
        prog = _parse(
            "effect SSE {\n"
            "    Emit(token: Token) -> Unit\n"
            "    Done() -> Never\n"
            "}\n"
            "\n"
            "flow Stream() -> Unit {\n"
            "  step Loop {\n"
            "    handle SSE {\n"
            "      Emit(token) -> { resume }\n"
            "      Done() -> { abort }\n"
            "    } in {\n"
            "      perform SSE.Emit(token)\n"
            "      perform SSE.Done()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        eff = prog.declarations[0]
        flow = prog.declarations[1]
        assert isinstance(eff, EffectDeclaration)
        assert isinstance(flow, FlowDefinition)
        handle = flow.body[0].body[0]
        assert isinstance(handle, HandleExpression)
        assert handle.effect_names == ["SSE"]
        assert len(handle.clauses) == 2
        assert len(handle.body) == 2
