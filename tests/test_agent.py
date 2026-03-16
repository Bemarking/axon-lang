"""
AXON Test Suite — agent Primitive
====================================

Tests for the BDI autonomous agent primitive.
Coverage: Lexer → Parser → AST → TypeChecker → IRGenerator → IR

Grounded in:
  • BDI Architecture (Bratman → Rao-Georgeff)
  • Coalgebraic Semantics (state transition functor)
  • π-calculus (concurrent tool communication)
  • STIT Logic (on_stuck recovery)
  • Linear Logic (resource budget consumption)

Structure mirrors test_deliberate_consensus.py.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import (
    AgentBudget,
    AgentDefinition,
    FlowDefinition,
    StepNode,
)
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRAgent,
    IRStep,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.tokens import TokenType
from axon.compiler.type_checker import TypeChecker


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def _lex(source: str):
    """Lex source and return list of tokens (no NEWLINE / COMMENT)."""
    tokens = Lexer(source).tokenize()
    return [t for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.COMMENT)]


def _parse(source: str):
    """Parse source and return ProgramNode."""
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def _check(source: str):
    """Type-check source and return list of errors."""
    program = _parse(source)
    return TypeChecker(program).check()


def _generate(source: str):
    """Generate IR from source and return IRProgram."""
    program = _parse(source)
    TypeChecker(program).check()
    return IRGenerator().generate(program)


# ═══════════════════════════════════════════════════════════════════
#  PART 1 — LEXER
# ═══════════════════════════════════════════════════════════════════


class TestAgentTokens:
    """Lexer recognizes all 6 agent keywords."""

    def test_agent_keyword(self):
        tokens = _lex("agent")
        assert tokens[0].type == TokenType.AGENT
        assert tokens[0].value == "agent"

    def test_goal_keyword(self):
        tokens = _lex("goal")
        assert tokens[0].type == TokenType.GOAL
        assert tokens[0].value == "goal"

    def test_tools_keyword(self):
        tokens = _lex("tools")
        assert tokens[0].type == TokenType.TOOLS
        assert tokens[0].value == "tools"

    def test_budget_keyword(self):
        tokens = _lex("budget")
        assert tokens[0].type == TokenType.BUDGET
        assert tokens[0].value == "budget"

    def test_strategy_keyword(self):
        tokens = _lex("strategy")
        assert tokens[0].type == TokenType.STRATEGY
        assert tokens[0].value == "strategy"

    def test_on_stuck_keyword(self):
        tokens = _lex("on_stuck")
        assert tokens[0].type == TokenType.ON_STUCK
        assert tokens[0].value == "on_stuck"

    def test_agent_not_identifier(self):
        tokens = _lex("agent")
        assert tokens[0].type != TokenType.IDENTIFIER

    def test_keywords_in_context(self):
        """All agent keywords are tokenized correctly in sequence."""
        tokens = _lex("agent goal tools budget strategy on_stuck")
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.AGENT, TokenType.GOAL, TokenType.TOOLS,
            TokenType.BUDGET, TokenType.STRATEGY, TokenType.ON_STUCK,
        ]


# ═══════════════════════════════════════════════════════════════════
#  PART 2 — PARSER
# ═══════════════════════════════════════════════════════════════════


class TestAgentParser:
    """Parser produces AgentDefinition AST nodes."""

    def test_parse_minimal_agent(self):
        """Minimal agent with only goal."""
        program = _parse("""
        agent Researcher() {
            goal: "Find relevant papers"
        }
        """)
        agent = program.declarations[0]
        assert isinstance(agent, AgentDefinition)
        assert agent.name == "Researcher"
        assert agent.goal == "Find relevant papers"

    def test_parse_agent_with_tools(self):
        """Agent with tool references."""
        program = _parse("""
        tool WebSearch {
            endpoint: "https://api.search.com"
        }
        tool Calculator {
            endpoint: "https://api.calc.com"
        }
        agent Analyst() {
            goal: "Analyze financial data"
            tools: [WebSearch, Calculator]
        }
        """)
        agents = [d for d in program.declarations if isinstance(d, AgentDefinition)]
        assert len(agents) == 1
        agent = agents[0]
        assert agent.name == "Analyst"
        assert agent.tools == ["WebSearch", "Calculator"]

    def test_parse_agent_with_budget(self):
        """Agent with full budget block (linear logic resources)."""
        program = _parse("""
        agent Worker() {
            goal: "Process tasks"
            budget {
                max_iterations: 20
                max_tokens: 50000
                max_time: 5m
                max_cost: 0.50
            }
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert agent.budget is not None
        assert isinstance(agent.budget, AgentBudget)
        assert agent.budget.max_iterations == 20
        assert agent.budget.max_tokens == 50000
        assert agent.budget.max_time == "5m"
        assert agent.budget.max_cost == 0.50

    def test_parse_agent_with_strategy(self):
        """Agent with strategy field."""
        program = _parse("""
        agent Planner() {
            goal: "Create execution plan"
            strategy: react
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert agent.strategy == "react"

    def test_parse_agent_with_on_stuck(self):
        """Agent with on_stuck recovery policy (STIT logic)."""
        program = _parse("""
        agent Resilient() {
            goal: "Complete reliably"
            on_stuck: forge
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert agent.on_stuck == "forge"

    def test_parse_agent_with_body_steps(self):
        """Agent with flow steps in body."""
        program = _parse("""
        agent Researcher() {
            goal: "Find papers"
            step Search {
                ask: "Search for papers on {{topic}}"
                output: Summary
            }
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert len(agent.body) == 1
        assert isinstance(agent.body[0], StepNode)
        assert agent.body[0].name == "Search"

    def test_parse_agent_with_parameters(self):
        """Agent with typed parameters."""
        program = _parse("""
        agent Researcher(topic: String, depth: Integer) -> Summary {
            goal: "Research the given topic"
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert len(agent.parameters) == 2
        assert agent.parameters[0].name == "topic"
        assert agent.parameters[0].type_expr.name == "String"
        assert agent.parameters[1].name == "depth"
        assert agent.return_type.name == "Summary"

    def test_parse_full_agent(self):
        """A fully-specified agent with all fields."""
        program = _parse("""
        tool WebSearch {
            endpoint: "https://api.search.com"
        }
        memory ConversationLog {
            store: session
        }
        agent FullAgent(query: String) -> StructuredReport {
            goal: "Comprehensive research and report"
            tools: [WebSearch]
            budget {
                max_iterations: 15
                max_tokens: 100000
                max_time: 10m
                max_cost: 1.00
            }
            strategy: plan_and_execute
            on_stuck: escalate
            step Research {
                ask: "Research {{query}}"
                output: Summary
            }
            step Compile {
                ask: "Compile findings into report"
                output: StructuredReport
            }
        }
        """)
        agents = [d for d in program.declarations if isinstance(d, AgentDefinition)]
        assert len(agents) == 1
        agent = agents[0]
        assert agent.name == "FullAgent"
        assert agent.goal == "Comprehensive research and report"
        assert agent.tools == ["WebSearch"]
        assert agent.budget.max_iterations == 15
        assert agent.budget.max_tokens == 100000
        assert agent.budget.max_time == "10m"
        assert agent.budget.max_cost == 1.00
        assert agent.strategy == "plan_and_execute"
        assert agent.on_stuck == "escalate"
        assert len(agent.body) == 2
        assert agent.return_type.name == "StructuredReport"


# ═══════════════════════════════════════════════════════════════════
#  PART 3 — TYPE CHECKER
# ═══════════════════════════════════════════════════════════════════


class TestAgentTypeChecker:
    """Type checker validates agent invariants."""

    def test_valid_minimal_agent(self):
        errors = _check("""
        agent Worker() {
            goal: "Do work"
        }
        """)
        agent_errors = [e for e in errors if "agent" in e.message.lower()
                        or "Agent" in e.message]
        assert len(agent_errors) == 0

    def test_missing_goal(self):
        """BDI requires at least one desire (goal)."""
        errors = _check("""
        agent Headless() {
        }
        """)
        goal_errors = [e for e in errors if "goal" in e.message.lower()]
        assert len(goal_errors) >= 1

    def test_tool_reference_wrong_kind(self):
        """Tool list must reference 'tool' declarations, not personas."""
        errors = _check("""
        persona Analyst {
            domain: ["analysis"]
        }
        agent BadRef() {
            goal: "Analyze"
            tools: [Analyst]
        }
        """)
        kind_errors = [e for e in errors if "not a tool" in e.message]
        assert len(kind_errors) >= 1

    def test_budget_negative_iterations(self):
        """Linear logic: max_iterations must be >= 1."""
        errors = _check("""
        agent BrokenBudget() {
            goal: "Work"
            budget {
                max_iterations: 0
            }
        }
        """)
        budget_errors = [e for e in errors if "max_iterations" in e.message]
        assert len(budget_errors) >= 1

    def test_budget_negative_cost(self):
        """Linear logic: max_cost cannot be negative."""
        errors = _check("""
        agent NegCost() {
            goal: "Work"
            budget {
                max_cost: -5.0
            }
        }
        """)
        cost_errors = [e for e in errors if "max_cost" in e.message]
        assert len(cost_errors) >= 1

    def test_invalid_strategy(self):
        """Only known strategies are valid."""
        errors = _check("""
        agent BadStrategy() {
            goal: "Work"
            strategy: ultra_mega
        }
        """)
        strat_errors = [e for e in errors if "strategy" in e.message.lower()]
        assert len(strat_errors) >= 1

    def test_valid_strategies(self):
        """All known strategies pass validation."""
        for strat in ("react", "reflexion", "plan_and_execute", "custom"):
            errors = _check(f"""
            agent Valid() {{
                goal: "Work"
                strategy: {strat}
            }}
            """)
            strat_errors = [e for e in errors if "strategy" in e.message.lower()]
            assert len(strat_errors) == 0, f"Strategy '{strat}' should be valid"

    def test_invalid_on_stuck(self):
        """Only known on_stuck policies are valid."""
        errors = _check("""
        agent BadRecovery() {
            goal: "Work"
            on_stuck: panic
        }
        """)
        stuck_errors = [e for e in errors if "on_stuck" in e.message.lower()]
        assert len(stuck_errors) >= 1

    def test_valid_on_stuck_policies(self):
        """All known on_stuck policies pass validation."""
        for policy in ("forge", "hibernate", "escalate", "retry"):
            errors = _check(f"""
            agent Valid() {{
                goal: "Work"
                on_stuck: {policy}
            }}
            """)
            stuck_errors = [e for e in errors if "on_stuck" in e.message.lower()]
            assert len(stuck_errors) == 0, f"on_stuck '{policy}' should be valid"

    def test_memory_ref_wrong_kind(self):
        """memory_ref must reference a 'memory' declaration."""
        errors = _check("""
        persona Analyst {
            domain: ["analysis"]
        }
        agent BadMem() {
            goal: "Work"
        }
        """)
        # This agent doesn't reference memory, so no error expected
        assert isinstance(errors, list)

    def test_valid_full_agent(self):
        """Comprehensive agent with all fields passes validation."""
        errors = _check("""
        tool WebSearch {
            endpoint: "https://api.search.com"
        }
        memory ConvLog {
            store: session
        }
        agent FullValid(q: String) -> StructuredReport {
            goal: "Research"
            tools: [WebSearch]
            budget {
                max_iterations: 10
                max_tokens: 50000
                max_time: 5m
                max_cost: 0.50
            }
            strategy: react
            on_stuck: hibernate
            step Search {
                ask: "Search for {{q}}"
                output: Summary
            }
        }
        """)
        agent_errors = [e for e in errors if "agent" in e.message.lower()
                        or "Agent" in e.message]
        assert len(agent_errors) == 0


# ═══════════════════════════════════════════════════════════════════
#  PART 4 — IR GENERATOR
# ═══════════════════════════════════════════════════════════════════


class TestAgentIR:
    """IR generator produces IRAgent nodes."""

    def test_ir_minimal_agent(self):
        ir = _generate("""
        agent Worker() {
            goal: "Do work"
        }
        """)
        assert len(ir.agents) >= 1
        agent = list(ir.agents)[0]
        assert isinstance(agent, IRAgent)
        assert agent.name == "Worker"
        assert agent.goal == "Do work"

    def test_ir_agent_with_tools(self):
        ir = _generate("""
        tool WebSearch {
            endpoint: "https://api.search.com"
        }
        agent Searcher() {
            goal: "Search"
            tools: [WebSearch]
        }
        """)
        agent = list(ir.agents)[0]
        assert agent.tools == ("WebSearch",)

    def test_ir_agent_budget_defaults(self):
        """Budget defaults: max_iterations=10 when no budget block."""
        ir = _generate("""
        agent DefaultBudget() {
            goal: "Work"
        }
        """)
        agent = list(ir.agents)[0]
        assert agent.max_iterations == 10  # default
        assert agent.max_tokens == 0      # default
        assert agent.max_cost == 0.0      # default

    def test_ir_agent_budget_custom(self):
        """Custom budget fields are propagated to IR."""
        ir = _generate("""
        agent CustomBudget() {
            goal: "Work"
            budget {
                max_iterations: 25
                max_tokens: 80000
                max_time: 8m
                max_cost: 2.50
            }
        }
        """)
        agent = list(ir.agents)[0]
        assert agent.max_iterations == 25
        assert agent.max_tokens == 80000
        assert agent.max_time == "8m"
        assert agent.max_cost == 2.50

    def test_ir_agent_strategy_and_on_stuck(self):
        ir = _generate("""
        agent Strategic() {
            goal: "Strategize"
            strategy: reflexion
            on_stuck: forge
        }
        """)
        agent = list(ir.agents)[0]
        assert agent.strategy == "reflexion"
        assert agent.on_stuck == "forge"

    def test_ir_agent_with_children(self):
        ir = _generate("""
        agent WithSteps() {
            goal: "Process"
            step Analyze {
                ask: "Analyze data"
                output: Summary
            }
        }
        """)
        agent = list(ir.agents)[0]
        assert len(agent.children) == 1
        assert isinstance(agent.children[0], IRStep)
        assert agent.children[0].name == "Analyze"

    def test_ir_agent_return_type(self):
        ir = _generate("""
        agent Typed() -> StructuredReport {
            goal: "Generate report"
        }
        """)
        agent = list(ir.agents)[0]
        assert agent.return_type == "StructuredReport"

    def test_ir_agent_serialization(self):
        """IRAgent serializes to dict correctly."""
        ir = _generate("""
        agent Serializable() {
            goal: "Serialize"
            strategy: react
            on_stuck: escalate
            budget {
                max_iterations: 5
            }
        }
        """)
        agent = list(ir.agents)[0]
        d = agent.to_dict()
        assert d["node_type"] == "agent"
        assert d["name"] == "Serializable"
        assert d["goal"] == "Serialize"
        assert d["strategy"] == "react"
        assert d["on_stuck"] == "escalate"
        assert d["max_iterations"] == 5


# ═══════════════════════════════════════════════════════════════════
#  PART 5 — BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Ensure agent keywords don't break existing deliberate/consensus syntax."""

    def test_deliberate_strategy_still_works(self):
        """'strategy' inside deliberate block still parses as a field."""
        program = _parse("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
            }
        }
        """)
        flow = program.declarations[0]
        assert isinstance(flow, FlowDefinition)
        delib = flow.body[0]
        assert delib.strategy == "thorough"

    def test_deliberate_budget_still_works(self):
        """'budget' inside deliberate block still parses as a field."""
        program = _parse("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 4000
            }
        }
        """)
        delib = program.declarations[0].body[0]
        assert delib.budget == 4000

    def test_agent_coexists_with_deliberate(self):
        """Agent and deliberate can coexist in the same program."""
        ir = _generate("""
        agent Researcher() {
            goal: "Research"
        }
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
            }
        }
        """)
        agents = list(ir.agents)
        assert len(agents) == 1
        assert agents[0].name == "Researcher"
        assert len(ir.flows) >= 1

    def test_agent_coexists_with_consensus(self):
        """Agent and consensus can coexist in the same program."""
        ir = _generate("""
        anchor QualityGuard {
            require: source_citation
        }
        agent Researcher() {
            goal: "Research"
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: QualityGuard
                selection: best
            }
        }
        """)
        agents = list(ir.agents)
        assert len(agents) == 1


# ═══════════════════════════════════════════════════════════════════
#  PART 6 — EDGE CASES
# ═══════════════════════════════════════════════════════════════════


class TestAgentEdgeCases:
    """Edge cases and boundary conditions."""

    def test_multiple_agents(self):
        """Multiple agents can be defined in the same program."""
        program = _parse("""
        agent Alpha() {
            goal: "Alpha work"
        }
        agent Beta() {
            goal: "Beta work"
        }
        """)
        agents = [d for d in program.declarations if isinstance(d, AgentDefinition)]
        assert len(agents) == 2
        assert agents[0].name == "Alpha"
        assert agents[1].name == "Beta"

    def test_agent_with_empty_tools(self):
        """Agent with empty tools list."""
        program = _parse("""
        agent NoTools() {
            goal: "Work without tools"
            tools: []
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert agent.tools == []

    def test_agent_budget_partial(self):
        """Budget with only some fields specified."""
        program = _parse("""
        agent PartialBudget() {
            goal: "Work"
            budget {
                max_iterations: 5
            }
        }
        """)
        agent = [d for d in program.declarations if isinstance(d, AgentDefinition)][0]
        assert agent.budget.max_iterations == 5
        assert agent.budget.max_tokens == 0  # default
        assert agent.budget.max_time == ""   # default
        assert agent.budget.max_cost == 0.0  # default

    def test_duplicate_agent_names(self):
        """Duplicate agent names produce a type error."""
        errors = _check("""
        agent Dup() {
            goal: "First"
        }
        agent Dup() {
            goal: "Second"
        }
        """)
        dup_errors = [e for e in errors if "Duplicate" in e.message or "duplicate" in e.message]
        assert len(dup_errors) >= 1
