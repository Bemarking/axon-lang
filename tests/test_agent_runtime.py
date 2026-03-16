"""
Tests for axon.runtime.executor — Agent BDI Runtime

Comprehensive test suite for the agent primitive runtime execution,
covering the full BDI (Belief-Desire-Intention) deliberation loop:

  - AgentResult dataclass serialization
  - _execute_agent_step: complete BDI lifecycle
  - Strategy modes: react, reflexion, plan_and_execute, custom
  - Budget guards: iterations, tokens, time, cost
  - Stuck detection + on_stuck recovery policies
  - Helper methods: epistemic, observation, action, plan extraction
  - Duration parsing for budget time limits
  - Trace event instrumentation
  - Error propagation (AgentStuckError)

Theoretical grounding:
  Coalgebraic semantics  — AgentResult as observable state
  Tarski fixed-point     — Epistemic lattice convergence
  Linear logic (⊗)       — Budget resource consumption
  STIT logic (¬◇φ)       — Stuck detection and recovery
"""

import json
import time

import pytest

from axon.backends.base_backend import (
    CompiledExecutionUnit,
    CompiledProgram,
    CompiledStep,
)
from axon.runtime.executor import (
    AgentResult,
    Executor,
    ModelResponse,
    StepResult,
)
from axon.runtime.runtime_errors import AgentStuckError
from axon.runtime.tracer import TraceEventType


# ═══════════════════════════════════════════════════════════════════
#  MOCK MODEL CLIENT — Agent-aware version
# ═══════════════════════════════════════════════════════════════════


class AgentMockClient:
    """A model client that returns controlled responses for agent testing.

    Supports:
      - Sequential responses (returns next in queue on each call)
      - Pattern-based responses (matches substrings in prompts)
      - Call tracking for assertion (count, prompts, efforts)
      - Configurable token usage reporting
    """

    def __init__(
        self,
        *,
        sequential_responses: list[str] | None = None,
        pattern_responses: dict[str, str] | None = None,
        default_response: str = "Default agent response",
        tokens_per_call: int = 100,
        fail_after: int | None = None,
    ):
        self._sequential = list(sequential_responses or [])
        self._patterns = pattern_responses or {}
        self._default = default_response
        self._tokens = tokens_per_call
        self._fail_after = fail_after
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
            "effort": effort,
        })

        if self._fail_after and self.call_count > self._fail_after:
            raise RuntimeError(f"Mock failure after {self._fail_after} calls")

        # Sequential mode: pop from queue
        if self._sequential:
            content = self._sequential.pop(0)
        else:
            # Pattern matching mode
            content = self._default
            for pattern, response in self._patterns.items():
                if pattern.lower() in user_prompt.lower():
                    content = response
                    break

        return ModelResponse(
            content=content,
            usage={
                "input_tokens": self._tokens // 2,
                "output_tokens": self._tokens // 2,
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  HELPERS — build agent-specific compiled steps
# ═══════════════════════════════════════════════════════════════════


def make_agent_step(
    name: str = "test_agent",
    goal: str = "Analyze the data",
    *,
    tools: list[str] | None = None,
    max_iterations: int = 3,
    max_tokens: int = 0,
    max_time: str = "",
    max_cost: float = 0.0,
    strategy: str = "react",
    on_stuck: str = "escalate",
    return_type: str = "",
    child_steps: list[dict] | None = None,
) -> CompiledStep:
    """Create a CompiledStep with agent metadata."""
    return CompiledStep(
        step_name=f"agent:{name}",
        system_prompt="",
        user_prompt="",
        metadata={
            "agent": {
                "name": name,
                "goal": goal,
                "tools": tools or [],
                "max_iterations": max_iterations,
                "max_tokens": max_tokens,
                "max_time": max_time,
                "max_cost": max_cost,
                "strategy": strategy,
                "on_stuck": on_stuck,
                "return_type": return_type,
                "child_steps": child_steps or [],
            },
        },
    )


def make_agent_unit(
    agent_step: CompiledStep,
    system_prompt: str = "You are an autonomous agent.",
) -> CompiledExecutionUnit:
    return CompiledExecutionUnit(
        flow_name="agent_flow",
        system_prompt=system_prompt,
        steps=[agent_step],
    )


def make_agent_program(agent_step: CompiledStep) -> CompiledProgram:
    return CompiledProgram(
        backend_name="mock",
        execution_units=[make_agent_unit(agent_step)],
    )


# ═══════════════════════════════════════════════════════════════════
#  AgentResult DATACLASS
# ═══════════════════════════════════════════════════════════════════


class TestAgentResult:
    """Tests for the AgentResult coalgebraic state container."""

    def test_defaults(self):
        r = AgentResult()
        assert r.agent_name == ""
        assert r.goal == ""
        assert r.strategy == "react"
        assert r.iterations_used == 0
        assert r.max_iterations == 10
        assert r.epistemic_state == "doubt"
        assert r.goal_achieved is False
        assert r.on_stuck_fired is False
        assert r.on_stuck_policy == "escalate"
        assert r.cycle_results == ()
        assert r.final_response is None
        assert r.total_tokens == 0

    def test_construction_with_values(self):
        response = ModelResponse(content="Final answer")
        cycle = StepResult(step_name="cycle:0")
        r = AgentResult(
            agent_name="Researcher",
            goal="Find the answer",
            strategy="reflexion",
            iterations_used=5,
            max_iterations=10,
            epistemic_state="believe",
            goal_achieved=True,
            on_stuck_fired=False,
            on_stuck_policy="forge",
            cycle_results=(cycle,),
            final_response=response,
            total_tokens=5000,
        )
        assert r.agent_name == "Researcher"
        assert r.strategy == "reflexion"
        assert r.epistemic_state == "believe"
        assert r.goal_achieved is True
        assert len(r.cycle_results) == 1
        assert r.total_tokens == 5000

    def test_to_dict_minimal(self):
        r = AgentResult(agent_name="Test", goal="Do thing")
        d = r.to_dict()
        assert d["agent_name"] == "Test"
        assert d["goal"] == "Do thing"
        assert d["strategy"] == "react"
        assert d["epistemic_state"] == "doubt"
        assert d["goal_achieved"] is False
        # No cycle_results or final_response in minimal form
        assert "cycle_results" not in d
        assert "final_response" not in d
        assert "total_tokens" not in d

    def test_to_dict_full(self):
        response = ModelResponse(content="Answer", usage={"total": 100})
        cycle = StepResult(step_name="c0", duration_ms=50.0)
        r = AgentResult(
            agent_name="Agent",
            goal="Goal",
            cycle_results=(cycle,),
            final_response=response,
            total_tokens=500,
        )
        d = r.to_dict()
        assert "cycle_results" in d
        assert len(d["cycle_results"]) == 1
        assert "final_response" in d
        assert d["total_tokens"] == 500

    def test_frozen_immutability(self):
        r = AgentResult(agent_name="Frozen")
        with pytest.raises(AttributeError):
            r.agent_name = "Modified"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  HELPER METHODS — Epistemic lattice
# ═══════════════════════════════════════════════════════════════════


class TestEpistemicLattice:
    """Tests for epistemic state extraction and advancement."""

    def setup_method(self):
        self.executor = Executor.__new__(Executor)

    def test_extract_epistemic_from_json(self):
        content = '{"epistemic_state": "speculate", "confidence": 0.5}'
        result = self.executor._extract_epistemic_state(content, "doubt")
        assert result == "speculate"

    def test_extract_epistemic_from_keyword(self):
        content = "I believe the answer is correct based on evidence."
        result = self.executor._extract_epistemic_state(content, "doubt")
        assert result == "believe"

    def test_extract_epistemic_highest_keyword(self):
        """When multiple lattice keywords appear, picks the highest."""
        content = "I know this for certain, beyond mere speculation."
        result = self.executor._extract_epistemic_state(content, "doubt")
        assert result == "know"

    def test_extract_epistemic_fallback_to_current(self):
        content = "No epistemic indicators here at all."
        result = self.executor._extract_epistemic_state(content, "speculate")
        assert result == "speculate"

    def test_advance_epistemic_forward(self):
        result = self.executor._advance_epistemic("doubt", "speculate")
        assert result == "speculate"

    def test_advance_epistemic_monotonic_no_backward(self):
        """Epistemic state never goes backward (Tarski monotonicity)."""
        result = self.executor._advance_epistemic("believe", "doubt")
        assert result == "believe"

    def test_advance_epistemic_same_state(self):
        result = self.executor._advance_epistemic("speculate", "speculate")
        assert result == "speculate"

    def test_advance_epistemic_unknown_defaults_to_zero(self):
        result = self.executor._advance_epistemic("unknown", "speculate")
        assert result == "speculate"

    def test_check_goal_achieved_by_epistemic(self):
        assert Executor._check_goal_achieved("anything", "believe") is True
        assert Executor._check_goal_achieved("anything", "know") is True

    def test_check_goal_achieved_not_by_epistemic(self):
        assert Executor._check_goal_achieved("nothing", "doubt") is False
        assert Executor._check_goal_achieved("nothing", "speculate") is False

    def test_check_goal_achieved_by_explicit_json(self):
        content = '{"goal_achieved": true, "reasoning": "done"}'
        assert Executor._check_goal_achieved(content, "doubt") is True

    def test_check_goal_no_spaces_json(self):
        content = '{"goal_achieved":true}'
        assert Executor._check_goal_achieved(content, "doubt") is True


# ═══════════════════════════════════════════════════════════════════
#  HELPER METHODS — Observation / Action prompts
# ═══════════════════════════════════════════════════════════════════


class TestObservationPrompt:
    """Tests for _build_observation_prompt."""

    def test_basic_prompt(self):
        prompt = Executor._build_observation_prompt(
            name="TestAgent",
            goal="Find answer",
            strategy="react",
            iteration=0,
            epistemic_state="doubt",
            observation_history=[],
            execution_plan=[],
        )
        assert "TestAgent" in prompt
        assert "Find answer" in prompt
        assert "react" in prompt
        assert "doubt" in prompt
        assert "BDI Cycle 0" in prompt

    def test_with_execution_plan(self):
        prompt = Executor._build_observation_prompt(
            name="Agent",
            goal="Goal",
            strategy="plan_and_execute",
            iteration=1,
            epistemic_state="speculate",
            observation_history=[],
            execution_plan=["Step A", "Step B", "Step C"],
        )
        assert "Execution Plan" in prompt
        assert "Step A" in prompt
        assert "Step B" in prompt
        # Iteration 1: Step A should be ✓, Step B should be →
        assert "✓" in prompt
        assert "→" in prompt

    def test_with_observation_history(self):
        prompt = Executor._build_observation_prompt(
            name="Agent",
            goal="Goal",
            strategy="react",
            iteration=2,
            epistemic_state="speculate",
            observation_history=[
                "[act:0] Did first thing",
                "[act:1] Did second thing",
            ],
            execution_plan=[],
        )
        assert "Observation History" in prompt
        assert "Did first thing" in prompt
        assert "Did second thing" in prompt

    def test_history_limited_to_last_five(self):
        history = [f"[act:{i}] Observation {i}" for i in range(10)]
        prompt = Executor._build_observation_prompt(
            name="Agent", goal="Goal", strategy="react",
            iteration=10, epistemic_state="speculate",
            observation_history=history, execution_plan=[],
        )
        # Only last 5 should be present
        assert "Observation 5" in prompt
        assert "Observation 9" in prompt
        assert "Observation 0" not in prompt


class TestActionPrompt:
    """Tests for _build_action_prompt."""

    def test_react_strategy(self):
        prompt = Executor._build_action_prompt(
            name="Agent", goal="Find it", strategy="react",
            iteration=1, child_steps_meta=[], tools=["search"],
            deliberation_content="Still looking...",
            execution_plan=[],
        )
        assert "Agent" in prompt
        assert "Find it" in prompt
        assert "search" in prompt
        assert "Still looking" in prompt

    def test_plan_and_execute_first_iteration(self):
        prompt = Executor._build_action_prompt(
            name="Planner", goal="Build plan", strategy="plan_and_execute",
            iteration=0, child_steps_meta=[], tools=["tool_a", "tool_b"],
            deliberation_content="", execution_plan=[],
        )
        assert "execution plan" in prompt.lower()
        assert "tool_a" in prompt
        assert "tool_b" in prompt

    def test_plan_and_execute_subsequent(self):
        prompt = Executor._build_action_prompt(
            name="Planner", goal="Execute plan",
            strategy="plan_and_execute", iteration=2,
            child_steps_meta=[], tools=[],
            deliberation_content="Progressing...",
            execution_plan=["Step 1", "Step 2", "Step 3"],
        )
        assert "Step 3" in prompt  # iteration 2 → index 2
        assert "step 3 of the plan" in prompt.lower()

    def test_tools_and_body_steps_in_prompt(self):
        prompt = Executor._build_action_prompt(
            name="Agent", goal="Do it", strategy="react", iteration=0,
            child_steps_meta=[{"name": "sub1"}, {"name": "sub2"}],
            tools=["scrape", "analyze"],
            deliberation_content="Ready",
            execution_plan=[],
        )
        assert "scrape" in prompt
        assert "analyze" in prompt
        assert "2" in prompt  # 2 body steps


# ═══════════════════════════════════════════════════════════════════
#  HELPER METHODS — Plan extraction
# ═══════════════════════════════════════════════════════════════════


class TestPlanExtraction:
    """Tests for _extract_execution_plan."""

    def test_numbered_list(self):
        content = "1. Search databases\n2. Analyze results\n3. Synthesize report"
        plan = Executor._extract_execution_plan(content)
        assert len(plan) == 3
        assert plan[0] == "Search databases"
        assert plan[2] == "Synthesize report"

    def test_numbered_with_parentheses(self):
        content = "1) First step\n2) Second step"
        plan = Executor._extract_execution_plan(content)
        assert len(plan) == 2
        assert plan[0] == "First step"

    def test_dashed_list(self):
        content = "- Step A\n- Step B\n- Step C"
        plan = Executor._extract_execution_plan(content)
        assert len(plan) == 3

    def test_mixed_format(self):
        content = "Plan:\n1. First\n2. Second\n- Third"
        plan = Executor._extract_execution_plan(content)
        assert len(plan) == 3

    def test_fallback_when_no_list(self):
        content = "Just a plain paragraph without any list items."
        plan = Executor._extract_execution_plan(content)
        assert len(plan) == 1
        assert plan[0].startswith("Just a plain")


# ═══════════════════════════════════════════════════════════════════
#  HELPER METHODS — Budget guards
# ═══════════════════════════════════════════════════════════════════


class TestBudgetGuards:
    """Tests for _check_budget_exceeded and _parse_duration."""

    def test_no_limits_not_exceeded(self):
        assert Executor._check_budget_exceeded(
            max_tokens=0, max_time_seconds=0, max_cost=0,
            accumulated_tokens=1000, accumulated_cost=10.0,
            step_start=time.perf_counter(),
        ) is False

    def test_token_limit_exceeded(self):
        assert Executor._check_budget_exceeded(
            max_tokens=500, max_time_seconds=0, max_cost=0,
            accumulated_tokens=600, accumulated_cost=0,
            step_start=time.perf_counter(),
        ) is True

    def test_token_limit_not_exceeded(self):
        assert Executor._check_budget_exceeded(
            max_tokens=1000, max_time_seconds=0, max_cost=0,
            accumulated_tokens=500, accumulated_cost=0,
            step_start=time.perf_counter(),
        ) is False

    def test_cost_limit_exceeded(self):
        assert Executor._check_budget_exceeded(
            max_tokens=0, max_time_seconds=0, max_cost=5.0,
            accumulated_tokens=0, accumulated_cost=6.0,
            step_start=time.perf_counter(),
        ) is True

    def test_time_limit_exceeded(self):
        # Set step_start far in the past
        past = time.perf_counter() - 100
        assert Executor._check_budget_exceeded(
            max_tokens=0, max_time_seconds=10, max_cost=0,
            accumulated_tokens=0, accumulated_cost=0,
            step_start=past,
        ) is True

    def test_time_limit_not_exceeded(self):
        assert Executor._check_budget_exceeded(
            max_tokens=0, max_time_seconds=9999, max_cost=0,
            accumulated_tokens=0, accumulated_cost=0,
            step_start=time.perf_counter(),
        ) is False

    # ── Duration parsing ──────────────────────────────────────

    def test_parse_seconds(self):
        assert Executor._parse_duration("30s") == 30.0

    def test_parse_minutes(self):
        assert Executor._parse_duration("5m") == 300.0

    def test_parse_hours(self):
        assert Executor._parse_duration("2h") == 7200.0

    def test_parse_combined(self):
        assert Executor._parse_duration("1h30m") == 5400.0

    def test_parse_full_duration(self):
        assert Executor._parse_duration("1h15m30s") == 4530.0

    def test_parse_empty(self):
        assert Executor._parse_duration("") == 0.0

    def test_parse_no_match(self):
        assert Executor._parse_duration("abc") == 0.0


# ═══════════════════════════════════════════════════════════════════
#  BDI LOOP — React Strategy (goal achieved quickly)
# ═══════════════════════════════════════════════════════════════════


class TestAgentBDIReact:
    """Tests for the BDI loop with react strategy."""

    @pytest.mark.asyncio
    async def test_goal_achieved_first_cycle(self):
        """Agent achieves goal on first deliberation cycle."""
        client = AgentMockClient(
            sequential_responses=[
                # Deliberation cycle 0 → goal achieved
                '{"epistemic_state": "know", "goal_achieved": true, '
                '"confidence": 1.0, "reasoning": "Done", "next_action": "none"}',
                # Final synthesis
                "The analysis is complete: data shows positive trends.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "Analyzer", "Analyze dataset", max_iterations=5,
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        step_result = result.unit_results[0].step_results[0]
        content = json.loads(step_result.response.content)
        assert content["agent"]["goal_achieved"] is True
        assert content["agent"]["epistemic_state"] == "know"
        assert content["agent"]["iterations_used"] == 1

    @pytest.mark.asyncio
    async def test_goal_achieved_after_multiple_cycles(self):
        """Agent needs several cycles before achieving the goal."""
        client = AgentMockClient(
            sequential_responses=[
                # Cycle 0: deliberation → doubt
                '{"epistemic_state": "doubt", "goal_achieved": false, '
                '"confidence": 0.2, "reasoning": "Need more data"}',
                # Cycle 0: action
                "Searched database, found partial results.",
                # Cycle 1: deliberation → speculate
                '{"epistemic_state": "speculate", "goal_achieved": false, '
                '"confidence": 0.5, "reasoning": "Getting closer"}',
                # Cycle 1: action
                "Analyzed results, patterns emerging.",
                # Cycle 2: deliberation → believe (goal achieved!)
                '{"epistemic_state": "believe", "goal_achieved": true, '
                '"confidence": 0.9, "reasoning": "Found answer"}',
                # Final synthesis
                "Comprehensive analysis complete.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "Researcher", "Find the answer", max_iterations=10,
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["goal_achieved"] is True
        assert content["agent"]["iterations_used"] == 3
        assert content["agent"]["epistemic_state"] == "believe"

    @pytest.mark.asyncio
    async def test_budget_iteration_limit(self):
        """Agent exhausts iteration budget without achieving goal."""
        client = AgentMockClient(
            pattern_responses={
                "deliberat": '{"epistemic_state": "doubt", "goal_achieved": false}',
            },
            default_response="Still working on it...",
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "Stubborn", "Impossible goal", max_iterations=2,
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True  # Executes fine, just doesn't achieve goal
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["goal_achieved"] is False
        assert content["agent"]["iterations_used"] == 2

    @pytest.mark.asyncio
    async def test_token_budget_stops_loop(self):
        """Agent stops when token budget is exceeded."""
        client = AgentMockClient(
            pattern_responses={
                "deliberat": '{"epistemic_state": "doubt", "goal_achieved": false}',
            },
            default_response="Working...",
            tokens_per_call=200,
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "TokenCounter", "Goal",
            max_iterations=100,
            max_tokens=500,  # Will be exceeded after ~2.5 calls
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        content = json.loads(result.unit_results[0].step_results[0].response.content)
        # Should have stopped early due to token budget
        assert content["agent"]["iterations_used"] < 100
        assert content["agent"]["goal_achieved"] is False


# ═══════════════════════════════════════════════════════════════════
#  BDI LOOP — Reflexion Strategy
# ═══════════════════════════════════════════════════════════════════


class TestAgentBDIReflexion:
    """Tests for the reflexion strategy (ReAct + self-critique)."""

    @pytest.mark.asyncio
    async def test_reflexion_adds_critique_step(self):
        """Reflexion strategy generates self-critique after each action."""
        client = AgentMockClient(
            sequential_responses=[
                # Cycle 0: deliberation → doubt
                '{"epistemic_state": "doubt", "goal_achieved": false}',
                # Cycle 0: action
                "Performed initial analysis.",
                # Cycle 0: critique (reflexion adds this)
                "The analysis was too shallow. Need deeper investigation.",
                # Cycle 1: deliberation → believe
                '{"epistemic_state": "believe", "goal_achieved": true}',
                # Final synthesis
                "Refined analysis complete with self-corrections.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "Critic", "Deep analysis",
            strategy="reflexion", max_iterations=5,
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["strategy"] == "reflexion"
        assert content["agent"]["goal_achieved"] is True

        # Reflexion uses "max" effort for critique steps
        critique_calls = [
            c for c in client.calls
            if "self-critique" in c["user_prompt"].lower()
        ]
        assert len(critique_calls) >= 1
        assert critique_calls[0]["effort"] == "max"


# ═══════════════════════════════════════════════════════════════════
#  BDI LOOP — Plan and Execute Strategy
# ═══════════════════════════════════════════════════════════════════


class TestAgentBDIPlanAndExecute:
    """Tests for the plan_and_execute strategy."""

    @pytest.mark.asyncio
    async def test_generates_plan_on_first_iteration(self):
        """plan_and_execute creates a plan on iteration 0."""
        client = AgentMockClient(
            sequential_responses=[
                # Cycle 0: deliberation
                '{"epistemic_state": "doubt", "goal_achieved": false}',
                # Cycle 0: plan generation
                "1. Gather data\n2. Analyze patterns\n3. Report findings",
                # Cycle 1: deliberation
                '{"epistemic_state": "believe", "goal_achieved": true}',
                # Final synthesis
                "Plan executed successfully.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "Planner", "Complete analysis",
            strategy="plan_and_execute", max_iterations=5,
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        # First action call should ask for an execution plan
        plan_call = client.calls[1]  # Second call is the action
        assert "plan" in plan_call["user_prompt"].lower()


# ═══════════════════════════════════════════════════════════════════
#  STUCK DETECTION + RECOVERY
# ═══════════════════════════════════════════════════════════════════


class TestAgentStuckDetection:
    """Tests for stuck detection and on_stuck recovery policies."""

    @pytest.mark.asyncio
    async def test_stuck_escalate_raises_error(self):
        """on_stuck='escalate' raises AgentStuckError."""
        # All deliberations return 'doubt' → stagnation ≥ 3 → escalate
        client = AgentMockClient(
            pattern_responses={
                "deliberat": '{"epistemic_state": "doubt", "goal_achieved": false}',
            },
            default_response="No progress.",
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "StuckAgent", "Impossible",
            max_iterations=10,
            on_stuck="escalate",
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        # The executor catches errors and reports failure
        assert result.success is False

    @pytest.mark.asyncio
    async def test_stuck_forge_recovery(self):
        """on_stuck='forge' triggers creative synthesis to break impasse."""
        call_counter = {"count": 0}

        class ForgeRecoveryClient(AgentMockClient):
            async def call(self, system_prompt, user_prompt, **kwargs):
                call_counter["count"] += 1
                # First 6 calls are deliberation + action for 3 cycles (all doubt)
                if call_counter["count"] <= 6:
                    if "deliberat" in user_prompt.lower():
                        return ModelResponse(
                            content='{"epistemic_state": "doubt", "goal_achieved": false}',
                            usage={"input_tokens": 50, "output_tokens": 50},
                        )
                    return ModelResponse(
                        content="No progress yet.",
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                # Call 7+: after forge recovery, goal achieved
                if "stuck" in user_prompt.lower():
                    return ModelResponse(
                        content="Creative breakthrough! New approach found.",
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                if "deliberat" in user_prompt.lower():
                    return ModelResponse(
                        content='{"epistemic_state": "believe", "goal_achieved": true}',
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                return ModelResponse(
                    content="Recovery synthesis complete.",
                    usage={"input_tokens": 50, "output_tokens": 50},
                )

        executor = Executor(client=ForgeRecoveryClient())
        step = make_agent_step(
            "RecoverAgent", "Hard problem",
            max_iterations=10,
            on_stuck="forge",
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["on_stuck_fired"] is True

    @pytest.mark.asyncio
    async def test_stuck_hibernate_returns_partial(self):
        """on_stuck='hibernate' exits loop gracefully with partial result."""
        client = AgentMockClient(
            pattern_responses={
                "deliberat": '{"epistemic_state": "doubt", "goal_achieved": false}',
            },
            default_response="No progress.",
        )
        executor = Executor(client=client)
        step = make_agent_step(
            "HibernateAgent", "Long task",
            max_iterations=10,
            on_stuck="hibernate",
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["goal_achieved"] is False
        assert content["agent"]["on_stuck_fired"] is True

    @pytest.mark.asyncio
    async def test_stuck_retry_recovery(self):
        """on_stuck='retry' resets stagnation and retries."""
        call_counter = {"count": 0}

        class RetryClient(AgentMockClient):
            async def call(self, system_prompt, user_prompt, **kwargs):
                call_counter["count"] += 1
                if "retrying" in user_prompt.lower():
                    return ModelResponse(
                        content="Trying completely different approach.",
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                # After retry, achieve goal
                if call_counter["count"] > 8 and "deliberat" in user_prompt.lower():
                    return ModelResponse(
                        content='{"epistemic_state": "believe", "goal_achieved": true}',
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                if "deliberat" in user_prompt.lower():
                    return ModelResponse(
                        content='{"epistemic_state": "doubt", "goal_achieved": false}',
                        usage={"input_tokens": 50, "output_tokens": 50},
                    )
                return ModelResponse(
                    content="Working...",
                    usage={"input_tokens": 50, "output_tokens": 50},
                )

        executor = Executor(client=RetryClient())
        step = make_agent_step(
            "RetryAgent", "Tricky goal",
            max_iterations=15,
            on_stuck="retry",
        )
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True


# ═══════════════════════════════════════════════════════════════════
#  TRACE EVENTS
# ═══════════════════════════════════════════════════════════════════


class TestAgentTraceEvents:
    """Tests for agent-specific trace event instrumentation."""

    @staticmethod
    def _collect_event_types(trace) -> set[TraceEventType]:
        """Recursively collect all event types from trace spans."""
        types: set[TraceEventType] = set()

        def _walk(spans):
            for span in spans:
                for event in span.events:
                    types.add(event.event_type)
                _walk(span.children)

        _walk(trace.spans)
        return types

    @pytest.mark.asyncio
    async def test_trace_contains_agent_events(self):
        """Agent execution produces agent-specific trace events."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Final answer.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("Traced", "Quick task", max_iterations=3)
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.trace is not None
        event_types = self._collect_event_types(result.trace)
        assert TraceEventType.AGENT_CYCLE_START in event_types
        assert TraceEventType.AGENT_CYCLE_END in event_types
        assert TraceEventType.AGENT_GOAL_CHECK in event_types

    @pytest.mark.asyncio
    async def test_trace_contains_step_start_end(self):
        """Agent produces STEP_START and STEP_END events."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("StepTraced", "Task")
        program = make_agent_program(step)
        result = await executor.execute(program)

        event_types = self._collect_event_types(result.trace)
        assert TraceEventType.STEP_START in event_types
        assert TraceEventType.STEP_END in event_types


# ═══════════════════════════════════════════════════════════════════
#  AGENT DISPATCH — Integration with _execute_step
# ═══════════════════════════════════════════════════════════════════


class TestAgentDispatch:
    """Tests that agent metadata is correctly routed through _execute_step."""

    @pytest.mark.asyncio
    async def test_agent_metadata_triggers_agent_execution(self):
        """Steps with agent metadata go through the BDI loop."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Agent result.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("DispatchTest", "Route test")
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True
        content = json.loads(result.unit_results[0].step_results[0].response.content)
        # The response should contain the agent structure
        assert "agent" in content
        assert content["agent"]["agent_name"] == "DispatchTest"

    @pytest.mark.asyncio
    async def test_non_agent_step_not_routed(self):
        """Regular steps (without agent metadata) go through normal path."""
        client = AgentMockClient(default_response="Normal response")
        executor = Executor(client=client)

        normal_step = CompiledStep(
            step_name="normal", system_prompt="", user_prompt="Hello",
        )
        program = CompiledProgram(
            backend_name="mock",
            execution_units=[CompiledExecutionUnit(
                flow_name="flow",
                system_prompt="System",
                steps=[normal_step],
            )],
        )
        result = await executor.execute(program)

        assert result.success is True
        # Normal step response is NOT JSON-wrapped agent result
        content = result.unit_results[0].step_results[0].response.content
        assert "Normal response" in content


# ═══════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═══════════════════════════════════════════════════════════════════


class TestAgentEdgeCases:
    """Edge cases and boundary conditions for agent execution."""

    @pytest.mark.asyncio
    async def test_single_iteration_no_goal(self):
        """Agent with max_iterations=1 runs exactly once."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "doubt", "goal_achieved": false}',
                "Single attempt result.",
                "Synthesis of single attempt.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("OneShot", "Quick check", max_iterations=1)
        program = make_agent_program(step)
        result = await executor.execute(program)

        content = json.loads(result.unit_results[0].step_results[0].response.content)
        assert content["agent"]["iterations_used"] == 1

    @pytest.mark.asyncio
    async def test_empty_tools_list(self):
        """Agent with no tools still runs correctly."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done without tools.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("NoTools", "Simple task", tools=[])
        program = make_agent_program(step)
        result = await executor.execute(program)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_system_prompt_propagated(self):
        """Agent execution passes system prompt to model calls."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("SysPrompt", "Task")
        unit = make_agent_unit(step, system_prompt="You are a legal expert.")
        program = CompiledProgram(
            backend_name="mock",
            execution_units=[unit],
        )
        await executor.execute(program)

        # All calls should use the system prompt
        for call in client.calls:
            assert call["system_prompt"] == "You are a legal expert."

    @pytest.mark.asyncio
    async def test_effort_mapping_react(self):
        """React strategy uses 'high' effort."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("EffortTest", "Task", strategy="react")
        program = make_agent_program(step)
        await executor.execute(program)

        assert client.calls[0]["effort"] == "high"

    @pytest.mark.asyncio
    async def test_effort_mapping_reflexion(self):
        """Reflexion strategy uses 'max' effort."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("EffortRef", "Task", strategy="reflexion")
        program = make_agent_program(step)
        await executor.execute(program)

        assert client.calls[0]["effort"] == "max"

    @pytest.mark.asyncio
    async def test_duration_ms_tracked(self):
        """Agent step reports non-zero duration."""
        client = AgentMockClient(
            sequential_responses=[
                '{"epistemic_state": "know", "goal_achieved": true}',
                "Done.",
            ],
        )
        executor = Executor(client=client)
        step = make_agent_step("DurationTest", "Task")
        program = make_agent_program(step)
        result = await executor.execute(program)

        step_result = result.unit_results[0].step_results[0]
        assert step_result.duration_ms > 0
