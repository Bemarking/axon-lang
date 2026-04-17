# AXON Compiler — Front-end pipeline + IR generation
# Source → Tokens → AST → Type-Checked AST → AXON IR

from .lexer import Lexer
from .parser import Parser
from .type_checker import TypeChecker
from .ir_generator import IRGenerator
from .ir_nodes import IRProgram
from .frontend import (
	FrontendCheckResult,
	FrontendCompileResult,
	FrontendDiagnostic,
	FrontendFacade,
	FrontendImplementation,
	NativeDevelopmentFrontendImplementation,
	NativeFrontendPlaceholder,
	PythonFrontendImplementation,
	frontend,
	get_frontend_implementation,
	reset_frontend_implementation,
	serialize_ir_program,
	set_frontend_implementation,
)
from .frontend_bootstrap import (
	FRONTEND_IMPLEMENTATION_ENV_VAR,
	bootstrap_frontend,
	create_frontend_implementation,
	current_frontend_selection,
	list_frontend_implementations,
	register_frontend_implementation,
)
