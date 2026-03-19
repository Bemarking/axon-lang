"""
AXON Runtime — Ontological Tool Synthesis Engine (ots)
======================================================
Implements the Sterile BDI Loop (Meta-Compiler Autopoietic) for JIT Tool Synthesis.
"""

import ast
import inspect
from typing import Any, Callable
import structlog
import traceback
from dataclasses import dataclass

from axon.runtime.tools.contract_tool import contract_tool
from axon.runtime.executor import ModelClient
from axon.runtime.retry_engine import RetryEngine
from axon.runtime.context_mgr import ContextManager
from axon.runtime.tracer import Tracer, TraceEventType

logger = structlog.get_logger(__name__)

class SandboxExecutionError(Exception):
    """Raised when the synthesized AST contains errors or unsafe operations."""
    def __init__(self, traceback: str):
        super().__init__(f"Sandbox Error: {traceback}")
        self.traceback = traceback

class OTSSynthesisFailedError(Exception):
    """Raised when the Homotopy search exhausts without converging."""
    pass

class AutopoieticSynthesizer:
    """
    The Meta-Compiler Autopoietic loop.
    Executes a Context Switch to lift a sterile sub-agent under draconian rules:
    - Context Isolation: Teleology only.
    - Epistemic Forcing: tau = 0.0
    - Turing Machine Sandbox: AST parsing local evaluation.
    - JIT Self-Healing: Traceback injection using the RetryEngine.
    """
    def __init__(self, client: ModelClient, retry_engine: RetryEngine):
        # Reciclamos la infraestructura sólida de AXON
        self.client = client
        self.retry_engine = retry_engine

    async def synthesize(self, ots_name: str, teleology: str, linear_constraints: list[tuple[str, Any]], tracer: Tracer) -> Callable:
        """
        Synthesize a tool mathematically from intent.
        """
        constraints_str = "\\n".join([f"- {k}: {v}" for k, v in linear_constraints])
        
        system_prompt = (
            "You are the AXON Compiler. Emit ONLY valid deterministic Python code containing a single async function. "
            "Do not use markdown. Do not provide explanations. Return pure Python."
        )
        
        user_prompt = (
            f"Synthesize capability: {ots_name}\\n"
            f"Teleology: {teleology}\\n\\n"
            f"Constraints:\\n{constraints_str}\\n\\n"
            "Return an async function that implements exactly this."
        )

        # 2. Bucle BDI de Auto-Sanación (Curry-Howard Compilation Loop)
        max_mutations = 3
        # Look for explicit max_mutations in constraints if any
        for k, v in linear_constraints:
            if k == "max_mutations":
                try:
                    max_mutations = int(v)
                except ValueError:
                    pass

        for attempt in range(max_mutations):
            # 3. Generación bajo rigor epistémico absoluto (know mode / τ = 0.0)
            try:
                # We call the model directly ignoring the main agent's user context
                response = await self.client.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    failure_context="" # For now, we inject failure into user_prompt manually
                )
                raw_code = response.content
                
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                if tracer:
                    tracer.emit_retry_attempt(step_name=f"ots_synthesize_{ots_name}", attempt=attempt, reason=tb)
                user_prompt += f"\\n\\nMODEL CALL FAILED:\\n{tb}\\nRetry."
                continue
            
            try:
                # 4. Verificación Sandbox (Aislamiento de la VRAM principal)
                local_env = self._evaluate_in_sandbox(raw_code)
                synthesized_function = self._extract_function(local_env)
                
                # 5. Sublimación Categórica (Aplicar Teoremas CT-2 y CT-3)
                # Wraps the newly evaluated function into Axon's execution fabric
                ephemeral_tool = contract_tool(
                    name=f"{ots_name}_{hash(raw_code) % 10000}",
                    epistemic="speculate",
                    effects=("pure", "epistemic:speculate"), # Nace dudosa
                )(synthesized_function)
                
                # Trace event para observabilidad extrema
                if tracer:
                    tracer.emit(TraceEventType.STEP_END, step_name=f"ots_synthesize_{ots_name}", data={"tool": ephemeral_tool.tool_name, "attempt": attempt})
                
                logger.info("OTS Synthesis successful.", teleology=teleology)
                return ephemeral_tool
                
            except SyntaxError as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                if tracer:
                    tracer.emit_retry_attempt(step_name=f"ots_synthesize_{ots_name}", attempt=attempt, reason=tb)
                user_prompt += f"\\n\\nAST Compilation failed:\\n{tb}\\nFix strictly."
                    
            except SandboxExecutionError as e:
                if tracer:
                    tracer.emit_retry_attempt(step_name=f"ots_synthesize_{ots_name}", attempt=attempt, reason=e.traceback)
                user_prompt += f"\\n\\nExecution validation failed:\\n{e.traceback}\\nFix strictly."
                
        # Proteger al agente principal: Si agota las mutaciones, fallar con gracia matemática
        raise OTSSynthesisFailedError("Homotopy search exhausted without converging to a valid morphism.")

    def _evaluate_in_sandbox(self, raw_code: str) -> dict:
        """
        Parses the code into an AST and evaluates it locally if safe.
        """
        clean_code = raw_code.strip()
        if clean_code.startswith("```python"):
            clean_code = clean_code[9:]
        if clean_code.startswith("```"):
            clean_code = clean_code[3:]
        if clean_code.endswith("```"):
            clean_code = clean_code[:-3]
        
        try:
            tree = ast.parse(clean_code)
        except SyntaxError as e:
            raise e
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ['eval', 'exec', 'open']:
                        try:
                            raise ValueError(f"Forbidden builtin '{node.func.id}' detected in AST.")
                        except Exception as ex:
                            tb = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
                            raise SandboxExecutionError(tb)
        
        local_env = {}
        try:
            code_obj = compile(tree, filename="<ast>", mode="exec")
            exec(code_obj, {"__builtins__": __builtins__}, local_env)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            raise SandboxExecutionError(tb)
            
        return local_env

    def _extract_function(self, local_env: dict) -> Callable:
        """Extracts the first async callable from the executed local environment."""
        for name, obj in local_env.items():
            if inspect.iscoroutinefunction(obj):
                return obj
            # Also allow normal function but we might need to wrap it
            if inspect.isfunction(obj):
                return obj
        
        raise SandboxExecutionError("No valid coroutine function found in the generated AST.")
