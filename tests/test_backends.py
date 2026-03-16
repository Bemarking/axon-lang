"""
AXON Backends — Unit Tests
============================
Verifies backend prompt compilation for both Anthropic and Gemini.
Tests cover: system prompt construction, step compilation, tool spec
formatting, anchor enforcement, and full program compilation.
"""

import pytest

from axon.compiler.ir_nodes import (
    IRAnchor,
    IRContext,
    IRFlow,
    IRIntent,
    IRPersona,
    IRProbe,
    IRProgram,
    IRReason,
    IRRun,
    IRStep,
    IRToolSpec,
    IRUseTool,
    IRWeave,
)
from axon.backends.base_backend import (
    BaseBackend,
    CompilationContext,
    CompiledStep,
    CompiledProgram,
    CompiledExecutionUnit,
)
from axon.backends.anthropic_backend import AnthropicBackend
from axon.backends.gemini_backend import GeminiBackend


# ═══════════════════════════════════════════════════════════════════
#  FIXTURES — IR node builders
# ═══════════════════════════════════════════════════════════════════


def _persona(**kw) -> IRPersona:
    defaults = dict(
        name="LegalExpert",
        domain=("contract law", "IP"),
        tone="precise",
        confidence_threshold=0.85,
        cite_sources=True,
        refuse_if=("medical advice",),
        language="en",
        description="Expert in legal analysis",
    )
    defaults.update(kw)
    return IRPersona(**defaults)


def _context(**kw) -> IRContext:
    defaults = dict(
        name="LegalSession",
        memory_scope="session",
        language="es",
        depth="deep",
        max_tokens=4000,
        temperature=0.3,
        cite_sources=True,
    )
    defaults.update(kw)
    return IRContext(**defaults)


def _anchor(**kw) -> IRAnchor:
    defaults = dict(
        name="NoHallucination",
        require="factual accuracy",
        reject=("speculation", "guessing"),
        enforce="cite sources",
        confidence_floor=0.9,
        unknown_response="I don't have sufficient information.",
        on_violation="raise",
        on_violation_target="HallucinationError",
    )
    defaults.update(kw)
    return IRAnchor(**defaults)


def _tool(**kw) -> IRToolSpec:
    defaults = dict(
        name="WebSearch", provider="brave",
        max_results=5, timeout="10s",
    )
    defaults.update(kw)
    return IRToolSpec(**defaults)


def _step(**kw) -> IRStep:
    defaults = dict(
        name="Analyze", given="document",
        ask="Analyze the document", output_type="Analysis",
    )
    defaults.update(kw)
    return IRStep(**defaults)


def _flow(**kw) -> IRFlow:
    defaults = dict(
        name="AnalyzeContract",
        steps=(_step(),),
    )
    defaults.update(kw)
    return IRFlow(**defaults)


def _run(**kw) -> IRRun:
    persona = _persona()
    context = _context()
    anchor = _anchor()
    flow = _flow()
    defaults = dict(
        flow_name="AnalyzeContract",
        persona_name="LegalExpert",
        context_name="LegalSession",
        anchor_names=("NoHallucination",),
        arguments=("doc.pdf",),
        resolved_flow=flow,
        resolved_persona=persona,
        resolved_context=context,
        resolved_anchors=(anchor,),
        effort="high",
        output_to="report.json",
    )
    defaults.update(kw)
    return IRRun(**defaults)


def _program(**kw) -> IRProgram:
    defaults = dict(
        personas=(_persona(),),
        contexts=(_context(),),
        anchors=(_anchor(),),
        tools=(_tool(),),
        flows=(_flow(),),
        runs=(_run(),),
    )
    defaults.update(kw)
    return IRProgram(**defaults)


def _ctx(**kw) -> CompilationContext:
    """Build a CompilationContext with tool lookup."""
    tool = _tool()
    defaults = dict(
        persona=_persona(),
        context=_context(),
        anchors=[_anchor()],
        tools={tool.name: tool},
        flow=_flow(),
        effort="high",
    )
    defaults.update(kw)
    return CompilationContext(**defaults)


# ═══════════════════════════════════════════════════════════════════
#  OUTPUT CONTAINERS
# ═══════════════════════════════════════════════════════════════════


class TestCompiledStep:
    """CompiledStep serialization."""

    def test_to_dict_basic(self):
        cs = CompiledStep(step_name="s1", user_prompt="Do stuff")
        d = cs.to_dict()
        assert d["step_name"] == "s1"
        assert d["user_prompt"] == "Do stuff"

    def test_to_dict_with_tools(self):
        cs = CompiledStep(
            step_name="search",
            user_prompt="Search",
            tool_declarations=[{"name": "WebSearch"}],
        )
        d = cs.to_dict()
        assert "tool_declarations" in d
        assert len(d["tool_declarations"]) == 1

    def test_to_dict_omits_empty_tools(self):
        cs = CompiledStep(step_name="s1", user_prompt="Do")
        d = cs.to_dict()
        assert "tool_declarations" not in d

    def test_to_dict_with_schema(self):
        cs = CompiledStep(
            step_name="probe",
            user_prompt="Extract",
            output_schema={"type": "object"},
        )
        d = cs.to_dict()
        assert "output_schema" in d


class TestCompiledExecutionUnit:
    """Execution unit serialization."""

    def test_to_dict_basic(self):
        unit = CompiledExecutionUnit(
            flow_name="Analyze",
            system_prompt="You are Expert.",
            steps=[CompiledStep(step_name="s1", user_prompt="Do")],
            effort="high",
        )
        d = unit.to_dict()
        assert d["flow_name"] == "Analyze"
        assert d["effort"] == "high"
        assert len(d["steps"]) == 1

    def test_to_dict_includes_anchor_instructions(self):
        unit = CompiledExecutionUnit(
            flow_name="F",
            system_prompt="SP",
            anchor_instructions=["Rule 1", "Rule 2"],
        )
        d = unit.to_dict()
        assert len(d["anchor_instructions"]) == 2


class TestCompiledProgram:
    """Program-level compilation output."""

    def test_to_dict(self):
        prog = CompiledProgram(
            backend_name="test",
            execution_units=[
                CompiledExecutionUnit(flow_name="F", system_prompt="SP"),
            ],
        )
        d = prog.to_dict()
        assert d["backend_name"] == "test"
        assert len(d["execution_units"]) == 1


# ═══════════════════════════════════════════════════════════════════
#  BASE BACKEND — Anchor Instruction (Default Implementation)
# ═══════════════════════════════════════════════════════════════════


class TestBaseBackendAnchorInstruction:
    """Default compile_anchor_instruction on the abstract class."""

    def _make_backend(self):
        """Creates a minimal concrete backend for testing base methods."""
        return AnthropicBackend()  # Use concrete subclass to test inherited

    def test_anchor_instruction_includes_name(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(_anchor())
        assert "[CONSTRAINT: NoHallucination]" in result

    def test_anchor_instruction_require(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(require="source citation")
        )
        assert "REQUIRE: source citation" in result

    def test_anchor_instruction_reject(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(reject=("speculation", "opinion"))
        )
        assert "REJECT: speculation, opinion" in result

    def test_anchor_instruction_enforce(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(enforce="no hallucination allowed")
        )
        assert "ENFORCE: no hallucination allowed" in result

    def test_anchor_instruction_confidence_floor(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(confidence_floor=0.75)
        )
        assert "CONFIDENCE FLOOR: 0.75" in result

    def test_anchor_instruction_on_violation(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(on_violation="raise", on_violation_target="SafetyError")
        )
        assert "ON VIOLATION: raise SafetyError" in result

    def test_anchor_instruction_unknown_response(self):
        backend = self._make_backend()
        result = backend.compile_anchor_instruction(
            _anchor(unknown_response="I'm not sure.")
        )
        assert "I'm not sure." in result


# ═══════════════════════════════════════════════════════════════════
#  ANTHROPIC BACKEND
# ═══════════════════════════════════════════════════════════════════


class TestAnthropicBackendMeta:
    """Backend identity and interface."""

    def test_name(self):
        assert AnthropicBackend().name == "anthropic"

    def test_is_base_backend(self):
        assert isinstance(AnthropicBackend(), BaseBackend)


class TestAnthropicSystemPrompt:
    """System prompt compilation for Claude."""

    def test_persona_block(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(_persona(), None, [])
        assert "You are LegalExpert." in prompt
        assert "contract law, IP" in prompt
        assert "Communication tone: precise." in prompt
        assert "Respond in: en." in prompt
        assert "85%" in prompt
        assert "Always cite your sources." in prompt
        assert "medical advice" in prompt

    def test_persona_description(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            _persona(description="A world-renowned legal mind"), None, [],
        )
        assert "world-renowned" in prompt

    def test_context_block(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(None, _context(), [])
        assert "[SESSION CONFIGURATION]" in prompt
        assert "thorough, detailed" in prompt  # deep depth
        assert "es" in prompt
        assert "4000" in prompt
        assert "Citation required: yes" in prompt

    def test_context_depth_shallow(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            None, _context(depth="shallow"), [],
        )
        assert "concise" in prompt

    def test_context_depth_exhaustive(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            None, _context(depth="exhaustive"), [],
        )
        assert "exhaustive" in prompt

    def test_context_depth_custom(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            None, _context(depth="custom123"), [],
        )
        assert "custom123" in prompt

    def test_anchor_block_hard_constraints(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            None, None, [_anchor()],
        )
        assert "HARD CONSTRAINTS" in prompt
        assert "NON-NEGOTIABLE" in prompt
        assert "CONSTRAINT 1: NoHallucination" in prompt
        assert "You MUST: factual accuracy" in prompt
        assert "You MUST NOT: speculation, guessing" in prompt
        assert "ENFORCE: cite sources" in prompt
        assert "90%" in prompt
        assert "I don't have sufficient information." in prompt

    def test_multiple_anchors(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            None, None,
            [_anchor(name="A"), _anchor(name="B")],
        )
        assert "CONSTRAINT 1: A" in prompt
        assert "CONSTRAINT 2: B" in prompt

    def test_full_system_prompt(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(
            _persona(), _context(), [_anchor()],
        )
        # Should have all three sections joined
        assert "You are LegalExpert." in prompt
        assert "[SESSION CONFIGURATION]" in prompt
        assert "HARD CONSTRAINTS" in prompt

    def test_empty_system_prompt(self):
        backend = AnthropicBackend()
        prompt = backend.compile_system_prompt(None, None, [])
        assert prompt == ""


class TestAnthropicStepCompilation:
    """Step → prompt compilation for Claude."""

    def test_basic_step(self):
        backend = AnthropicBackend()
        result = backend.compile_step(_step(), _ctx())
        assert isinstance(result, CompiledStep)
        assert result.step_name == "Analyze"
        assert "Given the input: document" in result.user_prompt
        assert "Analyze the document" in result.user_prompt
        assert "Analysis" in result.user_prompt

    def test_step_with_confidence(self):
        backend = AnthropicBackend()
        step = _step(confidence_floor=0.92)
        result = backend.compile_step(step, _ctx())
        assert "92%" in result.user_prompt

    def test_step_with_tool(self):
        backend = AnthropicBackend()
        step = _step(use_tool=IRUseTool(
            tool_name="WebSearch", argument="quantum",
        ))
        result = backend.compile_step(step, _ctx())
        assert "tool 'WebSearch'" in result.user_prompt
        assert "quantum" in result.user_prompt
        assert len(result.tool_declarations) == 1

    def test_step_with_embedded_probe(self):
        backend = AnthropicBackend()
        step = _step(
            ask="",
            probe=IRProbe(target="doc", fields=("parties", "dates")),
        )
        result = backend.compile_step(step, _ctx())
        assert "parties" in result.user_prompt
        assert "dates" in result.user_prompt

    def test_step_with_embedded_reason(self):
        backend = AnthropicBackend()
        step = _step(
            ask="",
            reason=IRReason(
                about="risks", given=("data",),
                show_work=True,
            ),
        )
        result = backend.compile_step(step, _ctx())
        assert "risks" in result.user_prompt
        assert "reasoning" in result.user_prompt.lower()

    def test_step_with_embedded_weave(self):
        backend = AnthropicBackend()
        step = _step(
            ask="",
            weave=IRWeave(
                sources=("analysis", "risk"),
                target="Report",
                priority=("risk", "summary"),
            ),
        )
        result = backend.compile_step(step, _ctx())
        assert "analysis" in result.user_prompt
        assert "Report" in result.user_prompt

    def test_intent_compilation(self):
        backend = AnthropicBackend()
        intent = IRIntent(
            name="Classify",
            given="contract",
            ask="Classify the risk level",
            output_type_name="RiskScore",
            confidence_floor=0.9,
        )
        result = backend.compile_step(intent, _ctx())
        assert result.step_name == "Classify"
        assert "contract" in result.user_prompt
        assert "RiskScore" in result.user_prompt
        assert "90%" in result.user_prompt
        assert result.metadata["ir_node_type"] == "intent"

    def test_intent_with_generic_type(self):
        backend = AnthropicBackend()
        intent = IRIntent(
            name="Extract",
            ask="Extract parties",
            output_type_name="List",
            output_type_generic="Party",
        )
        result = backend.compile_step(intent, _ctx())
        assert "List<Party>" in result.user_prompt

    def test_intent_with_optional_type(self):
        backend = AnthropicBackend()
        intent = IRIntent(
            name="MaybeFind",
            ask="Find it",
            output_type_name="Result",
            output_type_optional=True,
        )
        result = backend.compile_step(intent, _ctx())
        assert "may be null" in result.user_prompt

    def test_probe_compilation(self):
        backend = AnthropicBackend()
        probe = IRProbe(target="document", fields=("name", "date", "amount"))
        result = backend.compile_step(probe, _ctx())
        assert result.step_name == "probe_document"
        assert "name, date, amount" in result.user_prompt
        assert result.output_schema is not None
        assert "name" in result.output_schema["properties"]
        assert result.metadata["ir_node_type"] == "probe"

    def test_reason_compilation(self):
        backend = AnthropicBackend()
        reason = IRReason(
            name="Evaluate",
            about="risk exposure",
            given=("parties", "clauses"),
            depth=3,
            show_work=True,
            chain_of_thought=True,
            ask="What risks exist?",
            output_type="RiskReport",
        )
        result = backend.compile_step(reason, _ctx())
        assert "risk exposure" in result.user_prompt
        assert "parties, clauses" in result.user_prompt
        assert "3 levels" in result.user_prompt
        assert "chain of thought" in result.user_prompt.lower()
        assert "RiskReport" in result.user_prompt
        assert result.metadata["depth"] == 3
        assert result.metadata["show_work"] is True

    def test_reason_minimal(self):
        backend = AnthropicBackend()
        reason = IRReason(about="topic", depth=1)
        result = backend.compile_step(reason, _ctx())
        assert "topic" in result.user_prompt
        # depth=1 should NOT produce multi-level instruction
        assert "levels" not in result.user_prompt

    def test_weave_compilation(self):
        backend = AnthropicBackend()
        weave = IRWeave(
            sources=("analysis", "risk"),
            target="FinalReport",
            format_type="markdown",
            priority=("risk", "compliance"),
            style="formal",
        )
        result = backend.compile_step(weave, _ctx())
        assert "analysis, risk" in result.user_prompt
        assert "FinalReport" in result.user_prompt
        assert "markdown" in result.user_prompt
        assert "risk → compliance" in result.user_prompt
        assert "formal" in result.user_prompt.lower()

    def test_fallback_for_unknown_node(self):
        backend = AnthropicBackend()

        class FakeIRNode:
            node_type = "fake_node"

        result = backend.compile_step(FakeIRNode(), _ctx())  # type: ignore
        assert "fake_node" in result.user_prompt


class TestAnthropicToolSpec:
    """Tool spec → Claude native format."""

    def test_basic_tool(self):
        backend = AnthropicBackend()
        spec = backend.compile_tool_spec(_tool())
        assert spec["name"] == "WebSearch"
        assert "brave" in spec["description"]
        assert spec["input_schema"]["type"] == "object"
        assert "query" in spec["input_schema"]["properties"]
        assert "query" in spec["input_schema"]["required"]

    def test_tool_with_max_results(self):
        backend = AnthropicBackend()
        spec = backend.compile_tool_spec(_tool(max_results=10))
        assert "max_results" in spec["input_schema"]["properties"]
        assert spec["input_schema"]["properties"]["max_results"]["default"] == 10

    def test_tool_with_timeout(self):
        backend = AnthropicBackend()
        spec = backend.compile_tool_spec(_tool(timeout="30s"))
        assert "30s" in spec["description"]

    def test_tool_without_optional_fields(self):
        backend = AnthropicBackend()
        spec = backend.compile_tool_spec(IRToolSpec(name="Minimal"))
        assert spec["name"] == "Minimal"
        assert "max_results" not in spec["input_schema"]["properties"]


# ═══════════════════════════════════════════════════════════════════
#  GEMINI BACKEND
# ═══════════════════════════════════════════════════════════════════


class TestGeminiBackendMeta:
    """Backend identity and interface."""

    def test_name(self):
        assert GeminiBackend().name == "gemini"

    def test_is_base_backend(self):
        assert isinstance(GeminiBackend(), BaseBackend)


class TestGeminiSystemPrompt:
    """System instruction compilation for Gemini."""

    def test_persona_block(self):
        backend = GeminiBackend()
        prompt = backend.compile_system_prompt(_persona(), None, [])
        assert "Your identity is LegalExpert." in prompt
        assert "contract law, IP" in prompt
        assert "Tone of communication: precise." in prompt
        assert "Language for all responses: en." in prompt
        assert "85%" in prompt
        assert "Cite sources" in prompt
        assert "medical advice" in prompt

    def test_context_block(self):
        backend = GeminiBackend()
        prompt = backend.compile_system_prompt(None, _context(), [])
        assert "## Session Parameters" in prompt
        assert "in-depth" in prompt  # deep depth
        assert "es" in prompt
        assert "4000" in prompt
        assert "Citations: Required" in prompt

    def test_context_depth_variants(self):
        backend = GeminiBackend()
        for depth, expected in [
            ("shallow", "brief"),
            ("standard", "clear"),
            ("deep", "in-depth"),
            ("exhaustive", "thorough"),
        ]:
            prompt = backend.compile_system_prompt(
                None, _context(depth=depth), [],
            )
            assert expected in prompt.lower(), f"Failed for depth={depth}"

    def test_anchor_block(self):
        backend = GeminiBackend()
        prompt = backend.compile_system_prompt(None, None, [_anchor()])
        assert "## Mandatory Constraints" in prompt
        assert "### Constraint 1: NoHallucination" in prompt
        assert "**MUST**: factual accuracy" in prompt
        assert "**MUST NOT**: speculation, guessing" in prompt
        assert "**Rule**: cite sources" in prompt
        assert "90%" in prompt
        assert "I don't have sufficient information." in prompt

    def test_empty_system_prompt(self):
        backend = GeminiBackend()
        prompt = backend.compile_system_prompt(None, None, [])
        assert prompt == ""


class TestGeminiStepCompilation:
    """Step → prompt compilation for Gemini."""

    def test_basic_step_uses_markdown(self):
        backend = GeminiBackend()
        result = backend.compile_step(_step(), _ctx())
        assert "**Input:** document" in result.user_prompt
        assert "Analyze the document" in result.user_prompt
        assert "`Analysis`" in result.user_prompt

    def test_step_with_confidence(self):
        backend = GeminiBackend()
        step = _step(confidence_floor=0.88)
        result = backend.compile_step(step, _ctx())
        assert "88%" in result.user_prompt

    def test_step_with_tool_gemini_format(self):
        backend = GeminiBackend()
        step = _step(use_tool=IRUseTool(
            tool_name="WebSearch", argument="test query",
        ))
        result = backend.compile_step(step, _ctx())
        assert "`WebSearch`" in result.user_prompt
        assert "test query" in result.user_prompt

    def test_intent_gemini_format(self):
        backend = GeminiBackend()
        intent = IRIntent(
            name="Classify",
            given="input",
            ask="Classify this",
            output_type_name="Category",
            confidence_floor=0.85,
        )
        result = backend.compile_step(intent, _ctx())
        assert "**Given:** input" in result.user_prompt
        assert "`Category`" in result.user_prompt
        assert "85%" in result.user_prompt

    def test_intent_nullable_gemini(self):
        backend = GeminiBackend()
        intent = IRIntent(
            name="Maybe",
            ask="Find it",
            output_type_name="Result",
            output_type_optional=True,
        )
        result = backend.compile_step(intent, _ctx())
        assert "nullable" in result.user_prompt

    def test_probe_gemini_format(self):
        backend = GeminiBackend()
        probe = IRProbe(target="data", fields=("x", "y"))
        result = backend.compile_step(probe, _ctx())
        assert "x, y" in result.user_prompt
        assert result.output_schema is not None
        # Gemini uses uppercase types
        assert result.output_schema["type"] == "OBJECT"
        assert result.output_schema["properties"]["x"]["type"] == "STRING"

    def test_reason_gemini_format(self):
        backend = GeminiBackend()
        reason = IRReason(
            about="security",
            given=("findings",),
            depth=4,
            show_work=True,
            ask="Assess the risk",
            output_type="RiskReport",
        )
        result = backend.compile_step(reason, _ctx())
        assert "**Topic:** security" in result.user_prompt
        assert "4-level" in result.user_prompt
        assert "step by step" in result.user_prompt.lower()
        assert "`RiskReport`" in result.user_prompt

    def test_weave_gemini_format(self):
        backend = GeminiBackend()
        weave = IRWeave(
            sources=("a", "b"),
            target="Output",
            format_type="json",
            priority=("p1", "p2"),
            style="academic",
        )
        result = backend.compile_step(weave, _ctx())
        assert "**Synthesize**" in result.user_prompt
        assert "a, b" in result.user_prompt
        assert "Output" in result.user_prompt
        assert "json" in result.user_prompt
        assert "p1 → p2" in result.user_prompt
        assert "academic" in result.user_prompt.lower()


class TestGeminiToolSpec:
    """Tool spec → Gemini FunctionDeclaration format."""

    def test_basic_tool(self):
        backend = GeminiBackend()
        spec = backend.compile_tool_spec(_tool())
        assert spec["name"] == "WebSearch"
        assert "brave" in spec["description"]
        # Gemini uses "parameters" not "input_schema"
        assert spec["parameters"]["type"] == "OBJECT"
        assert spec["parameters"]["properties"]["query"]["type"] == "STRING"

    def test_tool_with_max_results_integer_type(self):
        backend = GeminiBackend()
        spec = backend.compile_tool_spec(_tool(max_results=10))
        assert "max_results" in spec["parameters"]["properties"]
        assert spec["parameters"]["properties"]["max_results"]["type"] == "INTEGER"


# ═══════════════════════════════════════════════════════════════════
#  CROSS-BACKEND PARITY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestCrossBackendParity:
    """Both backends produce structurally equivalent output."""

    @pytest.fixture(params=["anthropic", "gemini"])
    def backend(self, request) -> BaseBackend:
        if request.param == "anthropic":
            return AnthropicBackend()
        return GeminiBackend()

    def test_both_produce_compiled_step(self, backend):
        result = backend.compile_step(_step(), _ctx())
        assert isinstance(result, CompiledStep)
        assert result.step_name == "Analyze"
        assert result.user_prompt  # non-empty
        assert result.metadata["ir_node_type"] == "step"

    def test_both_produce_probe_schema(self, backend):
        probe = IRProbe(target="doc", fields=("x",))
        result = backend.compile_step(probe, _ctx())
        assert result.output_schema is not None
        assert "x" in result.output_schema["properties"]

    def test_both_produce_reason_metadata(self, backend):
        reason = IRReason(
            about="topic", depth=3, show_work=True,
        )
        result = backend.compile_step(reason, _ctx())
        assert result.metadata["depth"] == 3
        assert result.metadata["show_work"] is True

    def test_both_produce_tool_spec(self, backend):
        spec = backend.compile_tool_spec(_tool())
        assert spec["name"] == "WebSearch"
        assert isinstance(spec, dict)

    def test_system_prompt_is_string(self, backend):
        prompt = backend.compile_system_prompt(
            _persona(), _context(), [_anchor()],
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ═══════════════════════════════════════════════════════════════════
#  FULL PROGRAM COMPILATION (Integration)
# ═══════════════════════════════════════════════════════════════════


class TestFullProgramCompilation:
    """End-to-end program compilation through both backends."""

    @pytest.fixture(params=["anthropic", "gemini"])
    def backend(self, request) -> BaseBackend:
        if request.param == "anthropic":
            return AnthropicBackend()
        return GeminiBackend()

    def test_compile_program_structure(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        assert isinstance(result, CompiledProgram)
        assert result.backend_name == backend.name
        assert len(result.execution_units) == 1

    def test_execution_unit_has_system_prompt(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        assert unit.system_prompt  # non-empty
        assert unit.flow_name == "AnalyzeContract"
        assert unit.persona_name == "LegalExpert"
        assert unit.effort == "high"

    def test_execution_unit_has_compiled_steps(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        assert len(unit.steps) == 1
        assert unit.steps[0].step_name == "Analyze"
        assert unit.steps[0].user_prompt  # non-empty

    def test_execution_unit_has_tool_declarations(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        assert len(unit.tool_declarations) == 1
        assert unit.tool_declarations[0]["name"] == "WebSearch"

    def test_execution_unit_has_anchor_instructions(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        assert len(unit.anchor_instructions) == 1
        assert "NoHallucination" in unit.anchor_instructions[0]

    def test_program_serialization(self, backend):
        ir = _program()
        result = backend.compile_program(ir)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["backend_name"] == backend.name
        assert len(d["execution_units"]) == 1

    def test_program_without_runs(self, backend):
        ir = IRProgram()  # empty program
        result = backend.compile_program(ir)
        assert len(result.execution_units) == 0

    def test_program_without_persona(self, backend):
        run = _run(
            resolved_persona=None,
            persona_name="",
        )
        ir = IRProgram(
            flows=(_flow(),), runs=(run,), tools=(_tool(),),
        )
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        # System prompt should still work, just no persona block
        assert isinstance(unit.system_prompt, str)

    def test_multiple_runs(self, backend):
        flow_a = IRFlow(name="FlowA", steps=(_step(name="A1"),))
        flow_b = IRFlow(name="FlowB", steps=(_step(name="B1"),))
        run_a = _run(flow_name="FlowA", resolved_flow=flow_a)
        run_b = _run(flow_name="FlowB", resolved_flow=flow_b)
        ir = IRProgram(
            personas=(_persona(),),
            contexts=(_context(),),
            anchors=(_anchor(),),
            tools=(_tool(),),
            flows=(flow_a, flow_b),
            runs=(run_a, run_b),
        )
        result = backend.compile_program(ir)
        assert len(result.execution_units) == 2
        assert result.execution_units[0].flow_name == "FlowA"
        assert result.execution_units[1].flow_name == "FlowB"


# ═══════════════════════════════════════════════════════════════════
#  BACKEND-SPECIFIC DIFFERENTIATION
# ═══════════════════════════════════════════════════════════════════


class TestBackendDifferentiation:
    """Verify that backends produce provider-specific formatting."""

    def test_anthropic_uses_you_are_framing(self):
        prompt = AnthropicBackend().compile_system_prompt(_persona(), None, [])
        assert "You are LegalExpert." in prompt

    def test_gemini_uses_identity_framing(self):
        prompt = GeminiBackend().compile_system_prompt(_persona(), None, [])
        assert "Your identity is LegalExpert." in prompt

    def test_anthropic_uses_session_config_header(self):
        prompt = AnthropicBackend().compile_system_prompt(None, _context(), [])
        assert "[SESSION CONFIGURATION]" in prompt

    def test_gemini_uses_markdown_header(self):
        prompt = GeminiBackend().compile_system_prompt(None, _context(), [])
        assert "## Session Parameters" in prompt

    def test_anthropic_uses_hard_constraints_header(self):
        prompt = AnthropicBackend().compile_system_prompt(None, None, [_anchor()])
        assert "HARD CONSTRAINTS" in prompt

    def test_gemini_uses_mandatory_constraints_header(self):
        prompt = GeminiBackend().compile_system_prompt(None, None, [_anchor()])
        assert "## Mandatory Constraints" in prompt

    def test_anthropic_tool_uses_input_schema(self):
        spec = AnthropicBackend().compile_tool_spec(_tool())
        assert "input_schema" in spec
        assert spec["input_schema"]["properties"]["query"]["type"] == "string"

    def test_gemini_tool_uses_parameters(self):
        spec = GeminiBackend().compile_tool_spec(_tool())
        assert "parameters" in spec
        assert spec["parameters"]["properties"]["query"]["type"] == "STRING"

    def test_anthropic_probe_schema_lowercase(self):
        result = AnthropicBackend().compile_step(
            IRProbe(target="x", fields=("f",)), _ctx(),
        )
        assert result.output_schema["type"] == "object"

    def test_gemini_probe_schema_uppercase(self):
        result = GeminiBackend().compile_step(
            IRProbe(target="x", fields=("f",)), _ctx(),
        )
        assert result.output_schema["type"] == "OBJECT"


# ═══════════════════════════════════════════════════════════════════
#  AGENT BDI SYSTEM PROMPT COMPILATION — Phase 4
# ═══════════════════════════════════════════════════════════════════


class TestAnthropicAgentSystemPrompt:
    """Claude-optimized agent BDI system prompt compilation."""

    def _build(self, **kw) -> str:
        defaults = dict(
            agent_name="SalesAgent",
            goal="Qualify leads and schedule meetings",
            strategy="react",
            tools=["WebSearch", "CRMSync"],
            epistemic_state="doubt",
            iteration=0,
            max_iterations=10,
        )
        defaults.update(kw)
        return AnthropicBackend().compile_agent_system_prompt(**defaults)

    def test_agent_identity_framing(self):
        prompt = self._build()
        assert "You are Agent SalesAgent" in prompt
        assert "BDI" in prompt

    def test_goal_inclusion(self):
        prompt = self._build(goal="Close the deal")
        assert "Close the deal" in prompt

    def test_epistemic_state_doubt(self):
        prompt = self._build(epistemic_state="doubt")
        assert "[EPISTEMIC STATE]" in prompt
        assert "doubt" in prompt
        assert "LOW CONFIDENCE" in prompt

    def test_epistemic_state_know(self):
        prompt = self._build(epistemic_state="know")
        assert "TERMINAL" in prompt

    def test_react_strategy(self):
        prompt = self._build(strategy="react")
        assert "[STRATEGY: ReAct]" in prompt
        assert "THOUGHT" in prompt
        assert "ACTION" in prompt
        assert "OBSERVATION" in prompt

    def test_reflexion_strategy(self):
        prompt = self._build(strategy="reflexion")
        assert "[STRATEGY: Reflexion]" in prompt
        assert "CRITIQUE" in prompt
        assert "REVISION" in prompt

    def test_plan_and_execute_strategy(self):
        prompt = self._build(strategy="plan_and_execute")
        assert "[STRATEGY: Plan-and-Execute]" in prompt
        assert "PHASE 1" in prompt
        assert "PHASE 2" in prompt

    def test_custom_strategy_fallback(self):
        prompt = self._build(strategy="tree_of_thought")
        assert "[STRATEGY: tree_of_thought]" in prompt

    def test_tool_listing(self):
        prompt = self._build(tools=["WebSearch", "CRMSync", "Calendar"])
        assert "[AVAILABLE TOOLS]" in prompt
        assert "WebSearch" in prompt
        assert "CRMSync" in prompt
        assert "Calendar" in prompt

    def test_no_tools_omits_section(self):
        prompt = self._build(tools=[])
        assert "[AVAILABLE TOOLS]" not in prompt

    def test_budget_display(self):
        prompt = self._build(iteration=3, max_iterations=10)
        assert "[CONVERGENCE BUDGET]" in prompt
        assert "4 of 10" in prompt
        assert "7" in prompt  # remaining

    def test_budget_final_cycle(self):
        prompt = self._build(iteration=9, max_iterations=10)
        assert "10 of 10" in prompt
        assert "Remaining cycles: 1" in prompt


class TestGeminiAgentSystemPrompt:
    """Gemini-optimized agent BDI system prompt compilation."""

    def _build(self, **kw) -> str:
        defaults = dict(
            agent_name="ResearchAgent",
            goal="Gather comprehensive market intelligence",
            strategy="react",
            tools=["WebSearch"],
            epistemic_state="speculate",
            iteration=2,
            max_iterations=8,
        )
        defaults.update(kw)
        return GeminiBackend().compile_agent_system_prompt(**defaults)

    def test_agent_identity_markdown(self):
        prompt = self._build()
        assert "# Agent: ResearchAgent" in prompt
        assert "Your identity is Agent ResearchAgent" in prompt

    def test_goal_inclusion(self):
        prompt = self._build(goal="Analyze competitor pricing")
        assert "Analyze competitor pricing" in prompt

    def test_epistemic_state_speculate(self):
        prompt = self._build(epistemic_state="speculate")
        assert "## Current Epistemic State" in prompt
        assert "`speculate`" in prompt
        assert "Emerging" in prompt

    def test_epistemic_state_believe(self):
        prompt = self._build(epistemic_state="believe")
        assert "`believe`" in prompt
        assert "Convergent" in prompt

    def test_react_strategy_markdown(self):
        prompt = self._build(strategy="react")
        assert "## Strategy: ReAct" in prompt
        assert "**Thought:**" in prompt
        assert "**Action:**" in prompt
        assert "**Observation:**" in prompt

    def test_reflexion_strategy_markdown(self):
        prompt = self._build(strategy="reflexion")
        assert "## Strategy: Reflexion" in prompt
        assert "**Critique:**" in prompt
        assert "**mandatory**" in prompt

    def test_plan_and_execute_markdown(self):
        prompt = self._build(strategy="plan_and_execute")
        assert "## Strategy: Plan-and-Execute" in prompt
        assert "### Phase 1" in prompt
        assert "### Phase 2" in prompt

    def test_tool_listing_markdown(self):
        prompt = self._build(tools=["WebSearch", "EmailSend"])
        assert "## Available Tools" in prompt
        assert "- `WebSearch`" in prompt
        assert "- `EmailSend`" in prompt

    def test_no_tools_omits_section(self):
        prompt = self._build(tools=[])
        assert "## Available Tools" not in prompt

    def test_budget_table(self):
        prompt = self._build(iteration=2, max_iterations=8)
        assert "## Convergence Budget" in prompt
        assert "3 of 8" in prompt
        assert "6 cycles" in prompt

    def test_budget_uses_table_format(self):
        prompt = self._build()
        assert "| Parameter | Value |" in prompt
        assert "|-----------|-------|" in prompt


class TestBaseBackendAgentToolBinding:
    """Default tool binding resolution (inherited by all backends)."""

    def test_resolves_matching_tools(self):
        backend = AnthropicBackend()
        tools = {"WebSearch": _tool(), "CRM": _tool(name="CRM")}
        result = backend.compile_agent_tool_binding(
            ["WebSearch", "CRM"], tools,
        )
        assert len(result) == 2
        assert result[0]["name"] == "WebSearch"
        assert result[1]["name"] == "CRM"

    def test_skips_missing_tools(self):
        backend = GeminiBackend()
        tools = {"WebSearch": _tool()}
        result = backend.compile_agent_tool_binding(
            ["WebSearch", "NonExistent"], tools,
        )
        assert len(result) == 1
        assert result[0]["name"] == "WebSearch"

    def test_empty_tool_list(self):
        backend = AnthropicBackend()
        result = backend.compile_agent_tool_binding([], {"X": _tool()})
        assert result == []

    def test_empty_registry(self):
        backend = GeminiBackend()
        result = backend.compile_agent_tool_binding(["WebSearch"], {})
        assert result == []


class TestCrossBackendAgentParity:
    """Both backends produce structurally equivalent agent prompts."""

    @pytest.fixture(params=["anthropic", "gemini"])
    def backend(self, request) -> BaseBackend:
        if request.param == "anthropic":
            return AnthropicBackend()
        return GeminiBackend()

    def test_both_produce_string(self, backend):
        prompt = backend.compile_agent_system_prompt(
            agent_name="TestAgent",
            goal="Test goal",
            strategy="react",
            tools=["WebSearch"],
            epistemic_state="doubt",
            iteration=0,
            max_iterations=5,
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_both_include_agent_name(self, backend):
        prompt = backend.compile_agent_system_prompt(
            agent_name="AlphaAgent",
            goal="Do something",
            strategy="react",
            tools=[],
            epistemic_state="doubt",
            iteration=0,
            max_iterations=5,
        )
        assert "AlphaAgent" in prompt

    def test_both_include_goal(self, backend):
        prompt = backend.compile_agent_system_prompt(
            agent_name="A",
            goal="Find the answer to everything",
            strategy="react",
            tools=[],
            epistemic_state="doubt",
            iteration=0,
            max_iterations=5,
        )
        assert "Find the answer to everything" in prompt

    def test_both_include_budget_info(self, backend):
        prompt = backend.compile_agent_system_prompt(
            agent_name="A",
            goal="G",
            strategy="react",
            tools=[],
            epistemic_state="doubt",
            iteration=4,
            max_iterations=10,
        )
        assert "5 of 10" in prompt  # cycle display

    def test_both_handle_all_strategies(self, backend):
        for strategy in ("react", "reflexion", "plan_and_execute", "custom"):
            prompt = backend.compile_agent_system_prompt(
                agent_name="A", goal="G", strategy=strategy,
                tools=[], epistemic_state="doubt",
                iteration=0, max_iterations=5,
            )
            assert strategy in prompt.lower() or strategy.replace("_", "-").lower() in prompt.lower()

    def test_tool_binding_produces_native_format(self, backend):
        tools = {"WebSearch": _tool()}
        result = backend.compile_agent_tool_binding(["WebSearch"], tools)
        assert len(result) == 1
        assert result[0]["name"] == "WebSearch"
        # Anthropic uses input_schema, Gemini uses parameters
        if backend.name == "anthropic":
            assert "input_schema" in result[0]
        else:
            assert "parameters" in result[0]


class TestFullProgramAgentCompilation:
    """IRAgent within a flow compiles correctly through full pipeline."""

    @pytest.fixture(params=["anthropic", "gemini"])
    def backend(self, request) -> BaseBackend:
        if request.param == "anthropic":
            return AnthropicBackend()
        return GeminiBackend()

    def _agent_flow(self):
        """Build a flow containing an IRAgent as one of its steps."""
        from axon.compiler.ir_nodes import IRAgent
        agent = IRAgent(
            name="SalesBot",
            goal="Qualify the lead",
            tools=("WebSearch",),
            max_iterations=5,
            strategy="react",
            on_stuck="forge",
            return_type="SalesOutcome",
            children=(_step(name="Greet"), _step(name="Discover")),
        )
        return IRFlow(name="SalesFlow", steps=(agent,))

    def test_agent_compiled_as_budget_step(self, backend):
        flow = self._agent_flow()
        run = _run(flow_name="SalesFlow", resolved_flow=flow)
        ir = IRProgram(
            personas=(_persona(),), contexts=(_context(),),
            anchors=(_anchor(),), tools=(_tool(),),
            flows=(flow,), runs=(run,),
        )
        result = backend.compile_program(ir)
        unit = result.execution_units[0]
        assert len(unit.steps) == 1
        agent_step = unit.steps[0]
        assert agent_step.step_name == "agent:SalesBot"

    def test_agent_metadata_complete(self, backend):
        flow = self._agent_flow()
        run = _run(flow_name="SalesFlow", resolved_flow=flow)
        ir = IRProgram(
            personas=(_persona(),), contexts=(_context(),),
            anchors=(_anchor(),), tools=(_tool(),),
            flows=(flow,), runs=(run,),
        )
        result = backend.compile_program(ir)
        meta = result.execution_units[0].steps[0].metadata["agent"]
        assert meta["name"] == "SalesBot"
        assert meta["goal"] == "Qualify the lead"
        assert meta["strategy"] == "react"
        assert meta["on_stuck"] == "forge"
        assert meta["max_iterations"] == 5
        assert "WebSearch" in meta["tools"]
        assert len(meta["child_steps"]) == 2

    def test_agent_child_steps_compiled(self, backend):
        flow = self._agent_flow()
        run = _run(flow_name="SalesFlow", resolved_flow=flow)
        ir = IRProgram(
            personas=(_persona(),), contexts=(_context(),),
            anchors=(_anchor(),), tools=(_tool(),),
            flows=(flow,), runs=(run,),
        )
        result = backend.compile_program(ir)
        children = result.execution_units[0].steps[0].metadata["agent"]["child_steps"]
        assert children[0]["step_name"] == "Greet"
        assert children[1]["step_name"] == "Discover"
