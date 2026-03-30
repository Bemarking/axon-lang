"""
AXON Backends — Abstract Base Backend
=======================================
Defines the interface that every model-specific backend must implement.

A backend's job is to take model-agnostic AXON IR and produce
provider-specific prompt structures ready for execution.

The separation is intentional:
  - IR Generator produces WHAT to do (model-agnostic)
  - Backend produces HOW to say it (model-specific)
  - Runtime (Phase 3) will EXECUTE it

Design decisions:
  1. compile_program() produces the full compiled output.
  2. compile_step() handles individual step compilation with context.
  3. compile_system_prompt() builds the system prompt from persona + anchors.
  4. compile_tool_spec() produces provider-native tool declarations.
  5. CompilationContext carries state between step compilations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import (
    IRAnchor,
    IRAgent,
    IRAggregate,
    IRAssociate,
    IRComputeApply,
    IRConsensus,
    IRContext,
    IRCorroborate,
    IRDataSpace,
    IRDeliberate,
    IRExplore,
    IRFlow,
    IRFocus,
    IRForge,
    IRIngest,
    IRNavigate,
    IRNode,
    IRPersona,
    IRProgram,
    IRPsycheSpec,
    IRRun,
    IRShield,
    IRShieldApply,
    IRStep,
    IRToolSpec,
    IROtsApply,
)

# IR types that represent Data Science operations
_DATA_SCIENCE_IR_TYPES = (IRDataSpace, IRIngest, IRFocus, IRAssociate, IRAggregate, IRExplore)

# IR types that represent compute budget / consensus / forge operations
_BUDGET_IR_TYPES = (IRDeliberate, IRConsensus, IRForge, IRAgent)

# IR types that represent Shield operations (security boundaries)
_SHIELD_IR_TYPES = (IRShieldApply,)

# IR types that represent MDN operations (multi-document navigation)
_MDN_IR_TYPES = (IRNavigate, IRCorroborate)

# IR types that represent Psyche operations (psychological-epistemic modeling)
_PSYCHE_IR_TYPES = (IRPsycheSpec,)

# IR types that represent OTS operations (ontological tool synthesis)
_OTS_IR_TYPES = (IROtsApply,)

# IR types that represent Compute operations (deterministic muscle)
_COMPUTE_IR_TYPES = (IRComputeApply,)


# ═══════════════════════════════════════════════════════════════════
#  COMPILATION OUTPUT CONTAINERS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CompiledStep:
    """
    The compilation result for a single cognitive step.

    Contains the prompt(s) to send to the model, any tool
    declarations needed, and output format expectations.
    """
    step_name: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    tool_declarations: list[dict[str, Any]] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        result: dict[str, Any] = {
            "step_name": self.step_name,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
        }
        if self.tool_declarations:
            result["tool_declarations"] = self.tool_declarations
        if self.output_schema:
            result["output_schema"] = self.output_schema
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class CompiledProgram:
    """
    The complete compilation output for an AXON program.

    Contains all compiled execution units (one per run statement),
    plus global metadata about the compilation.
    """
    backend_name: str = ""
    execution_units: list[CompiledExecutionUnit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "backend_name": self.backend_name,
            "execution_units": [u.to_dict() for u in self.execution_units],
            "metadata": self.metadata,
        }


@dataclass
class CompiledExecutionUnit:
    """
    A single execution unit — one run statement fully compiled.

    Contains the system prompt (persona + anchors), the ordered
    step prompts, and all tool declarations needed.
    """
    flow_name: str = ""
    persona_name: str = ""
    context_name: str = ""
    system_prompt: str = ""
    steps: list[CompiledStep] = field(default_factory=list)
    tool_declarations: list[dict[str, Any]] = field(default_factory=list)
    anchor_instructions: list[str] = field(default_factory=list)
    active_anchors: list[dict[str, Any]] = field(default_factory=list)
    effort: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        result: dict[str, Any] = {
            "flow_name": self.flow_name,
            "system_prompt": self.system_prompt,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.persona_name:
            result["persona_name"] = self.persona_name
        if self.context_name:
            result["context_name"] = self.context_name
        if self.tool_declarations:
            result["tool_declarations"] = self.tool_declarations
        if self.anchor_instructions:
            result["anchor_instructions"] = self.anchor_instructions
        if self.active_anchors:
            result["active_anchors"] = self.active_anchors
        if self.effort:
            result["effort"] = self.effort
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class CompilationContext:
    """
    Carries state through the step compilation process.

    Backends use this to track the current persona, active anchors,
    available tools, and any accumulated context from prior steps.
    """
    persona: IRPersona | None = None
    context: IRContext | None = None
    anchors: list[IRAnchor] = field(default_factory=list)
    tools: dict[str, IRToolSpec] = field(default_factory=dict)
    flow: IRFlow | None = None
    prior_step_names: list[str] = field(default_factory=list)
    effort: str = ""


# ═══════════════════════════════════════════════════════════════════
#  ABSTRACT BASE BACKEND
# ═══════════════════════════════════════════════════════════════════

class BaseBackend(ABC):
    """
    Abstract base class for all AXON model backends.

    Every backend must implement these four methods to compile
    AXON IR into provider-specific prompt structures.

    The default compile_program() implementation handles the
    orchestration logic (iterating runs, building context),
    delegating model-specific work to the abstract methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name of this backend (e.g., 'anthropic')."""
        ...

    def compile_program(self, ir: IRProgram) -> CompiledProgram:
        """
        Compile a complete IR program into backend-specific output.

        The default implementation iterates over all run statements,
        resolves their dependencies, and delegates step compilation
        to the abstract methods. Subclasses may override for custom
        orchestration.
        """
        # Build tool lookup from program-level declarations
        tools = {tool.name: tool for tool in ir.tools}

        execution_units: list[CompiledExecutionUnit] = []

        for run in ir.runs:
            if run.resolved_flow is None:
                continue  # unresolved run — skip (should not happen post-IR gen)

            # Build compilation context for this run
            ctx = CompilationContext(
                persona=run.resolved_persona,
                context=run.resolved_context,
                anchors=list(run.resolved_anchors),
                tools=tools,
                flow=run.resolved_flow,
                effort=run.effort,
            )

            # Phase 1: Compile system prompt (persona + anchors)
            system_prompt = self.compile_system_prompt(
                persona=run.resolved_persona,
                context=run.resolved_context,
                anchors=list(run.resolved_anchors),
            )

            # Phase 2: Compile anchor enforcement instructions
            anchor_instructions = [
                self.compile_anchor_instruction(anchor)
                for anchor in run.resolved_anchors
            ]

            # Phase 3: Compile tool declarations
            tool_declarations = [
                self.compile_tool_spec(tools[name])
                for name in tools
                if name in tools
            ]

            # Phase 4: Compile each step in the flow
            compiled_steps: list[CompiledStep] = []
            for step in run.resolved_flow.steps:
                # Data Science IR nodes bypass the model — compile as
                # metadata-only steps that the executor routes to the
                # DataScienceDispatcher.
                if isinstance(step, _DATA_SCIENCE_IR_TYPES):
                    ds_step = self._compile_data_science_step(step)
                    compiled_steps.append(ds_step)
                elif isinstance(step, _BUDGET_IR_TYPES):
                    budget_step = self._compile_budget_step(step, ctx)
                    compiled_steps.append(budget_step)
                elif isinstance(step, _SHIELD_IR_TYPES):
                    shield_step = self._compile_shield_step(step, ir)
                    compiled_steps.append(shield_step)
                elif isinstance(step, _MDN_IR_TYPES):
                    mdn_step = self._compile_mdn_step(step, ir)
                    compiled_steps.append(mdn_step)
                elif isinstance(step, _PSYCHE_IR_TYPES):
                    psyche_step = self._compile_psyche_step(step, ir)
                    compiled_steps.append(psyche_step)
                elif isinstance(step, _OTS_IR_TYPES):
                    ots_step = self._compile_ots_step(step, ir)
                    compiled_steps.append(ots_step)
                elif isinstance(step, _COMPUTE_IR_TYPES):
                    compute_step = self._compile_compute_step(step, ir)
                    compiled_steps.append(compute_step)
                else:
                    compiled = self.compile_step(step, ctx)
                    compiled_steps.append(compiled)
                ctx.prior_step_names.append(
                    step.name if isinstance(step, IRStep) else ""
                )

            active_anchors = [
                {"name": anchor.name, "require": anchor.require, "reject": anchor.reject}
                for anchor in run.resolved_anchors
            ]

            unit = CompiledExecutionUnit(
                flow_name=run.flow_name,
                persona_name=run.persona_name,
                context_name=run.context_name,
                system_prompt=system_prompt,
                steps=compiled_steps,
                tool_declarations=tool_declarations,
                anchor_instructions=anchor_instructions,
                active_anchors=active_anchors,
                effort=run.effort,
            )
            execution_units.append(unit)

        return CompiledProgram(
            backend_name=self.name,
            execution_units=execution_units,
        )

    @staticmethod
    def _compile_data_science_step(step: IRNode) -> CompiledStep:
        """Compile a Data Science IR node into a metadata-only step.

        These steps bypass the model — the executor routes them
        directly to the ``DataScienceDispatcher``.
        """
        from axon.compiler.ir_nodes import (
            IRAggregate,
            IRAssociate,
            IRDataSpace,
            IRExplore,
            IRFocus,
            IRIngest,
        )

        op: str = "unknown"
        args: dict[str, Any] = {}

        match step:
            case IRDataSpace(name=name):
                op = "dataspace"
                args = {"name": name}
            case IRIngest(source=src, target=tgt):
                op = "ingest"
                args = {"source": src, "target": tgt}
            case IRFocus(expression=expr):
                op = "focus"
                args = {"expression": expr}
            case IRAssociate(left=l, right=r, using_field=f):
                op = "associate"
                args = {"left": l, "right": r, "using_field": f}
            case IRAggregate(target=tgt, group_by=gb, alias=alias):
                op = "aggregate"
                args = {"target": tgt, "group_by": list(gb), "alias": alias}
            case IRExplore(target=tgt, limit=lim):
                op = "explore"
                args = {"target": tgt, "limit": lim}

        return CompiledStep(
            step_name=f"ds:{op}",
            user_prompt="",
            metadata={
                "data_science": {
                    "operation": op,
                    "args": args,
                },
            },
        )

    def _compile_budget_step(
        self, step: IRNode, ctx: CompilationContext,
    ) -> CompiledStep:
        """Compile a deliberate/consensus IR node into a metadata step.

        Unlike data science steps, budget steps may contain child
        IR nodes that need recursive compilation.
        """
        match step:
            case IRDeliberate(
                budget=budget, depth=depth,
                strategy=strategy, children=children,
            ):
                child_steps = [
                    self.compile_step(child, ctx)
                    for child in children
                ] if children else []
                return CompiledStep(
                    step_name="budget:deliberate",
                    user_prompt="",
                    metadata={
                        "deliberate": {
                            "budget": budget,
                            "depth": depth,
                            "strategy": strategy,
                            "child_steps": [
                                cs.to_dict() for cs in child_steps
                            ],
                        },
                    },
                )

            case IRConsensus(
                n_branches=n_branches, reward_anchor=reward_anchor,
                selection=selection, children=children,
            ):
                child_steps = [
                    self.compile_step(child, ctx)
                    for child in children
                ] if children else []
                return CompiledStep(
                    step_name="budget:consensus",
                    user_prompt="",
                    metadata={
                        "consensus": {
                            "n_branches": n_branches,
                            "reward_anchor": reward_anchor,
                            "selection": selection,
                            "child_steps": [
                                cs.to_dict() for cs in child_steps
                            ],
                        },
                    },
                )

            case IRForge(
                name=name, seed=seed, output_type=output_type,
                mode=mode, novelty=novelty, constraints=constraints,
                depth=depth, branches=branches, children=children,
            ):
                child_steps = [
                    self.compile_step(child, ctx)
                    for child in children
                ] if children else []
                return CompiledStep(
                    step_name=f"forge:{name}",
                    user_prompt="",
                    metadata={
                        "forge": {
                            "name": name,
                            "seed": seed,
                            "output_type": output_type,
                            "mode": mode,
                            "novelty": novelty,
                            "constraints": constraints,
                            "depth": depth,
                            "branches": branches,
                            "child_steps": [
                                cs.to_dict() for cs in child_steps
                            ],
                        },
                    },
                )

            case IRAgent(
                name=name, goal=goal, tools=tools,
                max_iterations=max_iter, max_tokens=max_tok,
                max_time=max_time, max_cost=max_cost,
                memory_ref=memory_ref,
                strategy=strategy, on_stuck=on_stuck,
                return_type=return_type, children=children,
            ):
                child_steps = [
                    self.compile_step(child, ctx)
                    for child in children
                ] if children else []
                return CompiledStep(
                    step_name=f"agent:{name}",
                    user_prompt="",
                    metadata={
                        "agent": {
                            "name": name,
                            "goal": goal,
                            "tools": list(tools),
                            "max_iterations": max_iter,
                            "max_tokens": max_tok,
                            "max_time": max_time,
                            "max_cost": max_cost,
                            "memory_ref": memory_ref,
                            "strategy": strategy,
                            "on_stuck": on_stuck,
                            "return_type": return_type,
                            "shield_ref": step.shield_ref if hasattr(step, 'shield_ref') else "",
                            "child_steps": [
                                cs.to_dict() for cs in child_steps
                            ],
                        },
                    },
                )

            case _:
                return CompiledStep(
                    step_name="budget:unknown",
                    user_prompt="",
                    metadata={},
                )

    @staticmethod
    def _compile_shield_step(
        step: IRShieldApply, ir: IRProgram,
    ) -> CompiledStep:
        """Compile a shield application into a metadata-only step.

        Shield steps don't go to the model — the runtime's
        SecurityExecutor processes them inline, performing:
          1. Taint analysis (Untrusted → Sanitized)
          2. Pattern/classifier scanning
          3. Capability enforcement
          4. PII redaction
        """
        # Resolve the shield definition from the program
        shield_def: dict[str, Any] = {}
        for shield in ir.shields:
            if shield.name == step.shield_name:
                shield_def = {
                    "name": shield.name,
                    "scan": list(shield.scan),
                    "strategy": shield.strategy,
                    "on_breach": shield.on_breach,
                    "severity": shield.severity,
                    "quarantine": shield.quarantine,
                    "max_retries": shield.max_retries,
                    "confidence_threshold": shield.confidence_threshold,
                    "allow_tools": list(shield.allow_tools),
                    "deny_tools": list(shield.deny_tools),
                    "sandbox": shield.sandbox,
                    "redact": list(shield.redact),
                    "log": shield.log,
                    "deflect_message": shield.deflect_message,
                }
                break

        return CompiledStep(
            step_name=f"shield:{step.shield_name}",
            user_prompt="",
            metadata={
                "shield_apply": {
                    "shield_name": step.shield_name,
                    "target": step.target,
                    "output_type": step.output_type,
                    "shield_definition": shield_def,
                },
            },
        )

    @staticmethod
    def _compile_mdn_step(
        step: IRNode, ir: IRProgram,
    ) -> CompiledStep:
        """Compile an MDN IR node into a metadata-only step.

        MDN steps bypass the model — the executor routes them
        to the corpus navigator engine for graph-based retrieval
        and corroboration.

        Handles two IR types:
          - ``IRNavigate`` with ``corpus_ref`` — corpus-level navigation
          - ``IRCorroborate``                  — cross-path verification
        """
        # Helper: resolve corpus spec from program
        def _resolve_corpus(name: str) -> dict[str, Any]:
            for spec in ir.corpus_specs:
                if spec.name == name:
                    return {
                        "name": spec.name,
                        "documents": [
                            {
                                "pix_ref": d.pix_ref,
                                "doc_type": d.doc_type,
                                "role": d.role,
                            }
                            for d in spec.documents
                        ],
                        "edges": [
                            {
                                "source_ref": e.source_ref,
                                "target_ref": e.target_ref,
                                "relation_type": e.relation_type,
                            }
                            for e in spec.edges
                        ],
                        "weights": dict(spec.weights),
                    }
            return {}

        match step:
            case IRNavigate(
                corpus_ref=corpus_ref,
                query=query,
                trail_enabled=trail,
                output_name=out_name,
                budget_depth=depth,
                budget_nodes=nodes,
                edge_filter=edge_f,
            ) if corpus_ref:
                corpus_def = _resolve_corpus(corpus_ref)
                return CompiledStep(
                    step_name=f"mdn:navigate:{corpus_ref}",
                    user_prompt="",
                    metadata={
                        "corpus_navigate": {
                            "corpus_ref": corpus_ref,
                            "corpus_definition": corpus_def,
                            "query": query,
                            "trail_enabled": trail,
                            "output_name": out_name,
                            "budget_depth": depth,
                            "budget_nodes": nodes,
                            "edge_filter": list(edge_f) if edge_f else [],
                        },
                    },
                )

            case IRCorroborate(
                navigate_ref=nav_ref,
                output_name=out_name,
            ):
                return CompiledStep(
                    step_name=f"mdn:corroborate:{nav_ref}",
                    user_prompt="",
                    metadata={
                        "corroborate": {
                            "navigate_ref": nav_ref,
                            "output_name": out_name,
                        },
                    },
                )

            case _:
                # IRNavigate without corpus_ref (single-doc PIX mode)
                # falls through to regular step compilation
                return CompiledStep(
                    step_name="mdn:unknown",
                    user_prompt="",
                    metadata={},
                )

    @staticmethod
    def _compile_psyche_step(
        step: IRPsycheSpec, ir: IRProgram,
    ) -> CompiledStep:
        """Compile a psyche spec into a metadata-only step.

        Psyche steps don't go to the model directly — the runtime's
        PsycheExecutor processes them to initialize the PEM engine:
          1. Cognitive manifold construction (§1 — Riemannian dynamics)
          2. Density matrix allocation (§2 — quantum cognitive probability)
          3. Active inference loop setup (§3 — free energy minimization)
          4. Safety type enforcement (§4 — NonDiagnostic constraint)

        The compiled metadata carries all configuration needed to
        instantiate the PsycheEngine at runtime.
        """
        return CompiledStep(
            step_name=f"psyche:{step.name}",
            user_prompt="",
            metadata={
                "psyche_spec": {
                    "name": step.name,
                    "dimensions": list(step.dimensions),
                    "manifold": {
                        "curvature": dict(step.manifold_curvature),
                        "noise": step.manifold_noise,
                        "momentum": step.manifold_momentum,
                    },
                    "safety_constraints": list(step.safety_constraints),
                    "quantum_enabled": step.quantum_enabled,
                    "inference_mode": step.inference_mode,
                },
            },
        )

    @staticmethod
    def _compile_ots_step(
        step: IROtsApply, ir: IRProgram,
    ) -> CompiledStep:
        """Compile an OTS application into a metadata-only step.

        OTS steps don't go to the model directly during standard execution —
        the runtime's OtsDispatcher processes them via Just-In-Time synthesis.
        """
        # Resolve the OTS definition from the program
        ots_def: dict[str, Any] = {}
        for spec in ir.ots_specs:
            if spec.name == step.ots_name:
                ots_def = {
                    "name": spec.name,
                    "types": list(spec.types),
                    "teleology": spec.teleology,
                    "homotopy_search": spec.homotopy_search,
                    "linear_constraints": list(spec.linear_constraints),
                    "loss_function": spec.loss_function,
                }
                break

        return CompiledStep(
            step_name=f"ots:{step.ots_name}",
            user_prompt="",
            metadata={
                "ots_apply": {
                    "ots_name": step.ots_name,
                    "target": step.target,
                    "output_type": step.output_type,
                    "ots_definition": ots_def,
                },
            },
        )

    @staticmethod
    def _compile_compute_step(
        step: IRComputeApply, ir: IRProgram,
    ) -> CompiledStep:
        """Compile a compute application into a metadata-only step.

        Compute steps bypass the model entirely — the runtime's
        NativeComputeDispatcher executes them as deterministic
        Fast-Path operations (System 1).
        """
        compute_def: dict[str, Any] = {}
        for spec in ir.compute_specs:
            if spec.name == step.compute_name:
                compute_def = {
                    "name": spec.name,
                    "inputs": [
                        {"name": p.name, "type": p.type_name}
                        for p in spec.inputs
                    ],
                    "output_type": spec.output_type,
                    "logic_source": spec.logic_source,
                    "shield_ref": spec.shield_ref,
                    "verified": spec.verified,
                }
                break

        return CompiledStep(
            step_name=f"compute:{step.compute_name}",
            user_prompt="",
            metadata={
                "compute": {
                    "compute_name": step.compute_name,
                    "arguments": list(step.arguments),
                    "output_name": step.output_name,
                    "compute_definition": compute_def,
                },
            },
        )

    @abstractmethod
    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        """
        Compile a single IR step into a backend-specific prompt.

        Args:
            step: The IR node to compile (IRStep, IRProbe, etc.)
            context: The current compilation context.

        Returns:
            A CompiledStep with model-specific prompts.
        """
        ...

    @abstractmethod
    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        """
        Build the system prompt from persona, context, and anchors.

        This is the Anchor Enforcer's injection point: all hard
        constraints are woven into the system-level instructions
        that the model receives before any user messages.
        """
        ...

    @abstractmethod
    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        """
        Compile a tool specification into the backend's native format.

        E.g., for Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        E.g., for Gemini: {"function_declarations": [...]}
        """
        ...

    def compile_anchor_instruction(self, anchor: IRAnchor) -> str:
        """
        Compile a single anchor into a natural-language enforcement
        instruction for inclusion in the system prompt.

        The default implementation produces a structured constraint
        block. Backends may override for provider-specific formatting.
        """
        parts: list[str] = [f"[CONSTRAINT: {anchor.name}]"]

        if anchor.require:
            parts.append(f"  REQUIRE: {anchor.require}")
        if anchor.reject:
            parts.append(f"  REJECT: {', '.join(anchor.reject)}")
        if anchor.enforce:
            parts.append(f"  ENFORCE: {anchor.enforce}")
        if anchor.confidence_floor is not None:
            parts.append(
                f"  CONFIDENCE FLOOR: {anchor.confidence_floor}"
            )
        if anchor.unknown_response:
            parts.append(
                f"  WHEN UNCERTAIN: \"{anchor.unknown_response}\""
            )
        if anchor.on_violation:
            violation = anchor.on_violation
            if anchor.on_violation_target:
                violation += f" {anchor.on_violation_target}"
            parts.append(f"  ON VIOLATION: {violation}")

        return "\n".join(parts)

    # ═══════════════════════════════════════════════════════════════
    #  AGENT-SPECIFIC COMPILATION — BDI Prompt Engineering
    # ═══════════════════════════════════════════════════════════════

    @abstractmethod
    def compile_agent_system_prompt(
        self,
        agent_name: str,
        goal: str,
        strategy: str,
        tools: list[str],
        epistemic_state: str,
        iteration: int,
        max_iterations: int,
    ) -> str:
        """
        Build a provider-optimized system prompt for agent BDI cycles.

        This method is called by the executor during each BDI cycle
        to generate the system-level instructions that configure the
        LLM for the agent's current cognitive state.

        ╔══════════════════════════════════════════════════════════╗
        ║  FORMAL CONTRACT                                        ║
        ╠══════════════════════════════════════════════════════════╣
        ║  Input:                                                  ║
        ║    agent_name — identifier for the BDI entity            ║
        ║    goal — Davidson pro-attitude (desired state)          ║
        ║    strategy ∈ {react, reflexion, plan_and_execute,       ║
        ║               custom}                                    ║
        ║    tools — available tool names from plan library        ║
        ║    epistemic_state ∈ {doubt, speculate, believe, know}   ║
        ║    iteration — current cycle index (0-based)             ║
        ║    max_iterations — budget cap                           ║
        ║                                                          ║
        ║  Output:                                                 ║
        ║    Provider-native system prompt string encoding:        ║
        ║    - Agent identity and role framing                     ║
        ║    - BDI cognitive cycle instructions                    ║
        ║    - Strategy-specific reasoning protocol                ║
        ║    - Available capabilities enumeration                  ║
        ║    - Epistemic state awareness                           ║
        ║    - Convergence budget constraints                      ║
        ╚══════════════════════════════════════════════════════════╝

        Args:
            agent_name: The declared name of the agent.
            goal: The agent's goal statement (desire).
            strategy: The deliberation strategy to follow.
            tools: List of available tool names.
            epistemic_state: Current position on the Tarski lattice.
            iteration: Current BDI cycle number (0-based).
            max_iterations: Maximum cycles allowed by budget.

        Returns:
            A fully formatted system prompt string.
        """
        ...

    def compile_agent_tool_binding(
        self,
        tool_names: list[str],
        available_tools: dict[str, IRToolSpec],
    ) -> list[dict[str, Any]]:
        """
        Resolve agent tool references to compiled tool declarations.

        This default implementation iterates the agent's declared
        tool names, resolves each against the program-level tool
        registry, and compiles them using the backend's native
        ``compile_tool_spec()`` method.

        The resolution follows linear logic resource semantics:
        each tool binding is a resource allocated to the agent's
        plan library, available for consumption during BDI cycles.

        Args:
            tool_names: Tool names declared in the agent block.
            available_tools: Program-level tool registry (name → IRToolSpec).

        Returns:
            List of provider-native tool declarations (dicts).
        """
        bound: list[dict[str, Any]] = []
        for name in tool_names:
            if name in available_tools:
                bound.append(self.compile_tool_spec(available_tools[name]))
        return bound
