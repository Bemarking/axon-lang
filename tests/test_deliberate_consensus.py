"""
AXON Test Suite — deliberate & consensus Primitives
=====================================================

Tests for the two new Paradigm Shift primitives (Phase 10):
  • deliberate — compute budget envelope (System 2 depth control)
  • consensus  — Best-of-N selection with reward-based filtering

Coverage: Lexer → Parser → AST → TypeChecker → IRGenerator → IR

Structure mirrors test_paradigm_shifts.py.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import (
    ConsensusBlock,
    DeliberateBlock,
    FlowDefinition,
    StepNode,
)
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRConsensus,
    IRDeliberate,
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
#  PART 1 — deliberate
# ═══════════════════════════════════════════════════════════════════


class TestDeliberateTokens:
    """Lexer recognizes 'deliberate' keyword."""

    def test_deliberate_keyword(self):
        tokens = _lex("deliberate")
        assert tokens[0].type == TokenType.DELIBERATE
        assert tokens[0].value == "deliberate"

    def test_deliberate_not_identifier(self):
        tokens = _lex("deliberate")
        assert tokens[0].type != TokenType.IDENTIFIER


class TestDeliberateParser:
    """Parser produces DeliberateBlock AST nodes."""

    def test_parse_empty_deliberate(self):
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
        assert len(flow.body) == 1
        delib = flow.body[0]
        assert isinstance(delib, DeliberateBlock)
        assert delib.budget == 8000
        assert delib.depth == 3
        assert delib.strategy == "thorough"

    def test_parse_deliberate_with_step(self):
        program = _parse("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 4000
                strategy: quick
                step Summarize {
                    ask: "Summarize the topic"
                    output: Report
                }
            }
        }
        """)
        flow = program.declarations[0]
        delib = flow.body[0]
        assert isinstance(delib, DeliberateBlock)
        assert delib.budget == 4000
        assert delib.strategy == "quick"
        assert len(delib.body) == 1
        assert isinstance(delib.body[0], StepNode)
        assert delib.body[0].name == "Summarize"

    def test_parse_deliberate_defaults(self):
        program = _parse("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 2000
            }
        }
        """)
        delib = program.declarations[0].body[0]
        assert isinstance(delib, DeliberateBlock)
        assert delib.depth == 1       # default
        assert delib.strategy == "balanced"  # default

    def test_parse_deliberate_strategy_exhaustive(self):
        program = _parse("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                strategy: exhaustive
                depth: 5
                budget: 16000
            }
        }
        """)
        delib = program.declarations[0].body[0]
        assert delib.strategy == "exhaustive"
        assert delib.depth == 5
        assert delib.budget == 16000


class TestDeliberateTypeChecker:
    """Type checker validates deliberate blocks."""

    def test_valid_deliberate(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
            }
        }
        """)
        assert len(errors) == 0

    def test_negative_budget(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: -100
                depth: 1
            }
        }
        """)
        budget_errors = [e for e in errors if "budget" in e.message]
        assert len(budget_errors) >= 1

    def test_zero_depth(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 1000
                depth: 0
            }
        }
        """)
        depth_errors = [e for e in errors if "depth" in e.message]
        assert len(depth_errors) >= 1

    def test_invalid_strategy(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 1000
                strategy: ultramega
            }
        }
        """)
        strat_errors = [e for e in errors if "strategy" in e.message]
        assert len(strat_errors) >= 1

    def test_valid_strategy_quick(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 1000
                strategy: quick
            }
        }
        """)
        strat_errors = [e for e in errors if "strategy" in e.message]
        assert len(strat_errors) == 0

    def test_valid_strategy_balanced(self):
        errors = _check("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 1000
                strategy: balanced
            }
        }
        """)
        assert len(errors) == 0


class TestDeliberateIR:
    """IR generator produces IRDeliberate nodes."""

    def test_ir_deliberate_basic(self):
        ir = _generate("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
            }
        }
        """)
        flow = ir.flows[0]
        assert len(flow.steps) == 1
        delib = flow.steps[0]
        assert isinstance(delib, IRDeliberate)
        assert delib.node_type == "deliberate"
        assert delib.budget == 8000
        assert delib.depth == 3
        assert delib.strategy == "thorough"

    def test_ir_deliberate_with_children(self):
        ir = _generate("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 4000
                step Summarize {
                    ask: "Summarize the topic"
                    output: Report
                }
            }
        }
        """)
        delib = ir.flows[0].steps[0]
        assert isinstance(delib, IRDeliberate)
        assert len(delib.children) == 1
        assert isinstance(delib.children[0], IRStep)
        assert delib.children[0].name == "Summarize"

    def test_ir_deliberate_serialization(self):
        ir = _generate("""
        flow Analyze(topic: String) -> Report {
            deliberate {
                budget: 2000
                depth: 2
                strategy: quick
            }
        }
        """)
        delib = ir.flows[0].steps[0]
        d = delib.to_dict()
        assert d["node_type"] == "deliberate"
        assert d["budget"] == 2000
        assert d["depth"] == 2
        assert d["strategy"] == "quick"


# ═══════════════════════════════════════════════════════════════════
#  PART 2 — consensus
# ═══════════════════════════════════════════════════════════════════


class TestConsensusTokens:
    """Lexer recognizes 'consensus' keyword."""

    def test_consensus_keyword(self):
        tokens = _lex("consensus")
        assert tokens[0].type == TokenType.CONSENSUS
        assert tokens[0].value == "consensus"

    def test_consensus_not_identifier(self):
        tokens = _lex("consensus")
        assert tokens[0].type != TokenType.IDENTIFIER


class TestConsensusParser:
    """Parser produces ConsensusBlock AST nodes."""

    def test_parse_consensus_full(self):
        program = _parse("""
        anchor AccuracyAnchor {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: AccuracyAnchor
                selection: best
            }
        }
        """)
        flow = [d for d in program.declarations if isinstance(d, FlowDefinition)][0]
        assert len(flow.body) == 1
        cons = flow.body[0]
        assert isinstance(cons, ConsensusBlock)
        assert cons.branches == 5
        assert cons.reward_anchor == "AccuracyAnchor"
        assert cons.selection == "best"

    def test_parse_consensus_with_step(self):
        program = _parse("""
        anchor QualityAnchor {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
                reward: QualityAnchor
                selection: majority
                step Categorize {
                    ask: "Classify the data"
                    output: FactualClaim
                }
            }
        }
        """)
        flow = [d for d in program.declarations if isinstance(d, FlowDefinition)][0]
        cons = flow.body[0]
        assert isinstance(cons, ConsensusBlock)
        assert cons.selection == "majority"
        assert len(cons.body) == 1
        assert isinstance(cons.body[0], StepNode)
        assert cons.body[0].name == "Categorize"

    def test_parse_consensus_defaults(self):
        program = _parse("""
        anchor TestAnchor {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: TestAnchor
            }
        }
        """)
        cons = [d for d in program.declarations if isinstance(d, FlowDefinition)][0].body[0]
        assert isinstance(cons, ConsensusBlock)
        assert cons.selection == "best"  # default


class TestConsensusTypeChecker:
    """Type checker validates consensus blocks."""

    def test_valid_consensus(self):
        errors = _check("""
        anchor AccuracyGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: AccuracyGuard
                selection: best
            }
        }
        """)
        assert len(errors) == 0

    def test_consensus_needs_at_least_2_branches(self):
        errors = _check("""
        anchor AccuracyGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 1
                reward: AccuracyGuard
            }
        }
        """)
        branch_errors = [e for e in errors if "branches" in e.message]
        assert len(branch_errors) >= 1

    def test_consensus_requires_reward_anchor(self):
        errors = _check("""
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
            }
        }
        """)
        reward_errors = [e for e in errors if "reward" in e.message]
        assert len(reward_errors) >= 1

    def test_consensus_invalid_selection(self):
        errors = _check("""
        anchor AccuracyGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
                reward: AccuracyGuard
                selection: random
            }
        }
        """)
        sel_errors = [e for e in errors if "selection" in e.message]
        assert len(sel_errors) >= 1

    def test_consensus_undefined_anchor(self):
        errors = _check("""
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
                reward: NonExistentAnchor
            }
        }
        """)
        anchor_errors = [e for e in errors if "Undefined" in e.message or "anchor" in e.message.lower()]
        assert len(anchor_errors) >= 1

    def test_consensus_reward_must_be_anchor_not_persona(self):
        errors = _check("""
        persona Analyst {
            domain: ["data analysis"]
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
                reward: Analyst
            }
        }
        """)
        kind_errors = [e for e in errors if "not an anchor" in e.message]
        assert len(kind_errors) >= 1

    def test_consensus_majority_selection_valid(self):
        errors = _check("""
        anchor AccuracyGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: AccuracyGuard
                selection: majority
            }
        }
        """)
        sel_errors = [e for e in errors if "selection" in e.message]
        assert len(sel_errors) == 0


class TestConsensusIR:
    """IR generator produces IRConsensus nodes."""

    def test_ir_consensus_basic(self):
        ir = _generate("""
        anchor AccuracyGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 5
                reward: AccuracyGuard
                selection: best
            }
        }
        """)
        flow = [f for f in ir.flows if f.name == "Classify"][0]
        assert len(flow.steps) == 1
        cons = flow.steps[0]
        assert isinstance(cons, IRConsensus)
        assert cons.node_type == "consensus"
        assert cons.n_branches == 5
        assert cons.reward_anchor == "AccuracyGuard"
        assert cons.selection == "best"

    def test_ir_consensus_with_children(self):
        ir = _generate("""
        anchor QualityGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 3
                reward: QualityGuard
                step Categorize {
                    ask: "Classify the data"
                    output: FactualClaim
                }
            }
        }
        """)
        cons = [f for f in ir.flows if f.name == "Classify"][0].steps[0]
        assert isinstance(cons, IRConsensus)
        assert len(cons.children) == 1
        assert isinstance(cons.children[0], IRStep)

    def test_ir_consensus_serialization(self):
        ir = _generate("""
        anchor QualityGuard {
            require: source_citation
        }
        flow Classify(data: String) -> FactualClaim {
            consensus {
                branches: 7
                reward: QualityGuard
                selection: majority
            }
        }
        """)
        cons = [f for f in ir.flows if f.name == "Classify"][0].steps[0]
        d = cons.to_dict()
        assert d["node_type"] == "consensus"
        assert d["n_branches"] == 7
        assert d["reward_anchor"] == "QualityGuard"
        assert d["selection"] == "majority"


# ═══════════════════════════════════════════════════════════════════
#  PART 3 — INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestDeliberateInsideFlow:
    """deliberate block compiles correctly inside full flows."""

    def test_deliberate_coexists_with_steps(self):
        ir = _generate("""
        flow Pipeline(data: String) -> Report {
            step Extract {
                ask: "Extract entities from {{data}}"
                output: EntityMap
            }
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
                step Analyze {
                    ask: "Deep analysis of entities"
                    output: Report
                }
            }
        }
        """)
        flow = ir.flows[0]
        assert len(flow.steps) == 2
        assert isinstance(flow.steps[0], IRStep)
        assert isinstance(flow.steps[1], IRDeliberate)
        assert flow.steps[1].budget == 8000


class TestConsensusInsideFlow:
    """consensus block compiles correctly inside full flows."""

    def test_consensus_coexists_with_steps(self):
        ir = _generate("""
        anchor FactChecker {
            require: source_citation
        }
        flow Pipeline(data: String) -> Report {
            step Extract {
                ask: "Extract entities from {{data}}"
                output: EntityMap
            }
            consensus {
                branches: 5
                reward: FactChecker
                selection: best
                step Verify {
                    ask: "Verify the extracted entities"
                    output: Report
                }
            }
        }
        """)
        flow = [f for f in ir.flows if f.name == "Pipeline"][0]
        assert len(flow.steps) == 2
        assert isinstance(flow.steps[0], IRStep)
        assert isinstance(flow.steps[1], IRConsensus)
        assert flow.steps[1].n_branches == 5


class TestDeliberateConsensusComposed:
    """Both primitives can coexist in the same flow."""

    def test_deliberate_then_consensus(self):
        ir = _generate("""
        anchor QualityGuard {
            require: source_citation
        }
        flow FullPipeline(data: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
                step Analyze {
                    ask: "Deep analysis"
                    output: Report
                }
            }
            consensus {
                branches: 5
                reward: QualityGuard
                selection: best
                step Verify {
                    ask: "Verify analysis"
                    output: Report
                }
            }
        }
        """)
        flow = [f for f in ir.flows if f.name == "FullPipeline"][0]
        assert len(flow.steps) == 2
        assert isinstance(flow.steps[0], IRDeliberate)
        assert isinstance(flow.steps[1], IRConsensus)
