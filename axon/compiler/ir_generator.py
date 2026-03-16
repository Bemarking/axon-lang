"""
AXON Compiler — IR Generator
==============================
Transforms a validated AST into the AXON Intermediate Representation.

This is the bridge between the language front-end (Phase 1) and the
backend prompt compilers (Phase 2). It performs three critical roles:

  1. AST LOWERING — Converts each AST node into its IR equivalent.
  2. CROSS-REFERENCE RESOLUTION — Links run statements to their
     referenced personas, contexts, flows, and anchors by name.
  3. TOOL RESOLUTION — Maps tool usage within steps to their
     corresponding IRToolSpec declarations.

The generator uses a visitor pattern: one _visit_* method per AST
node type, dispatched via a central registry. This is intentionally
explicit (no getattr magic) for debuggability and maintainability.

Pipeline position:
  Source → Lexer → Parser → AST → TypeChecker → **IRGenerator** → IR → Backend
"""

from __future__ import annotations

import hashlib

from axon.compiler import ast_nodes as ast
from axon.compiler.errors import AxonError
from axon.compiler.ir_nodes import (
    IRAgent,
    IRAggregate,
    IRAnchor,
    IRAssociate,
    IRConditional,
    IRConsensus,
    IRContext,
    IRDataEdge,
    IRDataSpace,
    IRDeliberate,
    IREpistemicBlock,
    IRExplore,
    IRFlow,
    IRFocus,
    IRForge,
    IRHibernate,
    IRImport,
    IRIngest,
    IRIntent,
    IRMemory,
    IRNode,
    IRParallelBlock,
    IRParameter,
    IRPersona,
    IRProbe,
    IRProgram,
    IRReason,
    IRRecall,
    IRRefine,
    IRRemember,
    IRRun,
    IRStep,
    IRShield,
    IRShieldApply,
    IRToolSpec,
    IRType,
    IRTypeField,
    IRUseTool,
    IRValidate,
    IRValidateRule,
    IRWeave,
)


class AxonIRError(AxonError):
    """Raised when IR generation encounters an unresolvable issue."""
    pass


class IRGenerator:
    """
    Transforms a type-checked AST into an AXON IR program.

    Usage:
        generator = IRGenerator()
        ir_program = generator.generate(ast_program)

    The generated IRProgram contains all declarations resolved and
    cross-referenced, ready for backend compilation.
    """

    def __init__(self) -> None:
        # Symbol tables for cross-reference resolution
        self._personas: dict[str, IRPersona] = {}
        self._contexts: dict[str, IRContext] = {}
        self._anchors: dict[str, IRAnchor] = {}
        self._tools: dict[str, IRToolSpec] = {}
        self._memories: dict[str, IRMemory] = {}
        self._types: dict[str, IRType] = {}
        self._flows: dict[str, IRFlow] = {}
        self._imports: list[IRImport] = []
        self._runs: list[IRRun] = []
        self._agents: dict[str, IRAgent] = {}
        self._shields: dict[str, IRShield] = {}

    def generate(self, program: ast.ProgramNode) -> IRProgram:
        """
        Generate a complete IR program from a validated AST.

        Args:
            program: The root ProgramNode from the parser/type-checker.

        Returns:
            A fully resolved IRProgram ready for backend compilation.

        Raises:
            AxonIRError: If cross-references cannot be resolved.
        """
        self._reset()

        # Phase 1: Lower all declarations into IR (populates symbol tables)
        for declaration in program.declarations:
            self._visit(declaration)

        # Phase 2: Resolve cross-references in run statements
        resolved_runs = tuple(
            self._resolve_run(run) for run in self._runs
        )

        return IRProgram(
            source_line=program.line,
            source_column=program.column,
            personas=tuple(self._personas.values()),
            contexts=tuple(self._contexts.values()),
            anchors=tuple(self._anchors.values()),
            tools=tuple(self._tools.values()),
            memories=tuple(self._memories.values()),
            types=tuple(self._types.values()),
            flows=tuple(self._flows.values()),
            runs=resolved_runs,
            imports=tuple(self._imports),
            agents=tuple(self._agents.values()),
            shields=tuple(self._shields.values()),
        )

    # ═══════════════════════════════════════════════════════════════
    #  VISITOR DISPATCH
    # ═══════════════════════════════════════════════════════════════

    _VISITOR_MAP: dict[type, str] = {
        ast.ImportNode: "_visit_import",
        ast.PersonaDefinition: "_visit_persona",
        ast.ContextDefinition: "_visit_context",
        ast.AnchorConstraint: "_visit_anchor",
        ast.ToolDefinition: "_visit_tool",
        ast.MemoryDefinition: "_visit_memory",
        ast.TypeDefinition: "_visit_type",
        ast.FlowDefinition: "_visit_flow",
        ast.StepNode: "_visit_step",
        ast.IntentNode: "_visit_intent",
        ast.ProbeDirective: "_visit_probe",
        ast.ReasonChain: "_visit_reason",
        ast.WeaveNode: "_visit_weave",
        ast.ValidateGate: "_visit_validate",
        ast.RefineBlock: "_visit_refine",
        ast.UseToolNode: "_visit_use_tool",
        ast.RememberNode: "_visit_remember",
        ast.RecallNode: "_visit_recall",
        ast.ConditionalNode: "_visit_conditional",
        ast.RunStatement: "_visit_run",
        ast.EpistemicBlock: "_visit_epistemic_block",
        ast.ParallelBlock: "_visit_par_block",
        ast.HibernateNode: "_visit_hibernate",
        ast.DeliberateBlock: "_visit_deliberate",
        ast.ConsensusBlock: "_visit_consensus",
        # Creative synthesis
        ast.ForgeBlock: "_visit_forge",
        # Agent (BDI autonomous)
        ast.AgentDefinition: "_visit_agent",
        # Shield (security primitive)
        ast.ShieldDefinition: "_visit_shield",
        ast.ShieldApplyNode: "_visit_shield_apply",
        # Data Science
        ast.DataSpaceDefinition: "_visit_dataspace",
        ast.IngestNode: "_visit_ingest",
        ast.FocusNode: "_visit_focus",
        ast.AssociateNode: "_visit_associate",
        ast.AggregateNode: "_visit_aggregate",
        ast.ExploreNode: "_visit_explore",
    }

    def _visit(self, node: ast.ASTNode) -> IRNode:
        """
        Dispatch to the appropriate visitor method for an AST node.

        This is intentionally an explicit registry (not getattr)
        so that missing visitors produce clear errors at development
        time rather than silent failures.
        """
        visitor_name = self._VISITOR_MAP.get(type(node))
        if visitor_name is None:
            raise AxonIRError(
                f"No IR visitor for AST node type: {type(node).__name__}",
                line=node.line,
                column=node.column,
            )
        visitor = getattr(self, visitor_name)
        return visitor(node)

    # ═══════════════════════════════════════════════════════════════
    #  DECLARATION VISITORS
    # ═══════════════════════════════════════════════════════════════

    def _visit_import(self, node: ast.ImportNode) -> IRImport:
        ir_import = IRImport(
            source_line=node.line,
            source_column=node.column,
            module_path=tuple(node.module_path),
            names=tuple(node.names),
        )
        self._imports.append(ir_import)
        return ir_import

    def _visit_persona(self, node: ast.PersonaDefinition) -> IRPersona:
        ir_persona = IRPersona(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            domain=tuple(node.domain),
            tone=node.tone,
            confidence_threshold=node.confidence_threshold,
            cite_sources=node.cite_sources,
            refuse_if=tuple(node.refuse_if),
            language=node.language,
            description=node.description,
        )
        self._personas[node.name] = ir_persona
        return ir_persona

    def _visit_context(self, node: ast.ContextDefinition) -> IRContext:
        ir_context = IRContext(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            memory_scope=node.memory_scope,
            language=node.language,
            depth=node.depth,
            max_tokens=node.max_tokens,
            temperature=node.temperature,
            cite_sources=node.cite_sources,
        )
        self._contexts[node.name] = ir_context
        return ir_context

    def _visit_anchor(self, node: ast.AnchorConstraint) -> IRAnchor:
        ir_anchor = IRAnchor(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            require=node.require,
            reject=tuple(node.reject),
            enforce=node.enforce,
            confidence_floor=node.confidence_floor,
            unknown_response=node.unknown_response,
            on_violation=node.on_violation,
            on_violation_target=node.on_violation_target,
        )
        self._anchors[node.name] = ir_anchor
        return ir_anchor

    def _visit_tool(self, node: ast.ToolDefinition) -> IRToolSpec:
        ir_tool = IRToolSpec(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            provider=node.provider,
            max_results=node.max_results,
            filter_expr=node.filter_expr,
            timeout=node.timeout,
            runtime=node.runtime,
            sandbox=node.sandbox,
        )
        self._tools[node.name] = ir_tool
        return ir_tool

    def _visit_memory(self, node: ast.MemoryDefinition) -> IRMemory:
        ir_memory = IRMemory(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            store=node.store,
            backend=node.backend,
            retrieval=node.retrieval,
            decay=node.decay,
        )
        self._memories[node.name] = ir_memory
        return ir_memory

    # ═══════════════════════════════════════════════════════════════
    #  TYPE VISITOR
    # ═══════════════════════════════════════════════════════════════

    def _visit_type(self, node: ast.TypeDefinition) -> IRType:
        ir_fields = tuple(
            IRTypeField(
                source_line=f.line,
                source_column=f.column,
                name=f.name,
                type_name=f.type_expr.name if f.type_expr else "",
                generic_param=f.type_expr.generic_param if f.type_expr else "",
                optional=f.type_expr.optional if f.type_expr else False,
            )
            for f in node.fields
        )

        range_min: float | None = None
        range_max: float | None = None
        if node.range_constraint is not None:
            range_min = node.range_constraint.min_value
            range_max = node.range_constraint.max_value

        where_expr = ""
        if node.where_clause is not None:
            where_expr = node.where_clause.expression

        ir_type = IRType(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            fields=ir_fields,
            range_min=range_min,
            range_max=range_max,
            where_expression=where_expr,
        )
        self._types[node.name] = ir_type
        return ir_type

    # ═══════════════════════════════════════════════════════════════
    #  FLOW & STEP VISITORS
    # ═══════════════════════════════════════════════════════════════

    def _visit_flow(self, node: ast.FlowDefinition) -> IRFlow:
        parameters = tuple(
            IRParameter(
                source_line=p.line,
                source_column=p.column,
                name=p.name,
                type_name=p.type_expr.name if p.type_expr else "",
                generic_param=p.type_expr.generic_param if p.type_expr else "",
                optional=p.type_expr.optional if p.type_expr else False,
            )
            for p in node.parameters
        )

        # Compile flow body (steps, probes, reasons, etc.)
        raw_steps = tuple(self._visit(child) for child in node.body)

        sorted_steps, edges, execution_levels = self._calculate_execution_dag(
            raw_steps, node.line, node.column
        )

        ir_flow = IRFlow(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            parameters=parameters,
            return_type_name=node.return_type.name if node.return_type else "",
            return_type_generic=(
                node.return_type.generic_param if node.return_type else ""
            ),
            return_type_optional=(
                node.return_type.optional if node.return_type else False
            ),
            steps=sorted_steps,
            edges=edges,
            execution_levels=execution_levels,
        )
        self._flows[node.name] = ir_flow
        return ir_flow

    def _calculate_execution_dag(
        self,
        steps: tuple[IRNode, ...],
        flow_line: int,
        flow_column: int
    ) -> tuple[tuple[IRNode, ...], tuple[IRDataEdge, ...], tuple[tuple[str, ...], ...]]:
        import re

        def _extract_dependencies(node: IRNode) -> set[str]:
            deps = set()
            def _parse_expr(expr: str):
                if not expr: return
                matches = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\.output\b', expr)
                for m in matches:
                    deps.add(m)
                tags = re.findall(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.output)?)\s*\}\}', expr)
                for t in tags:
                    if t.endswith('.output'):
                        deps.add(t[:-7])
                    else:
                        deps.add(t)

            if isinstance(node, IRStep):
                _parse_expr(node.given)
                _parse_expr(node.ask)
                for child in node.body:
                    deps.update(_extract_dependencies(child))
            elif isinstance(node, IRIntent):
                _parse_expr(node.given)
                _parse_expr(node.ask)
            elif isinstance(node, IRProbe):
                _parse_expr(node.target)
            elif isinstance(node, IRReason):
                for g in node.given:
                    _parse_expr(g)
                _parse_expr(node.ask)
            elif isinstance(node, IRWeave):
                for s in node.sources:
                    _parse_expr(s)
            elif isinstance(node, IRValidate):
                _parse_expr(node.target)
                for r in node.rules:
                    _parse_expr(r.condition)
                    _parse_expr(r.comparison_value)
            elif isinstance(node, IRUseTool):
                _parse_expr(node.argument)
            elif isinstance(node, IRRemember):
                _parse_expr(node.expression)
            elif isinstance(node, IRRecall):
                _parse_expr(node.query)
            elif isinstance(node, IRConditional):
                _parse_expr(node.condition)
                _parse_expr(node.comparison_value)
                if node.then_branch:
                    deps.update(_extract_dependencies(node.then_branch))
                if node.else_branch:
                    deps.update(_extract_dependencies(node.else_branch))
            return deps

        name_to_idx = {}
        idx_to_node = {}
        for i, node in enumerate(steps):
            idx_to_node[i] = node
            if getattr(node, "name", ""):
                name_to_idx[node.name] = i
        
        in_degree = {i: 0 for i in range(len(steps))}
        out_edges = {i: [] for i in range(len(steps))}
        edges = []
        
        for i, node in enumerate(steps):
            raw_deps = _extract_dependencies(node)
            valid_deps = {dep for dep in raw_deps if dep in name_to_idx}
            
            target_name = getattr(node, "name", f"__anonymous_{i}__")
            
            for dep in valid_deps:
                if dep == target_name: continue  # Avoid self edges if any
                dep_idx = name_to_idx[dep]
                out_edges[dep_idx].append(i)
                in_degree[i] += 1
                
                edge = IRDataEdge(
                    source_line=node.source_line,
                    source_column=node.source_column,
                    source_step=dep,
                    target_step=target_name,
                    type_name="Any"
                )
                edges.append(edge)
                
        # topological sort via Kahn's algorithm
        queue = [i for i in range(len(steps)) if in_degree[i] == 0]
        sorted_indices = []
        levels = []
        
        while queue:
            levels.append(tuple(getattr(idx_to_node[i], "name", f"__anonymous_{i}__") for i in queue))
            
            next_queue = []
            for u in queue:
                sorted_indices.append(u)
                for v in out_edges[u]:
                    in_degree[v] -= 1
                    if in_degree[v] == 0:
                        next_queue.append(v)
            queue = next_queue
            
        if len(sorted_indices) != len(steps):
            raise AxonIRError(
                "Cycle detected in flow step dependencies",
                line=flow_line,
                column=flow_column
            )
            
        sorted_steps = tuple(idx_to_node[i] for i in sorted_indices)
        return sorted_steps, tuple(edges), tuple(levels)

    def _visit_step(self, node: ast.StepNode) -> IRStep:
        return IRStep(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            given=node.given,
            ask=node.ask,
            use_tool=(
                self._visit_use_tool(node.use_tool)
                if node.use_tool else None
            ),
            probe=(
                self._visit_probe(node.probe)
                if node.probe else None
            ),
            reason=(
                self._visit_reason(node.reason)
                if node.reason else None
            ),
            weave=(
                self._visit_weave(node.weave)
                if node.weave else None
            ),
            output_type=node.output_type,
            confidence_floor=node.confidence_floor,
            body=tuple(self._visit(child) for child in node.body),
        )

    # ═══════════════════════════════════════════════════════════════
    #  COGNITIVE NODE VISITORS
    # ═══════════════════════════════════════════════════════════════

    def _visit_intent(self, node: ast.IntentNode) -> IRIntent:
        return IRIntent(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            given=node.given,
            ask=node.ask,
            output_type_name=(
                node.output_type.name if node.output_type else ""
            ),
            output_type_generic=(
                node.output_type.generic_param if node.output_type else ""
            ),
            output_type_optional=(
                node.output_type.optional if node.output_type else False
            ),
            confidence_floor=node.confidence_floor,
        )

    def _visit_probe(self, node: ast.ProbeDirective) -> IRProbe:
        return IRProbe(
            source_line=node.line,
            source_column=node.column,
            target=node.target,
            fields=tuple(node.fields),
        )

    def _visit_reason(self, node: ast.ReasonChain) -> IRReason:
        # Normalize 'given' to always be a tuple of strings
        given: tuple[str, ...]
        if isinstance(node.given, list):
            given = tuple(node.given)
        elif node.given:
            given = (node.given,)
        else:
            given = ()

        return IRReason(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            about=node.about,
            given=given,
            depth=node.depth,
            show_work=node.show_work,
            chain_of_thought=node.chain_of_thought,
            ask=node.ask,
            output_type=node.output_type,
        )

    def _visit_weave(self, node: ast.WeaveNode) -> IRWeave:
        return IRWeave(
            source_line=node.line,
            source_column=node.column,
            sources=tuple(node.sources),
            target=node.target,
            format_type=node.format_type,
            priority=tuple(node.priority),
            style=node.style,
        )

    def _visit_validate(self, node: ast.ValidateGate) -> IRValidate:
        rules = tuple(
            IRValidateRule(
                source_line=rule.line,
                source_column=rule.column,
                condition=rule.condition,
                comparison_op=rule.comparison_op,
                comparison_value=rule.comparison_value,
                action=rule.action,
                action_target=rule.action_target,
                action_params=tuple(rule.action_params.items()),
            )
            for rule in node.rules
        )
        return IRValidate(
            source_line=node.line,
            source_column=node.column,
            target=node.target,
            schema=node.schema,
            rules=rules,
        )

    def _visit_refine(self, node: ast.RefineBlock) -> IRRefine:
        return IRRefine(
            source_line=node.line,
            source_column=node.column,
            max_attempts=node.max_attempts,
            pass_failure_context=node.pass_failure_context,
            backoff=node.backoff,
            on_exhaustion=node.on_exhaustion,
            on_exhaustion_target=node.on_exhaustion_target,
        )

    def _visit_use_tool(self, node: ast.UseToolNode) -> IRUseTool:
        return IRUseTool(
            source_line=node.line,
            source_column=node.column,
            tool_name=node.tool_name,
            argument=node.argument,
        )

    def _visit_remember(self, node: ast.RememberNode) -> IRRemember:
        return IRRemember(
            source_line=node.line,
            source_column=node.column,
            expression=node.expression,
            memory_target=node.memory_target,
        )

    def _visit_recall(self, node: ast.RecallNode) -> IRRecall:
        return IRRecall(
            source_line=node.line,
            source_column=node.column,
            query=node.query,
            memory_source=node.memory_source,
        )

    def _visit_conditional(self, node: ast.ConditionalNode) -> IRConditional:
        then_branch = self._visit(node.then_step) if node.then_step else None
        else_branch = self._visit(node.else_step) if node.else_step else None

        return IRConditional(
            source_line=node.line,
            source_column=node.column,
            condition=node.condition,
            comparison_op=node.comparison_op,
            comparison_value=node.comparison_value,
            then_branch=then_branch,
            else_branch=else_branch,
        )

    # ═══════════════════════════════════════════════════════════════
    #  PARADIGM SHIFT VISITORS
    # ═══════════════════════════════════════════════════════════════

    # Epistemic constraint matrix: compile-time calculation of
    # temperature, top_p, and auto-injected anchors per mode.
    _EPISTEMIC_CONSTRAINTS: dict[str, dict] = {
        "know": {
            "temperature": 0.1,
            "top_p": 0.3,
            "anchors": ("RequiresCitation", "NoHallucination"),
        },
        "believe": {
            "temperature": 0.3,
            "top_p": 0.5,
            "anchors": ("NoHallucination",),
        },
        "speculate": {
            "temperature": 0.9,
            "top_p": 0.95,
            "anchors": (),
        },
        "doubt": {
            "temperature": 0.2,
            "top_p": 0.4,
            "anchors": ("RequiresCitation", "SyllogismChecker"),
        },
    }

    def _visit_epistemic_block(self, node: ast.EpistemicBlock) -> IREpistemicBlock:
        constraints = self._EPISTEMIC_CONSTRAINTS.get(node.mode, {})
        children = tuple(self._visit(child) for child in node.body)
        return IREpistemicBlock(
            source_line=node.line,
            source_column=node.column,
            mode=node.mode,
            injected_anchors=constraints.get("anchors", ()),
            temperature_override=constraints.get("temperature"),
            top_p_override=constraints.get("top_p"),
            children=children,
        )

    def _visit_par_block(self, node: ast.ParallelBlock) -> IRParallelBlock:
        branches = tuple(self._visit(branch) for branch in node.branches)
        return IRParallelBlock(
            source_line=node.line,
            source_column=node.column,
            branches=branches,
        )

    def _visit_hibernate(self, node: ast.HibernateNode) -> IRHibernate:
        # Generate a deterministic continuation ID from flow context + event
        seed = f"hibernate:{node.event_name}:{node.line}:{node.column}"
        continuation_id = hashlib.sha256(seed.encode()).hexdigest()[:16]
        return IRHibernate(
            source_line=node.line,
            source_column=node.column,
            event_name=node.event_name,
            timeout=node.timeout,
            continuation_id=continuation_id,
        )

    # Deliberate strategy matrix: compile-time calculation of
    # reasoning effort and budget factor per strategy name.
    _DELIBERATE_STRATEGIES: dict[str, dict] = {
        "quick":      {"reasoning_effort": "low",    "budget_factor": 0.25},
        "balanced":   {"reasoning_effort": "medium", "budget_factor": 0.5},
        "thorough":   {"reasoning_effort": "high",   "budget_factor": 1.0},
        "exhaustive": {"reasoning_effort": "max",    "budget_factor": 1.0},
    }

    def _visit_deliberate(self, node: ast.DeliberateBlock) -> IRDeliberate:
        """Compile deliberate block → IRDeliberate with budget constraints."""
        children = tuple(self._visit(child) for child in node.body)
        return IRDeliberate(
            source_line=node.line,
            source_column=node.column,
            budget=node.budget,
            depth=node.depth,
            strategy=node.strategy,
            children=children,
        )

    def _visit_consensus(self, node: ast.ConsensusBlock) -> IRConsensus:
        """Compile consensus block → IRConsensus with branch config."""
        children = tuple(self._visit(child) for child in node.body)
        return IRConsensus(
            source_line=node.line,
            source_column=node.column,
            n_branches=node.branches,
            reward_anchor=node.reward_anchor,
            selection=node.selection,
            children=children,
        )

    # ── FORGE (creative synthesis) ────────────────────────────────

    # Boden's creativity taxonomy → LLM parameter mapping
    _FORGE_MODES: dict[str, dict[str, object]] = {
        "combinatory":      {"temperature": 0.9, "freedom": "high",    "rule_flex": "none"},
        "exploratory":      {"temperature": 0.7, "freedom": "medium",  "rule_flex": "none"},
        "transformational": {"temperature": 1.2, "freedom": "maximum", "rule_flex": "allowed"},
    }

    def _visit_forge(self, node: ast.ForgeBlock) -> IRForge:
        """Compile forge block → IRForge with Poincaré pipeline metadata."""
        children = tuple(self._visit(child) for child in node.body)
        return IRForge(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            seed=node.seed,
            output_type=node.output_type,
            mode=node.mode,
            novelty=node.novelty,
            constraints=node.constraints,
            depth=node.depth,
            branches=node.branches,
            children=children,
        )

    # ── AGENT (BDI autonomous agent) ──────────────────────────────

    def _visit_agent(self, node: ast.AgentDefinition) -> IRAgent:
        """
        Compile AgentDefinition → IRAgent.

        Resolves:
        - parameters (reuses IRParameter from flow visitors)
        - body steps (recursive _visit for each flow step)
        - budget constraints (extracted from AgentBudget, with defaults)
        - return type (name only, validated by type checker)

        The agent's tool references are stored as names at this stage;
        actual tool resolution occurs during run-time symbol lookup
        (same pattern as flow + run cross-referencing).
        """
        children = tuple(self._visit(child) for child in node.body)

        # Extract budget fields with defaults for absent budget block
        budget = node.budget
        max_iterations = budget.max_iterations if budget else 10
        max_tokens = budget.max_tokens if budget else 0
        max_time = budget.max_time if budget else ""
        max_cost = budget.max_cost if budget else 0.0

        ir_agent = IRAgent(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            goal=node.goal,
            tools=tuple(node.tools),
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            max_time=max_time,
            max_cost=max_cost,
            memory_ref=node.memory_ref,
            strategy=node.strategy,
            on_stuck=node.on_stuck,
            return_type=node.return_type.name if node.return_type else "",
            shield_ref=node.shield_ref,
            children=children,
        )
        self._agents[node.name] = ir_agent
        return ir_agent

    # ═══════════════════════════════════════════════════════════════════
    #  SHIELD VISITORS
    # ═══════════════════════════════════════════════════════════════════

    def _visit_shield(self, node: ast.ShieldDefinition) -> IRShield:
        """
        Compile ShieldDefinition → IRShield.

        Lowers the shield declaration into an IR node with
        all configuration fields preserved as tuples for immutability.
        """
        ir_shield = IRShield(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            scan=tuple(node.scan),
            strategy=node.strategy,
            on_breach=node.on_breach,
            severity=node.severity,
            quarantine=node.quarantine,
            max_retries=node.max_retries,
            confidence_threshold=node.confidence_threshold if node.confidence_threshold is not None else 0.0,
            allow_tools=tuple(node.allow_tools),
            deny_tools=tuple(node.deny_tools),
            sandbox=node.sandbox if node.sandbox is not None else False,
            redact=tuple(node.redact),
            log=node.log,
            deflect_message=node.deflect_message,
        )
        self._shields[node.name] = ir_shield
        return ir_shield

    def _visit_shield_apply(self, node: ast.ShieldApplyNode) -> IRShieldApply:
        """
        Compile ShieldApplyNode → IRShieldApply.

        The application point where taint analysis inserts
        the Untrusted → Sanitized type transformation.
        """
        return IRShieldApply(
            source_line=node.line,
            source_column=node.column,
            shield_name=node.shield_name,
            target=node.target,
            output_type=node.output_type,
        )

    # ═══════════════════════════════════════════════════════════════════
    #  DATA SCIENCE VISITORS
    # ═══════════════════════════════════════════════════════════════════

    def _visit_dataspace(self, node: ast.DataSpaceDefinition) -> IRDataSpace:
        body = tuple(self._visit(stmt) for stmt in node.body)
        return IRDataSpace(
            source_line=node.line,
            source_column=node.column,
            name=node.name,
            body=body,
        )

    def _visit_ingest(self, node: ast.IngestNode) -> IRIngest:
        return IRIngest(
            source_line=node.line,
            source_column=node.column,
            source=node.source,
            target=node.target,
        )

    def _visit_focus(self, node: ast.FocusNode) -> IRFocus:
        return IRFocus(
            source_line=node.line,
            source_column=node.column,
            expression=node.expression,
        )

    def _visit_associate(self, node: ast.AssociateNode) -> IRAssociate:
        return IRAssociate(
            source_line=node.line,
            source_column=node.column,
            left=node.left,
            right=node.right,
            using_field=node.using_field,
        )

    def _visit_aggregate(self, node: ast.AggregateNode) -> IRAggregate:
        return IRAggregate(
            source_line=node.line,
            source_column=node.column,
            target=node.target,
            group_by=tuple(node.group_by),
            alias=node.alias,
        )

    def _visit_explore(self, node: ast.ExploreNode) -> IRExplore:
        return IRExplore(
            source_line=node.line,
            source_column=node.column,
            target=node.target,
            limit=node.limit,
        )

    # ═══════════════════════════════════════════════════════════════
    #  RUN STATEMENT VISITOR & CROSS-REFERENCE RESOLVER
    # ═══════════════════════════════════════════════════════════════

    def _visit_run(self, node: ast.RunStatement) -> IRRun:
        """Visit a run statement and register it for later resolution."""
        ir_run = IRRun(
            source_line=node.line,
            source_column=node.column,
            flow_name=node.flow_name,
            arguments=tuple(node.arguments),
            persona_name=node.persona,
            context_name=node.context,
            anchor_names=tuple(node.anchors),
            on_failure=node.on_failure,
            on_failure_params=tuple(node.on_failure_params.items()),
            output_to=node.output_to,
            effort=node.effort,
        )
        self._runs.append(ir_run)
        return ir_run

    def _resolve_run(self, run: IRRun) -> IRRun:
        """
        Resolve all cross-references in a run statement.

        This is the Anchor Enforcer + Tool Resolver integration point:
        - Anchors listed in constrained_by are resolved to IRAnchor objects.
        - The flow is resolved and its tools are verified against declarations.

        Raises:
            AxonIRError: If any referenced entity cannot be found.
        """
        # Resolve flow
        resolved_flow = self._resolve_ref(
            run.flow_name, self._flows, "flow", run,
        )

        # Resolve persona (optional — a run can omit persona)
        resolved_persona: IRPersona | None = None
        if run.persona_name:
            resolved_persona = self._resolve_ref(
                run.persona_name, self._personas, "persona", run,
            )

        # Resolve context (optional)
        resolved_context: IRContext | None = None
        if run.context_name:
            resolved_context = self._resolve_ref(
                run.context_name, self._contexts, "context", run,
            )

        # Resolve anchors (Anchor Enforcer)
        resolved_anchors = tuple(
            self._resolve_ref(name, self._anchors, "anchor", run)
            for name in run.anchor_names
        )

        # Verify tool references within the flow
        if resolved_flow is not None:
            self._verify_flow_tools(resolved_flow, run)

        # Produce a new IRRun with all references resolved
        # (frozen dataclass — must create a new instance)
        return IRRun(
            source_line=run.source_line,
            source_column=run.source_column,
            node_type=run.node_type,
            flow_name=run.flow_name,
            arguments=run.arguments,
            persona_name=run.persona_name,
            context_name=run.context_name,
            anchor_names=run.anchor_names,
            on_failure=run.on_failure,
            on_failure_params=run.on_failure_params,
            output_to=run.output_to,
            effort=run.effort,
            resolved_flow=resolved_flow,
            resolved_persona=resolved_persona,
            resolved_context=resolved_context,
            resolved_anchors=resolved_anchors,
        )

    def _resolve_ref(
        self,
        name: str,
        table: dict[str, IRNode],
        kind: str,
        referrer: IRRun,
    ) -> IRNode:
        """
        Look up a named entity in a symbol table.

        Raises:
            AxonIRError: If the name is not found.
        """
        if name not in table:
            available = ", ".join(sorted(table.keys())) or "(none)"
            raise AxonIRError(
                f"Run statement references undefined {kind} '{name}'. "
                f"Available {kind}s: {available}",
                line=referrer.source_line,
                column=referrer.source_column,
            )
        return table[name]

    def _verify_flow_tools(self, flow: IRFlow, run: IRRun) -> None:
        """
        Verify that all tool references within a flow's steps
        are resolvable against declared tool definitions.

        This is the Tool Resolver's static verification pass.
        """
        for step_node in flow.steps:
            self._verify_step_tools(step_node, run)

    def _verify_step_tools(self, node: IRNode, run: IRRun) -> None:
        """Recursively verify tool references in a step tree."""
        if isinstance(node, IRStep):
            if node.use_tool is not None:
                tool_name = node.use_tool.tool_name
                if tool_name and tool_name not in self._tools:
                    available = (
                        ", ".join(sorted(self._tools.keys())) or "(none)"
                    )
                    raise AxonIRError(
                        f"Step '{node.name}' uses undefined tool "
                        f"'{tool_name}'. Available tools: {available}",
                        line=node.source_line,
                        column=node.source_column,
                    )
            # Check sub-steps recursively
            for child in node.body:
                self._verify_step_tools(child, run)

    # ═══════════════════════════════════════════════════════════════
    #  INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _reset(self) -> None:
        """Clear all internal state for a fresh generation pass."""
        self._personas.clear()
        self._contexts.clear()
        self._anchors.clear()
        self._tools.clear()
        self._memories.clear()
        self._types.clear()
        self._flows.clear()
        self._imports.clear()
        self._runs.clear()
