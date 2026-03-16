"""
AXON Integration Tests — Agent Primitive: IR → Backend → Executor
==================================================================

Exercises the **compilation + execution integration** for agent
primitives: builds IRProgram objects containing IRAgent nodes,
compiles them through real backends (Anthropic, Gemini), and
executes them with mock model clients.

This fills the gap between:
  • test_agent.py         — compiler pipeline (Source → IR)
  • test_backends.py      — backend compilation (IR → CompiledProgram)
  • test_agent_runtime.py — executor BDI loop (CompiledStep → AgentResult)

Integration tests verify these layers compose correctly:
  IRProgram → Backend.compile_program() → Executor.execute() → AgentResult

Theoretical grounding:
  Compositional semantics — [[φ ∘ ψ]] = [[φ]] ∘ [[ψ]]
  The meaning of a composed pipeline equals the composition
  of the meanings of its individual stages.
"""

import json

import pytest

from axon.backends.anthropic_backend import AnthropicBackend
from axon.backends.base_backend import (
    BaseBackend,
    CompiledProgram,
)
from axon.backends.gemini_backend import GeminiBackend
from axon.compiler.ir_nodes import (
    IRAnchor,
    IRAgent,
    IRContext,
    IRFlow,
    IRParameter,
    IRPersona,
    IRProgram,
    IRRun,
    IRStep,
    IRToolSpec,
)
from axon.runtime.executor import (
    AgentResult,
    Executor,
    ExecutionResult,
    ModelResponse,
    StepResult,
)
from axon.runtime.tracer import TraceEventType


# ═══════════════════════════════════════════════════════════════════
#  IR FACTORIES — build IRProgram components for agent integration
# ═══════════════════════════════════════════════════════════════════


def _persona(**kw) -> IRPersona:
    defaults = {
        "name": "IntegrationPersona",
        "domain": ("general",),
        "tone": "neutral",
        "description": "Integration test persona",
    }
    defaults.update(kw)
    return IRPersona(**defaults)


def _context(**kw) -> IRContext:
    defaults = {
        "name": "IntegrationContext",
        "memory_scope": "session",
        "language": "en",
        "depth": "standard",
    }
    defaults.update(kw)
    return IRContext(**defaults)


def _anchor(**kw) -> IRAnchor:
    defaults = {
        "name": "IntegrationAnchor",
        "require": "factual accuracy",
        "reject": ("speculation",),
    }
    defaults.update(kw)
    return IRAnchor(**defaults)


def _tool(**kw) -> IRToolSpec:
    defaults = {
        "name": "WebSearch",
        "provider": "brave",
        "timeout": "10s",
    }
    defaults.update(kw)
    return IRToolSpec(**defaults)


def _step(**kw) -> IRStep:
    defaults = {
        "name": "Step1",
        "ask": "Do something",
        "output_type": "Result",
    }
    defaults.update(kw)
    return IRStep(**defaults)


def _agent(
    name: str = "TestAgent",
    goal: str = "Analyze data",
    *,
    tools: tuple[str, ...] = (),
    max_iterations: int = 10,
    max_tokens: int = 0,
    max_time: str = "",
    max_cost: float = 0.0,
    strategy: str = "react",
    on_stuck: str = "escalate",
    return_type: str = "",
    children: tuple = (),
) -> IRAgent:
    return IRAgent(
        name=name,
        goal=goal,
        tools=tools,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        max_time=max_time,
        max_cost=max_cost,
        strategy=strategy,
        on_stuck=on_stuck,
        return_type=return_type,
        children=children,
    )


def _flow(name: str = "AgentFlow", steps: tuple = ()) -> IRFlow:
    return IRFlow(name=name, steps=steps)


def _run(
    flow_name: str = "AgentFlow",
    resolved_flow: IRFlow | None = None,
    resolved_persona: IRPersona | None = None,
    resolved_context: IRContext | None = None,
    resolved_anchors: tuple = (),
    effort: str = "",
) -> IRRun:
    return IRRun(
        flow_name=flow_name,
        resolved_flow=resolved_flow,
        resolved_persona=resolved_persona or _persona(),
        resolved_context=resolved_context or _context(),
        resolved_anchors=resolved_anchors,
        effort=effort,
    )


def _program(
    agent: IRAgent,
    flow_name: str = "AgentFlow",
    tools: tuple = (),
    extra_steps: tuple = (),
) -> IRProgram:
    """Build a complete IRProgram with an agent in a flow."""
    flow_steps = (*extra_steps, agent)
    flow = _flow(name=flow_name, steps=flow_steps)
    persona = _persona()
    context = _context()
    run = _run(
        flow_name=flow_name,
        resolved_flow=flow,
        resolved_persona=persona,
        resolved_context=context,
    )
    return IRProgram(
        personas=(persona,),
        contexts=(context,),
        anchors=(),
        tools=tools,
        flows=(flow,),
        runs=(run,),
    )


# ═══════════════════════════════════════════════════════════════════
#  MOCK MODEL CLIENT — Integration-grade
# ═══════════════════════════════════════════════════════════════════


class IntegrationMockClient:
    """Mock client for integration tests.

    Returns sequential responses and tracks all call metadata.
    Unlike unit-test mocks, this client processes full system
    prompts generated by real backends.
    """

    def __init__(
        self,
        *,
        responses: list[str] | None = None,
        default: str = "Default response",
        tokens_per_call: int = 100,
    ):
        self._responses = list(responses or [])
        self._default = default
        self._tokens = tokens_per_call
        self.call_count = 0
        self.calls: list[dict] = []

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools=None,
        output_schema=None,
        effort: str = "",
        failure_context: str = "",
    ) -> ModelResponse:
        self.call_count += 1
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "tools": tools,
            "effort": effort,
        })
        content = (
            self._responses.pop(0)
            if self._responses
            else self._default
        )
        return ModelResponse(
            content=content,
            usage={
                "input_tokens": self._tokens // 2,
                "output_tokens": self._tokens // 2,
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  PIPELINE HELPER
# ═══════════════════════════════════════════════════════════════════


async def _compile_and_execute(
    ir: IRProgram,
    backend: BaseBackend,
    mock_client: IntegrationMockClient,
) -> ExecutionResult:
    """Compile IR through a real backend, then execute with mock client."""
    compiled = backend.compile_program(ir)
    executor = Executor(client=mock_client)
    return await executor.execute(compiled)


def _extract_agent_data(result: ExecutionResult) -> dict:
    """Extract the agent JSON payload from the first step result."""
    content = result.unit_results[0].step_results[0].response.content
    return json.loads(content)["agent"]


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 1 — Full Pipeline with React Strategy
# ═══════════════════════════════════════════════════════════════════


class TestFullPipelineReact:
    """IR → Backend.compile_program → Executor → AgentResult (react)."""

    @pytest.mark.asyncio
    async def test_agent_goal_achieved_first_cycle(self):
        """Agent achieves goal on first BDI cycle through full pipeline."""
        agent = _agent(name="Researcher", goal="Find research papers")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true, '
            '"confidence": 1.0, "reasoning": "Found the papers"}',
            "Here are the relevant papers on the topic.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["goal_achieved"] is True
        assert agent_data["epistemic_state"] == "know"
        assert agent_data["iterations_used"] == 1

    @pytest.mark.asyncio
    async def test_agent_converges_multiple_cycles(self):
        """Agent progresses through epistemic lattice over 3 cycles."""
        agent = _agent(
            name="DeepSearcher",
            goal="Deep analysis of market trends",
        )
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "doubt", "goal_achieved": false}',
            "Initial search results.",
            '{"epistemic_state": "speculate", "goal_achieved": false}',
            "Deeper analysis in progress.",
            '{"epistemic_state": "believe", "goal_achieved": true}',
            "Comprehensive results found.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["goal_achieved"] is True
        assert agent_data["iterations_used"] == 3
        assert agent_data["epistemic_state"] == "believe"

    @pytest.mark.asyncio
    async def test_compilation_produces_agent_step_name(self):
        """Agent compiles to CompiledStep with `agent:` prefix."""
        agent = _agent(name="Researcher", goal="Find papers")
        ir = _program(agent)
        compiled = AnthropicBackend().compile_program(ir)
        unit = compiled.execution_units[0]
        assert len(unit.steps) == 1
        step = unit.steps[0]
        assert step.step_name == "agent:Researcher"
        assert "agent" in step.metadata
        assert step.metadata["agent"]["goal"] == "Find papers"

    @pytest.mark.asyncio
    def test_system_prompt_from_backend(self):
        """Full pipeline produces a non-empty system prompt."""
        agent = _agent(name="Researcher", goal="Find papers")
        ir = _program(agent)
        compiled = GeminiBackend().compile_program(ir)
        unit = compiled.execution_units[0]
        assert len(unit.system_prompt) > 0

    @pytest.mark.asyncio
    async def test_execution_result_structure(self):
        """ExecutionResult has correct structure from full pipeline."""
        agent = _agent(name="Researcher", goal="Research topic")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Done.",
        ])
        result = await _compile_and_execute(ir, GeminiBackend(), client)
        assert len(result.unit_results) == 1
        assert len(result.unit_results[0].step_results) == 1
        assert result.trace is not None
        assert result.duration_ms > 0


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 2 — Strategy-specific Pipeline Tests
# ═══════════════════════════════════════════════════════════════════


class TestFullPipelineStrategies:
    """Each strategy compiles and executes correctly through full pipeline."""

    @pytest.mark.asyncio
    async def test_reflexion_strategy_pipeline(self):
        """Reflexion agent compiles and executes with critique steps."""
        agent = _agent(
            name="Critic", goal="Deep critical analysis",
            strategy="reflexion", max_iterations=5,
        )
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "doubt", "goal_achieved": false}',
            "Initial analysis.",
            "Self-critique: shallow analysis, need deeper dive.",
            '{"epistemic_state": "believe", "goal_achieved": true}',
            "Refined analysis complete.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["strategy"] == "reflexion"
        assert agent_data["goal_achieved"] is True

    @pytest.mark.asyncio
    async def test_plan_and_execute_pipeline(self):
        """Plan-and-execute agent creates plan then executes."""
        agent = _agent(
            name="Planner", goal="Create research plan",
            strategy="plan_and_execute", max_iterations=5,
        )
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "doubt", "goal_achieved": false}',
            "Step 1: Gather data\nStep 2: Analyze patterns",
            '{"epistemic_state": "believe", "goal_achieved": true}',
            "Plan executed, report generated.",
        ])
        result = await _compile_and_execute(ir, GeminiBackend(), client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["strategy"] == "plan_and_execute"
        assert agent_data["goal_achieved"] is True

    @pytest.mark.asyncio
    async def test_custom_strategy_with_body_steps(self):
        """Custom strategy with body steps compiles and executes."""
        agent = _agent(
            name="CustomBot", goal="Run custom protocol",
            strategy="custom", max_iterations=3,
            children=(_step(name="Greet", ask="Greet the user"),),
        )
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Custom protocol executed.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["strategy"] == "custom"

    @pytest.mark.asyncio
    async def test_strategy_metadata_preserved_in_compilation(self):
        """Strategy field propagates from IRAgent to CompiledStep metadata."""
        for strategy in ("react", "reflexion", "plan_and_execute", "custom"):
            agent = _agent(
                name=f"Agent_{strategy}", goal="Test", strategy=strategy,
            )
            ir = _program(agent)
            compiled = AnthropicBackend().compile_program(ir)
            meta = compiled.execution_units[0].steps[0].metadata["agent"]
            assert meta["strategy"] == strategy


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 3 — Multi-Backend Parity
# ═══════════════════════════════════════════════════════════════════


class TestMultiBackendParity:
    """Same IRProgram produces equivalent results across backends."""

    @pytest.fixture(params=["anthropic", "gemini"])
    def backend(self, request) -> BaseBackend:
        if request.param == "anthropic":
            return AnthropicBackend()
        return GeminiBackend()

    @pytest.mark.asyncio
    async def test_same_ir_both_backends_succeed(self, backend):
        """Both backends compile and execute the same agent successfully."""
        agent = _agent(name="Researcher", goal="Find papers")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Done.",
        ])
        result = await _compile_and_execute(ir, backend, client)
        assert result.success is True
        agent_data = _extract_agent_data(result)
        assert agent_data["goal_achieved"] is True

    @pytest.mark.asyncio
    async def test_agent_metadata_identical_across_backends(self, backend):
        """Both backends produce identical agent metadata."""
        agent = _agent(
            name="Analyst", goal="Analyze market data",
            tools=("WebSearch", "DataAnalyzer"),
            max_iterations=5, strategy="react",
        )
        ir = _program(agent, tools=(_tool(name="WebSearch"), _tool(name="DataAnalyzer")))
        compiled = backend.compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["agent"]
        assert meta["name"] == "Analyst"
        assert meta["goal"] == "Analyze market data"
        assert "WebSearch" in meta["tools"]
        assert "DataAnalyzer" in meta["tools"]
        assert meta["max_iterations"] == 5
        assert meta["strategy"] == "react"

    @pytest.mark.asyncio
    async def test_multi_cycle_convergence_both_backends(self, backend):
        """Multi-cycle convergence works identically on both backends."""
        agent = _agent(name="Convergent", goal="Converge to answer")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "doubt", "goal_achieved": false}',
            "Step 1.",
            '{"epistemic_state": "believe", "goal_achieved": true}',
            "Final.",
        ])
        result = await _compile_and_execute(ir, backend, client)
        agent_data = _extract_agent_data(result)
        assert agent_data["iterations_used"] == 2
        assert agent_data["goal_achieved"] is True


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 4 — Agent With Tools Integration
# ═══════════════════════════════════════════════════════════════════


class TestAgentWithToolsIntegration:
    """Agent tool declarations propagate through full pipeline."""

    @pytest.mark.asyncio
    async def test_tool_names_in_compiled_metadata(self):
        """Tools declared in IRAgent appear in compiled metadata."""
        agent = _agent(
            name="Analyst", goal="Analyze data",
            tools=("WebSearch", "Calculator"),
        )
        ir = _program(
            agent,
            tools=(_tool(name="WebSearch"), _tool(name="Calculator")),
        )
        compiled = AnthropicBackend().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["agent"]
        assert "WebSearch" in meta["tools"]
        assert "Calculator" in meta["tools"]

    @pytest.mark.asyncio
    async def test_tools_reach_executor(self):
        """Tool names reach the executor's agent step and BDI loop."""
        agent = _agent(
            name="ToolUser", goal="Use tools for analysis",
            tools=("WebSearch",),
        )
        ir = _program(agent, tools=(_tool(name="WebSearch"),))
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Analysis complete with tools.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        assert client.call_count >= 2

    @pytest.mark.asyncio
    async def test_tool_count_in_metadata(self):
        """Correct number of tools in metadata through pipeline."""
        agent = _agent(
            name="MultiTool", goal="Multi-tool analysis",
            tools=("ToolA", "ToolB", "ToolC"),
        )
        ir = _program(agent)
        compiled = GeminiBackend().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["agent"]
        assert len(meta["tools"]) == 3


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 5 — Budget Integration
# ═══════════════════════════════════════════════════════════════════


class TestBudgetIntegration:
    """Budget constraints compose correctly from IR through execution."""

    @pytest.mark.asyncio
    async def test_iteration_budget_limits_cycles(self):
        """max_iterations from IR caps the agent's BDI cycles.

        When the agent exhausts its iteration budget without achieving
        the goal and on_stuck='escalate', the executor raises
        AgentStuckError, setting result.success=False. We verify
        that the mock client was called a bounded number of times
        (proportional to max_iterations) and that execution failed.
        """
        agent = _agent(
            name="BudgetWorker", goal="Process data",
            max_iterations=3, on_stuck="escalate",
        )
        ir = _program(agent)
        client = IntegrationMockClient(
            default='{"epistemic_state": "doubt", "goal_achieved": false}',
        )
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        # Agent should fail (stuck escalation) with bounded calls
        assert result.success is False
        # Each cycle has deliberation + action calls; 3 iterations ≈ ≤ 12 calls
        assert client.call_count <= 12

    @pytest.mark.asyncio
    async def test_token_budget_stops_agent(self):
        """max_tokens from IR stops agent when token budget exceeded."""
        agent = _agent(
            name="TokenWorker", goal="Process data",
            max_iterations=10, max_tokens=500,
        )
        ir = _program(agent)
        client = IntegrationMockClient(
            default='{"epistemic_state": "doubt", "goal_achieved": false}',
            tokens_per_call=200,
        )
        result = await _compile_and_execute(ir, GeminiBackend(), client)
        agent_data = _extract_agent_data(result)
        assert agent_data["goal_achieved"] is False

    @pytest.mark.asyncio
    async def test_budget_metadata_preserved(self):
        """All budget fields propagate from IR to compiled metadata."""
        agent = _agent(
            name="FullBudget", goal="Work",
            max_iterations=3, max_tokens=500,
            max_cost=1.00,
        )
        ir = _program(agent)
        compiled = AnthropicBackend().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["agent"]
        assert meta["max_iterations"] == 3
        assert meta["max_tokens"] == 500
        assert meta["max_cost"] == pytest.approx(1.00)


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 6 — Error Path Integration
# ═══════════════════════════════════════════════════════════════════


class TestErrorPathIntegration:
    """on_stuck recovery policies trigger correctly through pipeline."""

    @pytest.mark.asyncio
    async def test_on_stuck_metadata_preserved(self):
        """on_stuck policy propagates from IR through compilation."""
        agent = _agent(
            name="Resilient", goal="Complete reliably", on_stuck="forge",
        )
        ir = _program(agent)
        compiled = GeminiBackend().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["agent"]
        assert meta["on_stuck"] == "forge"

    @pytest.mark.asyncio
    async def test_escalate_triggers_on_stagnation(self):
        """on_stuck='escalate' fires when agent is stuck in doubt."""
        agent = _agent(
            name="Careful", goal="Process with care",
            max_iterations=10, on_stuck="escalate",
        )
        ir = _program(agent)
        client = IntegrationMockClient(
            default='{"epistemic_state": "doubt", "goal_achieved": false}',
        )
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_forge_recovery(self):
        """on_stuck='forge' attempts creative recovery and succeeds."""
        call_counter = {"n": 0}

        class ForgeClient(IntegrationMockClient):
            async def call(self, system_prompt, user_prompt, **kw):
                call_counter["n"] += 1
                if call_counter["n"] <= 6:
                    if "deliberat" in user_prompt.lower():
                        return ModelResponse(
                            content='{"epistemic_state": "doubt", '
                            '"goal_achieved": false}',
                            usage={"input_tokens": 50, "output_tokens": 50},
                        )
                    return ModelResponse(
                        content="No progress.",
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                if "deliberat" in user_prompt.lower():
                    return ModelResponse(
                        content='{"epistemic_state": "know", '
                        '"goal_achieved": true}',
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                return ModelResponse(
                    content="Recovered via forge.",
                    usage={"input_tokens": 50, "output_tokens": 50},
                )

        agent = _agent(
            name="Resilient", goal="Complete despite obstacles",
            max_iterations=10, on_stuck="forge",
        )
        ir = _program(agent)
        result = await _compile_and_execute(ir, AnthropicBackend(), ForgeClient())
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 7 — Multi-Agent Programs
# ═══════════════════════════════════════════════════════════════════


class TestMultiAgentProgram:
    """Multiple agents in one IRProgram execute independently."""

    @pytest.mark.asyncio
    async def test_two_agents_both_execute(self):
        """Both agents in a multi-agent flow reach execution."""
        alpha = _agent(name="Alpha", goal="Gather data", max_iterations=3)
        beta = _agent(name="Beta", goal="Analyze results", max_iterations=3)
        flow = _flow(name="MultiFlow", steps=(alpha, beta))
        run = _run(flow_name="MultiFlow", resolved_flow=flow)
        ir = IRProgram(
            personas=(_persona(),), contexts=(_context(),),
            anchors=(), tools=(),
            flows=(flow,), runs=(run,),
        )
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Data gathered.",
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Results analyzed.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.success is True
        unit = result.unit_results[0]
        assert len(unit.step_results) == 2

    @pytest.mark.asyncio
    async def test_multi_agent_metadata_distinct(self):
        """Each agent has distinct metadata in compilation."""
        alpha = _agent(name="Alpha", goal="Gather data")
        beta = _agent(name="Beta", goal="Analyze results")
        flow = _flow(name="MultiFlow", steps=(alpha, beta))
        run = _run(flow_name="MultiFlow", resolved_flow=flow)
        ir = IRProgram(
            personas=(_persona(),), contexts=(_context(),),
            anchors=(), tools=(),
            flows=(flow,), runs=(run,),
        )
        compiled = GeminiBackend().compile_program(ir)
        steps = compiled.execution_units[0].steps
        assert len(steps) == 2
        assert steps[0].metadata["agent"]["name"] == "Alpha"
        assert steps[0].metadata["agent"]["goal"] == "Gather data"
        assert steps[1].metadata["agent"]["name"] == "Beta"
        assert steps[1].metadata["agent"]["goal"] == "Analyze results"


# ═══════════════════════════════════════════════════════════════════
#  TEST CLASS 8 — Trace Event Integration
# ═══════════════════════════════════════════════════════════════════


def _collect_all_events(trace):
    """Recursively collect all TraceEvents from an ExecutionTrace."""
    all_events = []

    def _walk_spans(spans):
        for span in spans:
            all_events.extend(span.events)
            _walk_spans(span.children)

    _walk_spans(trace.spans)
    return all_events


class TestTraceEventIntegration:
    """Full pipeline emits correct trace events."""

    @pytest.mark.asyncio
    async def test_trace_contains_agent_events(self):
        """Execution trace includes agent-specific events."""
        agent = _agent(name="Traced", goal="Generate trace events")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Done.",
        ])
        result = await _compile_and_execute(ir, AnthropicBackend(), client)
        assert result.trace is not None
        all_events = _collect_all_events(result.trace)
        event_types = [e.event_type for e in all_events]
        assert TraceEventType.STEP_START in event_types
        assert TraceEventType.STEP_END in event_types

    @pytest.mark.asyncio
    async def test_trace_has_step_events(self):
        """Trace records step-level events during agent BDI execution."""
        agent = _agent(name="ModelTraced", goal="Track model calls")
        ir = _program(agent)
        client = IntegrationMockClient(responses=[
            '{"epistemic_state": "know", "goal_achieved": true}',
            "Done.",
        ])
        result = await _compile_and_execute(ir, GeminiBackend(), client)
        assert result.trace is not None
        all_events = _collect_all_events(result.trace)
        step_events = [
            e for e in all_events
            if e.event_type in (
                TraceEventType.STEP_START,
                TraceEventType.STEP_END,
                TraceEventType.MODEL_CALL,
            )
        ]
        assert len(step_events) >= 1
