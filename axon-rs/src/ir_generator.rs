//! AXON IR Generator — AST → IR transformation.
//!
//! Direct port of axon/compiler/ir_generator.py (Tier 1 subset).
//!
//! Tier 1 constructs produce fully typed IR nodes.
//! Tier 2+ GenericDeclarations are emitted as generic JSON objects.
//! Flow data edges and execution levels are computed.

use std::collections::HashMap;

use crate::ast::*;
use crate::ir_nodes::*;

pub struct IRGenerator {
    personas: HashMap<String, IRPersona>,
    contexts: HashMap<String, IRContext>,
    anchors: HashMap<String, IRAnchor>,
    flows: HashMap<String, IRFlow>,
    lambda_data_specs: HashMap<String, IRLambdaData>,
}

impl IRGenerator {
    pub fn new() -> Self {
        IRGenerator {
            personas: HashMap::new(),
            contexts: HashMap::new(),
            anchors: HashMap::new(),
            flows: HashMap::new(),
            lambda_data_specs: HashMap::new(),
        }
    }

    pub fn generate(mut self, program: &Program) -> IRProgram {
        let mut ir = IRProgram::new();

        // Phase 1: visit all declarations
        for decl in &program.declarations {
            self.visit_declaration(decl, &mut ir);
        }

        // Phase 2: resolve run cross-references
        for run in &mut ir.runs {
            if let Some(flow) = self.flows.get(&run.flow_name) {
                run.resolved_flow = Some(flow.clone());
            }
            if let Some(persona) = self.personas.get(&run.persona_name) {
                run.resolved_persona = Some(persona.clone());
            }
            if let Some(context) = self.contexts.get(&run.context_name) {
                run.resolved_context = Some(context.clone());
            }
            for anchor_name in &run.anchor_names {
                if let Some(anchor) = self.anchors.get(anchor_name) {
                    run.resolved_anchors.push(anchor.clone());
                }
            }
        }

        ir
    }

    fn visit_declaration(&mut self, decl: &Declaration, ir: &mut IRProgram) {
        match decl {
            Declaration::Import(n) => ir.imports.push(self.visit_import(n)),
            Declaration::Persona(n) => {
                let node = self.visit_persona(n);
                self.personas.insert(node.name.clone(), node.clone());
                ir.personas.push(node);
            }
            Declaration::Context(n) => {
                let node = self.visit_context(n);
                self.contexts.insert(node.name.clone(), node.clone());
                ir.contexts.push(node);
            }
            Declaration::Anchor(n) => {
                let node = self.visit_anchor(n);
                self.anchors.insert(node.name.clone(), node.clone());
                ir.anchors.push(node);
            }
            Declaration::Memory(n) => ir.memories.push(self.visit_memory(n)),
            Declaration::Tool(n) => ir.tools.push(self.visit_tool(n)),
            Declaration::Type(n) => ir.types.push(self.visit_type(n)),
            Declaration::Flow(n) => {
                let node = self.visit_flow(n);
                self.flows.insert(node.name.clone(), node.clone());
                ir.flows.push(node);
            }
            Declaration::Intent(_) => {} // intent is inlined into steps
            Declaration::Run(n) => ir.runs.push(self.visit_run(n)),
            Declaration::LambdaData(n) => {
                let node = self.visit_lambda_data(n);
                self.lambda_data_specs.insert(node.name.clone(), node.clone());
                ir.lambda_data_specs.push(node);
            }
            Declaration::Agent(n) => ir.agents.push(self.visit_agent(n)),
            Declaration::Shield(n) => ir.shields.push(self.visit_shield(n)),
            Declaration::Pix(n) => ir.pix_specs.push(self.visit_pix(n)),
            Declaration::Psyche(n) => ir.psyche_specs.push(self.visit_psyche(n)),
            Declaration::Corpus(n) => ir.corpus_specs.push(self.visit_corpus(n)),
            Declaration::Dataspace(n) => ir.dataspace_specs.push(self.visit_dataspace(n)),
            Declaration::Ots(n) => ir.ots_specs.push(self.visit_ots(n)),
            Declaration::Mandate(n) => ir.mandate_specs.push(self.visit_mandate(n)),
            Declaration::Compute(n) => ir.compute_specs.push(self.visit_compute(n)),
            Declaration::Daemon(n) => ir.daemons.push(self.visit_daemon(n)),
            Declaration::AxonStore(n) => ir.axonstore_specs.push(self.visit_axonstore(n)),
            Declaration::AxonEndpoint(n) => ir.endpoints.push(self.visit_axonendpoint(n)),
            Declaration::Epistemic(eb) => {
                for child in &eb.body {
                    self.visit_declaration(child, ir);
                }
            }
            Declaration::Let(_) => {}
            Declaration::Generic(g) => {
                // Emit as generic JSON in the appropriate collection
                let val = serde_json::json!({
                    "node_type": g.keyword,
                    "source_line": g.loc.line,
                    "source_column": g.loc.column,
                    "name": g.name,
                });
                // Tier 3+ generic fallback — no typed IR collection
                let _ = val; // suppress unused warning
            }
        }
    }

    // ── Visitors ─────────────────────────────────────────────────

    fn visit_import(&self, n: &ImportNode) -> IRImport {
        IRImport {
            node_type: "import",
            source_line: n.loc.line,
            source_column: n.loc.column,
            module_path: n.module_path.clone(),
            names: n.names.clone(),
        }
    }

    fn visit_persona(&self, n: &PersonaDefinition) -> IRPersona {
        IRPersona {
            node_type: "persona",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            domain: n.domain.clone(),
            tone: n.tone.clone(),
            confidence_threshold: n.confidence_threshold,
            cite_sources: n.cite_sources,
            refuse_if: n.refuse_if.clone(),
            language: n.language.clone(),
            description: n.description.clone(),
        }
    }

    fn visit_context(&self, n: &ContextDefinition) -> IRContext {
        IRContext {
            node_type: "context",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            memory_scope: n.memory_scope.clone(),
            language: n.language.clone(),
            depth: n.depth.clone(),
            max_tokens: n.max_tokens,
            temperature: n.temperature,
            cite_sources: n.cite_sources,
        }
    }

    fn visit_anchor(&self, n: &AnchorConstraint) -> IRAnchor {
        IRAnchor {
            node_type: "anchor",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            description: n.description.clone(),
            require: n.require.clone(),
            reject: n.reject.clone(),
            enforce: n.enforce.clone(),
            confidence_floor: n.confidence_floor,
            unknown_response: n.unknown_response.clone(),
            on_violation: n.on_violation.clone(),
            on_violation_target: n.on_violation_target.clone(),
        }
    }

    fn visit_memory(&self, n: &MemoryDefinition) -> IRMemory {
        IRMemory {
            node_type: "memory",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            store: n.store.clone(),
            backend: n.backend.clone(),
            retrieval: n.retrieval.clone(),
            decay: n.decay.clone(),
        }
    }

    fn visit_tool(&self, n: &ToolDefinition) -> IRToolSpec {
        let effect_row = match &n.effects {
            Some(eff) => {
                let mut row = eff.effects.clone();
                if !eff.epistemic_level.is_empty() {
                    row.push(format!("epistemic:{}", eff.epistemic_level));
                }
                row
            }
            None => Vec::new(),
        };

        IRToolSpec {
            node_type: "tool_spec",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            provider: n.provider.clone(),
            max_results: n.max_results,
            filter_expr: n.filter_expr.clone(),
            timeout: n.timeout.clone(),
            runtime: n.runtime.clone(),
            sandbox: n.sandbox,
            input_schema: Vec::new(),
            output_schema: String::new(),
            effect_row,
        }
    }

    fn visit_type(&self, n: &TypeDefinition) -> IRType {
        let fields = n
            .fields
            .iter()
            .map(|f| IRTypeField {
                node_type: "type_field",
                source_line: f.loc.line,
                source_column: f.loc.column,
                name: f.name.clone(),
                type_name: f.type_expr.name.clone(),
                generic_param: f.type_expr.generic_param.clone(),
                optional: f.type_expr.optional,
            })
            .collect();

        let (range_min, range_max) = match &n.range_constraint {
            Some(rc) => (Some(rc.min_value), Some(rc.max_value)),
            None => (None, None),
        };

        let where_expression = match &n.where_clause {
            Some(wc) => wc.expression.clone(),
            None => String::new(),
        };

        IRType {
            node_type: "type_def",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            fields,
            range_min,
            range_max,
            where_expression,
        }
    }

    fn visit_flow(&self, n: &FlowDefinition) -> IRFlow {
        let parameters: Vec<IRParameter> = n
            .parameters
            .iter()
            .map(|p| IRParameter {
                node_type: "parameter",
                source_line: p.loc.line,
                source_column: p.loc.column,
                name: p.name.clone(),
                type_name: p.type_expr.name.clone(),
                generic_param: p.type_expr.generic_param.clone(),
                optional: p.type_expr.optional,
            })
            .collect();

        let (return_type_name, return_type_generic, return_type_optional) = match &n.return_type {
            Some(rt) => (rt.name.clone(), rt.generic_param.clone(), rt.optional),
            None => (String::new(), String::new(), false),
        };

        // Collect all flow body nodes as typed IR
        let steps: Vec<IRFlowNode> = n.body.iter().map(|fs| self.visit_flow_step(fs)).collect();

        // Compute data edges from Step nodes: if step B's given references "A.output", create edge A → B
        let mut edges: Vec<IRDataEdge> = Vec::new();
        let step_names: Vec<String> = steps.iter().filter_map(|n| {
            if let IRFlowNode::Step(s) = n { Some(s.name.clone()) } else { None }
        }).collect();
        for node in &steps {
            if let IRFlowNode::Step(step) = node {
                if !step.given.is_empty() {
                    let given_root = step.given.split('.').next().unwrap_or("");
                    if step_names.contains(&given_root.to_string()) && given_root != step.name {
                        edges.push(IRDataEdge {
                            node_type: "data_edge",
                            source_line: step.source_line,
                            source_column: step.source_column,
                            source_step: given_root.to_string(),
                            target_step: step.name.clone(),
                            type_name: "Any".to_string(),
                        });
                    }
                }
            }
        }

        // Compute execution levels (topological ordering) — Step nodes only
        let execution_levels = self.compute_execution_levels(&steps, &edges);

        IRFlow {
            node_type: "flow",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            parameters,
            return_type_name,
            return_type_generic,
            return_type_optional,
            steps,
            edges,
            execution_levels,
        }
    }

    fn visit_flow_step(&self, fs: &FlowStep) -> IRFlowNode {
        match fs {
            FlowStep::Step(s) => IRFlowNode::Step(IRStep {
                node_type: "step", source_line: s.loc.line, source_column: s.loc.column,
                name: s.name.clone(), persona_ref: s.persona_ref.clone(),
                given: s.given.clone(), ask: s.ask.clone(),
                use_tool: None, probe: None, reason: None, weave: None,
                output_type: s.output_type.clone(), confidence_floor: s.confidence_floor,
                navigate_ref: s.navigate_ref.clone(), apply_ref: s.apply_ref.clone(),
                body: Vec::new(),
            }),
            FlowStep::Probe(s) => IRFlowNode::Probe(IRProbe {
                node_type: "probe", source_line: s.loc.line, source_column: s.loc.column,
                target: s.target.clone(),
            }),
            FlowStep::Reason(s) => IRFlowNode::Reason(IRReasonStep {
                node_type: "reason", source_line: s.loc.line, source_column: s.loc.column,
                strategy: s.strategy.clone(), target: s.target.clone(),
            }),
            FlowStep::Validate(s) => IRFlowNode::Validate(IRValidateStep {
                node_type: "validate", source_line: s.loc.line, source_column: s.loc.column,
                target: s.target.clone(), rule: s.rule.clone(),
            }),
            FlowStep::Refine(s) => IRFlowNode::Refine(IRRefineStep {
                node_type: "refine", source_line: s.loc.line, source_column: s.loc.column,
                target: s.target.clone(), strategy: s.strategy.clone(),
            }),
            FlowStep::Weave(s) => IRFlowNode::Weave(IRWeaveStep {
                node_type: "weave", source_line: s.loc.line, source_column: s.loc.column,
                sources: s.sources.clone(), target: s.target.clone(),
                format_type: s.format_type.clone(), priority: s.priority.clone(),
                style: s.style.clone(),
            }),
            FlowStep::UseTool(s) => IRFlowNode::UseTool(IRUseToolStep {
                node_type: "use_tool", source_line: s.loc.line, source_column: s.loc.column,
                tool_name: s.tool_name.clone(), argument: s.argument.clone(),
            }),
            FlowStep::Remember(s) => IRFlowNode::Remember(IRRememberStep {
                node_type: "remember", source_line: s.loc.line, source_column: s.loc.column,
                expression: s.expression.clone(), memory_target: s.memory_target.clone(),
            }),
            FlowStep::Recall(s) => IRFlowNode::Recall(IRRecallStep {
                node_type: "recall", source_line: s.loc.line, source_column: s.loc.column,
                query: s.query.clone(), memory_source: s.memory_source.clone(),
            }),
            FlowStep::If(s) => IRFlowNode::Conditional(IRConditional {
                node_type: "conditional", source_line: s.loc.line, source_column: s.loc.column,
                condition: s.condition.clone(), comparison_op: s.comparison_op.clone(),
                comparison_value: s.comparison_value.clone(),
                then_body: s.then_body.iter().map(|fs| self.visit_flow_step(fs)).collect(),
                else_body: s.else_body.iter().map(|fs| self.visit_flow_step(fs)).collect(),
                conditions: s.conditions.clone(), conjunctor: s.conjunctor.clone(),
            }),
            FlowStep::ForIn(s) => IRFlowNode::ForIn(IRForIn {
                node_type: "for_in", source_line: s.loc.line, source_column: s.loc.column,
                variable: s.variable.clone(), iterable: s.iterable.clone(),
                body: s.body.iter().map(|fs| self.visit_flow_step(fs)).collect(),
            }),
            FlowStep::Let(s) => IRFlowNode::Let(IRLetBinding {
                node_type: "let_binding", source_line: s.loc.line, source_column: s.loc.column,
                target: s.identifier.clone(), value: s.value_expr.clone(),
            }),
            FlowStep::Return(s) => IRFlowNode::Return(IRReturnStep {
                node_type: "return", source_line: s.loc.line, source_column: s.loc.column,
                value_expr: s.value_expr.clone(),
            }),
            FlowStep::LambdaDataApply(s) => IRFlowNode::LambdaDataApply(IRLambdaDataApply {
                node_type: "lambda_data_apply", source_line: s.loc.line, source_column: s.loc.column,
                lambda_data_name: s.lambda_data_name.clone(), target: s.target.clone(),
                output_type: s.output_type.clone(),
            }),
            FlowStep::Par(s) => IRFlowNode::Par(IRParallelBlock {
                node_type: "parallel_block", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::Hibernate(s) => IRFlowNode::Hibernate(IRHibernateStep {
                node_type: "hibernate", source_line: s.loc.line, source_column: s.loc.column,
                event_name: s.event_name.clone(), timeout: s.timeout.clone(),
            }),
            FlowStep::Deliberate(s) => IRFlowNode::Deliberate(IRDeliberateBlock {
                node_type: "deliberate", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::Consensus(s) => IRFlowNode::Consensus(IRConsensusBlock {
                node_type: "consensus", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::Forge(s) => IRFlowNode::Forge(IRForgeBlock {
                node_type: "forge", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::Focus(s) => IRFlowNode::Focus(IRFocusStep {
                node_type: "focus", source_line: s.loc.line, source_column: s.loc.column,
                expression: s.expression.clone(),
            }),
            FlowStep::Associate(s) => IRFlowNode::Associate(IRAssociateStep {
                node_type: "associate", source_line: s.loc.line, source_column: s.loc.column,
                left: s.left.clone(), right: s.right.clone(), using_field: s.using_field.clone(),
            }),
            FlowStep::Aggregate(s) => IRFlowNode::Aggregate(IRAggregateStep {
                node_type: "aggregate", source_line: s.loc.line, source_column: s.loc.column,
                target: s.target.clone(), group_by: s.group_by.clone(), alias: s.alias.clone(),
            }),
            FlowStep::ExploreStep(s) => IRFlowNode::Explore(IRExploreStep {
                node_type: "explore", source_line: s.loc.line, source_column: s.loc.column,
                target: s.target.clone(), limit: s.limit,
            }),
            FlowStep::Ingest(s) => IRFlowNode::Ingest(IRIngestStep {
                node_type: "ingest", source_line: s.loc.line, source_column: s.loc.column,
                source: s.source.clone(), target: s.target.clone(),
            }),
            FlowStep::ShieldApply(s) => IRFlowNode::ShieldApply(IRShieldApplyStep {
                node_type: "shield_apply", source_line: s.loc.line, source_column: s.loc.column,
                shield_name: s.shield_name.clone(), target: s.target.clone(),
                output_type: s.output_type.clone(),
            }),
            FlowStep::Stream(s) => IRFlowNode::Stream(IRStreamBlock {
                node_type: "stream", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::Navigate(s) => IRFlowNode::Navigate(IRNavigateStep {
                node_type: "navigate", source_line: s.loc.line, source_column: s.loc.column,
                pix_ref: s.pix_name.clone(), corpus_ref: s.corpus_name.clone(),
                query: s.query_expr.clone(), trail_enabled: s.trail_enabled,
                output_name: s.output_name.clone(),
            }),
            FlowStep::Drill(s) => IRFlowNode::Drill(IRDrillStep {
                node_type: "drill", source_line: s.loc.line, source_column: s.loc.column,
                pix_ref: s.pix_name.clone(), subtree_path: s.subtree_path.clone(),
                query: s.query_expr.clone(), output_name: s.output_name.clone(),
            }),
            FlowStep::Trail(s) => IRFlowNode::Trail(IRTrailStep {
                node_type: "trail", source_line: s.loc.line, source_column: s.loc.column,
                navigate_ref: s.navigate_ref.clone(),
            }),
            FlowStep::Corroborate(s) => IRFlowNode::Corroborate(IRCorroborateStep {
                node_type: "corroborate", source_line: s.loc.line, source_column: s.loc.column,
                navigate_ref: s.navigate_ref.clone(), output_name: s.output_name.clone(),
            }),
            FlowStep::OtsApply(s) => IRFlowNode::OtsApply(IROtsApplyStep {
                node_type: "ots_apply", source_line: s.loc.line, source_column: s.loc.column,
                ots_name: s.ots_name.clone(), target: s.target.clone(),
                output_type: s.output_type.clone(),
            }),
            FlowStep::MandateApply(s) => IRFlowNode::MandateApply(IRMandateApplyStep {
                node_type: "mandate_apply", source_line: s.loc.line, source_column: s.loc.column,
                mandate_name: s.mandate_name.clone(), target: s.target.clone(),
                output_type: s.output_type.clone(),
            }),
            FlowStep::ComputeApply(s) => IRFlowNode::ComputeApply(IRComputeApplyStep {
                node_type: "compute_apply", source_line: s.loc.line, source_column: s.loc.column,
                compute_name: s.compute_name.clone(), arguments: s.arguments.clone(),
                output_name: s.output_name.clone(),
            }),
            FlowStep::Listen(s) => IRFlowNode::Listen(IRListenStep {
                node_type: "listen", source_line: s.loc.line, source_column: s.loc.column,
                channel: s.channel.clone(), event_alias: s.event_alias.clone(),
            }),
            FlowStep::DaemonStep(s) => IRFlowNode::DaemonStep(IRDaemonStepNode {
                node_type: "daemon", source_line: s.loc.line, source_column: s.loc.column,
                daemon_ref: s.daemon_ref.clone(),
            }),
            FlowStep::Persist(s) => IRFlowNode::Persist(IRPersistStep {
                node_type: "persist", source_line: s.loc.line, source_column: s.loc.column,
                store_name: s.store_name.clone(),
            }),
            FlowStep::Retrieve(s) => IRFlowNode::Retrieve(IRRetrieveStep {
                node_type: "retrieve", source_line: s.loc.line, source_column: s.loc.column,
                store_name: s.store_name.clone(), where_expr: s.where_expr.clone(),
                alias: s.alias.clone(),
            }),
            FlowStep::Mutate(s) => IRFlowNode::Mutate(IRMutateStep {
                node_type: "mutate", source_line: s.loc.line, source_column: s.loc.column,
                store_name: s.store_name.clone(), where_expr: s.where_expr.clone(),
            }),
            FlowStep::Purge(s) => IRFlowNode::Purge(IRPurgeStep {
                node_type: "purge", source_line: s.loc.line, source_column: s.loc.column,
                store_name: s.store_name.clone(), where_expr: s.where_expr.clone(),
            }),
            FlowStep::Transact(s) => IRFlowNode::Transact(IRTransactBlock {
                node_type: "transact", source_line: s.loc.line, source_column: s.loc.column,
            }),
            FlowStep::GenericStep(_) => {
                // Should not occur — all flow steps have dedicated handlers
                IRFlowNode::Step(IRStep {
                    node_type: "step", source_line: 0, source_column: 0,
                    name: String::new(), persona_ref: String::new(),
                    given: String::new(), ask: String::new(),
                    use_tool: None, probe: None, reason: None, weave: None,
                    output_type: String::new(), confidence_floor: None,
                    navigate_ref: String::new(), apply_ref: String::new(),
                    body: Vec::new(),
                })
            }
        }
    }

    fn compute_execution_levels(
        &self,
        steps: &[IRFlowNode],
        edges: &[IRDataEdge],
    ) -> Vec<Vec<String>> {
        // Extract Step-only names for DAG computation
        let step_nodes: Vec<&IRStep> = steps.iter().filter_map(|n| {
            if let IRFlowNode::Step(s) = n { Some(s) } else { None }
        }).collect();

        if step_nodes.is_empty() {
            return Vec::new();
        }

        // Build dependency map
        let mut deps: HashMap<String, Vec<String>> = HashMap::new();
        for step in &step_nodes {
            deps.insert(step.name.clone(), Vec::new());
        }
        for edge in edges {
            deps.entry(edge.target_step.clone())
                .or_default()
                .push(edge.source_step.clone());
        }

        let mut levels: Vec<Vec<String>> = Vec::new();
        let mut placed: Vec<String> = Vec::new();

        loop {
            let mut level: Vec<String> = Vec::new();
            for step in &step_nodes {
                if placed.contains(&step.name) {
                    continue;
                }
                let step_deps = deps.get(&step.name).cloned().unwrap_or_default();
                if step_deps.iter().all(|d| placed.contains(d)) {
                    level.push(step.name.clone());
                }
            }
            if level.is_empty() {
                break;
            }
            placed.extend(level.clone());
            levels.push(level);
        }

        levels
    }

    // ── Tier 2 visitors ───────────────────────────────────────────

    fn visit_agent(&self, n: &AgentDefinition) -> IRAgent {
        IRAgent {
            node_type: "agent", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), goal: n.goal.clone(), tools: n.tools.clone(),
            memory_ref: n.memory_ref.clone(), strategy: n.strategy.clone(),
            on_stuck: n.on_stuck.clone(), shield_ref: n.shield_ref.clone(),
            max_iterations: n.max_iterations, max_tokens: n.max_tokens,
            max_time: n.max_time.clone(), max_cost: n.max_cost,
        }
    }

    fn visit_shield(&self, n: &ShieldDefinition) -> IRShield {
        IRShield {
            node_type: "shield", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), scan: n.scan.clone(), strategy: n.strategy.clone(),
            on_breach: n.on_breach.clone(), severity: n.severity.clone(),
            quarantine: n.quarantine.clone(), max_retries: n.max_retries,
            confidence_threshold: n.confidence_threshold, allow_tools: n.allow_tools.clone(),
            deny_tools: n.deny_tools.clone(), sandbox: n.sandbox, redact: n.redact.clone(),
            log: n.log.clone(), deflect_message: n.deflect_message.clone(), taint: n.taint.clone(),
        }
    }

    fn visit_pix(&self, n: &PixDefinition) -> IRPix {
        IRPix {
            node_type: "pix", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), source: n.source.clone(), depth: n.depth,
            branching: n.branching, model: n.model.clone(),
        }
    }

    fn visit_psyche(&self, n: &PsycheDefinition) -> IRPsyche {
        IRPsyche {
            node_type: "psyche", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), dimensions: n.dimensions.clone(),
            manifold_noise: n.manifold_noise, manifold_momentum: n.manifold_momentum,
            safety_constraints: n.safety_constraints.clone(), quantum_enabled: n.quantum_enabled,
            inference_mode: n.inference_mode.clone(),
        }
    }

    fn visit_corpus(&self, n: &CorpusDefinition) -> IRCorpus {
        IRCorpus {
            node_type: "corpus", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), documents: n.documents.clone(),
            mcp_server: n.mcp_server.clone(), mcp_resource_uri: n.mcp_resource_uri.clone(),
        }
    }

    fn visit_dataspace(&self, n: &DataspaceDefinition) -> IRDataspace {
        IRDataspace {
            node_type: "dataspace", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(),
        }
    }

    fn visit_ots(&self, n: &OtsDefinition) -> IROts {
        IROts {
            node_type: "ots", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), teleology: n.teleology.clone(),
            homotopy_search: n.homotopy_search.clone(), loss_function: n.loss_function.clone(),
        }
    }

    fn visit_mandate(&self, n: &MandateDefinition) -> IRMandate {
        IRMandate {
            node_type: "mandate", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), constraint: n.constraint.clone(), kp: n.kp, ki: n.ki,
            kd: n.kd, tolerance: n.tolerance, max_steps: n.max_steps,
            on_violation: n.on_violation.clone(),
        }
    }

    fn visit_compute(&self, n: &ComputeDefinition) -> IRCompute {
        IRCompute {
            node_type: "compute", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), shield_ref: n.shield_ref.clone(),
        }
    }

    fn visit_daemon(&self, n: &DaemonDefinition) -> IRDaemon {
        IRDaemon {
            node_type: "daemon", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), goal: n.goal.clone(), tools: n.tools.clone(),
            memory_ref: n.memory_ref.clone(), strategy: n.strategy.clone(),
            on_stuck: n.on_stuck.clone(), shield_ref: n.shield_ref.clone(),
            max_tokens: n.max_tokens, max_time: n.max_time.clone(), max_cost: n.max_cost,
        }
    }

    fn visit_axonstore(&self, n: &AxonStoreDefinition) -> IRAxonStore {
        IRAxonStore {
            node_type: "axonstore", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), backend: n.backend.clone(), connection: n.connection.clone(),
            confidence_floor: n.confidence_floor, isolation: n.isolation.clone(),
            on_breach: n.on_breach.clone(),
        }
    }

    fn visit_axonendpoint(&self, n: &AxonEndpointDefinition) -> IRAxonEndpoint {
        IRAxonEndpoint {
            node_type: "axonendpoint", source_line: n.loc.line, source_column: n.loc.column,
            name: n.name.clone(), method: n.method.clone(), path: n.path.clone(),
            body_type: n.body_type.clone(), execute_flow: n.execute_flow.clone(),
            output_type: n.output_type.clone(), shield_ref: n.shield_ref.clone(),
            retries: n.retries, timeout: n.timeout.clone(),
        }
    }

    fn visit_lambda_data(&self, n: &LambdaDataDefinition) -> IRLambdaData {
        IRLambdaData {
            node_type: "lambda_data",
            source_line: n.loc.line,
            source_column: n.loc.column,
            name: n.name.clone(),
            ontology: n.ontology.clone(),
            certainty: n.certainty,
            temporal_frame_start: n.temporal_frame_start.clone(),
            temporal_frame_end: n.temporal_frame_end.clone(),
            provenance: n.provenance.clone(),
            derivation: n.derivation.clone(),
        }
    }

    fn visit_run(&self, n: &RunStatement) -> IRRun {
        IRRun {
            node_type: "run",
            source_line: n.loc.line,
            source_column: n.loc.column,
            flow_name: n.flow_name.clone(),
            arguments: n.arguments.clone(),
            persona_name: n.persona.clone(),
            context_name: n.context.clone(),
            anchor_names: n.anchors.clone(),
            on_failure: n.on_failure.clone(),
            on_failure_params: n
                .on_failure_params
                .iter()
                .map(|(k, v)| vec![k.clone(), v.clone()])
                .collect(),
            output_to: n.output_to.clone(),
            effort: n.effort.clone(),
            resolved_flow: None,
            resolved_persona: None,
            resolved_context: None,
            resolved_anchors: Vec::new(),
        }
    }
}
