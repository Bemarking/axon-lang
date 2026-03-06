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
