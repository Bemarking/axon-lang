"""
AXON IR Generator — Unit Tests
=================================
Verifies AST → IR transformation correctness for every visitor,
cross-reference resolution, tool verification, and error paths.
"""

import pytest

from axon.compiler import ast_nodes as ast
from axon.compiler.ir_generator import IRGenerator, AxonIRError
from axon.compiler.ir_nodes import (
    IRAnchor,
    IRConditional,
    IRContext,
    IRFlow,
    IRImport,
    IRIntent,
    IRMemory,
    IRParameter,
    IRPersona,
    IRProbe,
    IRProgram,
    IRReason,
    IRRecall,
    IRRefine,
    IRRemember,
    IRRun,
    IRStep,
    IRToolSpec,
    IRType,
    IRTypeField,
    IRUseTool,
    IRValidate,
    IRValidateRule,
    IRWeave,
)


# ═══════════════════════════════════════════════════════════════════
#  FIXTURES — AST node builders
# ═══════════════════════════════════════════════════════════════════


def _persona(name: str = "Expert", **kw) -> ast.PersonaDefinition:
    defaults = dict(
        line=1, column=0, name=name, domain=["AI"],
        tone="precise", confidence_threshold=0.85,
    )
    defaults.update(kw)
    return ast.PersonaDefinition(**defaults)


def _context(name: str = "Session", **kw) -> ast.ContextDefinition:
    defaults = dict(
        line=2, column=0, name=name, memory_scope="session",
        depth="standard", max_tokens=4000, temperature=0.5,
    )
    defaults.update(kw)
    return ast.ContextDefinition(**defaults)


def _anchor(name: str = "NoHallucination", **kw) -> ast.AnchorConstraint:
    defaults = dict(
        line=3, column=0, name=name, require="factual accuracy",
        reject=["speculation"], confidence_floor=0.9,
        unknown_response="I don't know.",
        on_violation="raise", on_violation_target="HallucinationError",
    )
    defaults.update(kw)
    return ast.AnchorConstraint(**defaults)


def _tool(name: str = "WebSearch", **kw) -> ast.ToolDefinition:
    defaults = dict(
        line=4, column=0, name=name, provider="brave",
        max_results=5, timeout="10s",
    )
    defaults.update(kw)
    return ast.ToolDefinition(**defaults)


def _memory(name: str = "KnowledgeBase", **kw) -> ast.MemoryDefinition:
    defaults = dict(
        line=5, column=0, name=name, store="persistent",
        backend="vector_db", retrieval="semantic", decay="none",
    )
    defaults.update(kw)
    return ast.MemoryDefinition(**defaults)


def _type_def(name: str = "Party", **kw) -> ast.TypeDefinition:
    defaults = dict(
        line=6, column=0, name=name,
        fields=[
            ast.TypeFieldNode(
                line=7, column=4, name="name",
                type_expr=ast.TypeExprNode(name="String"),
            ),
            ast.TypeFieldNode(
                line=8, column=4, name="role",
                type_expr=ast.TypeExprNode(name="FactualClaim"),
            ),
        ],
    )
    defaults.update(kw)
    return ast.TypeDefinition(**defaults)


def _step(name: str = "Analyze", **kw) -> ast.StepNode:
    defaults = dict(
        line=10, column=4, name=name,
        given="document", ask="Analyze the document",
        output_type="Analysis",
    )
    defaults.update(kw)
    return ast.StepNode(**defaults)


def _flow(name: str = "AnalyzeContract", steps=None, **kw) -> ast.FlowDefinition:
    if steps is None:
        steps = [_step()]
    defaults = dict(
        line=9, column=0, name=name,
        parameters=[
            ast.ParameterNode(
                line=9, column=20, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            ),
        ],
        return_type=ast.TypeExprNode(name="ContractAnalysis"),
        body=steps,
    )
    defaults.update(kw)
    return ast.FlowDefinition(**defaults)


def _run(
    flow_name: str = "AnalyzeContract",
    persona: str = "Expert",
    context: str = "Session",
    anchors: list[str] | None = None,
    **kw,
) -> ast.RunStatement:
    if anchors is None:
        anchors = ["NoHallucination"]
    defaults = dict(
        line=20, column=0, flow_name=flow_name,
        arguments=["myContract.pdf"],
        persona=persona, context=context, anchors=anchors,
        on_failure="retry", on_failure_params={"backoff": "exponential"},
        output_to="report.json", effort="high",
    )
    defaults.update(kw)
    return ast.RunStatement(**defaults)


def _program(*declarations) -> ast.ProgramNode:
    return ast.ProgramNode(
        line=0, column=0,
        declarations=list(declarations),
    )


def _minimal_program() -> ast.ProgramNode:
    """A valid program with all entities referenced by a run statement."""
    return _program(
        _persona(), _context(), _anchor(), _tool(), _flow(), _run(),
    )


# ═══════════════════════════════════════════════════════════════════
#  GENERATOR BASICS
# ═══════════════════════════════════════════════════════════════════


class TestIRGeneratorBasics:
    """Basic generator lifecycle and output structure."""

    def test_generate_returns_ir_program(self):
        gen = IRGenerator()
        result = gen.generate(_minimal_program())
        assert isinstance(result, IRProgram)

    def test_source_location_propagated(self):
        gen = IRGenerator()
        result = gen.generate(_minimal_program())
        assert result.source_line == 0
        assert result.source_column == 0

    def test_generator_resets_between_calls(self):
        gen = IRGenerator()
        prog1 = gen.generate(_minimal_program())
        prog2 = gen.generate(_minimal_program())
        assert len(prog1.personas) == len(prog2.personas)
        assert len(prog1.flows) == len(prog2.flows)

    def test_empty_program(self):
        gen = IRGenerator()
        result = gen.generate(_program())
        assert result.personas == ()
        assert result.flows == ()
        assert result.runs == ()


# ═══════════════════════════════════════════════════════════════════
#  DECLARATION VISITORS
# ═══════════════════════════════════════════════════════════════════


class TestVisitPersona:
    """Persona AST → IR transformation."""

    def test_persona_fields_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_persona(
            name="LegalExpert",
            domain=["contract law", "IP"],
            tone="precise",
            confidence_threshold=0.85,
            cite_sources=True,
            refuse_if=["medical advice"],
            language="en",
            description="A legal expert",
        )))
        assert len(prog.personas) == 1
        p = prog.personas[0]
        assert isinstance(p, IRPersona)
        assert p.name == "LegalExpert"
        assert p.domain == ("contract law", "IP")
        assert p.tone == "precise"
        assert p.confidence_threshold == 0.85
        assert p.cite_sources is True
        assert p.refuse_if == ("medical advice",)
        assert p.language == "en"
        assert p.description == "A legal expert"

    def test_persona_source_location(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_persona(line=42, column=5)))
        assert prog.personas[0].source_line == 42
        assert prog.personas[0].source_column == 5

    def test_minimal_persona(self):
        gen = IRGenerator()
        prog = gen.generate(_program(ast.PersonaDefinition(name="Minimal")))
        p = prog.personas[0]
        assert p.name == "Minimal"
        assert p.domain == ()
        assert p.confidence_threshold is None


class TestVisitContext:
    """Context AST → IR transformation."""

    def test_context_fields_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_context(
            name="DeepReview",
            memory_scope="persistent",
            language="es",
            depth="exhaustive",
            max_tokens=8000,
            temperature=0.2,
            cite_sources=True,
        )))
        c = prog.contexts[0]
        assert isinstance(c, IRContext)
        assert c.name == "DeepReview"
        assert c.memory_scope == "persistent"
        assert c.language == "es"
        assert c.depth == "exhaustive"
        assert c.max_tokens == 8000
        assert c.temperature == 0.2


class TestVisitAnchor:
    """Anchor AST → IR transformation."""

    def test_anchor_fields_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_anchor(
            name="SafeOutput",
            require="no harmful content",
            reject=["violence", "hate speech"],
            enforce="safety policy",
            confidence_floor=0.95,
            on_violation="raise",
            on_violation_target="SafetyError",
        )))
        a = prog.anchors[0]
        assert isinstance(a, IRAnchor)
        assert a.name == "SafeOutput"
        assert a.reject == ("violence", "hate speech")
        assert a.confidence_floor == 0.95
        assert a.on_violation_target == "SafetyError"


class TestVisitTool:
    """Tool AST → IR transformation."""

    def test_tool_fields_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_tool(
            name="CodeRunner",
            provider="docker",
            max_results=1,
            filter_expr="recent(days: 7)",
            timeout="30s",
            runtime="python3.11",
            sandbox=True,
        )))
        t = prog.tools[0]
        assert isinstance(t, IRToolSpec)
        assert t.name == "CodeRunner"
        assert t.provider == "docker"
        assert t.sandbox is True
        assert t.runtime == "python3.11"


class TestVisitMemory:
    """Memory AST → IR transformation."""

    def test_memory_fields_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_memory(
            name="ConversationLog",
            store="session",
            backend="in_memory",
            retrieval="exact",
            decay="daily",
        )))
        m = prog.memories[0]
        assert isinstance(m, IRMemory)
        assert m.name == "ConversationLog"
        assert m.store == "session"
        assert m.backend == "in_memory"
        assert m.decay == "daily"


class TestVisitAxonEndpoint:
    """AxonEndpoint AST → IR transformation."""

    def test_axonendpoint_fields_mapped(self):
        gen = IRGenerator()
        endpoint = ast.AxonEndpointDefinition(
            line=50,
            column=2,
            name="ContractsAPI",
            method="POST",
            path="/api/contracts/analyze",
            body_type="ContractInput",
            execute_flow="AnalyzeContract",
            output_type="ContractReport",
            shield_ref="EdgeShield",
            retries=2,
            timeout="10s",
        )
        program = gen.generate(_program(endpoint))
        assert len(program.endpoints) == 1
        ir_endpoint = program.endpoints[0]
        assert ir_endpoint.name == "ContractsAPI"
        assert ir_endpoint.method == "POST"
        assert ir_endpoint.path == "/api/contracts/analyze"
        assert ir_endpoint.execute_flow == "AnalyzeContract"
        assert ir_endpoint.source_line == 50


class TestVisitImport:
    """Import AST → IR transformation."""

    def test_import_mapped(self):
        gen = IRGenerator()
        imp = ast.ImportNode(
            line=1, column=0,
            module_path=["axon", "anchors"],
            names=["NoHallucination", "NoBias"],
        )
        prog = gen.generate(_program(imp))
        assert len(prog.imports) == 1
        assert prog.imports[0].module_path == ("axon", "anchors")
        assert prog.imports[0].names == ("NoHallucination", "NoBias")


# ═══════════════════════════════════════════════════════════════════
#  TYPE VISITOR
# ═══════════════════════════════════════════════════════════════════


class TestVisitType:
    """Type definition AST → IR transformation."""

    def test_structured_type(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_type_def("Party")))
        t = prog.types[0]
        assert isinstance(t, IRType)
        assert t.name == "Party"
        assert len(t.fields) == 2
        assert t.fields[0].name == "name"
        assert t.fields[0].type_name == "String"
        assert t.fields[1].name == "role"
        assert t.fields[1].type_name == "FactualClaim"

    def test_ranged_type(self):
        gen = IRGenerator()
        td = ast.TypeDefinition(
            line=1, column=0, name="RiskScore",
            range_constraint=ast.RangeConstraint(
                line=1, column=10, min_value=0.0, max_value=1.0,
            ),
        )
        prog = gen.generate(_program(td))
        t = prog.types[0]
        assert t.range_min == 0.0
        assert t.range_max == 1.0

    def test_constrained_type(self):
        gen = IRGenerator()
        td = ast.TypeDefinition(
            line=1, column=0, name="HighConfidence",
            where_clause=ast.WhereClause(
                line=1, column=10, expression="confidence >= 0.85",
            ),
        )
        prog = gen.generate(_program(td))
        t = prog.types[0]
        assert t.where_expression == "confidence >= 0.85"

    def test_type_field_with_generic(self):
        gen = IRGenerator()
        td = ast.TypeDefinition(
            line=1, column=0, name="Container",
            fields=[
                ast.TypeFieldNode(
                    line=2, column=4, name="items",
                    type_expr=ast.TypeExprNode(
                        name="List", generic_param="Party", optional=False,
                    ),
                ),
            ],
        )
        prog = gen.generate(_program(td))
        f = prog.types[0].fields[0]
        assert f.type_name == "List"
        assert f.generic_param == "Party"
        assert f.optional is False

    def test_type_field_optional(self):
        gen = IRGenerator()
        td = ast.TypeDefinition(
            line=1, column=0, name="Result",
            fields=[
                ast.TypeFieldNode(
                    line=2, column=4, name="error",
                    type_expr=ast.TypeExprNode(
                        name="String", optional=True,
                    ),
                ),
            ],
        )
        prog = gen.generate(_program(td))
        f = prog.types[0].fields[0]
        assert f.optional is True

    def test_type_field_without_type_expr(self):
        gen = IRGenerator()
        td = ast.TypeDefinition(
            line=1, column=0, name="Loose",
            fields=[
                ast.TypeFieldNode(line=2, column=4, name="data"),
            ],
        )
        prog = gen.generate(_program(td))
        f = prog.types[0].fields[0]
        assert f.type_name == ""
        assert f.generic_param == ""
        assert f.optional is False


# ═══════════════════════════════════════════════════════════════════
#  FLOW & STEP VISITORS
# ═══════════════════════════════════════════════════════════════════


class TestVisitFlow:
    """Flow AST → IR transformation."""

    def test_flow_basic(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_flow()))
        f = prog.flows[0]
        assert isinstance(f, IRFlow)
        assert f.name == "AnalyzeContract"
        assert len(f.parameters) == 1
        assert f.parameters[0].name == "doc"
        assert f.parameters[0].type_name == "Document"
        assert f.return_type_name == "ContractAnalysis"

    def test_flow_with_multiple_steps(self):
        gen = IRGenerator()
        steps = [_step("Extract"), _step("Reason"), _step("Synthesize")]
        prog = gen.generate(_program(_flow(steps=steps)))
        f = prog.flows[0]
        assert len(f.steps) == 3
        assert f.steps[0].name == "Extract"
        assert f.steps[2].name == "Synthesize"

    def test_flow_without_return_type(self):
        gen = IRGenerator()
        flow_ast = ast.FlowDefinition(
            line=1, column=0, name="SimpleFlow",
            body=[_step()],
        )
        prog = gen.generate(_program(flow_ast))
        f = prog.flows[0]
        assert f.return_type_name == ""

    def test_flow_parameter_generic(self):
        gen = IRGenerator()
        flow_ast = ast.FlowDefinition(
            line=1, column=0, name="BatchFlow",
            parameters=[
                ast.ParameterNode(
                    line=1, column=15, name="items",
                    type_expr=ast.TypeExprNode(
                        name="List", generic_param="Document", optional=True,
                    ),
                ),
            ],
            body=[_step()],
        )
        prog = gen.generate(_program(flow_ast))
        p = prog.flows[0].parameters[0]
        assert p.type_name == "List"
        assert p.generic_param == "Document"
        assert p.optional is True


class TestVisitStep:
    """Step AST → IR transformation."""

    def test_step_basic(self):
        gen = IRGenerator()
        prog = gen.generate(_program(_flow()))
        s = prog.flows[0].steps[0]
        assert isinstance(s, IRStep)
        assert s.name == "Analyze"
        assert s.given == "document"
        assert s.ask == "Analyze the document"

    def test_step_with_tool(self):
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="WebSearch",
            argument="quantum computing 2025",
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.use_tool is not None
        assert isinstance(s.use_tool, IRUseTool)
        assert s.use_tool.tool_name == "WebSearch"
        assert s.use_tool.argument == "quantum computing 2025"

    def test_step_with_probe(self):
        gen = IRGenerator()
        step = _step(probe=ast.ProbeDirective(
            line=11, column=8, target="doc",
            fields=["parties", "dates", "obligations"],
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.probe is not None
        assert isinstance(s.probe, IRProbe)
        assert s.probe.target == "doc"
        assert s.probe.fields == ("parties", "dates", "obligations")

    def test_step_with_reason(self):
        gen = IRGenerator()
        step = _step(reason=ast.ReasonChain(
            line=11, column=8, name="Assess",
            about="risks", given=["parties", "clauses"],
            depth=3, show_work=True, chain_of_thought=True,
            ask="What risks exist?", output_type="RiskAnalysis",
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.reason is not None
        assert isinstance(s.reason, IRReason)
        assert s.reason.depth == 3
        assert s.reason.given == ("parties", "clauses")

    def test_step_with_weave(self):
        gen = IRGenerator()
        step = _step(weave=ast.WeaveNode(
            line=11, column=8,
            sources=["analysis", "precedents"],
            target="Report", format_type="markdown",
            priority=["risk", "summary"], style="formal",
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.weave is not None
        assert isinstance(s.weave, IRWeave)
        assert s.weave.sources == ("analysis", "precedents")
        assert s.weave.style == "formal"

    def test_step_with_sub_steps(self):
        gen = IRGenerator()
        parent_step = _step(
            name="Parent",
            body=[_step("Child1"), _step("Child2")],
        )
        prog = gen.generate(_program(_flow(steps=[parent_step])))
        s = prog.flows[0].steps[0]
        assert len(s.body) == 2
        assert s.body[0].name == "Child1"
        assert s.body[1].name == "Child2"

    def test_step_with_confidence_floor(self):
        gen = IRGenerator()
        step = _step(confidence_floor=0.92)
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.confidence_floor == 0.92

    def test_step_with_static_tool_binding(self):
        """v0.25.5: static_args lowered to IRUseTool.parameters tuple."""
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="create_md",
            static_args={"path": "out.md", "mode": "append"},
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.use_tool is not None
        assert s.use_tool.parameters == (("path", "out.md"), ("mode", "append"))
        assert s.use_tool.argument == ""

    def test_step_with_tool_backward_compat(self):
        """v0.25.5: positional argument still works, parameters stays empty."""
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="WebSearch",
            argument="quantum computing",
        ))
        prog = gen.generate(_program(_flow(steps=[step])))
        s = prog.flows[0].steps[0]
        assert s.use_tool.parameters == ()
        assert s.use_tool.argument == "quantum computing"


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE NODE VISITORS
# ═══════════════════════════════════════════════════════════════════


class TestVisitCognitiveNodes:
    """Intent, Probe, Reason, Weave, Validate, Refine visitors."""

    def test_intent_standalone(self):
        gen = IRGenerator()
        intent_ast = ast.IntentNode(
            line=10, column=4, name="ClassifyRisk",
            given="contract", ask="Classify the risk level",
            output_type=ast.TypeExprNode(
                name="RiskScore", generic_param="", optional=False,
            ),
            confidence_floor=0.9,
        )
        flow = _flow(steps=[intent_ast])
        prog = gen.generate(_program(flow))
        i = prog.flows[0].steps[0]
        assert isinstance(i, IRIntent)
        assert i.name == "ClassifyRisk"
        assert i.output_type_name == "RiskScore"
        assert i.confidence_floor == 0.9

    def test_intent_without_output_type(self):
        gen = IRGenerator()
        intent_ast = ast.IntentNode(
            line=10, column=4, name="Think",
            ask="What do you think?",
        )
        flow = _flow(steps=[intent_ast])
        prog = gen.generate(_program(flow))
        i = prog.flows[0].steps[0]
        assert i.output_type_name == ""

    def test_probe_standalone(self):
        gen = IRGenerator()
        probe_ast = ast.ProbeDirective(
            line=10, column=4, target="input",
            fields=["entities", "dates"],
        )
        flow = _flow(steps=[probe_ast])
        prog = gen.generate(_program(flow))
        p = prog.flows[0].steps[0]
        assert isinstance(p, IRProbe)
        assert p.target == "input"
        assert p.fields == ("entities", "dates")

    def test_reason_with_string_given(self):
        """Reason.given can be a single string, normalized to tuple."""
        gen = IRGenerator()
        reason_ast = ast.ReasonChain(
            line=10, column=4, name="Think",
            about="topic", given="single_input",
            depth=2, show_work=False,
        )
        flow = _flow(steps=[reason_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert isinstance(r, IRReason)
        assert r.given == ("single_input",)

    def test_reason_with_list_given(self):
        gen = IRGenerator()
        reason_ast = ast.ReasonChain(
            line=10, column=4, name="Reason",
            about="topic", given=["a", "b", "c"],
            depth=5, show_work=True, chain_of_thought=True,
        )
        flow = _flow(steps=[reason_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert r.given == ("a", "b", "c")
        assert r.chain_of_thought is True

    def test_reason_with_empty_given(self):
        gen = IRGenerator()
        reason_ast = ast.ReasonChain(
            line=10, column=4, name="Ponder",
            about="everything", given="",
        )
        flow = _flow(steps=[reason_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert r.given == ()

    def test_weave_standalone(self):
        gen = IRGenerator()
        weave_ast = ast.WeaveNode(
            line=10, column=4,
            sources=["analysis", "risk"], target="Report",
            format_type="pdf", priority=["executive_summary"],
        )
        flow = _flow(steps=[weave_ast])
        prog = gen.generate(_program(flow))
        w = prog.flows[0].steps[0]
        assert isinstance(w, IRWeave)
        assert w.target == "Report"

    def test_validate_with_rules(self):
        gen = IRGenerator()
        validate_ast = ast.ValidateGate(
            line=10, column=4, target="output", schema="RiskSchema",
            rules=[
                ast.ValidateRule(
                    line=11, column=8,
                    condition="confidence", comparison_op="<",
                    comparison_value="0.80",
                    action="refine", action_params={"max_attempts": "2"},
                ),
                ast.ValidateRule(
                    line=12, column=8,
                    condition="structural_mismatch",
                    action="raise", action_target="ValidationError",
                ),
            ],
        )
        flow = _flow(steps=[validate_ast])
        prog = gen.generate(_program(flow))
        v = prog.flows[0].steps[0]
        assert isinstance(v, IRValidate)
        assert v.target == "output"
        assert v.schema == "RiskSchema"
        assert len(v.rules) == 2
        assert v.rules[0].action == "refine"
        assert v.rules[0].action_params == (("max_attempts", "2"),)
        assert v.rules[1].action == "raise"
        assert v.rules[1].action_target == "ValidationError"

    def test_refine(self):
        gen = IRGenerator()
        refine_ast = ast.RefineBlock(
            line=10, column=4,
            max_attempts=5, pass_failure_context=True,
            backoff="exponential",
            on_exhaustion="escalate", on_exhaustion_target="QualityGate",
        )
        flow = _flow(steps=[refine_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert isinstance(r, IRRefine)
        assert r.max_attempts == 5
        assert r.backoff == "exponential"
        assert r.on_exhaustion_target == "QualityGate"

    def test_conditional_with_branches(self):
        gen = IRGenerator()
        cond_ast = ast.ConditionalNode(
            line=10, column=4,
            condition="confidence", comparison_op="<",
            comparison_value="0.5",
            then_step=_step("Retry"),
            else_step=_step("Accept"),
        )
        flow = _flow(steps=[cond_ast])
        prog = gen.generate(_program(flow))
        c = prog.flows[0].steps[0]
        assert isinstance(c, IRConditional)
        assert c.then_branch is not None
        assert c.then_branch.name == "Retry"
        assert c.else_branch is not None
        assert c.else_branch.name == "Accept"

    def test_conditional_without_else(self):
        gen = IRGenerator()
        cond_ast = ast.ConditionalNode(
            line=10, column=4,
            condition="risk", comparison_op=">",
            comparison_value="0.9",
            then_step=_step("Escalate"),
        )
        flow = _flow(steps=[cond_ast])
        prog = gen.generate(_program(flow))
        c = prog.flows[0].steps[0]
        assert c.else_branch is None


# ═══════════════════════════════════════════════════════════════════
#  MEMORY OPERATION VISITORS
# ═══════════════════════════════════════════════════════════════════


class TestVisitMemoryOps:
    """Remember and Recall visitors."""

    def test_remember(self):
        gen = IRGenerator()
        rem_ast = ast.RememberNode(
            line=10, column=4,
            expression="analysis_result",
            memory_target="KnowledgeBase",
        )
        flow = _flow(steps=[rem_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert isinstance(r, IRRemember)
        assert r.expression == "analysis_result"
        assert r.memory_target == "KnowledgeBase"

    def test_recall(self):
        gen = IRGenerator()
        rec_ast = ast.RecallNode(
            line=10, column=4,
            query="prior research on quantum computing",
            memory_source="KnowledgeBase",
        )
        flow = _flow(steps=[rec_ast])
        prog = gen.generate(_program(flow))
        r = prog.flows[0].steps[0]
        assert isinstance(r, IRRecall)
        assert r.query == "prior research on quantum computing"
        assert r.memory_source == "KnowledgeBase"


# ═══════════════════════════════════════════════════════════════════
#  RUN STATEMENT & CROSS-REFERENCE RESOLUTION
# ═══════════════════════════════════════════════════════════════════


class TestVisitRun:
    """Run statement visitor and cross-reference resolution."""

    def test_run_basic_fields(self):
        gen = IRGenerator()
        prog = gen.generate(_minimal_program())
        assert len(prog.runs) == 1
        r = prog.runs[0]
        assert isinstance(r, IRRun)
        assert r.flow_name == "AnalyzeContract"
        assert r.persona_name == "Expert"
        assert r.context_name == "Session"
        assert r.anchor_names == ("NoHallucination",)
        assert r.arguments == ("myContract.pdf",)
        assert r.effort == "high"
        assert r.output_to == "report.json"

    def test_run_resolved_references(self):
        gen = IRGenerator()
        prog = gen.generate(_minimal_program())
        r = prog.runs[0]
        assert r.resolved_flow is not None
        assert r.resolved_flow.name == "AnalyzeContract"
        assert r.resolved_persona is not None
        assert r.resolved_persona.name == "Expert"
        assert r.resolved_context is not None
        assert r.resolved_context.name == "Session"
        assert len(r.resolved_anchors) == 1
        assert r.resolved_anchors[0].name == "NoHallucination"

    def test_run_multiple_anchors(self):
        gen = IRGenerator()
        prog = gen.generate(_program(
            _persona(), _context(),
            _anchor("NoBias"), _anchor("NoHallucination"),
            _flow(), _run(anchors=["NoBias", "NoHallucination"]),
        ))
        r = prog.runs[0]
        assert len(r.resolved_anchors) == 2
        anchor_names = {a.name for a in r.resolved_anchors}
        assert anchor_names == {"NoBias", "NoHallucination"}

    def test_run_without_persona(self):
        gen = IRGenerator()
        prog = gen.generate(_program(
            _context(), _anchor(), _flow(),
            _run(persona=""),
        ))
        r = prog.runs[0]
        assert r.resolved_persona is None

    def test_run_without_context(self):
        gen = IRGenerator()
        prog = gen.generate(_program(
            _persona(), _anchor(), _flow(),
            _run(context=""),
        ))
        r = prog.runs[0]
        assert r.resolved_context is None

    def test_run_without_anchors(self):
        gen = IRGenerator()
        prog = gen.generate(_program(
            _persona(), _context(), _flow(),
            _run(anchors=[]),
        ))
        r = prog.runs[0]
        assert r.resolved_anchors == ()

    def test_on_failure_params_mapped(self):
        gen = IRGenerator()
        prog = gen.generate(_minimal_program())
        r = prog.runs[0]
        assert r.on_failure == "retry"
        assert ("backoff", "exponential") in r.on_failure_params


# ═══════════════════════════════════════════════════════════════════
#  ERROR PATHS — Cross-reference resolution
# ═══════════════════════════════════════════════════════════════════


class TestCrossReferenceErrors:
    """Undefined entity references must raise AxonIRError."""

    def test_undefined_flow_raises(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match="undefined flow 'MissingFlow'"):
            gen.generate(_program(
                _persona(), _context(), _anchor(),
                _run(flow_name="MissingFlow"),
            ))

    def test_undefined_persona_raises(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match="undefined persona 'Ghost'"):
            gen.generate(_program(
                _context(), _anchor(), _flow(),
                _run(persona="Ghost"),
            ))

    def test_undefined_context_raises(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match="undefined context 'Missing'"):
            gen.generate(_program(
                _persona(), _anchor(), _flow(),
                _run(context="Missing"),
            ))

    def test_undefined_anchor_raises(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match="undefined anchor 'Phantom'"):
            gen.generate(_program(
                _persona(), _context(), _flow(),
                _run(anchors=["Phantom"]),
            ))

    def test_error_includes_available_entities(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match="Available flows: AnalyzeContract"):
            gen.generate(_program(
                _persona(), _context(), _anchor(), _flow(),
                _run(flow_name="WrongFlow"),
            ))

    def test_error_shows_none_when_no_entities(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError, match=r"\(none\)"):
            gen.generate(_program(
                _run(flow_name="Missing", persona="", context="", anchors=[]),
            ))

    def test_error_includes_source_location(self):
        gen = IRGenerator()
        with pytest.raises(AxonIRError) as exc_info:
            gen.generate(_program(
                _run(
                    flow_name="Missing", persona="", context="",
                    anchors=[], line=42, column=10,
                ),
            ))
        assert exc_info.value.line == 42
        assert exc_info.value.column == 10


# ═══════════════════════════════════════════════════════════════════
#  TOOL VERIFICATION
# ═══════════════════════════════════════════════════════════════════


class TestToolVerification:
    """Static tool resolution at compile time."""

    def test_valid_tool_reference_passes(self):
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="WebSearch",
            argument="query",
        ))
        prog = gen.generate(_program(
            _persona(), _context(), _anchor(),
            _tool("WebSearch"), _flow(steps=[step]), _run(),
        ))
        assert prog.flows[0].steps[0].use_tool.tool_name == "WebSearch"

    def test_undefined_tool_raises(self):
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="FakeTool",
            argument="query",
        ))
        with pytest.raises(AxonIRError, match="undefined tool 'FakeTool'"):
            gen.generate(_program(
                _persona(), _context(), _anchor(),
                _flow(steps=[step]), _run(),
            ))

    def test_tool_error_lists_available(self):
        gen = IRGenerator()
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="Missing", argument="x",
        ))
        with pytest.raises(AxonIRError, match="Available tools: WebSearch"):
            gen.generate(_program(
                _persona(), _context(), _anchor(),
                _tool("WebSearch"), _flow(steps=[step]), _run(),
            ))

    def test_nested_tool_verification(self):
        """Tools in sub-steps should also be verified."""
        gen = IRGenerator()
        child = _step(
            name="Child",
            use_tool=ast.UseToolNode(
                line=12, column=12, tool_name="UnknownTool",
                argument="test",
            ),
        )
        parent = _step(name="Parent", body=[child])
        with pytest.raises(AxonIRError, match="undefined tool 'UnknownTool'"):
            gen.generate(_program(
                _persona(), _context(), _anchor(),
                _flow(steps=[parent]), _run(),
            ))

    def test_step_without_tool_passes_verification(self):
        gen = IRGenerator()
        prog = gen.generate(_minimal_program())
        # Should not raise — no tool usage
        assert len(prog.runs) == 1

    def test_use_psyche_ref_passes_verification(self):
        """use X() where X is a psyche spec should NOT raise (v0.25.1 fix)."""
        gen = IRGenerator()
        psyche = ast.PsycheDefinition(
            line=1, column=0, name="UserStress",
            dimensions=["affect", "cognitive_load"],
        )
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="UserStress",
            argument="session_data",
        ))
        prog = gen.generate(_program(
            _persona(), _context(), _anchor(),
            psyche, _flow(steps=[step]), _run(),
        ))
        assert prog.flows[0].steps[0].use_tool.tool_name == "UserStress"

    def test_use_ots_ref_passes_verification(self):
        """use X() where X is an OTS spec should NOT raise (v0.25.1 fix)."""
        gen = IRGenerator()
        ots = ast.OtsDefinition(
            line=1, column=0, name="DataExtractor",
            teleology="Extract structured data",
        )
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="DataExtractor",
            argument="raw_input",
        ))
        prog = gen.generate(_program(
            _persona(), _context(), _anchor(),
            ots, _flow(steps=[step]), _run(),
        ))
        assert prog.flows[0].steps[0].use_tool.tool_name == "DataExtractor"

    def test_undefined_use_ref_error_lists_all_namespaces(self):
        """Error message should list refs from tools + psyche + OTS."""
        gen = IRGenerator()
        psyche = ast.PsycheDefinition(
            line=1, column=0, name="UserStress",
            dimensions=["affect"],
        )
        ots = ast.OtsDefinition(
            line=2, column=0, name="DataExtractor",
            teleology="extract",
        )
        step = _step(use_tool=ast.UseToolNode(
            line=11, column=8, tool_name="GhostRef",
            argument="x",
        ))
        with pytest.raises(AxonIRError, match="DataExtractor") as exc_info:
            gen.generate(_program(
                _persona(), _context(), _anchor(),
                _tool("WebSearch"), psyche, ots,
                _flow(steps=[step]), _run(),
            ))
        # All 3 namespaces should appear in the error
        err_msg = str(exc_info.value)
        assert "WebSearch" in err_msg
        assert "UserStress" in err_msg
        assert "DataExtractor" in err_msg


# ═══════════════════════════════════════════════════════════════════
#  VISITOR DISPATCH ERRORS
# ═══════════════════════════════════════════════════════════════════


class TestVisitorDispatch:
    """Unknown AST node types should raise clear errors."""

    def test_unknown_ast_node_type_raises(self):
        gen = IRGenerator()

        class FakeASTNode(ast.ASTNode):
            pass

        prog = _program(FakeASTNode(line=99, column=5))
        with pytest.raises(AxonIRError, match="No IR visitor for AST node type"):
            gen.generate(prog)


# ═══════════════════════════════════════════════════════════════════
#  FULL PROGRAM INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestFullProgramGeneration:
    """End-to-end IR generation with all declaration types."""

    def test_full_program_all_entities(self):
        """A program with every entity type should generate correctly."""
        gen = IRGenerator()
        prog = gen.generate(_program(
            # Imports
            ast.ImportNode(
                line=1, column=0,
                module_path=["axon", "std"],
                names=["SafetyAnchors"],
            ),
            # Declarations
            _persona("Analyst"),
            _context("ResearchMode"),
            _anchor("StrictFacts"),
            _tool("WebSearch"),
            _memory("LongTerm"),
            _type_def("Report"),
            # Flow with mixed step types
            _flow("Research", steps=[
                _step("Gather"),
                ast.ProbeDirective(
                    line=15, column=8, target="data",
                    fields=["entities"],
                ),
                ast.ReasonChain(
                    line=16, column=8, name="Evaluate",
                    about="findings", depth=2,
                ),
            ]),
            # Run
            _run(
                flow_name="Research", persona="Analyst",
                context="ResearchMode", anchors=["StrictFacts"],
            ),
        ))

        assert len(prog.imports) == 1
        assert len(prog.personas) == 1
        assert len(prog.contexts) == 1
        assert len(prog.anchors) == 1
        assert len(prog.tools) == 1
        assert len(prog.memories) == 1
        assert len(prog.types) == 1
        assert len(prog.flows) == 1
        assert len(prog.runs) == 1

        # Verify resolved references
        run = prog.runs[0]
        assert run.resolved_flow.name == "Research"
        assert run.resolved_persona.name == "Analyst"
        assert run.resolved_context.name == "ResearchMode"
        assert run.resolved_anchors[0].name == "StrictFacts"

        # Verify flow has mixed step types
        flow = prog.flows[0]
        assert len(flow.steps) == 3
        assert isinstance(flow.steps[0], IRStep)
        assert isinstance(flow.steps[1], IRProbe)
        assert isinstance(flow.steps[2], IRReason)

    def test_multiple_runs_share_entities(self):
        gen = IRGenerator()
        prog = gen.generate(_program(
            _persona("A"), _persona("B"),
            _context("Ctx"),
            _anchor("Anchor1"),
            _flow("FlowA", steps=[_step("s1")]),
            _flow("FlowB", steps=[_step("s2")]),
            _run(flow_name="FlowA", persona="A", context="Ctx",
                 anchors=["Anchor1"]),
            _run(flow_name="FlowB", persona="B", context="Ctx",
                 anchors=["Anchor1"]),
        ))
        assert len(prog.runs) == 2
        assert prog.runs[0].resolved_flow.name == "FlowA"
        assert prog.runs[1].resolved_flow.name == "FlowB"
        assert prog.runs[0].resolved_persona.name == "A"
        assert prog.runs[1].resolved_persona.name == "B"

    def test_program_ir_is_serializable(self):
        gen = IRGenerator()
        prog = gen.generate(_minimal_program())
        d = prog.to_dict()
        assert isinstance(d, dict)
        assert d["node_type"] == "program"
        assert isinstance(d["personas"], tuple)
        assert isinstance(d["flows"], tuple)


# ═══════════════════════════════════════════════════════════════════
#  DAG & EXECUTION LEVELS VISITORS
# ═══════════════════════════════════════════════════════════════════

class TestIRGeneratorDAG:
    """Tests Kahn's topological sort and DAG generation."""

    def test_linear_dependencies(self):
        gen = IRGenerator()
        steps = [
            _step("Step1", output_type="T1"),
            _step("Step2", given="Step1.output", output_type="T2"),
            _step("Step3", given="{{Step2.output}}", output_type="T3"),
        ]
        # Mix them up to verify sorting
        flow = _flow(steps=[steps[2], steps[1], steps[0]])
        prog = gen.generate(_program(flow))
        f = prog.flows[0]
        
        # Check order
        assert len(f.steps) == 3
        assert f.steps[0].name == "Step1"
        assert f.steps[1].name == "Step2"
        assert f.steps[2].name == "Step3"
        
        # Check edges
        assert len(f.edges) == 2
        edges = {(e.source_step, e.target_step) for e in f.edges}
        assert edges == {("Step1", "Step2"), ("Step2", "Step3")}
        
        # Check levels
        assert f.execution_levels == (("Step1",), ("Step2",), ("Step3",))

    def test_parallel_dependencies(self):
        gen = IRGenerator()
        steps = [
            _step("FetchA", output_type="A"),
            _step("FetchB", output_type="B"),
            _step("Combine", given="FetchA.output and FetchB", ask="{{FetchB.output}}", output_type="C"),
        ]
        flow = _flow(steps=steps)
        prog = gen.generate(_program(flow))
        f = prog.flows[0]
        
        assert len(f.edges) == 2
        edges = {(e.source_step, e.target_step) for e in f.edges}
        assert edges == {("FetchA", "Combine"), ("FetchB", "Combine")}
        
        assert len(f.execution_levels) == 2
        # First level can be FetchA, FetchB in any order
        assert set(f.execution_levels[0]) == {"FetchA", "FetchB"}
        assert f.execution_levels[1] == ("Combine",)

    def test_cycle_detection(self):
        gen = IRGenerator()
        steps = [
            _step("A", given="B.output"),
            _step("B", given="A.output"),
        ]
        flow = _flow(steps=steps)
        with pytest.raises(AxonIRError, match="Cycle detected"):
            gen.generate(_program(flow))


# ═══════════════════════════════════════════════════════════════════
#  I/O COGNITIVO — λ-L-E Fase 1: IR lowering + Intention Tree
# ═══════════════════════════════════════════════════════════════════


from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ir_nodes import (
    IRFabric,
    IRIntentionTree,
    IRManifest,
    IRObserve,
    IRResource,
)


def _compile(source: str):
    """Lex + parse + generate IR. Assumes source is type-check-clean."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return IRGenerator().generate(tree)


class TestIOCognitivoIR:
    """IR Generator lowers I/O primitives to IR nodes and an Intention Tree."""

    def test_resource_lowered(self):
        ir = _compile('''resource Db {
  kind: postgres
  endpoint: "db:5432"
  capacity: 10
  lifetime: linear
  certainty_floor: 0.9
}''')
        assert len(ir.resources) == 1
        r = ir.resources[0]
        assert isinstance(r, IRResource)
        assert r.name == "Db"
        assert r.kind == "postgres"
        assert r.lifetime == "linear"
        assert r.certainty_floor == 0.9

    def test_fabric_lowered(self):
        ir = _compile('''fabric Vpc {
  provider: aws
  region: "us-east-1"
  zones: 2
  ephemeral: true
}''')
        assert len(ir.fabrics) == 1
        f = ir.fabrics[0]
        assert isinstance(f, IRFabric)
        assert f.provider == "aws"
        assert f.zones == 2
        assert f.ephemeral is True

    def test_manifest_lowered_and_added_to_intention_tree(self):
        ir = _compile('''resource Db { kind: postgres }
manifest M { resources: [Db] }''')
        assert len(ir.manifests) == 1
        m = ir.manifests[0]
        assert isinstance(m, IRManifest)
        assert m.resources == ("Db",)
        # The manifest is a provisioning intention — must be in the tree
        assert ir.intention_tree is not None
        assert isinstance(ir.intention_tree, IRIntentionTree)
        assert any(op.name == "M" for op in ir.intention_tree.operations)

    def test_observe_lowered_and_added_to_intention_tree(self):
        ir = _compile('''resource Db { kind: postgres }
manifest M { resources: [Db] }
observe S from M {
  sources: [prometheus, cloudwatch]
  quorum: 1
  timeout: 3s
  on_partition: shield_quarantine
  certainty_floor: 0.8
}''')
        assert len(ir.observations) == 1
        o = ir.observations[0]
        assert isinstance(o, IRObserve)
        assert o.target == "M"
        assert o.sources == ("prometheus", "cloudwatch")
        assert o.on_partition == "shield_quarantine"
        # Intention tree contains both manifest M and observation S
        tree = ir.intention_tree
        assert tree is not None
        names = {op.name for op in tree.operations}
        assert names == {"M", "S"}

    def test_intention_tree_is_none_when_no_io_declared(self):
        ir = _compile('''persona E { tone: precise }''')
        assert ir.intention_tree is None
        assert ir.manifests == ()
        assert ir.observations == ()

    def test_ir_program_serializes_intention_tree(self):
        ir = _compile('''resource Db { kind: postgres }
manifest M { resources: [Db] }''')
        d = ir.to_dict()
        assert d["intention_tree"]["node_type"] == "intention_tree"
        assert len(d["intention_tree"]["operations"]) == 1
        assert d["intention_tree"]["operations"][0]["node_type"] == "manifest"


# ═══════════════════════════════════════════════════════════════════
#  CONTROL COGNITIVO — Fase 3 IR lowering (reconcile, lease, ensemble)
# ═══════════════════════════════════════════════════════════════════


from axon.compiler.ir_nodes import IREnsemble, IRLease, IRReconcile


_IR_PROLOGUE = '''
resource Db { kind: postgres lifetime: affine }
resource Db2 { kind: postgres lifetime: affine }
manifest M { resources: [Db] }
manifest M2 { resources: [Db2] }
observe O from M { sources: [prometheus] quorum: 1 timeout: 5s }
observe O2 from M2 { sources: [prometheus] quorum: 1 timeout: 5s }
'''


class TestControlCognitivoIR:

    def test_reconcile_lowered(self):
        ir = _compile(_IR_PROLOGUE + '''
reconcile R { observe: O threshold: 0.85 tolerance: 0.1 on_drift: provision max_retries: 5 }
''')
        assert len(ir.reconciles) == 1
        r = ir.reconciles[0]
        assert isinstance(r, IRReconcile)
        assert r.observe_ref == "O"
        assert r.threshold == 0.85
        assert r.tolerance == 0.10
        assert r.on_drift == "provision"
        assert r.max_retries == 5
        # Reconcile is NOT auto-added to the Intention Tree — it is a
        # control-loop declaration, not a one-shot intention.
        tree = ir.intention_tree
        assert tree is not None
        assert all(op.node_type != "reconcile" for op in tree.operations)

    def test_lease_lowered(self):
        ir = _compile(_IR_PROLOGUE + '''
lease L { resource: Db duration: 30s acquire: on_start on_expire: anchor_breach }
''')
        assert len(ir.leases) == 1
        lease = ir.leases[0]
        assert isinstance(lease, IRLease)
        assert lease.resource_ref == "Db"
        assert lease.duration == "30s"
        assert lease.on_expire == "anchor_breach"

    def test_ensemble_lowered(self):
        ir = _compile(_IR_PROLOGUE + '''
ensemble E { observations: [O, O2] quorum: 2 aggregation: byzantine certainty_mode: harmonic }
''')
        assert len(ir.ensembles) == 1
        e = ir.ensembles[0]
        assert isinstance(e, IREnsemble)
        assert e.observations == ("O", "O2")
        assert e.aggregation == "byzantine"
        assert e.certainty_mode == "harmonic"

    def test_ir_program_serializes_control_cognitivo(self):
        ir = _compile(_IR_PROLOGUE + '''
reconcile R { observe: O }
lease L { resource: Db duration: 1s }
ensemble E { observations: [O, O2] }
''')
        d = ir.to_dict()
        assert len(d["reconciles"]) == 1
        assert len(d["leases"]) == 1
        assert len(d["ensembles"]) == 1
        assert d["reconciles"][0]["node_type"] == "reconcile"


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGY & SESSION TYPES — Fase 4 IR lowering
# ═══════════════════════════════════════════════════════════════════


from axon.compiler.ir_nodes import IRSession, IRTopology


class TestTopologySessionIR:

    _IR_PROLOGUE = '''
resource A { kind: postgres }
resource B { kind: redis }
session DbSess {
  client: [send Query, receive Result, end]
  server: [receive Query, send Result, end]
}
'''

    def test_session_lowered_with_dual_roles(self):
        ir = _compile(self._IR_PROLOGUE)
        assert len(ir.sessions) == 1
        s = ir.sessions[0]
        assert isinstance(s, IRSession)
        assert s.name == "DbSess"
        assert len(s.roles) == 2
        client, server = s.roles
        assert client.name == "client"
        assert server.name == "server"
        assert client.steps[0].op == "send"
        assert client.steps[0].message_type == "Query"

    def test_topology_lowered(self):
        ir = _compile(self._IR_PROLOGUE + '''
topology Prod {
  nodes: [A, B]
  edges: [A -> B : DbSess]
}''')
        assert len(ir.topologies) == 1
        t = ir.topologies[0]
        assert isinstance(t, IRTopology)
        assert t.name == "Prod"
        assert t.nodes == ("A", "B")
        assert len(t.edges) == 1
        assert (t.edges[0].source, t.edges[0].target, t.edges[0].session_ref) == (
            "A", "B", "DbSess",
        )

    def test_ir_program_serializes_topology_and_session(self):
        ir = _compile(self._IR_PROLOGUE + '''
topology Prod { nodes: [A, B] edges: [A -> B : DbSess] }''')
        d = ir.to_dict()
        assert len(d["sessions"]) == 1
        assert len(d["topologies"]) == 1
        assert d["sessions"][0]["node_type"] == "session"
        assert d["topologies"][0]["edges"][0]["node_type"] == "topology_edge"


# ═══════════════════════════════════════════════════════════════════
#  COMPOSITION TEST — Fase 4 closing criterion (endpoint↔daemon↔resource)
# ═══════════════════════════════════════════════════════════════════


class TestPhase4Composition:
    """End-to-end: an axonendpoint, a daemon, and a resource composed in
    a single typed topology that compiles cleanly and reaches the IR."""

    _SRC = '''
type ContractInput { sql: String }
type ContractReport { rows: integer }

flow AnalyzeContract(req: ContractInput) -> ContractReport {
  step S { ask: "Analyze" output: ContractReport }
}

resource PrimaryDb { kind: postgres lifetime: linear }

shield EdgeShield {
  scan: [prompt_injection]
  on_breach: quarantine
  severity: medium
}

axonendpoint ContractsAPI {
  method: post
  path: "/api/contracts"
  body: ContractInput
  execute: AnalyzeContract
  output: ContractReport
  shield: EdgeShield
}

daemon OrdersDaemon(input: String) -> String {
  goal: "Process order events"
  listen "orders" as evt {
    step Process {
      ask: "Process: {{evt}}"
      output: String
    }
  }
}

session ApiToDb {
  client: [send Query, receive Result, end]
  server: [receive Query, send Result, end]
}

session DaemonToDb {
  client: [send Event, receive Ack, end]
  server: [receive Event, send Ack, end]
}

topology ProdSurface {
  nodes: [ContractsAPI, OrdersDaemon, PrimaryDb]
  edges: [
    ContractsAPI -> PrimaryDb : ApiToDb,
    OrdersDaemon -> PrimaryDb : DaemonToDb
  ]
}
'''

    def test_endpoint_daemon_resource_compose_into_topology(self):
        ir = _compile(self._SRC)
        # All five entities in the IR.
        assert len(ir.endpoints) == 1
        assert len(ir.daemons) == 1
        assert len(ir.resources) == 1
        assert len(ir.sessions) == 2
        assert len(ir.topologies) == 1

        topo = ir.topologies[0]
        # The topology connects the endpoint and the daemon to the same
        # resource through two distinct typed sessions.
        edges_by_target = {(e.source, e.target): e.session_ref for e in topo.edges}
        assert edges_by_target[("ContractsAPI", "PrimaryDb")] == "ApiToDb"
        assert edges_by_target[("OrdersDaemon", "PrimaryDb")] == "DaemonToDb"

    def test_composition_is_deadlock_free(self):
        """No cycles, no duality violations → type-check passes cleanly."""
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.type_checker import TypeChecker
        tree = Parser(Lexer(self._SRC).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == []


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE IMMUNE SYSTEM — Fase 5 IR lowering
# ═══════════════════════════════════════════════════════════════════


from axon.compiler.ir_nodes import IRHeal, IRImmune, IRReflex


class TestImmuneSystemIR:

    _SRC = '''
shield S { scan: [prompt_injection] on_breach: quarantine severity: medium }
immune Vigil {
  watch: [Traffic, Queries]
  sensitivity: 0.9
  baseline: learned
  window: 200
  scope: tenant
  tau: 300s
  decay: exponential
}
reflex Drop {
  trigger: Vigil
  on_level: doubt
  action: drop
  scope: tenant
  sla: 1ms
}
heal Patch {
  source: Vigil
  on_level: doubt
  mode: human_in_loop
  scope: tenant
  review_sla: 24h
  shield: S
  max_patches: 3
}
'''

    def test_immune_lowered(self):
        ir = _compile(self._SRC)
        assert len(ir.immunes) == 1
        imm = ir.immunes[0]
        assert isinstance(imm, IRImmune)
        assert imm.name == "Vigil"
        assert imm.watch == ("Traffic", "Queries")
        assert imm.sensitivity == 0.9
        assert imm.window == 200
        assert imm.scope == "tenant"
        assert imm.decay == "exponential"

    def test_reflex_lowered(self):
        ir = _compile(self._SRC)
        assert len(ir.reflexes) == 1
        r = ir.reflexes[0]
        assert isinstance(r, IRReflex)
        assert r.trigger == "Vigil"
        assert r.on_level == "doubt"
        assert r.action == "drop"

    def test_heal_lowered(self):
        ir = _compile(self._SRC)
        assert len(ir.heals) == 1
        h = ir.heals[0]
        assert isinstance(h, IRHeal)
        assert h.source == "Vigil"
        assert h.mode == "human_in_loop"
        assert h.shield_ref == "S"
        assert h.max_patches == 3

    def test_immune_system_serializes(self):
        ir = _compile(self._SRC)
        d = ir.to_dict()
        assert len(d["immunes"]) == 1
        assert len(d["reflexes"]) == 1
        assert len(d["heals"]) == 1
        assert d["immunes"][0]["node_type"] == "immune"
        assert d["reflexes"][0]["node_type"] == "reflex"
        assert d["heals"][0]["node_type"] == "heal"


# ────────────────────────────────────────────────────────────────────
# Mobile Typed Channels — Fase 13.c
# (paper_mobile_channels.md §3 + §4 — IRChannel / IREmit / IRPublish /
#  IRDiscover; π-calc structurally embedded in containing flow/listener)
# ────────────────────────────────────────────────────────────────────


class TestChannelIR:
    """IR generator lowers Channel declarations to IRChannel nodes."""

    def test_channel_lowered_with_all_fields(self):
        from axon.compiler.ir_nodes import IRChannel
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [pii_leak] }
channel C {
  message: Order
  qos: at_least_once
  lifetime: affine
  persistence: ephemeral
  shield: Gate
}
''')
        assert len(ir.channels) == 1
        ch = ir.channels[0]
        assert isinstance(ch, IRChannel)
        assert ch.name == "C"
        assert ch.message == "Order"
        assert ch.qos == "at_least_once"
        assert ch.lifetime == "affine"
        assert ch.persistence == "ephemeral"
        assert ch.shield_ref == "Gate"

    def test_channel_defaults_match_paper_d1(self):
        ir = _compile('''
type Order { id: String }
channel C { message: Order }
''')
        ch = ir.channels[0]
        assert ch.qos == "at_least_once"
        assert ch.lifetime == "affine"
        assert ch.persistence == "ephemeral"
        assert ch.shield_ref == ""

    def test_channel_second_order_message_preserved(self):
        """Channel<Order> is preserved verbatim in IR for runtime resolution."""
        ir = _compile('''
type Order { id: String }
channel C1 { message: Order }
channel C2 { message: Channel<Order> }
channel C3 { message: Channel<Channel<Order>> }
''')
        names_to_msgs = {c.name: c.message for c in ir.channels}
        assert names_to_msgs == {
            "C1": "Order",
            "C2": "Channel<Order>",
            "C3": "Channel<Channel<Order>>",
        }

    def test_channel_persistent_axonstore_lowered(self):
        ir = _compile('''
type Order { id: String }
channel C { message: Order persistence: persistent_axonstore }
''')
        assert ir.channels[0].persistence == "persistent_axonstore"

    def test_channel_not_in_intention_tree(self):
        """Channels are declarative; only manifest/observe enter the Free Monad tree."""
        ir = _compile('''
type Order { id: String }
channel C { message: Order }
''')
        # No manifest/observe → tree stays None.
        assert ir.intention_tree is None

    def test_channel_serializes_to_dict(self):
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [pii_leak] }
channel C { message: Order shield: Gate }
''')
        d = ir.to_dict()
        assert len(d["channels"]) == 1
        ch_d = d["channels"][0]
        assert ch_d["node_type"] == "channel"
        assert ch_d["name"] == "C"
        assert ch_d["message"] == "Order"
        assert ch_d["shield_ref"] == "Gate"


class TestEmitIR:
    """IR generator lowers EmitStatement → IREmit (Chan-Output / Chan-Mobility)."""

    def test_emit_scalar_payload_value_is_channel_false(self):
        from axon.compiler.ir_nodes import IREmit
        ir = _compile('''
type Order { id: String }
channel Out { message: Order }
flow f() -> O { emit Out(payload) }
''')
        emit = ir.flows[0].steps[0]
        assert isinstance(emit, IREmit)
        assert emit.channel_ref == "Out"
        assert emit.value_ref == "payload"
        assert emit.value_is_channel is False

    def test_emit_mobility_value_is_channel_true(self):
        """Emit a channel-as-value — value_is_channel resolves at lowering."""
        from axon.compiler.ir_nodes import IREmit
        ir = _compile('''
type Order { id: String }
channel Inner { message: Order }
channel Outer { message: Channel<Order> }
flow f() -> O { emit Outer(Inner) }
''')
        emit = ir.flows[0].steps[0]
        assert isinstance(emit, IREmit)
        assert emit.channel_ref == "Outer"
        assert emit.value_ref == "Inner"
        assert emit.value_is_channel is True

    def test_emit_serializes_to_dict(self):
        ir = _compile('''
type Order { id: String }
channel Out { message: Order }
flow f() -> O { emit Out(payload) }
''')
        d = ir.to_dict()
        emit_d = d["flows"][0]["steps"][0]
        assert emit_d["node_type"] == "emit"
        assert emit_d["channel_ref"] == "Out"
        assert emit_d["value_ref"] == "payload"
        assert emit_d["value_is_channel"] is False


class TestPublishIR:
    """IR generator lowers PublishStatement → IRPublish (Publish-Ext)."""

    def test_publish_lowered(self):
        from axon.compiler.ir_nodes import IRPublish
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [pii_leak] }
channel C { message: Order shield: Gate }
flow f() -> Cap { publish C within Gate }
''')
        pub = ir.flows[0].steps[0]
        assert isinstance(pub, IRPublish)
        assert pub.channel_ref == "C"
        assert pub.shield_ref == "Gate"

    def test_publish_serializes_to_dict(self):
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [] }
channel C { message: Order shield: Gate }
flow f() -> Cap { publish C within Gate }
''')
        d = ir.to_dict()
        pub_d = d["flows"][0]["steps"][0]
        assert pub_d["node_type"] == "publish"
        assert pub_d["channel_ref"] == "C"
        assert pub_d["shield_ref"] == "Gate"


class TestDiscoverIR:
    """IR generator lowers DiscoverStatement → IRDiscover (dual of publish)."""

    def test_discover_lowered(self):
        from axon.compiler.ir_nodes import IRDiscover
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [] }
channel C { message: Order shield: Gate }
flow f() -> O { discover C as ch }
''')
        disc = ir.flows[0].steps[0]
        assert isinstance(disc, IRDiscover)
        assert disc.capability_ref == "C"
        assert disc.alias == "ch"

    def test_discover_serializes_to_dict(self):
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [] }
channel C { message: Order shield: Gate }
flow f() -> O { discover C as ch }
''')
        d = ir.to_dict()
        disc_d = d["flows"][0]["steps"][0]
        assert disc_d["node_type"] == "discover"
        assert disc_d["capability_ref"] == "C"
        assert disc_d["alias"] == "ch"


class TestListenIRDualMode:
    """IRListen now carries channel_is_ref for dual-mode dispatch (D4)."""

    def test_listen_typed_ref_carries_flag(self):
        from axon.compiler.ir_nodes import IRListen
        ir = _compile('''
type Order { id: String }
channel C { message: Order }
daemon D() {
  goal: "x"
  listen C as ev { step S { ask: "p" } }
}
''')
        lis = ir.daemons[0].listeners[0]
        assert isinstance(lis, IRListen)
        assert lis.channel_topic == "C"
        assert lis.channel_is_ref is True

    def test_listen_string_topic_legacy_flag_false(self):
        from axon.compiler.ir_nodes import IRListen
        ir = _compile('''
daemon D() {
  goal: "x"
  listen "topic.x" as ev { step S { ask: "p" } }
}
''')
        lis = ir.daemons[0].listeners[0]
        assert isinstance(lis, IRListen)
        assert lis.channel_topic == "topic.x"
        assert lis.channel_is_ref is False


class TestChannelIRIntegration:
    """End-to-end paper §9 lowering — all four IR shapes coexist."""

    def test_paper_example_lowers_completely(self):
        ir = _compile('''
type Order { id: String }
shield PublicBroker { scan: [pii_leak] }

channel OrdersCreated {
  message: Order
  qos: at_least_once
  lifetime: affine
  persistence: ephemeral
  shield: PublicBroker
}

channel BrokerHandoff {
  message: Channel<Order>
  qos: exactly_once
  lifetime: affine
  persistence: persistent_axonstore
}

daemon OrderConsumer() {
  goal: "consume"
  listen OrdersCreated as order_event {
    step S { ask: "process" }
  }
}

flow hand_off() -> Cap {
  emit BrokerHandoff(OrdersCreated)
  publish OrdersCreated within PublicBroker
}
''')
        # Channel declarations
        names_to_msgs = {c.name: c.message for c in ir.channels}
        assert names_to_msgs == {
            "OrdersCreated": "Order",
            "BrokerHandoff": "Channel<Order>",
        }
        # Daemon listener typed ref
        listener = ir.daemons[0].listeners[0]
        assert listener.channel_topic == "OrdersCreated"
        assert listener.channel_is_ref is True
        # Flow body — emit (mobility) + publish
        flow_steps = [s.node_type for s in ir.flows[0].steps]
        assert flow_steps == ["emit", "publish"]
        emit, publish = ir.flows[0].steps
        assert emit.value_is_channel is True   # OrdersCreated is a channel
        assert emit.channel_ref == "BrokerHandoff"
        assert publish.shield_ref == "PublicBroker"

    def test_paper_example_serializes_completely(self):
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [] }
channel C { message: Order shield: Gate }
flow f() -> Cap {
  emit C(payload)
  publish C within Gate
  discover C as alias
}
''')
        d = ir.to_dict()
        # All four IR shapes serialize with correct node_type
        assert d["channels"][0]["node_type"] == "channel"
        flow_steps_types = [s["node_type"] for s in d["flows"][0]["steps"]]
        assert flow_steps_types == ["emit", "publish", "discover"]

    def test_emit_inside_listen_lowered(self):
        """Embedded reductions: emit/publish/discover inside a listener body."""
        ir = _compile('''
type Order { id: String }
shield Gate { scan: [] }
channel In { message: Order }
channel Out { message: Order shield: Gate }
daemon D() {
  goal: "x"
  listen In as ev {
    emit Out(ev)
    publish Out within Gate
  }
}
''')
        lis = ir.daemons[0].listeners[0]
        child_types = [c.node_type for c in lis.children]
        assert child_types == ["emit", "publish"]
