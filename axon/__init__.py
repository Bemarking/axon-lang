"""
AXON Language Compiler
The first programming language for AI cognition.
"""

from __future__ import annotations

__version__ = "0.25.4"

# ── Public API ────────────────────────────────────────────────────
# These imports define what ``import axon`` gives you.

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ast_nodes import ProgramNode
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRProgram
from axon.compiler.errors import (
    AxonError,
    AxonLexerError,
    AxonParseError,
    AxonTypeError,
)
from axon.backends import get_backend, BACKEND_REGISTRY

__all__ = [
    "__version__",
    # Compiler pipeline
    "Lexer",
    "Parser",
    "ProgramNode",
    "TypeChecker",
    "IRGenerator",
    "IRProgram",
    # Errors
    "AxonError",
    "AxonLexerError",
    "AxonParseError",
    "AxonTypeError",
    # Backends
    "get_backend",
    "BACKEND_REGISTRY",
]
