"""
AXON Compiler — Parser
========================
Recursive descent parser: Token stream → Cognitive AST.

One method per EBNF grammar rule. Produces a tree of cognitive nodes
(PersonaDefinition, FlowDefinition, ReasonChain, …) — no mechanical nodes.

Entry point: Parser(tokens).parse() → ProgramNode
"""

from __future__ import annotations

from .ast_nodes import (
    ASTNode,
    AgentBudget,
    AgentDefinition,
    AggregateNode,
    AnchorConstraint,
    AssociateNode,
    AxonEndpointDefinition,
    AxonStoreDefinition,
    ConditionalNode,
    ConsensusBlock,
    ContextDefinition,
    CorpusDefinition,
    CorpusDocEntry,
    CorpusEdgeEntry,
    CorroborateNode,
    DaemonBudget,
    DaemonDefinition,
    DataSpaceDefinition,
    DeliberateBlock,
    DrillNode,
    EffectRowNode,
    EpistemicBlock,
    ExploreNode,
    FlowDefinition,
    FocusNode,
    ForInStatement,
    ForgeBlock,
    HibernateNode,
    ImportNode,
    IngestNode,
    IntentNode,
    ComputeApplyNode,
    ComputeDefinition,
    LambdaDataApplyNode,
    LambdaDataDefinition,
    LetStatement,
    ListenBlock,
    MandateApplyNode,
    MandateDefinition,
    MemoryDefinition,
    MutateNode,
    NavigateNode,
    OtsApplyNode,
    OtsDefinition,
    ParallelBlock,
    ParameterNode,
    PersistNode,
    PersonaDefinition,
    PixDefinition,
    ProbeDirective,
    ProgramNode,
    PsycheDefinition,
    PurgeNode,
    RangeConstraint,
    ReasonChain,
    RecallNode,
    RefineBlock,
    RememberNode,
    RetrieveNode,
    ReturnStatement,
    RunStatement,
    ShieldApplyNode,
    ShieldDefinition,
    StepNode,
    StoreColumnNode,
    StoreSchemaNode,
    StreamDefinition,
    StreamHandlerNode,
    ToolDefinition,
    TrailNode,
    TransactNode,
    TypeDefinition,
    TypeExprNode,
    TypeFieldNode,
    UseToolNode,
    ValidateGate,
    ValidateRule,
    WeaveNode,
    WhereClause,
)
from .errors import AxonParseError
from .tokens import Token, TokenType


class Parser:
    """Recursive descent parser for the AXON language."""

    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    # ── public API ────────────────────────────────────────────────

    def parse(self) -> ProgramNode:
        """Parse the full program → ProgramNode."""
        program = ProgramNode(line=1, column=1)
        while not self._check(TokenType.EOF):
            decl = self._parse_declaration()
            if decl is not None:
                program.declarations.append(decl)
        return program

    # ── top-level dispatch ────────────────────────────────────────

    def _parse_declaration(self) -> ASTNode | None:
        """Dispatch to the correct declaration parser based on current token."""
        tok = self._current()

        match tok.type:
            case TokenType.IMPORT:
                return self._parse_import()
            case TokenType.PERSONA:
                return self._parse_persona()
            case TokenType.CONTEXT:
                return self._parse_context()
            case TokenType.ANCHOR:
                return self._parse_anchor()
            case TokenType.MEMORY:
                return self._parse_memory()
            case TokenType.TOOL:
                return self._parse_tool()
            case TokenType.TYPE:
                return self._parse_type()
            case TokenType.FLOW:
                return self._parse_flow()
            case TokenType.INTENT:
                return self._parse_intent()
            case TokenType.RUN:
                return self._parse_run()
            case TokenType.KNOW | TokenType.BELIEVE | TokenType.SPECULATE | TokenType.DOUBT:
                return self._parse_epistemic_block()
            case TokenType.DATASPACE:
                return self._parse_dataspace()
            case TokenType.INGEST:
                return self._parse_ingest()
            case TokenType.AGENT:
                return self._parse_agent()
            case TokenType.SHIELD:
                return self._parse_shield()
            case TokenType.PIX:
                return self._parse_pix_definition()
            case TokenType.CORPUS:
                return self._parse_corpus_definition()
            case TokenType.PSYCHE:
                return self._parse_psyche()
            case TokenType.OTS:
                return self._parse_ots_definition()
            case TokenType.MANDATE:
                return self._parse_mandate()
            case TokenType.COMPUTE:
                return self._parse_compute()
            case TokenType.LAMBDA:
                return self._parse_lambda_data()
            case TokenType.DAEMON:
                return self._parse_daemon()
            case TokenType.AXONSTORE:
                return self._parse_axonstore()
            case TokenType.AXONENDPOINT:
                return self._parse_axonendpoint()
            case TokenType.PERSIST:
                return self._parse_persist()
            case TokenType.RETRIEVE:
                return self._parse_retrieve()
            case TokenType.MUTATE:
                return self._parse_mutate()
            case TokenType.PURGE:
                return self._parse_purge()
            case TokenType.TRANSACT:
                return self._parse_transact()
            case TokenType.LET:
                return self._parse_let()
            case _:
                raise AxonParseError(
                    f"Unexpected token at top level",
                    line=tok.line,
                    column=tok.column,
                    expected="declaration (persona, context, anchor, flow, agent, shield, psyche, pix, ots, mandate, lambda, daemon, axonstore, run, know, speculate, ...)",
                    found=tok.value,
                )

    # ── IMPORT ────────────────────────────────────────────────────

    def _parse_import(self) -> ImportNode:
        """import axon.anchors.{NoHallucination, NoBias}"""
        tok = self._consume(TokenType.IMPORT)
        node = ImportNode(line=tok.line, column=tok.column)

        # module path: [@] IDENTIFIER { . IDENTIFIER }
        if self._check(TokenType.AT):
            self._advance()  # consume @ scope operator
            first = self._consume(TokenType.IDENTIFIER)
            path_parts = ["@" + first.value]
        else:
            first = self._consume(TokenType.IDENTIFIER)
            path_parts = [first.value]
        while self._check(TokenType.DOT):
            self._advance()  # consume DOT
            # If the next token is '{', the DOT is a separator before named imports
            if self._check(TokenType.LBRACE):
                break
            part = self._consume(TokenType.IDENTIFIER)
            path_parts.append(part.value)
        node.module_path = path_parts

        # optional named imports: { Name1, Name2 }
        if self._check(TokenType.LBRACE):
            self._advance()
            node.names = self._parse_identifier_list()
            self._consume(TokenType.RBRACE)

        # optional APX policy: with apx { ... }
        if self._check_contextual_keyword("with"):
            self._advance()  # consume contextual 'with'
            apx_kw = self._consume_any_identifier_or_keyword()
            if apx_kw.value.lower() != "apx":
                raise AxonParseError(
                    "Invalid import policy scope",
                    line=apx_kw.line,
                    column=apx_kw.column,
                    expected="apx",
                    found=apx_kw.value,
                )
            node.apx_enabled = True
            if self._check(TokenType.LBRACE):
                node.apx_policy = self._parse_apx_policy_block()

        return node

    def _parse_apx_policy_block(self) -> dict[str, object]:
        """Parse APX import policy block.

        Example:
          with apx {
            min_epr: 0.70
            on_low_rank: quarantine
            require_pcc: true
          }
        """
        policy: dict[str, object] = {}
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            key_tok = self._consume_any_identifier_or_keyword()
            key = key_tok.value
            self._consume(TokenType.COLON)
            value = self._parse_apx_value()
            policy[key] = value

            if self._check(TokenType.COMMA):
                self._advance()

        self._consume(TokenType.RBRACE)
        return policy

    def _parse_apx_value(self) -> object:
        """Parse a scalar/list APX policy value."""
        if self._check(TokenType.AT):
            self._advance()
            scoped = self._consume(TokenType.IDENTIFIER)
            return "@" + scoped.value

        if self._check(TokenType.LBRACKET):
            self._consume(TokenType.LBRACKET)
            items: list[object] = []
            if not self._check(TokenType.RBRACKET):
                items.append(self._parse_apx_value())
                while self._check(TokenType.COMMA):
                    self._advance()
                    if self._check(TokenType.RBRACKET):
                        break
                    items.append(self._parse_apx_value())
            self._consume(TokenType.RBRACKET)
            return items

        tok = self._current()
        if tok.type == TokenType.STRING:
            return self._advance().value
        if tok.type == TokenType.BOOL:
            return self._parse_bool()
        if tok.type == TokenType.FLOAT:
            return float(self._advance().value)
        if tok.type == TokenType.INTEGER:
            return int(self._advance().value)

        return self._consume_any_identifier_or_keyword().value

    # ── PERSONA ───────────────────────────────────────────────────

    def _parse_persona(self) -> PersonaDefinition:
        tok = self._consume(TokenType.PERSONA)
        name = self._consume(TokenType.IDENTIFIER)
        node = PersonaDefinition(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "domain":
                    node.domain = self._parse_string_list()
                case "tone":
                    node.tone = self._consume_any_identifier_or_keyword().value
                case "confidence_threshold":
                    node.confidence_threshold = float(self._consume(TokenType.FLOAT).value)
                case "cite_sources":
                    node.cite_sources = self._parse_bool()
                case "refuse_if":
                    node.refuse_if = self._parse_bracketed_identifiers()
                case "language":
                    node.language = self._consume(TokenType.STRING).value
                case "description":
                    node.description = self._consume(TokenType.STRING).value
                case _:
                    # skip unknown fields gracefully
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── CONTEXT ───────────────────────────────────────────────────

    def _parse_context(self) -> ContextDefinition:
        tok = self._consume(TokenType.CONTEXT)
        name = self._consume(TokenType.IDENTIFIER)
        node = ContextDefinition(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "memory":
                    node.memory_scope = self._consume_any_identifier_or_keyword().value
                case "language":
                    node.language = self._consume(TokenType.STRING).value
                case "depth":
                    node.depth = self._consume_any_identifier_or_keyword().value
                case "max_tokens":
                    node.max_tokens = int(self._consume(TokenType.INTEGER).value)
                case "temperature":
                    node.temperature = float(self._consume(TokenType.FLOAT).value)
                case "cite_sources":
                    node.cite_sources = self._parse_bool()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── ANCHOR ────────────────────────────────────────────────────

    def _parse_anchor(self) -> AnchorConstraint:
        tok = self._consume(TokenType.ANCHOR)
        name = self._consume(TokenType.IDENTIFIER)
        node = AnchorConstraint(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "require":
                    node.require = self._consume_any_identifier_or_keyword().value
                case "description":
                    node.description = self._consume(TokenType.STRING).value
                case "reject":
                    node.reject = self._parse_bracketed_identifiers()
                case "enforce":
                    node.enforce = self._consume_any_identifier_or_keyword().value
                case "confidence_floor":
                    node.confidence_floor = float(self._consume(TokenType.FLOAT).value)
                case "unknown_response":
                    node.unknown_response = self._consume(TokenType.STRING).value
                case "on_violation":
                    action, target = self._parse_violation_action()
                    node.on_violation = action
                    node.on_violation_target = target
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_violation_action(self) -> tuple[str, str]:
        """Parse: raise ErrorName | warn | log | escalate | fallback("...")"""
        tok = self._current()
        if tok.value == "raise":
            self._advance()
            target = self._consume(TokenType.IDENTIFIER)
            return ("raise", target.value)
        elif tok.value in ("warn", "log", "escalate"):
            self._advance()
            return (tok.value, "")
        elif tok.value == "fallback":
            self._advance()
            self._consume(TokenType.LPAREN)
            msg = self._consume(TokenType.STRING)
            self._consume(TokenType.RPAREN)
            return ("fallback", msg.value)
        else:
            self._advance()
            return (tok.value, "")

    # ── MEMORY ────────────────────────────────────────────────────

    def _parse_memory(self) -> MemoryDefinition:
        tok = self._consume(TokenType.MEMORY)
        name = self._consume(TokenType.IDENTIFIER)
        node = MemoryDefinition(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "store":
                    node.store = self._consume_any_identifier_or_keyword().value
                case "backend":
                    node.backend = self._consume_any_identifier_or_keyword().value
                case "retrieval":
                    node.retrieval = self._consume_any_identifier_or_keyword().value
                case "decay":
                    tok_val = self._current()
                    if tok_val.type == TokenType.DURATION:
                        node.decay = self._advance().value
                    else:
                        node.decay = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── TOOL ──────────────────────────────────────────────────────

    def _parse_tool(self) -> ToolDefinition:
        tok = self._consume(TokenType.TOOL)
        name = self._consume(TokenType.IDENTIFIER)
        node = ToolDefinition(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "provider":
                    node.provider = self._consume_any_identifier_or_keyword().value
                case "max_results":
                    node.max_results = int(self._consume(TokenType.INTEGER).value)
                case "filter":
                    node.filter_expr = self._parse_filter_expression()
                case "timeout":
                    node.timeout = self._consume(TokenType.DURATION).value
                case "runtime":
                    node.runtime = self._consume_any_identifier_or_keyword().value
                case "sandbox":
                    node.sandbox = self._parse_bool()
                case "effects":
                    # v0.14.0 — CT-2: parse effect row <eff1, eff2, epistemic:level>
                    node.effects = self._parse_effect_row()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_filter_expression(self) -> str:
        """Parse filter: recent(days: 30) or just an identifier."""
        tok = self._current()
        name = self._consume_any_identifier_or_keyword().value
        if self._check(TokenType.LPAREN):
            self._advance()
            parts = [name, "("]
            while not self._check(TokenType.RPAREN):
                parts.append(self._advance().value)
            self._consume(TokenType.RPAREN)
            parts.append(")")
            return "".join(parts)
        return name

    # ── TYPE ──────────────────────────────────────────────────────

    def _parse_type(self) -> TypeDefinition:
        tok = self._consume(TokenType.TYPE)
        name = self._consume(TokenType.IDENTIFIER)
        node = TypeDefinition(name=name.value, line=tok.line, column=tok.column)

        # optional range constraint: (0.0..1.0)
        if self._check(TokenType.LPAREN):
            self._advance()
            min_val = self._consume_number()
            self._consume(TokenType.DOTDOT)
            max_val = self._consume_number()
            self._consume(TokenType.RPAREN)
            node.range_constraint = RangeConstraint(
                min_value=min_val, max_value=max_val,
                line=tok.line, column=tok.column,
            )

        # optional where clause
        if self._check(TokenType.WHERE):
            self._advance()
            expr_parts: list[str] = []
            # consume until { or next declaration keyword or EOF
            while not self._check(TokenType.LBRACE) and not self._at_declaration_start():
                if self._check(TokenType.EOF):
                    break
                expr_parts.append(self._advance().value)
            node.where_clause = WhereClause(
                expression=" ".join(expr_parts),
                line=tok.line,
                column=tok.column,
            )

        # optional body: { field: Type, ... }
        if self._check(TokenType.LBRACE):
            self._advance()
            while not self._check(TokenType.RBRACE):
                field_name = self._consume(TokenType.IDENTIFIER)
                self._consume(TokenType.COLON)
                type_expr = self._parse_type_expr()
                node.fields.append(TypeFieldNode(
                    name=field_name.value,
                    type_expr=type_expr,
                    line=field_name.line,
                    column=field_name.column,
                ))
                # optional comma
                if self._check(TokenType.COMMA):
                    self._advance()
            self._consume(TokenType.RBRACE)

        return node

    def _parse_type_expr(self) -> TypeExprNode:
        """Parse a type expression: Identifier, List<T>, or Type?"""
        name_tok = self._consume(TokenType.IDENTIFIER)
        node = TypeExprNode(name=name_tok.value, line=name_tok.line, column=name_tok.column)

        # generic: List<Party>
        if self._check(TokenType.LT):
            self._advance()
            param = self._consume(TokenType.IDENTIFIER)
            node.generic_param = param.value
            self._consume(TokenType.GT)

        # optional: FactualClaim?
        if self._check(TokenType.QUESTION):
            self._advance()
            node.optional = True

        return node

    # ── INTENT ────────────────────────────────────────────────────

    def _parse_intent(self) -> IntentNode:
        tok = self._consume(TokenType.INTENT)
        name = self._consume(TokenType.IDENTIFIER)
        node = IntentNode(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "given":
                    node.given = self._consume(TokenType.IDENTIFIER).value
                case "ask":
                    node.ask = self._consume(TokenType.STRING).value
                case "output":
                    node.output_type = self._parse_type_expr()
                case "confidence_floor":
                    node.confidence_floor = float(self._consume(TokenType.FLOAT).value)
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── FLOW ──────────────────────────────────────────────────────

    def _parse_flow(self) -> FlowDefinition:
        tok = self._consume(TokenType.FLOW)
        name = self._consume(TokenType.IDENTIFIER)
        node = FlowDefinition(name=name.value, line=tok.line, column=tok.column)

        # parameters: (param: Type, ...)
        self._consume(TokenType.LPAREN)
        if not self._check(TokenType.RPAREN):
            node.parameters = self._parse_param_list()
        self._consume(TokenType.RPAREN)

        # optional return type: -> ReturnType
        if self._check(TokenType.ARROW):
            self._advance()
            node.return_type = self._parse_type_expr()

        # body
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            step = self._parse_flow_step()
            if step is not None:
                node.body.append(step)
        self._consume(TokenType.RBRACE)

        return node

    def _parse_param_list(self) -> list[ParameterNode]:
        params: list[ParameterNode] = []
        # first param
        name = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.COLON)
        type_expr = self._parse_type_expr()
        params.append(ParameterNode(
            name=name.value, type_expr=type_expr,
            line=name.line, column=name.column,
        ))
        # additional params
        while self._check(TokenType.COMMA):
            self._advance()
            name = self._consume(TokenType.IDENTIFIER)
            self._consume(TokenType.COLON)
            type_expr = self._parse_type_expr()
            params.append(ParameterNode(
                name=name.value, type_expr=type_expr,
                line=name.line, column=name.column,
            ))
        return params

    # ── FLOW STEPS ────────────────────────────────────────────────

    def _parse_flow_step(self) -> ASTNode | None:
        """Dispatch to the correct step parser."""
        tok = self._current()

        match tok.type:
            case TokenType.STEP:
                return self._parse_step()
            case TokenType.PROBE:
                return self._parse_probe()
            case TokenType.REASON:
                return self._parse_reason()
            case TokenType.VALIDATE:
                return self._parse_validate()
            case TokenType.REFINE:
                return self._parse_refine()
            case TokenType.WEAVE:
                return self._parse_weave()
            case TokenType.USE:
                return self._parse_use_tool()
            case TokenType.REMEMBER:
                return self._parse_remember()
            case TokenType.RECALL:
                return self._parse_recall()
            case TokenType.IF:
                return self._parse_if()
            case TokenType.PAR:
                return self._parse_par_block()
            case TokenType.HIBERNATE:
                return self._parse_hibernate()
            case TokenType.DELIBERATE:
                return self._parse_deliberate()
            case TokenType.CONSENSUS:
                return self._parse_consensus()
            case TokenType.FORGE:
                return self._parse_forge()
            case TokenType.FOCUS:
                return self._parse_focus()
            case TokenType.ASSOCIATE:
                return self._parse_associate()
            case TokenType.AGGREGATE:
                return self._parse_aggregate()
            case TokenType.EXPLORE:
                return self._parse_explore()
            case TokenType.INGEST:
                return self._parse_ingest()
            case TokenType.SHIELD:
                return self._parse_shield_apply()
            case TokenType.STREAM:
                # v0.14.0 — CT-1: stream<τ> definition
                return self._parse_stream_definition()
            case TokenType.NAVIGATE:
                return self._parse_navigate()
            case TokenType.DRILL:
                return self._parse_drill()
            case TokenType.TRAIL:
                return self._parse_trail()
            case TokenType.CORROBORATE:
                return self._parse_corroborate()
            case TokenType.OTS:
                return self._parse_ots_apply()
            case TokenType.MANDATE:
                return self._parse_mandate_apply()
            case TokenType.COMPUTE:
                return self._parse_compute_apply()
            case TokenType.LAMBDA:
                return self._parse_lambda_data_apply()
            case TokenType.LISTEN:
                return self._parse_listen()
            case TokenType.DAEMON:
                return self._parse_daemon()
            case TokenType.PERSIST:
                return self._parse_persist()
            case TokenType.RETRIEVE:
                return self._parse_retrieve()
            case TokenType.MUTATE:
                return self._parse_mutate()
            case TokenType.PURGE:
                return self._parse_purge()
            case TokenType.TRANSACT:
                return self._parse_transact()
            case TokenType.FOR:
                return self._parse_for_in()
            case TokenType.LET:
                return self._parse_let()
            case TokenType.RETURN:
                return self._parse_return()
            case _:
                raise AxonParseError(
                    "Unexpected token in flow body",
                    line=tok.line,
                    column=tok.column,
                    expected="step, probe, reason, validate, refine, weave, use, remember, recall, if, par, hibernate, shield, stream, navigate, drill, trail, corroborate, ots, mandate, lambda, daemon, listen, persist, retrieve, mutate, purge, transact, focus, associate, aggregate, explore, ingest, let, return",
                    found=tok.value,
                )

    def _parse_step(self) -> StepNode:
        tok = self._consume(TokenType.STEP)
        name = self._consume(TokenType.IDENTIFIER)
        node = StepNode(name=name.value, line=tok.line, column=tok.column)

        # v0.25.4 — Gap 1: step X use Persona { }
        # LL(1) peek: if USE appears before LBRACE, it's persona binding
        if self._check(TokenType.USE):
            self._advance()  # consume USE
            node.persona_ref = self._consume_any_identifier_or_keyword().value

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                case TokenType.GIVEN:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.given = self._parse_expression_string()

                case TokenType.ASK:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.ask = self._consume(TokenType.STRING).value

                case TokenType.USE:
                    node.use_tool = self._parse_use_tool()

                case TokenType.PROBE:
                    node.probe = self._parse_probe()

                case TokenType.REASON:
                    node.reason = self._parse_reason()

                case TokenType.WEAVE:
                    node.weave = self._parse_weave()

                case TokenType.STREAM:
                    # v0.14.0 — CT-1: stream<τ> inside step body
                    node.body.append(self._parse_stream_definition())

                case TokenType.OUTPUT:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.output_type = self._consume(TokenType.IDENTIFIER).value

                case TokenType.IDENTIFIER if inner.value == "confidence_floor":
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.confidence_floor = float(self._consume(TokenType.FLOAT).value)

                # v0.25.4 — Gap 2: navigate: / apply: step fields
                case TokenType.NAVIGATE:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.navigate_ref = self._parse_dotted_identifier()

                case TokenType.IDENTIFIER if inner.value == "apply":
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.apply_ref = self._consume_any_identifier_or_keyword().value

                case _:
                    raise AxonParseError(
                        "Unexpected token in step body",
                        line=inner.line,
                        column=inner.column,
                        expected="given, ask, use, probe, reason, weave, stream, output, confidence_floor, navigate, apply",
                        found=inner.value,
                    )

        self._consume(TokenType.RBRACE)
        return node

    # ── PROBE ─────────────────────────────────────────────────────

    def _parse_probe(self) -> ProbeDirective:
        tok = self._consume(TokenType.PROBE)
        target = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.FOR)
        fields = self._parse_bracketed_identifiers()
        return ProbeDirective(
            target=target.value,
            fields=fields,
            line=tok.line,
            column=tok.column,
        )

    # ── REASON ────────────────────────────────────────────────────

    def _parse_reason(self) -> ReasonChain:
        tok = self._consume(TokenType.REASON)
        node = ReasonChain(line=tok.line, column=tok.column)

        # optional: about <Topic>
        if self._check(TokenType.ABOUT):
            self._advance()
            node.about = self._consume(TokenType.IDENTIFIER).value
        elif self._check(TokenType.IDENTIFIER):
            node.name = self._current().value
            self._advance()

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "given":
                    node.given = self._parse_expression_string()
                case "about":
                    node.about = self._consume(TokenType.STRING).value
                case "ask":
                    node.ask = self._consume(TokenType.STRING).value
                case "depth":
                    node.depth = int(self._consume(TokenType.INTEGER).value)
                case "show_work":
                    node.show_work = self._parse_bool()
                case "chain_of_thought":
                    node.chain_of_thought = self._parse_bool()
                case "output":
                    node.output_type = self._consume(TokenType.IDENTIFIER).value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── VALIDATE ──────────────────────────────────────────────────

    def _parse_validate(self) -> ValidateGate:
        tok = self._consume(TokenType.VALIDATE)
        target = self._parse_dotted_identifier()
        self._consume(TokenType.AGAINST)
        schema = self._consume(TokenType.IDENTIFIER)
        node = ValidateGate(
            target=target, schema=schema.value,
            line=tok.line, column=tok.column,
        )
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            rule = self._parse_validate_rule()
            node.rules.append(rule)

        self._consume(TokenType.RBRACE)
        return node

    def _parse_validate_rule(self) -> ValidateRule:
        """Parse: if condition -> action"""
        tok = self._consume(TokenType.IF)
        rule = ValidateRule(line=tok.line, column=tok.column)

        # condition: identifier [op value]
        cond = self._consume_any_identifier_or_keyword()
        rule.condition = cond.value

        if self._check_comparison():
            rule.comparison_op = self._advance().value
            rule.comparison_value = self._advance().value

        self._consume(TokenType.ARROW)

        # action: refine(...) | raise X | warn "..." | pass
        action_tok = self._current()
        if action_tok.value == "refine":
            self._advance()
            rule.action = "refine"
            if self._check(TokenType.LPAREN):
                self._advance()
                while not self._check(TokenType.RPAREN):
                    key = self._consume_any_identifier_or_keyword().value
                    self._consume(TokenType.COLON)
                    val = self._advance().value
                    rule.action_params[key] = val
                    if self._check(TokenType.COMMA):
                        self._advance()
                self._consume(TokenType.RPAREN)
        elif action_tok.value == "raise":
            self._advance()
            rule.action = "raise"
            rule.action_target = self._consume(TokenType.IDENTIFIER).value
        elif action_tok.value == "warn":
            self._advance()
            rule.action = "warn"
            rule.action_target = self._consume(TokenType.STRING).value
        elif action_tok.value == "pass":
            self._advance()
            rule.action = "pass"
        else:
            self._advance()
            rule.action = action_tok.value

        return rule

    # ── REFINE ────────────────────────────────────────────────────

    def _parse_refine(self) -> RefineBlock:
        tok = self._consume(TokenType.REFINE)
        node = RefineBlock(line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "max_attempts":
                    node.max_attempts = int(self._consume(TokenType.INTEGER).value)
                case "pass_failure_context":
                    node.pass_failure_context = self._parse_bool()
                case "backoff":
                    node.backoff = self._consume_any_identifier_or_keyword().value
                case "on_exhaustion":
                    action, target = self._parse_violation_action()
                    node.on_exhaustion = action
                    node.on_exhaustion_target = target
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── WEAVE ─────────────────────────────────────────────────────

    def _parse_weave(self) -> WeaveNode:
        tok = self._consume(TokenType.WEAVE)
        sources = self._parse_bracketed_dot_identifiers()
        self._consume(TokenType.INTO)
        target = self._consume(TokenType.IDENTIFIER)
        node = WeaveNode(
            sources=sources, target=target.value,
            line=tok.line, column=tok.column,
        )

        if self._check(TokenType.LBRACE):
            self._advance()
            while not self._check(TokenType.RBRACE):
                field_tok = self._current()
                field_name = field_tok.value
                self._advance()
                self._consume(TokenType.COLON)

                match field_name:
                    case "format":
                        node.format_type = self._consume(TokenType.IDENTIFIER).value
                    case "priority":
                        node.priority = self._parse_bracketed_identifiers()
                    case "style":
                        node.style = self._consume(TokenType.STRING).value
                    case _:
                        self._skip_value()

            self._consume(TokenType.RBRACE)

        return node

    # ── USE TOOL ──────────────────────────────────────────────────

    def _parse_use_tool(self) -> UseToolNode:
        tok = self._consume(TokenType.USE)
        tool_name = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.LPAREN)

        arg = ""
        static_args: dict[str, object] = {}

        if not self._check(TokenType.RPAREN):
            # Lookahead: if next token is ASSIGN → key=value mode
            # (key can be IDENTIFIER or contextual keyword like 'strategy')
            next_pos = self._pos + 1
            is_named = (
                next_pos < len(self._tokens)
                and self._tokens[next_pos].type == TokenType.ASSIGN
            )

            if is_named:
                # ── key=value parsing loop ────────────────────────
                while not self._check(TokenType.RPAREN):
                    key = self._consume_any_identifier_or_keyword().value
                    self._consume(TokenType.ASSIGN)
                    # Parse value: STRING | INTEGER | FLOAT | BOOL | dotted IDENTIFIER
                    val_tok = self._current()
                    if val_tok.type == TokenType.STRING:
                        static_args[key] = self._advance().value
                    elif val_tok.type == TokenType.INTEGER:
                        static_args[key] = int(self._advance().value)
                    elif val_tok.type == TokenType.FLOAT:
                        static_args[key] = float(self._advance().value)
                    elif val_tok.type == TokenType.BOOL:
                        static_args[key] = self._advance().value == "true"
                    else:
                        # Dotted path: IDENTIFIER { . IDENTIFIER }
                        parts = [self._consume_any_identifier_or_keyword().value]
                        while self._check(TokenType.DOT):
                            self._advance()
                            parts.append(self._consume_any_identifier_or_keyword().value)
                        static_args[key] = ".".join(parts)
                    # Optional comma separator
                    if self._check(TokenType.COMMA):
                        self._advance()
            else:
                # ── Legacy positional argument ────────────────────
                if self._check(TokenType.STRING):
                    arg = self._consume(TokenType.STRING).value
                else:
                    arg = self._consume_any_identifier_or_keyword().value

        self._consume(TokenType.RPAREN)
        return UseToolNode(
            tool_name=tool_name.value, argument=arg,
            static_args=static_args,
            line=tok.line, column=tok.column,
        )

    # ── EFFECT ROW (CT-2) ──────────────────────────────────────────

    def _parse_effect_row(self) -> EffectRowNode:
        """Parse: <eff1, eff2, epistemic:level>

        Produces an EffectRowNode with a list of effect names and
        an optional epistemic level annotation.
        """
        tok = self._consume(TokenType.LT)
        effects: list[str] = []
        epistemic_level: str = ""

        while not self._check(TokenType.GT):
            # Each entry is either a plain identifier or epistemic:level
            name_tok = self._consume_any_identifier_or_keyword()
            name = name_tok.value

            if self._check(TokenType.COLON):
                # epistemic:level syntax
                self._advance()  # consume ':'
                level_tok = self._consume_any_identifier_or_keyword()
                if name == "epistemic":
                    epistemic_level = level_tok.value
                else:
                    # Treat as composite effect name: name:qualifier
                    effects.append(f"{name}:{level_tok.value}")
            else:
                effects.append(name)

            # Consume comma separator if present
            if self._check(TokenType.COMMA):
                self._advance()

        self._consume(TokenType.GT)

        return EffectRowNode(
            effects=effects,
            epistemic_level=epistemic_level,
            line=tok.line,
            column=tok.column,
        )

    # ── STREAM DEFINITION (CT-1) ──────────────────────────────────

    def _parse_stream_definition(self) -> StreamDefinition:
        """Parse: stream<Type> { on_chunk: { ... } on_complete: { ... } }

        Produces a StreamDefinition with an element type and
        optional handler blocks.
        """
        tok = self._consume(TokenType.STREAM)

        # Parse generic parameter: stream<Type>
        element_type = ""
        if self._check(TokenType.LT):
            self._advance()  # consume '<'
            element_type = self._consume_any_identifier_or_keyword().value
            self._consume(TokenType.GT)

        node = StreamDefinition(
            element_type=element_type,
            line=tok.line,
            column=tok.column,
        )

        # Optional block body with handlers
        if self._check(TokenType.LBRACE):
            self._consume(TokenType.LBRACE)

            while not self._check(TokenType.RBRACE):
                cur = self._current()

                if cur.type == TokenType.ON_CHUNK:
                    handler_tok = self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACE)

                    handler_body: list[ASTNode] = []
                    while not self._check(TokenType.RBRACE):
                        decl = self._parse_flow_step()
                        if decl is not None:
                            handler_body.append(decl)

                    self._consume(TokenType.RBRACE)
                    node.on_chunk = StreamHandlerNode(
                        handler_type="on_chunk",
                        body=handler_body,
                        line=handler_tok.line,
                        column=handler_tok.column,
                    )

                elif cur.type == TokenType.ON_COMPLETE:
                    handler_tok = self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACE)

                    handler_body = []
                    while not self._check(TokenType.RBRACE):
                        decl = self._parse_flow_step()
                        if decl is not None:
                            handler_body.append(decl)

                    self._consume(TokenType.RBRACE)
                    node.on_complete = StreamHandlerNode(
                        handler_type="on_complete",
                        body=handler_body,
                        line=handler_tok.line,
                        column=handler_tok.column,
                    )
                else:
                    # Skip unknown fields inside stream block
                    self._advance()

            self._consume(TokenType.RBRACE)

        return node

    # ── PIX DEFINITION ────────────────────────────────────────────

    def _parse_pix_definition(self) -> PixDefinition:
        """Parse: pix Name { source: "...", depth: N, branching: N, model: M }

        Produces a PixDefinition node.
        """
        tok = self._consume(TokenType.PIX)
        name = self._consume(TokenType.IDENTIFIER)
        node = PixDefinition(name=name.value, line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "source":
                    node.source = self._consume(TokenType.STRING).value
                case "depth":
                    node.depth = int(self._consume(TokenType.INTEGER).value)
                case "branching":
                    node.branching = int(self._consume(TokenType.INTEGER).value)
                case "model":
                    node.model = self._consume_any_identifier_or_keyword().value
                case "effects":
                    node.effects = self._parse_effect_row()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── NAVIGATE (PIX retrieval) ──────────────────────────────────

    def _parse_navigate(self) -> NavigateNode:
        """Parse: navigate PixName with query: "..." trail: enabled
        or:    navigate CorpusName with query: "..." budget_depth: N budget_nodes: N edge_filter: [cite, implement]

        Produces a NavigateNode. The corpus_name / pix_name
        ambiguity is resolved at type-check time (§5.3).
        """
        tok = self._consume(TokenType.NAVIGATE)
        ref_name = self._consume(TokenType.IDENTIFIER).value
        node = NavigateNode(pix_name=ref_name, line=tok.line, column=tok.column)

        # Expect 'with' keyword (parsed as identifier)
        if self._current().value == "with":
            self._advance()

        # Parse key-value pairs
        while self._current().type in (
            TokenType.IDENTIFIER, TokenType.TRAIL, TokenType.AS,
            TokenType.EDGE_FILTER,
        ):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "query":
                    node.query_expr = self._consume(TokenType.STRING).value
                case "trail":
                    val = self._consume_any_identifier_or_keyword().value
                    node.trail_enabled = val.lower() in ("enabled", "true", "yes")
                case "as":
                    node.output_name = self._consume(TokenType.IDENTIFIER).value
                case "corpus":
                    # Reclassify: the ref is a corpus, not a pix
                    node.corpus_name = ref_name
                    node.pix_name = ""
                case "budget_depth":
                    node.budget_depth = int(self._consume(TokenType.INTEGER).value)
                case "budget_nodes":
                    node.budget_nodes = int(self._consume(TokenType.INTEGER).value)
                case "edge_filter":
                    node.edge_filter = self._parse_bracketed_identifiers()
                case _:
                    self._skip_value()

        return node

    # ── DRILL (PIX subtree descent) ───────────────────────────────

    def _parse_drill(self) -> DrillNode:
        """Parse: drill PixName into "subtree.path" with query: "..."

        Produces a DrillNode.
        """
        tok = self._consume(TokenType.DRILL)
        pix_name = self._consume(TokenType.IDENTIFIER).value
        node = DrillNode(pix_name=pix_name, line=tok.line, column=tok.column)

        # Expect 'into' keyword (parsed as identifier)
        if self._current().value == "into":
            self._advance()
            node.subtree_path = self._consume(TokenType.STRING).value

        # Expect 'with' keyword
        if self._current().value == "with":
            self._advance()

        # Parse key-value pairs
        while self._current().type in (TokenType.IDENTIFIER, TokenType.AS):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "query":
                    node.query_expr = self._consume(TokenType.STRING).value
                case "as":
                    node.output_name = self._consume(TokenType.IDENTIFIER).value
                case _:
                    self._skip_value()

        return node

    # ── TRAIL (PIX reasoning path) ────────────────────────────────

    def _parse_trail(self) -> TrailNode:
        """Parse: trail NavigateRef

        Produces a TrailNode — accesses the reasoning path.
        """
        tok = self._consume(TokenType.TRAIL)
        ref = self._consume(TokenType.IDENTIFIER).value
        return TrailNode(
            navigate_ref=ref,
            line=tok.line,
            column=tok.column,
        )

    # ── CORPUS DEFINITION (MDN §5.3) ────────────────────────────────

    def _parse_corpus_definition(self) -> CorpusDefinition:
        """Parse:
        corpus LegalCorpus {
            documents: [statute_A, case_law_B]
            relationships: [
                (case_law_B, statute_A, cite)
            ]
            weights: {
                (case_law_B, statute_A, cite): 0.9
            }
        }

        Produces a CorpusDefinition node — C = (D, R, τ, ω, σ) from §2.1.
        """
        tok = self._consume(TokenType.CORPUS)
        name = self._consume(TokenType.IDENTIFIER)
        node = CorpusDefinition(name=name.value, line=tok.line, column=tok.column)

        if self._check(TokenType.FROM):
            self._advance()
            self._consume(TokenType.MCP)
            self._consume(TokenType.LPAREN)
            node.mcp_server = self._consume(TokenType.STRING).value
            self._consume(TokenType.COMMA)
            node.mcp_resource_uri = self._consume(TokenType.STRING).value
            self._consume(TokenType.RPAREN)
            return node

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "documents":
                    node.documents = self._parse_corpus_doc_list()
                case "relationships":
                    node.edges = self._parse_corpus_edge_list()
                case "weights":
                    node.weights = self._parse_corpus_weight_map()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_corpus_doc_list(self) -> list[CorpusDocEntry]:
        """Parse: [doc_a, doc_b, doc_c] as CorpusDocEntry list."""
        docs: list[CorpusDocEntry] = []
        self._consume(TokenType.LBRACKET)
        while not self._check(TokenType.RBRACKET):
            ref_tok = self._consume(TokenType.IDENTIFIER)
            entry = CorpusDocEntry(
                pix_ref=ref_tok.value,
                line=ref_tok.line,
                column=ref_tok.column,
            )
            docs.append(entry)
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACKET)
        return docs

    def _parse_corpus_edge_list(self) -> list[CorpusEdgeEntry]:
        """Parse: [(source, target, relation_type), ...]"""
        edges: list[CorpusEdgeEntry] = []
        self._consume(TokenType.LBRACKET)
        while not self._check(TokenType.RBRACKET):
            self._consume(TokenType.LPAREN)
            src_tok = self._consume(TokenType.IDENTIFIER)
            self._consume(TokenType.COMMA)
            tgt = self._consume(TokenType.IDENTIFIER).value
            self._consume(TokenType.COMMA)
            rel = self._consume_any_identifier_or_keyword().value
            self._consume(TokenType.RPAREN)
            edges.append(CorpusEdgeEntry(
                source_ref=src_tok.value,
                target_ref=tgt,
                relation_type=rel,
                line=src_tok.line,
                column=src_tok.column,
            ))
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACKET)
        return edges

    def _parse_corpus_weight_map(self) -> dict[str, float]:
        """Parse: { (source, target, rel): 0.9, ... }"""
        weights: dict[str, float] = {}
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            self._consume(TokenType.LPAREN)
            src = self._consume(TokenType.IDENTIFIER).value
            self._consume(TokenType.COMMA)
            tgt = self._consume(TokenType.IDENTIFIER).value
            self._consume(TokenType.COMMA)
            rel = self._consume_any_identifier_or_keyword().value
            self._consume(TokenType.RPAREN)
            self._consume(TokenType.COLON)
            weight_tok = self._current()
            weight = float(weight_tok.value)
            self._advance()
            key = f"{src},{tgt},{rel}"
            weights[key] = weight
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACE)
        return weights

    # ── CORROBORATE (MDN §4.2) ─────────────────────────────────────

    def _parse_corroborate(self) -> CorroborateNode:
        """Parse: corroborate nav_result as: verified_claims

        Cross-path verification — Proposition 6 (§4.1).
        """
        tok = self._consume(TokenType.CORROBORATE)
        ref = self._consume(TokenType.IDENTIFIER).value
        node = CorroborateNode(
            navigate_ref=ref,
            line=tok.line,
            column=tok.column,
        )
        # Optional 'as:' output name
        if self._current().type == TokenType.AS:
            self._advance()
            self._consume(TokenType.COLON)
            node.output_name = self._consume(TokenType.IDENTIFIER).value

        return node

    # ── REMEMBER / RECALL ─────────────────────────────────────────

    def _parse_remember(self) -> RememberNode:
        tok = self._consume(TokenType.REMEMBER)
        self._consume(TokenType.LPAREN)
        expr = self._consume(TokenType.IDENTIFIER).value
        self._consume(TokenType.RPAREN)
        self._consume(TokenType.ARROW)
        target = self._consume(TokenType.IDENTIFIER).value
        return RememberNode(
            expression=expr, memory_target=target,
            line=tok.line, column=tok.column,
        )

    def _parse_recall(self) -> RecallNode:
        tok = self._consume(TokenType.RECALL)
        self._consume(TokenType.LPAREN)
        query = ""
        if self._check(TokenType.STRING):
            query = self._consume(TokenType.STRING).value
        else:
            query = self._consume(TokenType.IDENTIFIER).value
        self._consume(TokenType.RPAREN)
        self._consume(TokenType.FROM)
        source = self._consume(TokenType.IDENTIFIER).value
        return RecallNode(
            query=query, memory_source=source,
            line=tok.line, column=tok.column,
        )

    # ── EPISTEMIC BLOCKS ──────────────────────────────────────────

    def _parse_epistemic_block(self) -> EpistemicBlock:
        """Parse: know { ... } | believe { ... } | speculate { ... } | doubt { ... }"""
        tok = self._advance()  # consume the epistemic keyword
        mode_map = {
            TokenType.KNOW: "know",
            TokenType.BELIEVE: "believe",
            TokenType.SPECULATE: "speculate",
            TokenType.DOUBT: "doubt",
        }
        node = EpistemicBlock(
            mode=mode_map[tok.type],
            line=tok.line,
            column=tok.column,
        )
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            decl = self._parse_declaration()
            if decl is not None:
                node.body.append(decl)

        self._consume(TokenType.RBRACE)
        return node

    # ── PARALLEL BLOCK ────────────────────────────────────────────

    def _parse_par_block(self) -> ParallelBlock:
        """Parse: par { step A { ... } step B { ... } }"""
        tok = self._consume(TokenType.PAR)
        node = ParallelBlock(line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            branch = self._parse_flow_step()
            if branch is not None:
                node.branches.append(branch)

        self._consume(TokenType.RBRACE)
        return node

    # ── HIBERNATE ─────────────────────────────────────────────────

    def _parse_hibernate(self) -> HibernateNode:
        """Parse: hibernate until \"event_name\" [timeout 30s]"""
        tok = self._consume(TokenType.HIBERNATE)
        node = HibernateNode(line=tok.line, column=tok.column)

        # 'until' is not a keyword — it's an identifier used contextually
        if self._check(TokenType.IDENTIFIER) and self._current().value == "until":
            self._advance()
            node.event_name = self._consume(TokenType.STRING).value

        # optional timeout
        if self._check(TokenType.IDENTIFIER) and self._current().value == "timeout":
            self._advance()
            node.timeout = self._consume(TokenType.DURATION).value

        return node

    # ── DELIBERATE BLOCK ──────────────────────────────────────────

    def _parse_deliberate(self) -> DeliberateBlock:
        """Parse: deliberate { budget: N  depth: M  strategy: S  ... steps ... }"""
        tok = self._consume(TokenType.DELIBERATE)
        node = DeliberateBlock(line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            cur = self._current()
            # Config fields: budget, depth, strategy
            # These field names may arrive as IDENTIFIER (pre-agent era) or
            # as keyword tokens (BUDGET, STRATEGY) after the agent primitive
            # was introduced. Map keyword tokens → canonical field names.
            _KW_FIELD_MAP = {
                TokenType.BUDGET: "budget",
                TokenType.STRATEGY: "strategy",
            }
            is_ident_field = (cur.type == TokenType.IDENTIFIER
                              and cur.value in ("budget", "depth", "strategy"))
            is_kw_field = cur.type in _KW_FIELD_MAP

            if is_ident_field or is_kw_field:
                field_name = _KW_FIELD_MAP.get(cur.type, cur.value)
                self._advance()
                self._consume(TokenType.COLON)
                match field_name:
                    case "budget":
                        node.budget = int(self._consume(TokenType.INTEGER).value)
                    case "depth":
                        node.depth = int(self._consume(TokenType.INTEGER).value)
                    case "strategy":
                        node.strategy = self._consume_any_identifier_or_keyword().value
            else:
                # Nested flow step
                step = self._parse_flow_step()
                if step is not None:
                    node.body.append(step)

        self._consume(TokenType.RBRACE)
        return node

    # ── CONSENSUS BLOCK ───────────────────────────────────────────

    def _parse_consensus(self) -> ConsensusBlock:
        """Parse: consensus { branches: N  reward: Anchor  selection: S  ... steps ... }"""
        tok = self._consume(TokenType.CONSENSUS)
        node = ConsensusBlock(line=tok.line, column=tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            cur = self._current()
            # Config fields: branches, reward, selection
            if cur.type == TokenType.IDENTIFIER and cur.value in (
                "branches", "reward", "selection",
            ):
                field_name = cur.value
                self._advance()
                self._consume(TokenType.COLON)
                match field_name:
                    case "branches":
                        node.branches = int(self._consume(TokenType.INTEGER).value)
                    case "reward":
                        node.reward_anchor = self._consume(TokenType.IDENTIFIER).value
                    case "selection":
                        node.selection = self._consume_any_identifier_or_keyword().value
            else:
                # Nested flow step
                step = self._parse_flow_step()
                if step is not None:
                    node.body.append(step)

        self._consume(TokenType.RBRACE)
        return node

    # ── FORGE BLOCK ───────────────────────────────────────────────────

    def _parse_forge(self) -> ForgeBlock:
        """Parse: forge Name(seed: "...") -> OutputType { config... steps... }"""
        tok = self._consume(TokenType.FORGE)
        node = ForgeBlock(line=tok.line, column=tok.column)

        # Name
        if self._check(TokenType.IDENTIFIER):
            node.name = self._advance().value

        # Optional (seed: "...")
        if self._check(TokenType.LPAREN):
            self._advance()
            if self._check(TokenType.IDENTIFIER) and self._current().value == "seed":
                self._advance()  # skip 'seed'
                self._consume(TokenType.COLON)
                node.seed = self._consume(TokenType.STRING).value
            self._consume(TokenType.RPAREN)

        # Optional -> OutputType
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_type = self._consume(TokenType.IDENTIFIER).value

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            cur = self._current()
            # Config fields: mode, novelty, constraints, depth, branches
            if cur.type == TokenType.IDENTIFIER and cur.value in (
                "mode", "novelty", "constraints", "depth", "branches",
            ):
                field_name = cur.value
                self._advance()
                self._consume(TokenType.COLON)
                match field_name:
                    case "mode":
                        node.mode = self._consume_any_identifier_or_keyword().value
                    case "novelty":
                        val_tok = self._advance()
                        node.novelty = float(val_tok.value)
                    case "constraints":
                        node.constraints = self._consume(TokenType.IDENTIFIER).value
                    case "depth":
                        node.depth = int(self._consume(TokenType.INTEGER).value)
                    case "branches":
                        node.branches = int(self._consume(TokenType.INTEGER).value)
            else:
                # Nested flow step
                step = self._parse_flow_step()
                if step is not None:
                    node.body.append(step)

        self._consume(TokenType.RBRACE)
        return node

    # ── OTS (Ontological Tool Synthesis) ──────────────────────────────

    def _parse_ots_definition(self) -> OtsDefinition:
        """Parse: ots Name<In, Out> { teleology: "...", homotopy_search: deep, linear_constraints: {...}, loss_function: "..." }"""
        tok = self._consume(TokenType.OTS)
        name = self._consume(TokenType.IDENTIFIER)
        node = OtsDefinition(name=name.value, line=tok.line, column=tok.column)

        if self._check(TokenType.LT):
            self._advance()
            node.input_type = self._parse_type_expr()
            self._consume(TokenType.COMMA)
            node.output_type = self._parse_type_expr()
            self._consume(TokenType.GT)

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            cur = self._current()
            is_valid_field = (
                cur.type == TokenType.IDENTIFIER or 
                cur.type in (TokenType.TELEOLOGY, TokenType.HOMOTOPY_SEARCH, TokenType.LINEAR_CONSTRAINTS, TokenType.LOSS_FUNCTION)
            )
            
            if is_valid_field and cur.value in ("teleology", "homotopy_search", "linear_constraints", "loss_function"):
                field_name = cur.value
                self._advance()
                self._consume(TokenType.COLON)
                match field_name:
                    case "teleology":
                        node.teleology = self._consume(TokenType.STRING).value
                    case "homotopy_search":
                        node.homotopy_search = self._consume_any_identifier_or_keyword().value
                    case "linear_constraints":
                        node.linear_constraints = self._parse_linear_constraints_dict()
                    case "loss_function":
                        node.loss_function = self._parse_loss_function_expr()
            else:
                step = self._parse_flow_step()
                if step is not None:
                    node.body.append(step)

        self._consume(TokenType.RBRACE)
        return node

    def _parse_linear_constraints_dict(self) -> dict[str, str]:
        """Parse: { Consumption: strictly_once }"""
        constraints: dict[str, str] = {}
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            key = self._consume_any_identifier_or_keyword().value
            self._consume(TokenType.COLON)
            val = self._consume_any_identifier_or_keyword().value
            constraints[key] = val
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACE)
        return constraints

    def _parse_loss_function_expr(self) -> str:
        """Parse a loss function expression: 'L_accuracy + 0.1 * L_complexity'"""
        expr_parts = []
        # Consume tokens until we see the start of the next field '}' or an identifier followed by ':' 
        while not self._check(TokenType.RBRACE):
            if self._check(TokenType.IDENTIFIER) and self._peek_next_token().type == TokenType.COLON:
                break
            if self._check(TokenType.STEP):
                break
            expr_parts.append(self._advance().value)
        return " ".join(expr_parts)

    def _parse_ots_apply(self) -> OtsApplyNode:
        """Parse: ots DataExtractor(invoice_data) -> SqlInserts"""
        tok = self._consume(TokenType.OTS)
        name = self._consume(TokenType.IDENTIFIER).value
        node = OtsApplyNode(ots_name=name, line=tok.line, column=tok.column)
        
        self._consume(TokenType.LPAREN)
        node.target = self._consume(TokenType.IDENTIFIER).value
        self._consume(TokenType.RPAREN)
        
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_type = self._consume(TokenType.IDENTIFIER).value
            
        return node

    # ── IF / CONDITIONAL ──────────────────────────────────────────

    def _parse_if(self) -> ConditionalNode:
        tok = self._consume(TokenType.IF)
        node = ConditionalNode(line=tok.line, column=tok.column)

        # Parse first condition
        parts = [self._consume_any_identifier_or_keyword().value]
        while self._check(TokenType.DOT):
            self._advance()
            parts.append(self._consume_any_identifier_or_keyword().value)
        node.condition = ".".join(parts)
        if self._check_comparison():
            node.comparison_op = self._advance().value
            # v0.25.4: accept STRING as comparison value (for == "word")
            val_tok = self._current()
            if val_tok.type == TokenType.STRING:
                node.comparison_value = val_tok.value
                self._advance()
            else:
                node.comparison_value = self._advance().value

        # v0.25.4 — Gap 4: compound conditions (or/and)
        while self._check(TokenType.OR):
            node.conjunctor = "or"
            self._advance()  # consume 'or'
            cond_parts = [self._consume_any_identifier_or_keyword().value]
            while self._check(TokenType.DOT):
                self._advance()
                cond_parts.append(self._consume_any_identifier_or_keyword().value)
            cond_str = ".".join(cond_parts)
            cond_op = ""
            cond_val = ""
            if self._check_comparison():
                cond_op = self._advance().value
                val_tok = self._current()
                if val_tok.type == TokenType.STRING:
                    cond_val = val_tok.value
                    self._advance()
                else:
                    cond_val = self._advance().value
            node.conditions.append((cond_str, cond_op, cond_val))

        # Dispatch: arrow form (legacy) vs block form (v0.25.4)
        if self._check(TokenType.ARROW):
            self._advance()
            node.then_step = self._parse_flow_step()
        elif self._check(TokenType.LBRACE):
            # v0.25.4 — Gap 4: if cond { body }
            self._advance()
            while not self._check(TokenType.RBRACE):
                node.then_body.append(self._parse_flow_step())
            self._consume(TokenType.RBRACE)

        if self._check(TokenType.ELSE):
            self._advance()
            if self._check(TokenType.ARROW):
                self._advance()
                node.else_step = self._parse_flow_step()
            elif self._check(TokenType.LBRACE):
                self._advance()
                while not self._check(TokenType.RBRACE):
                    node.else_body.append(self._parse_flow_step())
                self._consume(TokenType.RBRACE)

        return node

    # ── FOR-IN (cognitive iteration) ──────────────────────────────

    def _parse_for_in(self) -> ForInStatement:
        """Parse: for variable in iterable.path { body }

        Cognitive iteration — systematic traversal of a structured
        collection.  The iterable is a dotted path expression resolved
        at runtime (e.g. ``thesis.chapters``, ``corpus.documents``).
        """
        tok = self._consume(TokenType.FOR)
        var_name = self._consume(TokenType.IDENTIFIER).value
        self._consume(TokenType.IN)
        iterable = self._parse_dotted_identifier()

        node = ForInStatement(
            variable=var_name,
            iterable=iterable,
            line=tok.line,
            column=tok.column,
        )

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            step = self._parse_flow_step()
            if step is not None:
                node.body.append(step)
        self._consume(TokenType.RBRACE)
        return node

    # ── LET (SSA immutable binding) ──────────────────────────────

    def _parse_let(self) -> LetStatement:
        """Parse: let identifier = expression

        SSA immutable binding — a lexical axiom that cannot
        be rebound.  The right-hand side is a compile-time
        constant (string, number, boolean, dotted path, or
        list literal).

        Grammar (EBNF)::

            LetStatement ::= "let" IDENTIFIER "=" ValueExpr
            ValueExpr    ::= STRING | INTEGER | FLOAT | BOOL
                           | DottedIdentifier
                           | "[" [ ValueExpr { "," ValueExpr } ] "]"
        """
        tok = self._consume(TokenType.LET)
        # Accept IDENTIFIER or any keyword token as binding name
        # (many common words like 'strategy', 'context' are Axon keywords)
        name_tok = self._current()
        if name_tok.type == TokenType.IDENTIFIER:
            name = self._consume(TokenType.IDENTIFIER).value
        elif name_tok.value and name_tok.type != TokenType.EOF:
            name = name_tok.value
            self._advance()
        else:
            raise AxonParseError(
                "Expected identifier after 'let'",
                line=name_tok.line,
                column=name_tok.column,
                expected="identifier",
                found=name_tok.value,
            )
        self._consume(TokenType.ASSIGN)
        value = self._parse_let_value_expr()

        return LetStatement(
            identifier=name,
            value_expr=value,
            line=tok.line,
            column=tok.column,
        )

    _ARITHMETIC_OPS = frozenset({
        TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
    })

    def _parse_let_value_expr(self) -> str | int | float | bool | list:
        """Parse a compile-time constant value expression for let bindings.

        Returns the parsed value as a Python literal (str, int, float,
        bool, list) or a dotted identifier string.

        When the expression contains arithmetic operators (+, -, *, /),
        the entire expression is returned as a string so that the
        NativeComputeDispatcher can evaluate it at runtime.
        """
        atom = self._parse_let_atom()

        # If the next token is an arithmetic operator, collect the full
        # expression as a string for runtime evaluation.
        if self._current().type in self._ARITHMETIC_OPS:
            parts: list[str] = [str(atom)]
            while self._current().type in self._ARITHMETIC_OPS:
                op_tok = self._current()
                self._advance()
                parts.append(op_tok.value)
                parts.append(str(self._parse_let_atom()))
            return " ".join(parts)

        return atom

    def _parse_let_atom(self) -> str | int | float | bool | list:
        """Parse a single atomic value in a let expression."""
        tok = self._current()

        if tok.type == TokenType.STRING:
            self._advance()
            return tok.value

        if tok.type == TokenType.INTEGER:
            self._advance()
            return int(tok.value)

        if tok.type == TokenType.FLOAT:
            self._advance()
            return float(tok.value)

        if tok.type == TokenType.BOOL:
            self._advance()
            return tok.value.lower() == "true"

        if tok.type == TokenType.IDENTIFIER:
            return self._parse_dotted_identifier()

        # Keywords (pix, for, etc.) can start dotted-path values:
        #   let strategy = pix.document_tree
        if (self._pos + 1 < len(self._tokens)
                and self._tokens[self._pos + 1].type == TokenType.DOT):
            return self._parse_dotted_identifier()

        if tok.type == TokenType.LBRACKET:
            return self._parse_let_list_literal()

        raise AxonParseError(
            "Expected value expression for let binding",
            line=tok.line,
            column=tok.column,
            expected="string, number, boolean, identifier, or list literal",
            found=tok.value,
        )


    def _parse_return(self) -> ReturnStatement:
        """Parse: return expression

        Early Exit Sink — the flow collapses and projects its result.
        The value_expr is parsed as a LetStatement-compatible sub-tree
        (string, number, boolean, dotted path, or list literal).
        """
        tok = self._consume(TokenType.RETURN)
        value = self._parse_let_value_expr()

        # Wrap primitive value into a LetStatement-compatible node
        # ReturnStatement.value_expr stores the raw parsed value
        node = ReturnStatement(line=tok.line, column=tok.column)
        # Store as a LetStatement node to keep AST consistency
        node.value_expr = LetStatement(
            identifier="__return__",
            value_expr=value,
            line=tok.line,
            column=tok.column,
        )
        return node

    def _parse_let_list_literal(self) -> list:
        """Parse a list literal: [ value1, value2, ... ]"""
        self._consume(TokenType.LBRACKET)
        items: list = []

        if not self._check(TokenType.RBRACKET):
            items.append(self._parse_let_value_expr())
            while self._check(TokenType.COMMA):
                self._advance()  # consume comma
                if self._check(TokenType.RBRACKET):
                    break  # trailing comma
                items.append(self._parse_let_value_expr())

        self._consume(TokenType.RBRACKET)
        return items

    # ── RUN ───────────────────────────────────────────────────────

    def _parse_run(self) -> RunStatement:
        tok = self._consume(TokenType.RUN)
        flow_name = self._consume(TokenType.IDENTIFIER)
        node = RunStatement(flow_name=flow_name.value, line=tok.line, column=tok.column)

        # arguments: (arg1, arg2, ...)
        self._consume(TokenType.LPAREN)
        if not self._check(TokenType.RPAREN):
            node.arguments = self._parse_argument_list()
        self._consume(TokenType.RPAREN)

        # modifiers
        while self._check_run_modifier():
            mod = self._current()
            match mod.type:
                case TokenType.AS:
                    self._advance()
                    node.persona = self._consume(TokenType.IDENTIFIER).value
                case TokenType.WITHIN:
                    self._advance()
                    node.context = self._consume(TokenType.IDENTIFIER).value
                case TokenType.CONSTRAINED_BY:
                    self._advance()
                    node.anchors = self._parse_bracketed_identifiers()
                case TokenType.ON_FAILURE:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.on_failure, node.on_failure_params = self._parse_failure_strategy()
                case TokenType.OUTPUT_TO:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.output_to = self._consume(TokenType.STRING).value
                case TokenType.EFFORT:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.effort = self._consume_any_identifier_or_keyword().value
                case _:
                    break

        return node

    def _parse_failure_strategy(self) -> tuple[str, dict[str, str]]:
        """Parse: log | retry(backoff: exp) | escalate | raise X"""
        tok = self._current()
        params: dict[str, str] = {}
        if tok.value == "retry":
            self._advance()
            if self._check(TokenType.LPAREN):
                self._advance()
                while not self._check(TokenType.RPAREN):
                    key = self._consume_any_identifier_or_keyword().value
                    self._consume(TokenType.COLON)
                    val = self._consume_any_identifier_or_keyword().value
                    params[key] = val
                    if self._check(TokenType.COMMA):
                        self._advance()
                self._consume(TokenType.RPAREN)
            return ("retry", params)
        elif tok.value == "raise":
            self._advance()
            target = self._consume(TokenType.IDENTIFIER).value
            return ("raise", {"target": target})
        else:
            self._advance()
            return (tok.value, {})

    # ── HELPER METHODS ────────────────────────────────────────────

    def _current(self) -> Token:
        if self._pos >= len(self._tokens):
            return Token(TokenType.EOF, "", 0, 0)
        return self._tokens[self._pos]

    def _peek_next_token(self) -> Token:
        if self._pos + 1 >= len(self._tokens):
            return Token(TokenType.EOF, "", 0, 0)
        return self._tokens[self._pos + 1]

    def _advance(self) -> Token:
        tok = self._current()
        self._pos += 1
        return tok

    def _check(self, token_type: TokenType) -> bool:
        return self._current().type == token_type

    def _check_comparison(self) -> bool:
        return self._current().type in (
            TokenType.LT, TokenType.GT, TokenType.LTE,
            TokenType.GTE, TokenType.EQ, TokenType.NEQ,
        )

    def _check_run_modifier(self) -> bool:
        return self._current().type in (
            TokenType.AS, TokenType.WITHIN, TokenType.CONSTRAINED_BY,
            TokenType.ON_FAILURE, TokenType.OUTPUT_TO, TokenType.EFFORT,
        )

    def _check_contextual_keyword(self, keyword: str) -> bool:
        tok = self._current()
        return tok.type == TokenType.IDENTIFIER and tok.value.lower() == keyword.lower()

    def _consume(self, expected: TokenType) -> Token:
        tok = self._current()
        if tok.type != expected:
            raise AxonParseError(
                f"Unexpected token",
                line=tok.line,
                column=tok.column,
                expected=expected.name,
                found=f"{tok.type.name}({tok.value!r})",
            )
        return self._advance()

    def _consume_any_identifier_or_keyword(self) -> Token:
        """Consume any identifier or keyword-used-as-value (e.g., tone: precise)."""
        tok = self._current()
        # Allow keywords to be used as values in field contexts
        if tok.type == TokenType.IDENTIFIER or tok.type in (
            TokenType.BOOL, TokenType.STRING, TokenType.INTEGER, TokenType.FLOAT,
        ):
            return self._advance()
        # Allow any keyword to be used as a value
        if tok.value.isalpha() or "_" in tok.value:
            return self._advance()
        raise AxonParseError(
            "Expected identifier or keyword value",
            line=tok.line,
            column=tok.column,
            found=f"{tok.type.name}({tok.value!r})",
        )

    def _consume_number(self) -> float:
        tok = self._current()
        if tok.type == TokenType.FLOAT:
            self._advance()
            return float(tok.value)
        elif tok.type == TokenType.INTEGER:
            self._advance()
            return float(tok.value)
        raise AxonParseError(
            "Expected number",
            line=tok.line,
            column=tok.column,
            found=f"{tok.type.name}({tok.value!r})",
        )

    def _parse_bool(self) -> bool:
        tok = self._consume(TokenType.BOOL)
        return tok.value == "true"

    def _parse_identifier_list(self) -> list[str]:
        """Parse: Ident1, Ident2, ..."""
        names: list[str] = []
        names.append(self._consume(TokenType.IDENTIFIER).value)
        while self._check(TokenType.COMMA):
            self._advance()
            names.append(self._consume(TokenType.IDENTIFIER).value)
        return names

    def _parse_bracketed_identifiers(self) -> list[str]:
        """Parse: [Ident1, Ident2, ...]"""
        self._consume(TokenType.LBRACKET)
        items = self._parse_extended_identifier_list()
        self._consume(TokenType.RBRACKET)
        return items

    def _parse_extended_identifier_list(self) -> list[str]:
        """Parse a comma-separated list of identifiers, allowing keywords as values."""
        items: list[str] = []
        items.append(self._consume_any_identifier_or_keyword().value)
        while self._check(TokenType.COMMA):
            self._advance()
            items.append(self._consume_any_identifier_or_keyword().value)
        return items

    def _parse_bracketed_dot_identifiers(self) -> list[str]:
        """Parse: [Extract.output, Assess.output, ...] — allows dotted names."""
        self._consume(TokenType.LBRACKET)
        items: list[str] = []
        items.append(self._parse_dotted_identifier())
        while self._check(TokenType.COMMA):
            self._advance()
            items.append(self._parse_dotted_identifier())
        self._consume(TokenType.RBRACKET)
        return items

    def _parse_dotted_identifier(self) -> str:
        """Parse: Foo, Foo.bar, or keyword.bar (e.g. pix.document_tree).

        Accepts both IDENTIFIER and keyword tokens as the first segment,
        since many common words are reserved in AXON's grammar.
        """
        parts = [self._consume_any_identifier_or_keyword().value]
        while self._check(TokenType.DOT):
            self._advance()
            parts.append(self._consume_any_identifier_or_keyword().value)
        return ".".join(parts)

    def _parse_string_list(self) -> list[str]:
        """Parse: ["str1", "str2", ...]"""
        self._consume(TokenType.LBRACKET)
        items: list[str] = []
        items.append(self._consume(TokenType.STRING).value)
        while self._check(TokenType.COMMA):
            self._advance()
            items.append(self._consume(TokenType.STRING).value)
        self._consume(TokenType.RBRACKET)
        return items

    def _parse_argument_list(self) -> list[str]:
        """Parse arguments in a run() call — may be identifiers, strings, or keyword args."""
        args: list[str] = []
        while not self._check(TokenType.RPAREN):
            tok = self._current()
            if tok.type == TokenType.STRING:
                args.append(self._advance().value)
            elif tok.type in (TokenType.INTEGER, TokenType.FLOAT):
                args.append(self._advance().value)
            elif tok.type == TokenType.IDENTIFIER:
                val = self._advance().value
                # check for dotted: file.pdf
                if self._check(TokenType.DOT):
                    self._advance()
                    val += "." + self._consume_any_identifier_or_keyword().value
                args.append(val)
            else:
                # keyword argument: depth: 3
                key = self._advance().value
                if self._check(TokenType.COLON):
                    self._advance()
                    val = self._advance().value
                    args.append(f"{key}:{val}")
                else:
                    args.append(key)

            if self._check(TokenType.COMMA):
                self._advance()
        return args

    def _parse_expression_string(self) -> str:
        """Parse an expression — could be identifier, dotted, or bracketed list."""
        tok = self._current()

        # [Extract.output, Assess.output]
        if tok.type == TokenType.LBRACKET:
            items = self._parse_bracketed_dot_identifiers()
            return "[" + ", ".join(items) + "]"

        # Foo.bar or just Foo
        return self._parse_dotted_identifier()

    def _skip_value(self) -> None:
        """Skip a single value token or dotted expression (for unknown fields)."""
        tok = self._current()
        if tok.type == TokenType.LBRACKET:
            self._advance()
            depth = 1
            while depth > 0 and not self._check(TokenType.EOF):
                if self._check(TokenType.LBRACKET):
                    depth += 1
                elif self._check(TokenType.RBRACKET):
                    depth -= 1
                self._advance()
        elif tok.type == TokenType.LBRACE:
            self._advance()
            depth = 1
            while depth > 0 and not self._check(TokenType.EOF):
                if self._check(TokenType.LBRACE):
                    depth += 1
                elif self._check(TokenType.RBRACE):
                    depth -= 1
                self._advance()
        else:
            self._advance()
            # Consume trailing dot-notation: ident.ident.ident
            while self._check(TokenType.DOT):
                self._advance()  # consume DOT
                self._advance()  # consume following identifier

    def _at_declaration_start(self) -> bool:
        """Check if current token starts a new top-level declaration."""
        return self._current().type in (
            TokenType.PERSONA, TokenType.CONTEXT, TokenType.ANCHOR,
            TokenType.MEMORY, TokenType.TOOL, TokenType.TYPE,
            TokenType.FLOW, TokenType.INTENT, TokenType.RUN,
            TokenType.IMPORT, TokenType.DATASPACE, TokenType.INGEST,
            TokenType.AXONENDPOINT,
            TokenType.EOF,
        )

    # ── DATA SCIENCE PARSERS ─────────────────────────────────────

    def _parse_dataspace(self) -> DataSpaceDefinition:
        """Parse: dataspace SalesAnalysis { ... }"""
        tok = self._consume(TokenType.DATASPACE)
        name = self._consume(TokenType.IDENTIFIER)
        node = DataSpaceDefinition(
            name=name.value, line=tok.line, column=tok.column
        )

        # Optional body
        if self._check(TokenType.LBRACE):
            self._advance()
            while not self._check(TokenType.RBRACE):
                inner = self._parse_flow_step()
                if inner is not None:
                    node.body.append(inner)
            self._consume(TokenType.RBRACE)

        return node

    def _parse_ingest(self) -> IngestNode:
        """Parse: ingest (string | identifier) into identifier"""
        tok = self._consume(TokenType.INGEST)
        node = IngestNode(line=tok.line, column=tok.column)

        # Source: string literal or identifier
        src_tok = self._current()
        if src_tok.type == TokenType.STRING:
            node.source = self._advance().value
        elif src_tok.type == TokenType.IDENTIFIER:
            node.source = self._parse_dotted_identifier()
        else:
            raise AxonParseError(
                "Expected source (string or identifier) after 'ingest'",
                line=src_tok.line, column=src_tok.column,
                expected="string or identifier", found=src_tok.value,
            )

        # "into" keyword (contextual — parsed as IDENTIFIER with value "into")
        into_tok = self._current()
        if into_tok.type == TokenType.INTO:
            self._advance()
        elif into_tok.type == TokenType.IDENTIFIER and into_tok.value == "into":
            self._advance()
        else:
            raise AxonParseError(
                "Expected 'into' after source in ingest",
                line=into_tok.line, column=into_tok.column,
                expected="into", found=into_tok.value,
            )

        node.target = self._consume(TokenType.IDENTIFIER).value
        return node

    def _parse_focus(self) -> FocusNode:
        """Parse: focus on <expression>"""
        tok = self._consume(TokenType.FOCUS)
        node = FocusNode(line=tok.line, column=tok.column)

        # "on" keyword (contextual)
        on_tok = self._current()
        if on_tok.type == TokenType.IDENTIFIER and on_tok.value == "on":
            self._advance()
        else:
            raise AxonParseError(
                "Expected 'on' after 'focus'",
                line=on_tok.line, column=on_tok.column,
                expected="on", found=on_tok.value,
            )

        # Collect expression tokens until we hit a flow step keyword or RBRACE
        expr_parts: list[str] = []
        while not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            cur = self._current()
            # Stop if we see a flow-step keyword (next statement)
            if cur.type in (
                TokenType.STEP, TokenType.PROBE, TokenType.REASON,
                TokenType.VALIDATE, TokenType.REFINE, TokenType.WEAVE,
                TokenType.USE, TokenType.REMEMBER, TokenType.RECALL,
                TokenType.IF, TokenType.PAR, TokenType.HIBERNATE,
                TokenType.FOCUS, TokenType.ASSOCIATE, TokenType.AGGREGATE,
                TokenType.EXPLORE, TokenType.INGEST, TokenType.DATASPACE,
            ):
                break
            expr_parts.append(self._advance().value)

        node.expression = " ".join(expr_parts)
        return node

    def _parse_associate(self) -> AssociateNode:
        """Parse: associate X with Y [using Z]"""
        tok = self._consume(TokenType.ASSOCIATE)
        node = AssociateNode(line=tok.line, column=tok.column)

        node.left = self._consume(TokenType.IDENTIFIER).value

        # "with" keyword (contextual)
        with_tok = self._current()
        if with_tok.type == TokenType.IDENTIFIER and with_tok.value == "with":
            self._advance()
        elif with_tok.type == TokenType.WITHIN:
            # 'within' is close but not right — raise helpful error
            raise AxonParseError(
                "Expected 'with' after table name in associate",
                line=with_tok.line, column=with_tok.column,
                expected="with", found="within",
            )
        else:
            raise AxonParseError(
                "Expected 'with' after table name in associate",
                line=with_tok.line, column=with_tok.column,
                expected="with", found=with_tok.value,
            )

        node.right = self._consume(TokenType.IDENTIFIER).value

        # Optional "using field_name"
        if (self._current().type == TokenType.IDENTIFIER
                and self._current().value == "using"):
            self._advance()
            node.using_field = self._consume(TokenType.IDENTIFIER).value

        return node

    def _parse_aggregate(self) -> AggregateNode:
        """Parse: aggregate X by Y, Z [as alias]"""
        tok = self._consume(TokenType.AGGREGATE)
        node = AggregateNode(line=tok.line, column=tok.column)

        node.target = self._parse_dotted_identifier()

        # "by" keyword (contextual)
        by_tok = self._current()
        if by_tok.type == TokenType.IDENTIFIER and by_tok.value == "by":
            self._advance()
        else:
            raise AxonParseError(
                "Expected 'by' after target in aggregate",
                line=by_tok.line, column=by_tok.column,
                expected="by", found=by_tok.value,
            )

        # identifier_list: at least one identifier, comma-separated
        node.group_by.append(self._consume(TokenType.IDENTIFIER).value)
        while self._check(TokenType.COMMA):
            self._advance()
            node.group_by.append(self._consume(TokenType.IDENTIFIER).value)

        # Optional "as alias"
        if (self._current().type == TokenType.AS):
            self._advance()
            node.alias = self._consume(TokenType.IDENTIFIER).value

        return node

    def _parse_explore(self) -> ExploreNode:
        """Parse: explore X [limit N]"""
        tok = self._consume(TokenType.EXPLORE)
        node = ExploreNode(line=tok.line, column=tok.column)

        node.target = self._parse_dotted_identifier()

        # Optional "limit N"
        if (self._current().type == TokenType.IDENTIFIER
                and self._current().value == "limit"):
            self._advance()
            limit_tok = self._consume(TokenType.INTEGER)
            node.limit = int(limit_tok.value)

        return node

    # ── AGENT ─────────────────────────────────────────────────────

    def _parse_agent(self) -> AgentDefinition:
        """
        Parse a BDI agent definition:

          agent Name(params) -> ReturnType {
              goal: "objective"
              tools: [ToolA, ToolB]
              budget: { max_iterations: 10, max_tokens: 50000 }
              memory: MemoryRef
              strategy: react
              on_stuck: forge
              step X { ... }
              par { ... }
          }

        The agent body supports both agent-specific clauses (goal,
        tools, budget, memory, strategy, on_stuck) and any valid
        flow step (step, par, forge, deliberate, etc.).

        Grammar follows the same pattern as flow() but adds the
        BDI configuration clauses before delegating body parsing
        to _parse_flow_step().
        """
        tok = self._consume(TokenType.AGENT)
        name = self._consume(TokenType.IDENTIFIER)
        node = AgentDefinition(name=name.value, line=tok.line, column=tok.column)

        # parameters: (param: Type, ...)
        self._consume(TokenType.LPAREN)
        if not self._check(TokenType.RPAREN):
            node.parameters = self._parse_param_list()
        self._consume(TokenType.RPAREN)

        # optional return type: -> ReturnType
        if self._check(TokenType.ARROW):
            self._advance()
            node.return_type = self._parse_type_expr()

        # body
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                # ── Agent-specific clauses ────────────────────────
                case TokenType.GOAL:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.goal = self._consume(TokenType.STRING).value

                case TokenType.TOOLS:
                    self._advance()
                    self._consume(TokenType.COLON)
                    # Handle tools: [] (empty) and tools: [A, B]
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.tools = []
                    else:
                        node.tools = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.BUDGET:
                    self._advance()
                    # Accept both 'budget { ... }' and 'budget: { ... }'
                    if self._check(TokenType.COLON):
                        self._advance()
                    node.budget = self._parse_agent_budget()

                case TokenType.MEMORY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.memory_ref = self._consume_any_identifier_or_keyword().value

                case TokenType.STRATEGY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.strategy = self._consume_any_identifier_or_keyword().value

                case TokenType.ON_STUCK:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.on_stuck = self._consume_any_identifier_or_keyword().value

                # ── Shield binding ────────────────────────────────
                case TokenType.SHIELD:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.shield_ref = self._consume_any_identifier_or_keyword().value

                # ── Delegate to flow step parser for body ────────
                case _:
                    step = self._parse_flow_step()
                    if step is not None:
                        node.body.append(step)

        self._consume(TokenType.RBRACE)
        return node

    def _parse_agent_budget(self) -> AgentBudget:
        """
        Parse the resource budget block for an agent:

          budget: {
              max_iterations: 10
              max_tokens: 50000
              max_time: 120s
              max_cost: 0.50
          }

        Grounded in Linear Logic — each field declares a consumable
        resource that bounds the agent's deliberation cycle.
        """
        node = AgentBudget(line=self._current().line, column=self._current().column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "max_iterations":
                    node.max_iterations = int(self._consume(TokenType.INTEGER).value)
                case "max_tokens":
                    node.max_tokens = int(self._consume(TokenType.INTEGER).value)
                case "max_time":
                    node.max_time = self._consume(TokenType.DURATION).value
                case "max_cost":
                    # Accept both float (0.50) and integer (1) values
                    cost_tok = self._current()
                    if cost_tok.type == TokenType.FLOAT:
                        node.max_cost = float(self._advance().value)
                    else:
                        node.max_cost = float(self._consume(TokenType.INTEGER).value)
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── DAEMON (AxonServer — π-calculus reactive primitive) ────────

    def _parse_daemon(self) -> DaemonDefinition:
        """
        Parse a daemon definition:

          daemon OrderProcessor(config: ServerConfig) -> OrderResult {
              goal: "Process incoming orders"
              tools: [DBQuery, EmailSender]
              budget_per_event: { max_tokens: 5000, max_time: 30s, max_cost: 0.10 }
              memory: OrderMemory
              strategy: react
              on_stuck: hibernate
              shield: InputGuard

              listen "orders" as order_event {
                  step Validate { ... }
              }
          }

        π-Calculus grounding:
          P ::= !c(x).Q — replicated listener
          The daemon is the replication operator (!), each listen
          block is a channel input prefix c(x).Q.
        """
        tok = self._consume(TokenType.DAEMON)
        name = self._consume(TokenType.IDENTIFIER)
        node = DaemonDefinition(name=name.value, line=tok.line, column=tok.column)

        # parameters: (param: Type, ...)
        self._consume(TokenType.LPAREN)
        if not self._check(TokenType.RPAREN):
            node.parameters = self._parse_param_list()
        self._consume(TokenType.RPAREN)

        # optional return type: -> ReturnType
        if self._check(TokenType.ARROW):
            self._advance()
            node.return_type = self._parse_type_expr()

        # body
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                # ── Daemon-specific clauses ───────────────────────
                case TokenType.GOAL:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.goal = self._consume(TokenType.STRING).value

                case TokenType.TOOLS:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.tools = []
                    else:
                        node.tools = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.BUDGET_PER_EVENT:
                    self._advance()
                    if self._check(TokenType.COLON):
                        self._advance()
                    node.budget_per_event = self._parse_daemon_budget()

                case TokenType.MEMORY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.memory_ref = self._consume_any_identifier_or_keyword().value

                case TokenType.STRATEGY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.strategy = self._consume_any_identifier_or_keyword().value

                case TokenType.ON_STUCK:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.on_stuck = self._consume_any_identifier_or_keyword().value

                case TokenType.SHIELD:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.shield_ref = self._consume_any_identifier_or_keyword().value

                # ── Listen blocks (π-calculus channel input) ──────
                case TokenType.LISTEN:
                    node.listeners.append(self._parse_listen())

                # ── Delegate to flow step parser for body ────────
                case _:
                    step = self._parse_flow_step()
                    if step is not None:
                        node.listeners  # ensure exists; flow steps go in listeners' bodies
                        raise AxonParseError(
                            "Non-listen flow steps must be inside a listen block in a daemon",
                            line=inner.line,
                            column=inner.column,
                            expected="listen, goal, tools, budget_per_event, memory, strategy, on_stuck, shield",
                            found=inner.value,
                        )

        self._consume(TokenType.RBRACE)
        return node

    def _parse_listen(self) -> ListenBlock:
        """
        Parse a listen block:

          listen "orders" as order_event {
              step Validate { ... }
              step Process { ... }
          }

        π-Calculus correspondence: c(x).Q
          "orders" is the channel c, order_event is the binding x,
          and the body is the continuation Q.
        """
        tok = self._consume(TokenType.LISTEN)
        node = ListenBlock(line=tok.line, column=tok.column)

        # channel expression (string literal — topic name)
        node.channel_expr = self._consume(TokenType.STRING).value

        # optional: as <alias>
        if self._check(TokenType.AS):
            self._advance()
            node.event_alias = self._consume(TokenType.IDENTIFIER).value

        # body: { flow_steps... }
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            step = self._parse_flow_step()
            if step is not None:
                node.body.append(step)
        self._consume(TokenType.RBRACE)
        return node

    def _parse_daemon_budget(self) -> DaemonBudget:
        """
        Parse the per-event budget for a daemon:

          budget_per_event: {
              max_tokens: 5000
              max_time: 30s
              max_cost: 0.10
          }

        Grounded in Linear Logic — each field declares a consumable
        resource replenished per event cycle.
        No max_iterations: daemons are νX (greatest fixpoint).
        """
        node = DaemonBudget(line=self._current().line, column=self._current().column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "max_tokens":
                    node.max_tokens = int(self._consume(TokenType.INTEGER).value)
                case "max_time":
                    node.max_time = self._consume(TokenType.DURATION).value
                case "max_cost":
                    cost_tok = self._current()
                    if cost_tok.type == TokenType.FLOAT:
                        node.max_cost = float(self._advance().value)
                    else:
                        node.max_cost = float(self._consume(TokenType.INTEGER).value)
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── SHIELD ─────────────────────────────────────────────────────

    def _parse_shield(self) -> ShieldDefinition:
        """
        Parse a top-level shield definition:

          shield InputGuard {
              scan:     [prompt_injection, jailbreak, data_exfil]
              strategy: dual_llm
              on_breach: halt
              severity: critical
              quarantine: untrusted_input
              max_retries: 3
              confidence_threshold: 0.85
              allow: [WebSearch, Calculator]
              deny:  [CodeExecutor]
              sandbox: true
              redact: [ssn, credit_card, email]
              log: verbose
              deflect_message: "I cannot help with that request."
          }

        Grounded in Denning's Lattice Model for Information Flow:
          Untrusted → Quarantined → Sanitized → Validated → Trusted

        The shield block declares the security boundary — the compiler
        ensures completeness, the runtime enforces it.
        """
        tok = self._consume(TokenType.SHIELD)
        name = self._consume(TokenType.IDENTIFIER)
        node = ShieldDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                case TokenType.TAINT:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.taint = self._consume_any_identifier_or_keyword().value

                case TokenType.SCAN:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.scan = []
                    else:
                        node.scan = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.STRATEGY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.strategy = self._consume_any_identifier_or_keyword().value

                case TokenType.ON_BREACH:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.on_breach = self._consume_any_identifier_or_keyword().value

                case TokenType.SEVERITY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.severity = self._consume_any_identifier_or_keyword().value

                case TokenType.QUARANTINE:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.quarantine = self._consume_any_identifier_or_keyword().value

                case TokenType.ALLOW:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.allow_tools = []
                    else:
                        node.allow_tools = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.DENY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.deny_tools = []
                    else:
                        node.deny_tools = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.SANDBOX:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.sandbox = self._consume(TokenType.BOOL).value == "true"

                case TokenType.REDACT:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.redact = []
                    else:
                        node.redact = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case _:
                    # Identifier-based fields: max_retries, confidence_threshold, log, deflect_message
                    field_name = inner.value
                    self._advance()
                    self._consume(TokenType.COLON)

                    match field_name:
                        case "max_retries":
                            node.max_retries = int(self._consume(TokenType.INTEGER).value)
                        case "confidence_threshold":
                            ct = self._current()
                            if ct.type == TokenType.FLOAT:
                                node.confidence_threshold = float(self._advance().value)
                            else:
                                node.confidence_threshold = float(self._consume(TokenType.INTEGER).value)
                        case "log":
                            node.log = self._consume_any_identifier_or_keyword().value
                        case "deflect_message":
                            node.deflect_message = self._consume(TokenType.STRING).value
                        case _:
                            self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_shield_apply(self) -> ShieldApplyNode:
        """
        Parse an in-flow shield application:

          shield InputGuard on user_input
          shield InputGuard on user_input -> SanitizedInput

        This is the taint analysis insertion point: the shield node
        transforms data from Untrusted to Sanitized in the trust lattice.
        """
        tok = self._consume(TokenType.SHIELD)
        shield_name = self._consume(TokenType.IDENTIFIER).value

        # "on" keyword expected (parsed as identifier since it's not reserved)
        on_tok = self._consume_any_identifier_or_keyword()
        if on_tok.value != "on":
            raise AxonParseError(
                "Expected 'on' after shield name in flow step",
                line=on_tok.line,
                column=on_tok.column,
                expected="on",
                found=on_tok.value,
            )

        target = self._consume_any_identifier_or_keyword().value

        node = ShieldApplyNode(
            shield_name=shield_name,
            target=target,
            line=tok.line,
            column=tok.column,
        )

        # optional -> OutputType
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_type = self._consume(TokenType.IDENTIFIER).value

        return node

    # ── PSYCHE ─────────────────────────────────────────────────────

    def _parse_psyche(self) -> PsycheDefinition:
        """
        Parse a top-level psyche definition:

          psyche TherapeuticProfile {
              dimensions: [affect, cognitive_load, certainty, openness, trust]
              manifold: {
                  curvature: { certainty: 0.8, trust: 0.9 }
                  noise: 0.05
                  momentum: 0.7
              }
              safety: [non_diagnostic, non_prescriptive]
              quantum: enabled
              inference: active
          }

        Grounded in the PEM formal framework:
          §1  Riemannian Manifold — ψ ∈ M with metric tensor g
          §2  Density Operators — ρ_ψ ∈ ℝ^{k×k}, P(D|ψ) = Tr(Π·ρ·Π)
          §3  Active Inference — G(π,τ) = epistemic + pragmatic value
          §4  Dependent Types — NonDiagnostic safety constraint

        The psyche block declares the psychological-epistemic model —
        the compiler validates completeness, the runtime executes it.
        """
        tok = self._consume(TokenType.PSYCHE)
        name = self._consume(TokenType.IDENTIFIER)
        node = PsycheDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                case TokenType.DIMENSIONS:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACKET)
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        node.dimensions = []
                    else:
                        node.dimensions = self._parse_extended_identifier_list()
                        self._consume(TokenType.RBRACKET)

                case TokenType.MANIFOLD:
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._consume(TokenType.LBRACE)
                    while not self._check(TokenType.RBRACE):
                        field_tok = self._current()
                        field_name = field_tok.value
                        self._advance()
                        self._consume(TokenType.COLON)

                        match field_name:
                            case "curvature":
                                # curvature: { dim_name: float, ... }
                                self._consume(TokenType.LBRACE)
                                while not self._check(TokenType.RBRACE):
                                    dim_name = self._consume_any_identifier_or_keyword().value
                                    self._consume(TokenType.COLON)
                                    val_tok = self._current()
                                    if val_tok.type == TokenType.FLOAT:
                                        node.manifold_curvature[dim_name] = float(self._advance().value)
                                    else:
                                        node.manifold_curvature[dim_name] = float(self._consume(TokenType.INTEGER).value)
                                    # optional comma
                                    if self._check(TokenType.COMMA):
                                        self._advance()
                                self._consume(TokenType.RBRACE)
                            case "noise":
                                val_tok = self._current()
                                if val_tok.type == TokenType.FLOAT:
                                    node.manifold_noise = float(self._advance().value)
                                else:
                                    node.manifold_noise = float(self._consume(TokenType.INTEGER).value)
                            case "momentum":
                                val_tok = self._current()
                                if val_tok.type == TokenType.FLOAT:
                                    node.manifold_momentum = float(self._advance().value)
                                else:
                                    node.manifold_momentum = float(self._consume(TokenType.INTEGER).value)
                            case _:
                                self._skip_value()
                    self._consume(TokenType.RBRACE)

                case _:
                    # Identifier-based fields: safety, quantum, inference
                    field_name = inner.value
                    self._advance()
                    self._consume(TokenType.COLON)

                    match field_name:
                        case "safety":
                            self._consume(TokenType.LBRACKET)
                            if self._check(TokenType.RBRACKET):
                                self._advance()
                                node.safety_constraints = []
                            else:
                                node.safety_constraints = self._parse_extended_identifier_list()
                                self._consume(TokenType.RBRACKET)
                        case "quantum":
                            val = self._consume_any_identifier_or_keyword().value
                            node.quantum_enabled = val in ("enabled", "true")
                        case "inference":
                            node.inference_mode = self._consume_any_identifier_or_keyword().value
                        case _:
                            self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ── MANDATE ─────────────────────────────────────────────────────

    def _parse_mandate(self) -> MandateDefinition:
        """
        Parse a top-level mandate definition:

          mandate StrictJSON {
              constraint: "Output must be valid JSON with keys: name, score, reasoning"
              kp: 10.0
              ki: 0.1
              kd: 0.05
              tolerance: 0.01
              max_steps: 50
              on_violation: coerce
          }

        Grounded in the Cybernetic Refinement Calculus (CRC):
          Vía C — Refinement type T_M = { x ∈ Σ* | M(x) ⊢ ⊤ }
          Vía A — PID control  u(t) = Kp·e + Ki·∫e·dτ + Kd·de/dt
          Vía B — Logit bias   ΔL_t collapses violating tokens

        The mandate block declares deterministic constraints — the compiler
        validates the PID gains and policy, the runtime enforces convergence.
        """
        tok = self._consume(TokenType.MANDATE)
        name = self._consume(TokenType.IDENTIFIER)
        node = MandateDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                case TokenType.CONSTRAINT:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.constraint = self._consume(TokenType.STRING).value

                case TokenType.KP:
                    self._advance()
                    self._consume(TokenType.COLON)
                    val_tok = self._current()
                    if val_tok.type == TokenType.FLOAT:
                        node.kp = float(self._advance().value)
                    else:
                        node.kp = float(self._consume(TokenType.INTEGER).value)

                case TokenType.KI:
                    self._advance()
                    self._consume(TokenType.COLON)
                    val_tok = self._current()
                    if val_tok.type == TokenType.FLOAT:
                        node.ki = float(self._advance().value)
                    else:
                        node.ki = float(self._consume(TokenType.INTEGER).value)

                case TokenType.KD:
                    self._advance()
                    self._consume(TokenType.COLON)
                    val_tok = self._current()
                    if val_tok.type == TokenType.FLOAT:
                        node.kd = float(self._advance().value)
                    else:
                        node.kd = float(self._consume(TokenType.INTEGER).value)

                case TokenType.TOLERANCE:
                    self._advance()
                    self._consume(TokenType.COLON)
                    val_tok = self._current()
                    if val_tok.type == TokenType.FLOAT:
                        node.tolerance = float(self._advance().value)
                    else:
                        node.tolerance = float(self._consume(TokenType.INTEGER).value)

                case TokenType.MAX_STEPS:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.max_steps = int(self._consume(TokenType.INTEGER).value)

                case TokenType.ON_VIOLATION:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.on_violation = self._consume_any_identifier_or_keyword().value

                case _:
                    # skip unknown fields gracefully
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_mandate_apply(self) -> MandateApplyNode:
        """
        Parse an in-flow mandate application:

          mandate StrictJSON on llm_output
          mandate StrictJSON on raw_data -> ValidatedData

        This is the PID control insertion point: the mandate node
        activates the closed-loop controller at runtime to enforce
        convergence to the constraint setpoint.
        """
        tok = self._consume(TokenType.MANDATE)
        mandate_name = self._consume(TokenType.IDENTIFIER).value

        # "on" keyword expected (parsed as identifier since it's not reserved)
        on_tok = self._consume_any_identifier_or_keyword()
        if on_tok.value != "on":
            raise AxonParseError(
                "Expected 'on' after mandate name in flow step",
                line=on_tok.line,
                column=on_tok.column,
                expected="on",
                found=on_tok.value,
            )

        target = self._consume_any_identifier_or_keyword().value

        node = MandateApplyNode(
            mandate_name=mandate_name,
            target=target,
            line=tok.line,
            column=tok.column,
        )

        # optional -> OutputType
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_type = self._consume(TokenType.IDENTIFIER).value

        return node

    # ── COMPUTE (Deterministic Muscle Primitive §CM) ───────────────

    def _parse_compute(self) -> ComputeDefinition:
        """
        Parse a top-level compute definition:

          compute CalculateTax {
              input: amount (Float), rate (Float)
              output: TaxResult
              shield: TypeSafety
              logic {
                  let tax = amount * rate
                  let total = amount + tax
                  return { tax: tax, total: total }
              }
          }

        The compute primitive — deterministic "muscle" execution.
        System 1 (Kahneman) for the AXON cognitive architecture.
        Bypasses the LLM entirely via the Fast-Path.
        """
        tok = self._consume(TokenType.COMPUTE)
        name = self._consume(TokenType.IDENTIFIER)
        node = ComputeDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            # "input", "output", "shield", "logic" are parsed as identifiers
            # or keywords depending on whether they are reserved.
            if inner.value == "input":
                self._advance()
                self._consume(TokenType.COLON)
                node.inputs = self._parse_compute_input_params()

            elif inner.type == TokenType.OUTPUT:
                self._advance()
                self._consume(TokenType.COLON)
                node.output_type = self._parse_type_expr()

            elif inner.type == TokenType.SHIELD:
                self._advance()
                self._consume(TokenType.COLON)
                node.shield_ref = self._consume_any_identifier_or_keyword().value

            elif inner.type == TokenType.LOGIC:
                self._advance()
                self._consume(TokenType.LBRACE)
                while not self._check(TokenType.RBRACE):
                    node.logic_body.append(self._parse_compute_logic_stmt())
                self._consume(TokenType.RBRACE)

            else:
                # Skip unknown fields gracefully
                self._advance()
                if self._check(TokenType.COLON):
                    self._consume(TokenType.COLON)
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_compute_logic_stmt(self) -> ASTNode:
        """Parse a single statement inside compute logic { }.

        Only deterministic, pure statements are allowed:
          - let bindings: let x = expr
          - return statements: return expr

        All other constructs (step, probe, reason, etc.) are
        rejected — compute logic must be statically deterministic.
        """
        tok = self._current()
        if tok.type == TokenType.LET:
            return self._parse_let()
        if tok.type == TokenType.RETURN:
            return self._parse_return()

        raise AxonParseError(
            "Only 'let' and 'return' statements are allowed inside "
            "compute logic blocks. Compute must be deterministic — "
            "flow steps, probes, and LLM calls are not permitted.",
            line=tok.line,
            column=tok.column,
            expected="let or return",
            found=tok.value,
        )

    def _parse_compute_input_params(self) -> list[ParameterNode]:
        """Parse compute input parameter list: name (Type), name (Type), ..."""
        params: list[ParameterNode] = []

        # First parameter
        name_tok = self._consume_any_identifier_or_keyword()
        self._consume(TokenType.LPAREN)
        type_expr = self._parse_type_expr()
        self._consume(TokenType.RPAREN)
        params.append(ParameterNode(
            name=name_tok.value, type_expr=type_expr,
            line=name_tok.line, column=name_tok.column,
        ))

        # Additional comma-separated parameters
        while self._check(TokenType.COMMA):
            self._advance()
            name_tok = self._consume_any_identifier_or_keyword()
            self._consume(TokenType.LPAREN)
            type_expr = self._parse_type_expr()
            self._consume(TokenType.RPAREN)
            params.append(ParameterNode(
                name=name_tok.value, type_expr=type_expr,
                line=name_tok.line, column=name_tok.column,
            ))

        return params

    def _parse_compute_apply(self) -> ComputeApplyNode:
        """
        Parse an in-flow compute application:

          compute CalculateTax on order.amount, 0.19 -> tax_result

        The Fast-Path insertion point — the executor bypasses the
        LLM and routes directly to the NativeComputeDispatcher.
        """
        tok = self._consume(TokenType.COMPUTE)
        compute_name = self._consume(TokenType.IDENTIFIER).value

        # "on" keyword expected (parsed as identifier since it's not reserved)
        on_tok = self._consume_any_identifier_or_keyword()
        if on_tok.value != "on":
            raise AxonParseError(
                "Expected 'on' after compute name in flow step",
                line=on_tok.line,
                column=on_tok.column,
                expected="on",
                found=on_tok.value,
            )

        # Parse arguments: dotted paths, numbers, strings (comma-separated)
        arguments: list[str] = []
        arguments.append(self._parse_compute_argument())

        while self._check(TokenType.COMMA):
            self._advance()
            arguments.append(self._parse_compute_argument())

        node = ComputeApplyNode(
            compute_name=compute_name,
            arguments=arguments,
            line=tok.line,
            column=tok.column,
        )

        # optional -> output_name
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_name = self._consume_any_identifier_or_keyword().value

        return node

    def _parse_compute_argument(self) -> str:
        """Parse a single compute argument: dotted path, number, or string."""
        tok = self._current()

        if tok.type == TokenType.STRING:
            self._advance()
            return tok.value
        if tok.type == TokenType.FLOAT:
            self._advance()
            return tok.value
        if tok.type == TokenType.INTEGER:
            self._advance()
            return tok.value

        # Dotted identifier: order.amount.subtotal
        parts = [self._consume_any_identifier_or_keyword().value]
        while self._check(TokenType.DOT):
            self._advance()
            parts.append(self._consume_any_identifier_or_keyword().value)
        return ".".join(parts)

    # ── LAMBDA DATA (ΛD) ───────────────────────────────────────────

    def _parse_lambda_data(self) -> LambdaDataDefinition:
        """
        Parse a top-level Lambda Data (ΛD) definition:

          lambda SensorReading {
              ontology: "measurement.temperature"
              certainty: 0.95
              temporal_frame: "2024-01-01/2024-12-31"
              provenance: "IoT sensor array Alpha-7"
              derivation: "raw"
          }

        Grounded in the Lambda Data formalism:
          ΛD: V → (V × O × C × T)
          ψ = ⟨T, V, E⟩  — Epistemic State Vector

        Where:
          O — Ontological tag (domain classification)
          C — Certainty coefficient c ∈ [0, 1]
          T — Temporal frame [t_start, t_end]
          E — Epistemic provenance chain
        """
        tok = self._consume(TokenType.LAMBDA)
        name = self._consume(TokenType.IDENTIFIER)
        node = LambdaDataDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._current()

            match inner.type:
                case TokenType.ONTOLOGY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.ontology = self._consume(TokenType.STRING).value

                case TokenType.CERTAINTY:
                    self._advance()
                    self._consume(TokenType.COLON)
                    val_tok = self._current()
                    if val_tok.type == TokenType.FLOAT:
                        node.certainty = float(self._advance().value)
                    else:
                        node.certainty = float(self._consume(TokenType.INTEGER).value)

                case TokenType.TEMPORAL_FRAME:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.temporal_frame_start = self._consume(TokenType.STRING).value
                    # Optional end frame (second string)
                    if self._check(TokenType.STRING):
                        node.temporal_frame_end = self._consume(TokenType.STRING).value

                case TokenType.PROVENANCE:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.provenance = self._consume(TokenType.STRING).value

                case TokenType.DERIVATION:
                    self._advance()
                    self._consume(TokenType.COLON)
                    node.derivation = self._consume_any_identifier_or_keyword().value

                case _:
                    # Skip unknown fields gracefully
                    self._advance()
                    self._consume(TokenType.COLON)
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_lambda_data_apply(self) -> LambdaDataApplyNode:
        """
        Parse an in-flow Lambda Data application:

          lambda SensorReading on raw_data
          lambda SensorReading on raw_data -> ValidatedReading

        This is the epistemic binding point: the ΛD specification
        is applied to a data target, enriching it with the full
        epistemic state vector ψ = ⟨T, V, E⟩.
        """
        tok = self._consume(TokenType.LAMBDA)
        lambda_data_name = self._consume(TokenType.IDENTIFIER).value

        # "on" keyword expected (parsed as identifier since it's not reserved)
        on_tok = self._consume_any_identifier_or_keyword()
        if on_tok.value != "on":
            raise AxonParseError(
                "Expected 'on' after lambda data name in flow step",
                line=on_tok.line,
                column=on_tok.column,
                expected="on",
                found=on_tok.value,
            )

        target = self._consume_any_identifier_or_keyword().value

        node = LambdaDataApplyNode(
            lambda_data_name=lambda_data_name,
            target=target,
            line=tok.line,
            column=tok.column,
        )

        # optional -> OutputType
        if self._check(TokenType.ARROW):
            self._advance()
            node.output_type = self._consume(TokenType.IDENTIFIER).value

        return node

    # ══════════════════════════════════════════════════════════════
    #  AXONSTORE PRIMITIVE — HoTT Transactional Persistence (§AS)
    # ══════════════════════════════════════════════════════════════

    def _parse_axonstore(self) -> AxonStoreDefinition:
        """Parse: axonstore Name { backend: ..., schema { ... }, ... }"""
        tok = self._consume(TokenType.AXONSTORE)
        name = self._consume(TokenType.IDENTIFIER)
        node = AxonStoreDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            inner = self._current()
            field_name = inner.value
            if inner.type == TokenType.SCHEMA:
                self._advance()
                node.schema = self._parse_store_schema(tok)
            elif field_name in (
                "backend", "connection", "confidence_floor",
                "isolation", "on_breach",
            ):
                self._advance()
                self._consume(TokenType.COLON)
                match field_name:
                    case "backend":
                        node.backend = self._consume_any_identifier_or_keyword().value
                    case "connection":
                        node.connection = self._consume(TokenType.STRING).value
                    case "confidence_floor":
                        val_tok = self._current()
                        if val_tok.type == TokenType.FLOAT:
                            node.confidence_floor = float(self._advance().value)
                        elif val_tok.type == TokenType.INTEGER:
                            node.confidence_floor = float(self._advance().value)
                        else:
                            node.confidence_floor = float(
                                self._consume_any_identifier_or_keyword().value
                            )
                    case "isolation":
                        node.isolation = self._consume_any_identifier_or_keyword().value
                    case "on_breach":
                        node.on_breach = self._consume_any_identifier_or_keyword().value
            else:
                self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_axonendpoint(self) -> AxonEndpointDefinition:
        """Parse: axonendpoint Name { method: ..., path: ..., execute: ... }"""
        tok = self._consume(TokenType.AXONENDPOINT)
        name = self._consume(TokenType.IDENTIFIER)
        node = AxonEndpointDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "method":
                    node.method = self._consume_any_identifier_or_keyword().value.upper()
                case "path":
                    node.path = self._consume(TokenType.STRING).value
                case "body":
                    node.body_type = self._consume_any_identifier_or_keyword().value
                case "execute":
                    node.execute_flow = self._consume_any_identifier_or_keyword().value
                case "output":
                    node.output_type = self._consume_any_identifier_or_keyword().value
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case "retries":
                    node.retries = int(self._consume(TokenType.INTEGER).value)
                case "timeout":
                    if self._check(TokenType.DURATION):
                        node.timeout = self._advance().value
                    else:
                        node.timeout = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_store_schema(self, parent_tok: Token) -> StoreSchemaNode:
        """Parse: schema { col: type constraints, ... }"""
        node = StoreSchemaNode(line=parent_tok.line, column=parent_tok.column)
        self._consume(TokenType.LBRACE)

        while not self._check(TokenType.RBRACE):
            col = self._parse_store_column()
            node.columns.append(col)

        self._consume(TokenType.RBRACE)
        return node

    def _parse_store_column(self) -> StoreColumnNode:
        """Parse: col_name: col_type [primary_key] [auto_increment] [not_null] [unique] [default V]"""
        col_tok = self._current()
        col_name = self._consume_any_identifier_or_keyword().value
        node = StoreColumnNode(col_name=col_name, line=col_tok.line, column=col_tok.column)
        self._consume(TokenType.COLON)
        node.col_type = self._consume_any_identifier_or_keyword().value

        # Parse trailing column constraints (position-independent)
        while not self._check(TokenType.RBRACE) and self._current().type == TokenType.IDENTIFIER:
            cval = self._current().value
            if cval == "primary_key":
                node.primary_key = True
                self._advance()
            elif cval == "auto_increment":
                node.auto_increment = True
                self._advance()
            elif cval == "not_null":
                node.not_null = True
                self._advance()
            elif cval == "unique":
                node.unique = True
                self._advance()
            elif cval == "default":
                self._advance()
                default_tok = self._current()
                if default_tok.type in (TokenType.STRING, TokenType.INTEGER, TokenType.FLOAT):
                    node.default_value = self._advance().value
                else:
                    node.default_value = self._consume_any_identifier_or_keyword().value
            else:
                break

        return node

    def _parse_persist(self) -> PersistNode:
        """Parse: persist into StoreName { field: value, ... }"""
        tok = self._consume(TokenType.PERSIST)
        node = PersistNode(line=tok.line, column=tok.column)

        # 'into' is a known token
        self._consume(TokenType.INTO)
        node.store_name = self._consume(TokenType.IDENTIFIER).value

        # field body { key: value, ... }
        node.fields = self._parse_store_field_body()
        return node

    def _parse_retrieve(self) -> RetrieveNode:
        """Parse: retrieve from StoreName [where "expr"] [as alias]"""
        tok = self._consume(TokenType.RETRIEVE)
        node = RetrieveNode(line=tok.line, column=tok.column)

        self._consume(TokenType.FROM)
        node.store_name = self._consume(TokenType.IDENTIFIER).value

        # optional where clause
        if self._check(TokenType.WHERE):
            self._advance()
            node.where_expr = self._consume(TokenType.STRING).value

        # optional as alias
        if self._check(TokenType.AS):
            self._advance()
            node.alias = self._consume(TokenType.IDENTIFIER).value

        return node

    def _parse_mutate(self) -> MutateNode:
        """Parse: mutate StoreName where "expr" { field: value, ... }"""
        tok = self._consume(TokenType.MUTATE)
        node = MutateNode(line=tok.line, column=tok.column)

        node.store_name = self._consume(TokenType.IDENTIFIER).value

        # mandatory where clause
        self._consume(TokenType.WHERE)
        node.where_expr = self._consume(TokenType.STRING).value

        # field body
        node.fields = self._parse_store_field_body()
        return node

    def _parse_purge(self) -> PurgeNode:
        """Parse: purge from StoreName where "expr" """
        tok = self._consume(TokenType.PURGE)
        node = PurgeNode(line=tok.line, column=tok.column)

        self._consume(TokenType.FROM)
        node.store_name = self._consume(TokenType.IDENTIFIER).value

        self._consume(TokenType.WHERE)
        node.where_expr = self._consume(TokenType.STRING).value

        return node

    def _parse_transact(self) -> TransactNode:
        """Parse: transact { persist ... ; mutate ... ; ... }"""
        tok = self._consume(TokenType.TRANSACT)
        node = TransactNode(line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            inner = self._parse_flow_step()
            if inner is not None:
                node.body.append(inner)
        self._consume(TokenType.RBRACE)

        return node

    def _parse_store_field_body(self) -> dict[str, str]:
        """Parse: { key: value, key: value, ... } → dict."""
        fields: dict[str, str] = {}
        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            key = self._consume_any_identifier_or_keyword().value
            self._consume(TokenType.COLON)
            val_tok = self._current()
            if val_tok.type == TokenType.STRING:
                fields[key] = self._advance().value
            elif val_tok.type in (TokenType.INTEGER, TokenType.FLOAT):
                fields[key] = self._advance().value
            elif val_tok.type == TokenType.BOOL:
                fields[key] = self._advance().value
            else:
                fields[key] = self._consume_any_identifier_or_keyword().value
        self._consume(TokenType.RBRACE)
        return fields
