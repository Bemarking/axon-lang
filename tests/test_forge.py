"""
AXON Test Suite — forge Primitive
===================================

Tests for the directed creative synthesis primitive (Phase 11):
  • forge — Poincaré pipeline orchestrator (Preparation → Incubation →
             Illumination → Verification) with Boden mode control

Coverage: Lexer → Parser → AST → TypeChecker → IRGenerator → IR

Structure mirrors test_deliberate_consensus.py.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import (
    FlowDefinition,
    ForgeBlock,
    StepNode,
)
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRForge,
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


class TestForgeTokens:
    """Lexer recognizes 'forge' keyword."""

    def test_forge_keyword(self):
        tokens = _lex("forge")
        assert tokens[0].type == TokenType.FORGE
        assert tokens[0].value == "forge"

    def test_forge_not_identifier(self):
        tokens = _lex("forge")
        assert tokens[0].type != TokenType.IDENTIFIER

    def test_forge_case_sensitive(self):
        tokens = _lex("Forge")
        assert tokens[0].type == TokenType.IDENTIFIER


# ═══════════════════════════════════════════════════════════════════
#  PART 2 — PARSER
# ═══════════════════════════════════════════════════════════════════


class TestForgeParser:
    """Parser produces ForgeBlock AST nodes."""

    def test_parse_forge_full(self):
        program = _parse("""
        anchor GoldenRatio {
            require: aesthetic_harmony
        }
        flow Create(seed: String) -> Visual {
            forge Painting(seed: "aurora boreal") -> Visual {
                mode: combinatory
                novelty: 0.8
                constraints: GoldenRatio
                depth: 3
                branches: 5
            }
        }
        """)
        flow = [d for d in program.declarations if isinstance(d, FlowDefinition)][0]
        assert len(flow.body) == 1
        forge = flow.body[0]
        assert isinstance(forge, ForgeBlock)
        assert forge.name == "Painting"
        assert forge.seed == "aurora boreal"
        assert forge.output_type == "Visual"
        assert forge.mode == "combinatory"
        assert forge.novelty == 0.8
        assert forge.constraints == "GoldenRatio"
        assert forge.depth == 3
        assert forge.branches == 5

    def test_parse_forge_minimal(self):
        program = _parse("""
        flow Create(seed: String) -> Visual {
            forge ArtPiece(seed: "sunset") -> Visual {
                mode: exploratory
                depth: 2
                branches: 3
            }
        }
        """)
        forge = program.declarations[0].body[0]
        assert isinstance(forge, ForgeBlock)
        assert forge.name == "ArtPiece"
        assert forge.seed == "sunset"
        assert forge.mode == "exploratory"
        assert forge.constraints == ""  # default

    def test_parse_forge_transformational(self):
        program = _parse("""
        flow Create(seed: String) -> Visual {
            forge Revolution(seed: "classical architecture") -> Visual {
                mode: transformational
                novelty: 0.95
                depth: 5
                branches: 7
            }
        }
        """)
        forge = program.declarations[0].body[0]
        assert forge.mode == "transformational"
        assert forge.novelty == 0.95
        assert forge.depth == 5
        assert forge.branches == 7

    def test_parse_forge_with_step(self):
        program = _parse("""
        flow Create(seed: String) -> Visual {
            forge Render(seed: "ocean waves") -> Visual {
                mode: combinatory
                depth: 2
                branches: 3
                step Refine {
                    ask: "Polish the output"
                    output: Visual
                }
            }
        }
        """)
        forge = program.declarations[0].body[0]
        assert isinstance(forge, ForgeBlock)
        assert len(forge.body) == 1
        assert isinstance(forge.body[0], StepNode)
        assert forge.body[0].name == "Refine"


# ═══════════════════════════════════════════════════════════════════
#  PART 3 — TYPE CHECKER
# ═══════════════════════════════════════════════════════════════════


class TestForgeTypeChecker:
    """Type checker validates forge blocks."""

    def test_valid_forge(self):
        errors = _check("""
        anchor Beauty {
            require: aesthetic_harmony
        }
        flow Create(seed: String) -> Visual {
            forge Painting(seed: "aurora") -> Visual {
                mode: combinatory
                novelty: 0.8
                constraints: Beauty
                depth: 3
                branches: 5
            }
        }
        """)
        assert len(errors) == 0

    def test_invalid_mode(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: random
                depth: 2
                branches: 3
            }
        }
        """)
        mode_errors = [e for e in errors if "mode" in e.message]
        assert len(mode_errors) >= 1

    def test_novelty_out_of_range_high(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                novelty: 1.5
                depth: 2
                branches: 3
            }
        }
        """)
        novelty_errors = [e for e in errors if "novelty" in e.message]
        assert len(novelty_errors) >= 1

    def test_novelty_out_of_range_low(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                novelty: -0.1
                depth: 2
                branches: 3
            }
        }
        """)
        novelty_errors = [e for e in errors if "novelty" in e.message]
        assert len(novelty_errors) >= 1

    def test_branches_less_than_2(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                depth: 2
                branches: 1
            }
        }
        """)
        branch_errors = [e for e in errors if "branches" in e.message]
        assert len(branch_errors) >= 1

    def test_depth_less_than_1(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                depth: 0
                branches: 3
            }
        }
        """)
        depth_errors = [e for e in errors if "depth" in e.message]
        assert len(depth_errors) >= 1

    def test_undefined_constraint_anchor(self):
        errors = _check("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                constraints: NonExistentAnchor
                depth: 2
                branches: 3
            }
        }
        """)
        anchor_errors = [e for e in errors if "Undefined" in e.message or "anchor" in e.message.lower()]
        assert len(anchor_errors) >= 1

    def test_constraint_must_be_anchor_not_persona(self):
        errors = _check("""
        persona Artist {
            domain: ["visual arts"]
        }
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                constraints: Artist
                depth: 2
                branches: 3
            }
        }
        """)
        kind_errors = [e for e in errors if "not an anchor" in e.message]
        assert len(kind_errors) >= 1

    def test_valid_all_modes(self):
        """All three Boden modes should pass validation."""
        for mode in ("combinatory", "exploratory", "transformational"):
            errors = _check(f"""
            flow Create(seed: String) -> Visual {{
                forge Art(seed: "test") -> Visual {{
                    mode: {mode}
                    depth: 2
                    branches: 3
                }}
            }}
            """)
            mode_errors = [e for e in errors if "mode" in e.message]
            assert len(mode_errors) == 0, f"Mode '{mode}' should be valid"


# ═══════════════════════════════════════════════════════════════════
#  PART 4 — IR GENERATOR
# ═══════════════════════════════════════════════════════════════════


class TestForgeIR:
    """IR generator produces IRForge nodes."""

    def test_ir_forge_basic(self):
        ir = _generate("""
        anchor Beauty {
            require: aesthetic_harmony
        }
        flow Create(seed: String) -> Visual {
            forge Painting(seed: "aurora") -> Visual {
                mode: combinatory
                novelty: 0.8
                constraints: Beauty
                depth: 3
                branches: 5
            }
        }
        """)
        flow = [f for f in ir.flows if f.name == "Create"][0]
        assert len(flow.steps) == 1
        forge = flow.steps[0]
        assert isinstance(forge, IRForge)
        assert forge.node_type == "forge"
        assert forge.name == "Painting"
        assert forge.seed == "aurora"
        assert forge.output_type == "Visual"
        assert forge.mode == "combinatory"
        assert forge.novelty == 0.8
        assert forge.constraints == "Beauty"
        assert forge.depth == 3
        assert forge.branches == 5

    def test_ir_forge_with_children(self):
        ir = _generate("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "waves") -> Visual {
                mode: exploratory
                depth: 2
                branches: 3
                step Refine {
                    ask: "Polish the output"
                    output: Visual
                }
            }
        }
        """)
        forge = ir.flows[0].steps[0]
        assert isinstance(forge, IRForge)
        assert len(forge.children) == 1
        assert isinstance(forge.children[0], IRStep)
        assert forge.children[0].name == "Refine"

    def test_ir_forge_serialization(self):
        ir = _generate("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "mountains") -> Visual {
                mode: transformational
                novelty: 0.9
                depth: 4
                branches: 7
            }
        }
        """)
        forge = ir.flows[0].steps[0]
        d = forge.to_dict()
        assert d["node_type"] == "forge"
        assert d["name"] == "Art"
        assert d["seed"] == "mountains"
        assert d["mode"] == "transformational"
        assert d["novelty"] == 0.9
        assert d["depth"] == 4
        assert d["branches"] == 7

    def test_ir_forge_defaults(self):
        ir = _generate("""
        flow Create(seed: String) -> Visual {
            forge Art(seed: "test") -> Visual {
                mode: combinatory
                depth: 2
                branches: 3
            }
        }
        """)
        forge = ir.flows[0].steps[0]
        assert forge.constraints == ""  # default
        assert forge.novelty == 0.7     # default from AST


# ═══════════════════════════════════════════════════════════════════
#  PART 5 — INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestForgeInsideFlow:
    """forge block compiles correctly inside full flows."""

    def test_forge_coexists_with_steps(self):
        ir = _generate("""
        flow Pipeline(data: String) -> Report {
            step Research {
                ask: "Research the topic {{data}}"
                output: Report
            }
            forge Synthesize(seed: "novel insights") -> Report {
                mode: combinatory
                depth: 2
                branches: 3
            }
        }
        """)
        flow = ir.flows[0]
        assert len(flow.steps) == 2
        assert isinstance(flow.steps[0], IRStep)
        assert isinstance(flow.steps[1], IRForge)
        assert flow.steps[1].name == "Synthesize"

    def test_forge_with_deliberate_and_consensus(self):
        """forge can coexist with deliberate and consensus in the same flow."""
        ir = _generate("""
        anchor QualityGuard {
            require: source_citation
        }
        flow FullCreative(data: String) -> Report {
            deliberate {
                budget: 8000
                depth: 3
                strategy: thorough
                step Analyze {
                    ask: "Deep analysis"
                    output: Report
                }
            }
            forge Create(seed: "creative synthesis") -> Report {
                mode: exploratory
                constraints: QualityGuard
                depth: 2
                branches: 5
            }
            consensus {
                branches: 3
                reward: QualityGuard
                selection: best
                step Verify {
                    ask: "Verify results"
                    output: Report
                }
            }
        }
        """)
        flow = [f for f in ir.flows if f.name == "FullCreative"][0]
        assert len(flow.steps) == 3
        from axon.compiler.ir_nodes import IRDeliberate, IRConsensus
        assert isinstance(flow.steps[0], IRDeliberate)
        assert isinstance(flow.steps[1], IRForge)
        assert isinstance(flow.steps[2], IRConsensus)
