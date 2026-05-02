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
    Trivia,
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
    ChannelDefinition,
    DaemonBudget,
    DaemonDefinition,
    DataSpaceDefinition,
    DeliberateBlock,
    DiscoverStatement,
    DrillNode,
    EffectRowNode,
    EmitStatement,
    EpistemicBlock,
    EnsembleDefinition,
    ExploreNode,
    FabricDefinition,
    FlowDefinition,
    FocusNode,
    ForInStatement,
    ForgeBlock,
    ComponentDefinition,
    HealDefinition,
    HibernateNode,
    ImmuneDefinition,
    ImportNode,
    IngestNode,
    IntentNode,
    ComputeApplyNode,
    ComputeDefinition,
    LambdaDataApplyNode,
    LambdaDataDefinition,
    LeaseDefinition,
    LetStatement,
    ListenBlock,
    MandateApplyNode,
    MandateDefinition,
    ManifestDefinition,
    MemoryDefinition,
    MutateNode,
    NavigateNode,
    ObserveDefinition,
    OtsApplyNode,
    OtsDefinition,
    ParallelBlock,
    ParameterNode,
    PersistNode,
    PersonaDefinition,
    PixDefinition,
    ProbeDirective,
    ProgramNode,
    PublishStatement,
    PsycheDefinition,
    PurgeNode,
    RangeConstraint,
    ReasonChain,
    RecallNode,
    ReconcileDefinition,
    ReflexDefinition,
    RefineBlock,
    RememberNode,
    ResourceDefinition,
    RetrieveNode,
    SessionDefinition,
    SessionRole,
    SessionStep,
    ReturnStatement,
    RunStatement,
    ShieldApplyNode,
    ShieldDefinition,
    StepNode,
    StoreColumnNode,
    StoreSchemaNode,
    TopologyDefinition,
    TopologyEdge,
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
    ViewDefinition,
    WeaveNode,
    WhereClause,
)
from .errors import AxonParseError
from .tokens import Token, TokenType


# Comment token kinds the lexer now emits (Fase 14.a). The parser
# filters these out of its working stream — they are materialised into
# `Trivia` objects on a parallel array indexed by effective-token
# position, then attached to AST nodes as leading / trailing trivia.
_COMMENT_TOKEN_KINDS = frozenset({
    TokenType.LINE_COMMENT,
    TokenType.BLOCK_COMMENT,
    TokenType.DOC_LINE_COMMENT,
    TokenType.DOC_BLOCK_COMMENT,
})

# TokenType → Trivia.kind string. Trivia uses string kinds so the
# `ast_nodes` module does not depend on `tokens` (keeps the import
# graph one-directional: parser depends on both).
_TRIVIA_KIND_BY_TOKEN: dict[TokenType, str] = {
    TokenType.LINE_COMMENT: "line",
    TokenType.BLOCK_COMMENT: "block",
    TokenType.DOC_LINE_COMMENT: "doc_line",
    TokenType.DOC_BLOCK_COMMENT: "doc_block",
}


class Parser:
    """Recursive descent parser for the AXON language."""

    def __init__(self, tokens: list[Token]):
        # ── Fase 14.a — Lossless lexing → trivia channel ──
        # Split the raw token stream into:
        #   - `self._tokens`: only the *effective* tokens the grammar
        #     consumes (strips comment kinds). Cursor `_pos` advances
        #     over this list as before, so the existing parser code
        #     does not need to know about trivia.
        #   - `self._leading_trivia`: parallel list — for each effective
        #     token at index i, the comment trivia that appeared *before*
        #     it (since the previous effective token, or since the start
        #     of file).
        #   - `self._trailing_trivia`: parallel list — comment trivia that
        #     appeared *after* the effective token at index i, on the
        #     same line, before the next effective token (Roslyn rule).
        # Comments on a fresh line attach as leading trivia of the next
        # effective token; comments on the same line as an effective
        # token attach as trailing trivia of that token. This is the
        # convention used by C# Roslyn, Swift, and rust-analyzer.
        effective: list[Token] = []
        leading: list[tuple[Trivia, ...]] = []
        trailing: list[tuple[Trivia, ...]] = []

        pending_leading: list[Trivia] = []
        last_effective_line = -1
        for tok in tokens:
            if tok.type in _COMMENT_TOKEN_KINDS:
                triv = Trivia(
                    kind=_TRIVIA_KIND_BY_TOKEN[tok.type],
                    text=tok.value,
                    line=tok.line,
                    column=tok.column,
                )
                # Trailing iff on the same line as the most recent
                # effective token. Otherwise it's leading for the next.
                if effective and tok.line == last_effective_line:
                    trailing[-1] = trailing[-1] + (triv,)
                else:
                    pending_leading.append(triv)
            else:
                effective.append(tok)
                leading.append(tuple(pending_leading))
                trailing.append(())
                pending_leading = []
                last_effective_line = tok.line

        # Stranded leading trivia at end-of-file (comments after the
        # last effective token but separated by a newline) are exposed
        # via `final_leading_trivia` so a top-level program node can
        # collect them as program-level trailing trivia.
        self._tokens = effective
        self._leading_trivia = leading
        self._trailing_trivia = trailing
        self._final_leading_trivia: tuple[Trivia, ...] = tuple(pending_leading)
        self._pos = 0

        # Auto-decorate every `_parse_*` method so AST nodes returned
        # from any production rule get their leading/trailing trivia
        # attached transparently — no per-method edits required across
        # the ~50 grammar rules.
        for name in dir(type(self)):
            if name.startswith("_parse_"):
                method = getattr(self, name)
                if callable(method):
                    setattr(self, name, self._with_trivia(method))

    def _with_trivia(self, method):
        """Decorator: capture start position, run the production, attach
        leading + trailing trivia to any returned ``ASTNode``."""
        def wrapper(*args, **kwargs):
            start_pos = self._pos
            result = method(*args, **kwargs)
            if isinstance(result, ASTNode):
                self._attach_trivia(result, start_pos)
            return result
        return wrapper

    def _attach_trivia(self, node: ASTNode, start_pos: int) -> None:
        """Attach leading + trailing trivia to ``node`` (Fase 14.a).

        Leading trivia is the comments that appeared between the
        previous effective token (or file start) and ``self._tokens[start_pos]``.
        Trailing trivia is the comments on the same line as the last
        effective token consumed by the production rule that returned
        ``node`` (i.e., ``self._tokens[self._pos - 1]``).

        The first writer wins so the *innermost* AST node along a
        chain of nested productions keeps the trivia. Outer wrappers
        (e.g., ``_parse_program`` wrapping ``_parse_persona_definition``)
        see the slots already populated and do not duplicate the data.
        """
        if 0 <= start_pos < len(self._leading_trivia):
            leading = self._leading_trivia[start_pos]
            if leading and not node.leading_trivia:
                object.__setattr__(node, "leading_trivia", leading)
        end_pos = self._pos - 1
        if 0 <= end_pos < len(self._trailing_trivia):
            trailing = self._trailing_trivia[end_pos]
            if trailing and not node.trailing_trivia:
                object.__setattr__(node, "trailing_trivia", trailing)

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
            case TokenType.RESOURCE:
                return self._parse_resource()
            case TokenType.FABRIC:
                return self._parse_fabric()
            case TokenType.MANIFEST:
                return self._parse_manifest()
            case TokenType.OBSERVE:
                return self._parse_observe()
            case TokenType.RECONCILE:
                return self._parse_reconcile()
            case TokenType.LEASE:
                return self._parse_lease()
            case TokenType.ENSEMBLE:
                return self._parse_ensemble()
            case TokenType.SESSION:
                return self._parse_session()
            case TokenType.TOPOLOGY:
                return self._parse_topology()
            case TokenType.IMMUNE:
                return self._parse_immune()
            case TokenType.REFLEX:
                return self._parse_reflex()
            case TokenType.HEAL:
                return self._parse_heal()
            case TokenType.COMPONENT:
                return self._parse_component()
            case TokenType.VIEW:
                return self._parse_view()
            case TokenType.CHANNEL:
                return self._parse_channel()
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
                    expected="declaration (persona, context, anchor, flow, agent, shield, psyche, pix, ots, mandate, lambda, daemon, axonstore, axonendpoint, resource, fabric, manifest, observe, reconcile, lease, ensemble, session, topology, immune, reflex, heal, run, know, speculate, ...)",
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

        # optional ESK Fase 6.1 compliance annotation: compliance [HIPAA, ...]
        if self._check(TokenType.IDENTIFIER) and self._current().value == "compliance":
            self._advance()
            node.compliance = self._parse_bracketed_identifiers()

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
            case TokenType.EMIT:
                return self._parse_emit()
            case TokenType.PUBLISH:
                return self._parse_publish()
            case TokenType.DISCOVER:
                return self._parse_discover()
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
        Parse a listen block (dual-mode per Fase 13 D4):

          # Canonical (v1.5.0+) — typed channel reference
          listen OrdersCreated as order_event {
              step Validate { ... }
          }

          # Legacy — string topic, emits deprecation warning in type checker
          listen "orders" as order_event {
              step Validate { ... }
          }

        π-Calculus correspondence: c(x).Q
          In canonical mode `c` resolves to a declared ChannelDefinition
          (typed); in legacy mode `c` is a string topic resolved by the
          runtime EventBus.  Either way, `order_event` binds x and the
          body is the continuation Q.
        """
        tok = self._consume(TokenType.LISTEN)
        node = ListenBlock(line=tok.line, column=tok.column)

        # channel: STRING (legacy) or IDENTIFIER (canonical, Fase 13)
        head = self._current()
        if head.type == TokenType.STRING:
            node.channel_expr = self._consume(TokenType.STRING).value
            node.channel_is_ref = False
        else:
            ref = self._consume(TokenType.IDENTIFIER)
            node.channel_expr = ref.value
            node.channel_is_ref = True

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
                        case "compliance":
                            # ESK Fase 6.1 — regulatory coverage list
                            node.compliance = self._parse_bracketed_identifiers()
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
                case "compliance":
                    # ESK Fase 6.1 — regulatory coverage for this HTTP boundary
                    node.compliance = self._parse_bracketed_identifiers()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ═══════════════════════════════════════════════════════════════
    #  I/O COGNITIVO — Cálculo Lambda Lineal Epistémico (λ-L-E) · Fase 1
    # ═══════════════════════════════════════════════════════════════

    _VALID_LIFETIMES = frozenset({"linear", "affine", "persistent"})
    _VALID_PARTITION_POLICIES = frozenset({"fail", "shield_quarantine"})

    def _parse_resource(self) -> ResourceDefinition:
        """Parse: resource Name { kind, endpoint, capacity, lifetime, certainty_floor, shield }."""
        tok = self._consume(TokenType.RESOURCE)
        name = self._consume(TokenType.IDENTIFIER)
        node = ResourceDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "kind":
                    node.kind = self._consume_any_identifier_or_keyword().value
                case "endpoint":
                    node.endpoint = self._consume(TokenType.STRING).value
                case "capacity":
                    node.capacity = int(self._consume(TokenType.INTEGER).value)
                case "lifetime":
                    lt_tok = self._consume_any_identifier_or_keyword()
                    lt = lt_tok.value
                    if lt not in self._VALID_LIFETIMES:
                        raise AxonParseError(
                            f"Invalid lifetime '{lt}' in resource '{name.value}'",
                            line=lt_tok.line, column=lt_tok.column,
                            expected="linear | affine | persistent",
                            found=lt,
                        )
                    node.lifetime = lt
                case "certainty_floor":
                    node.certainty_floor = self._parse_number_value()
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_fabric(self) -> FabricDefinition:
        """Parse: fabric Name { provider, region, zones, ephemeral, shield }."""
        tok = self._consume(TokenType.FABRIC)
        name = self._consume(TokenType.IDENTIFIER)
        node = FabricDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "provider":
                    node.provider = self._consume_any_identifier_or_keyword().value
                case "region":
                    node.region = self._consume(TokenType.STRING).value
                case "zones":
                    node.zones = int(self._consume(TokenType.INTEGER).value)
                case "ephemeral":
                    tok_val = self._consume(TokenType.BOOL)
                    node.ephemeral = (tok_val.value.lower() == "true")
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_manifest(self) -> ManifestDefinition:
        """Parse: manifest Name { resources, fabric, region, zones, compliance }."""
        tok = self._consume(TokenType.MANIFEST)
        name = self._consume(TokenType.IDENTIFIER)
        node = ManifestDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "resources":
                    node.resources = self._parse_bracketed_identifiers()
                case "fabric":
                    node.fabric_ref = self._consume_any_identifier_or_keyword().value
                case "region":
                    node.region = self._consume(TokenType.STRING).value
                case "zones":
                    node.zones = int(self._consume(TokenType.INTEGER).value)
                case "compliance":
                    node.compliance = self._parse_bracketed_identifiers()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_observe(self) -> ObserveDefinition:
        """Parse: observe Name from Manifest { sources, quorum, timeout, on_partition, certainty_floor }."""
        tok = self._consume(TokenType.OBSERVE)
        name = self._consume(TokenType.IDENTIFIER)
        node = ObserveDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.FROM)
        target = self._consume(TokenType.IDENTIFIER)
        node.target = target.value

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "sources":
                    node.sources = self._parse_bracketed_identifiers()
                case "quorum":
                    node.quorum = int(self._consume(TokenType.INTEGER).value)
                case "timeout":
                    if self._check(TokenType.DURATION):
                        node.timeout = self._advance().value
                    else:
                        node.timeout = self._consume_any_identifier_or_keyword().value
                case "on_partition":
                    p_tok = self._consume_any_identifier_or_keyword()
                    p = p_tok.value
                    if p not in self._VALID_PARTITION_POLICIES:
                        raise AxonParseError(
                            f"Invalid on_partition '{p}' in observe '{name.value}'",
                            line=p_tok.line, column=p_tok.column,
                            expected="fail | shield_quarantine",
                            found=p,
                        )
                    node.on_partition = p
                case "certainty_floor":
                    node.certainty_floor = self._parse_number_value()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_number_value(self) -> float:
        """Consume an INTEGER or FLOAT and return it as float."""
        tok = self._advance()
        if tok.type in (TokenType.FLOAT, TokenType.INTEGER):
            return float(tok.value)
        raise AxonParseError(
            "Expected numeric value",
            line=tok.line, column=tok.column,
            expected="FLOAT or INTEGER",
            found=tok.value,
        )

    # ═══════════════════════════════════════════════════════════════
    #  CONTROL COGNITIVO — Fase 3 of λ-L-E (reconcile / lease / ensemble)
    # ═══════════════════════════════════════════════════════════════

    _VALID_ON_DRIFT = frozenset({"provision", "alert", "refine"})
    _VALID_LEASE_ACQUIRE = frozenset({"on_start", "on_demand"})
    _VALID_LEASE_ON_EXPIRE = frozenset({"anchor_breach", "release", "extend"})
    _VALID_AGGREGATION = frozenset({"majority", "weighted", "byzantine"})
    _VALID_CERTAINTY_MODE = frozenset({"min", "weighted", "harmonic"})

    def _parse_reconcile(self) -> ReconcileDefinition:
        """Parse: reconcile Name { observe, threshold, tolerance, on_drift, shield, mandate, max_retries }."""
        tok = self._consume(TokenType.RECONCILE)
        name = self._consume(TokenType.IDENTIFIER)
        node = ReconcileDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "observe":
                    node.observe_ref = self._consume_any_identifier_or_keyword().value
                case "threshold":
                    node.threshold = self._parse_number_value()
                case "tolerance":
                    node.tolerance = self._parse_number_value()
                case "on_drift":
                    d_tok = self._consume_any_identifier_or_keyword()
                    if d_tok.value not in self._VALID_ON_DRIFT:
                        raise AxonParseError(
                            f"Invalid on_drift '{d_tok.value}' in reconcile '{name.value}'",
                            line=d_tok.line, column=d_tok.column,
                            expected="provision | alert | refine",
                            found=d_tok.value,
                        )
                    node.on_drift = d_tok.value
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case "mandate":
                    node.mandate_ref = self._consume_any_identifier_or_keyword().value
                case "max_retries":
                    node.max_retries = int(self._consume(TokenType.INTEGER).value)
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_lease(self) -> LeaseDefinition:
        """Parse: lease Name { resource, duration, acquire, on_expire }."""
        tok = self._consume(TokenType.LEASE)
        name = self._consume(TokenType.IDENTIFIER)
        node = LeaseDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "resource":
                    node.resource_ref = self._consume_any_identifier_or_keyword().value
                case "duration":
                    if self._check(TokenType.DURATION):
                        node.duration = self._advance().value
                    else:
                        node.duration = self._consume_any_identifier_or_keyword().value
                case "acquire":
                    a_tok = self._consume_any_identifier_or_keyword()
                    if a_tok.value not in self._VALID_LEASE_ACQUIRE:
                        raise AxonParseError(
                            f"Invalid acquire '{a_tok.value}' in lease '{name.value}'",
                            line=a_tok.line, column=a_tok.column,
                            expected="on_start | on_demand",
                            found=a_tok.value,
                        )
                    node.acquire = a_tok.value
                case "on_expire":
                    e_tok = self._consume_any_identifier_or_keyword()
                    if e_tok.value not in self._VALID_LEASE_ON_EXPIRE:
                        raise AxonParseError(
                            f"Invalid on_expire '{e_tok.value}' in lease '{name.value}'",
                            line=e_tok.line, column=e_tok.column,
                            expected="anchor_breach | release | extend",
                            found=e_tok.value,
                        )
                    node.on_expire = e_tok.value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ═══════════════════════════════════════════════════════════════
    #  TOPOLOGY & SESSION TYPES — Fase 4 of λ-L-E (π-calculus binary sessions)
    # ═══════════════════════════════════════════════════════════════

    _VALID_SESSION_OPS = frozenset({"send", "receive", "loop", "end"})

    def _parse_session(self) -> SessionDefinition:
        """Parse: session Name { role1: [step, ...]   role2: [step, ...] }."""
        tok = self._consume(TokenType.SESSION)
        name = self._consume(TokenType.IDENTIFIER)
        node = SessionDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            role_tok = self._consume_any_identifier_or_keyword()
            self._consume(TokenType.COLON)
            steps = self._parse_session_steps()
            node.roles.append(SessionRole(
                name=role_tok.value,
                steps=steps,
                line=role_tok.line,
                column=role_tok.column,
            ))

        self._consume(TokenType.RBRACE)
        return node

    def _parse_session_steps(self) -> list[SessionStep]:
        """Parse: [send T, receive U, loop, end]."""
        steps: list[SessionStep] = []
        self._consume(TokenType.LBRACKET)
        while not self._check(TokenType.RBRACKET):
            step = self._parse_session_step()
            steps.append(step)
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACKET)
        return steps

    def _parse_session_step(self) -> SessionStep:
        """Parse a single step: 'send T' | 'receive T' | 'loop' | 'end'."""
        op_tok = self._current()
        match op_tok.type:
            case TokenType.SEND:
                self._advance()
                msg = self._consume_any_identifier_or_keyword()
                return SessionStep(
                    op="send", message_type=msg.value,
                    line=op_tok.line, column=op_tok.column,
                )
            case TokenType.RECEIVE:
                self._advance()
                msg = self._consume_any_identifier_or_keyword()
                return SessionStep(
                    op="receive", message_type=msg.value,
                    line=op_tok.line, column=op_tok.column,
                )
            case TokenType.LOOP:
                self._advance()
                return SessionStep(
                    op="loop", line=op_tok.line, column=op_tok.column,
                )
            case TokenType.END:
                self._advance()
                return SessionStep(
                    op="end", line=op_tok.line, column=op_tok.column,
                )
            case _:
                raise AxonParseError(
                    f"Invalid session step",
                    line=op_tok.line, column=op_tok.column,
                    expected="send | receive | loop | end",
                    found=op_tok.value,
                )

    def _parse_topology(self) -> TopologyDefinition:
        """Parse: topology Name { nodes: [A, B, ...] edges: [A -> B : Sess, ...] }."""
        tok = self._consume(TokenType.TOPOLOGY)
        name = self._consume(TokenType.IDENTIFIER)
        node = TopologyDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "nodes":
                    node.nodes = self._parse_bracketed_identifiers()
                case "edges":
                    node.edges = self._parse_topology_edges()
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_topology_edges(self) -> list[TopologyEdge]:
        """Parse: [A -> B : Sess, C -> D : Sess2]."""
        edges: list[TopologyEdge] = []
        self._consume(TokenType.LBRACKET)
        while not self._check(TokenType.RBRACKET):
            edge = self._parse_topology_edge()
            edges.append(edge)
            if self._check(TokenType.COMMA):
                self._advance()
        self._consume(TokenType.RBRACKET)
        return edges

    def _parse_topology_edge(self) -> TopologyEdge:
        """Parse: source -> target : SessionName."""
        src_tok = self._consume_any_identifier_or_keyword()
        self._consume(TokenType.ARROW)
        tgt_tok = self._consume_any_identifier_or_keyword()
        self._consume(TokenType.COLON)
        sess_tok = self._consume_any_identifier_or_keyword()
        return TopologyEdge(
            source=src_tok.value,
            target=tgt_tok.value,
            session_ref=sess_tok.value,
            line=src_tok.line,
            column=src_tok.column,
        )

    # ═══════════════════════════════════════════════════════════════
    #  COGNITIVE IMMUNE SYSTEM — Fase 5 of λ-L-E (immune / reflex / heal)
    #  Formal spec: docs/paper_inmune.md
    # ═══════════════════════════════════════════════════════════════

    _VALID_EPISTEMIC_LEVELS = frozenset({"know", "believe", "speculate", "doubt"})
    _VALID_REFLEX_ACTIONS = frozenset({
        "drop", "revoke", "emit", "redact", "quarantine", "terminate", "alert",
    })
    _VALID_HEAL_MODES = frozenset({"audit_only", "human_in_loop", "adversarial"})
    _VALID_SCOPES = frozenset({"tenant", "flow", "global"})
    _VALID_DECAY = frozenset({"exponential", "linear", "none"})

    def _parse_immune(self) -> ImmuneDefinition:
        """Parse: immune Name { watch, sensitivity, baseline, window, scope, tau, decay }."""
        tok = self._consume(TokenType.IMMUNE)
        name = self._consume(TokenType.IDENTIFIER)
        node = ImmuneDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "watch":
                    node.watch = self._parse_bracketed_identifiers()
                case "sensitivity":
                    node.sensitivity = self._parse_number_value()
                case "baseline":
                    node.baseline = self._consume_any_identifier_or_keyword().value
                case "window":
                    node.window = int(self._consume(TokenType.INTEGER).value)
                case "scope":
                    s_tok = self._consume_any_identifier_or_keyword()
                    if s_tok.value not in self._VALID_SCOPES:
                        raise AxonParseError(
                            f"Invalid scope '{s_tok.value}' in immune '{name.value}'",
                            line=s_tok.line, column=s_tok.column,
                            expected="tenant | flow | global",
                            found=s_tok.value,
                        )
                    node.scope = s_tok.value
                case "tau":
                    if self._check(TokenType.DURATION):
                        node.tau = self._advance().value
                    else:
                        node.tau = self._consume_any_identifier_or_keyword().value
                case "decay":
                    d_tok = self._consume_any_identifier_or_keyword()
                    if d_tok.value not in self._VALID_DECAY:
                        raise AxonParseError(
                            f"Invalid decay '{d_tok.value}' in immune '{name.value}'",
                            line=d_tok.line, column=d_tok.column,
                            expected="exponential | linear | none",
                            found=d_tok.value,
                        )
                    node.decay = d_tok.value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_reflex(self) -> ReflexDefinition:
        """Parse: reflex Name { trigger, on_level, action, scope, sla }."""
        tok = self._consume(TokenType.REFLEX)
        name = self._consume(TokenType.IDENTIFIER)
        node = ReflexDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "trigger":
                    node.trigger = self._consume_any_identifier_or_keyword().value
                case "on_level":
                    l_tok = self._consume_any_identifier_or_keyword()
                    if l_tok.value not in self._VALID_EPISTEMIC_LEVELS:
                        raise AxonParseError(
                            f"Invalid on_level '{l_tok.value}' in reflex '{name.value}'",
                            line=l_tok.line, column=l_tok.column,
                            expected="know | believe | speculate | doubt",
                            found=l_tok.value,
                        )
                    node.on_level = l_tok.value
                case "action":
                    a_tok = self._consume_any_identifier_or_keyword()
                    if a_tok.value not in self._VALID_REFLEX_ACTIONS:
                        raise AxonParseError(
                            f"Invalid action '{a_tok.value}' in reflex '{name.value}'",
                            line=a_tok.line, column=a_tok.column,
                            expected="drop | revoke | emit | redact | quarantine | terminate | alert",
                            found=a_tok.value,
                        )
                    node.action = a_tok.value
                case "scope":
                    s_tok = self._consume_any_identifier_or_keyword()
                    if s_tok.value not in self._VALID_SCOPES:
                        raise AxonParseError(
                            f"Invalid scope '{s_tok.value}' in reflex '{name.value}'",
                            line=s_tok.line, column=s_tok.column,
                            expected="tenant | flow | global",
                            found=s_tok.value,
                        )
                    node.scope = s_tok.value
                case "sla":
                    if self._check(TokenType.DURATION):
                        node.sla = self._advance().value
                    else:
                        node.sla = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_heal(self) -> HealDefinition:
        """Parse: heal Name { source, on_level, mode, scope, review_sla, shield, max_patches }."""
        tok = self._consume(TokenType.HEAL)
        name = self._consume(TokenType.IDENTIFIER)
        node = HealDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "source":
                    node.source = self._consume_any_identifier_or_keyword().value
                case "on_level":
                    l_tok = self._consume_any_identifier_or_keyword()
                    if l_tok.value not in self._VALID_EPISTEMIC_LEVELS:
                        raise AxonParseError(
                            f"Invalid on_level '{l_tok.value}' in heal '{name.value}'",
                            line=l_tok.line, column=l_tok.column,
                            expected="know | believe | speculate | doubt",
                            found=l_tok.value,
                        )
                    node.on_level = l_tok.value
                case "mode":
                    m_tok = self._consume_any_identifier_or_keyword()
                    if m_tok.value not in self._VALID_HEAL_MODES:
                        raise AxonParseError(
                            f"Invalid mode '{m_tok.value}' in heal '{name.value}'",
                            line=m_tok.line, column=m_tok.column,
                            expected="audit_only | human_in_loop | adversarial",
                            found=m_tok.value,
                        )
                    node.mode = m_tok.value
                case "scope":
                    s_tok = self._consume_any_identifier_or_keyword()
                    if s_tok.value not in self._VALID_SCOPES:
                        raise AxonParseError(
                            f"Invalid scope '{s_tok.value}' in heal '{name.value}'",
                            line=s_tok.line, column=s_tok.column,
                            expected="tenant | flow | global",
                            found=s_tok.value,
                        )
                    node.scope = s_tok.value
                case "review_sla":
                    if self._check(TokenType.DURATION):
                        node.review_sla = self._advance().value
                    else:
                        node.review_sla = self._consume_any_identifier_or_keyword().value
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case "max_patches":
                    node.max_patches = int(self._consume(TokenType.INTEGER).value)
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    # ═══════════════════════════════════════════════════════════════
    #  UI COGNITIVA — Fase 9 of λ-L-E (component / view)
    # ═══════════════════════════════════════════════════════════════

    _VALID_RENDER_HINTS = frozenset({"card", "list", "form", "chart", "custom"})

    def _parse_component(self) -> ComponentDefinition:
        """Parse: component Name { renders, via_shield, on_interact, render_hint }."""
        tok = self._consume(TokenType.COMPONENT)
        name = self._consume(TokenType.IDENTIFIER)
        node = ComponentDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "renders":
                    node.renders = self._consume_any_identifier_or_keyword().value
                case "via_shield":
                    node.via_shield = self._consume_any_identifier_or_keyword().value
                case "on_interact":
                    node.on_interact = self._consume_any_identifier_or_keyword().value
                case "render_hint":
                    h_tok = self._consume_any_identifier_or_keyword()
                    if h_tok.value not in self._VALID_RENDER_HINTS:
                        raise AxonParseError(
                            f"Invalid render_hint '{h_tok.value}' in component '{name.value}'",
                            line=h_tok.line, column=h_tok.column,
                            expected="card | list | form | chart | custom",
                            found=h_tok.value,
                        )
                    node.render_hint = h_tok.value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_view(self) -> ViewDefinition:
        """Parse: view Name { title, components: [...], route }."""
        tok = self._consume(TokenType.VIEW)
        name = self._consume(TokenType.IDENTIFIER)
        node = ViewDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "title":
                    node.title = self._consume(TokenType.STRING).value
                case "components":
                    node.components = self._parse_bracketed_identifiers()
                case "route":
                    node.route = self._consume(TokenType.STRING).value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_ensemble(self) -> EnsembleDefinition:
        """Parse: ensemble Name { observations, quorum, aggregation, certainty_mode }."""
        tok = self._consume(TokenType.ENSEMBLE)
        name = self._consume(TokenType.IDENTIFIER)
        node = EnsembleDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "observations":
                    node.observations = self._parse_bracketed_identifiers()
                case "quorum":
                    node.quorum = int(self._consume(TokenType.INTEGER).value)
                case "aggregation":
                    a_tok = self._consume_any_identifier_or_keyword()
                    if a_tok.value not in self._VALID_AGGREGATION:
                        raise AxonParseError(
                            f"Invalid aggregation '{a_tok.value}' in ensemble '{name.value}'",
                            line=a_tok.line, column=a_tok.column,
                            expected="majority | weighted | byzantine",
                            found=a_tok.value,
                        )
                    node.aggregation = a_tok.value
                case "certainty_mode":
                    c_tok = self._consume_any_identifier_or_keyword()
                    if c_tok.value not in self._VALID_CERTAINTY_MODE:
                        raise AxonParseError(
                            f"Invalid certainty_mode '{c_tok.value}' in ensemble '{name.value}'",
                            line=c_tok.line, column=c_tok.column,
                            expected="min | weighted | harmonic",
                            found=c_tok.value,
                        )
                    node.certainty_mode = c_tok.value
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

    # ──────────────────────────────────────────────────────────────
    #  MOBILE TYPED CHANNELS — Fase 13 (paper_mobile_channels.md)
    # ──────────────────────────────────────────────────────────────

    _VALID_CHANNEL_QOS = frozenset({
        "at_most_once", "at_least_once", "exactly_once", "broadcast", "queue",
    })
    _VALID_CHANNEL_PERSISTENCE = frozenset({
        "ephemeral", "persistent_axonstore",
    })

    def _parse_channel(self) -> ChannelDefinition:
        """
        Parse: channel Name { message, qos, lifetime, persistence, shield }.

        Example:

          channel OrdersCreated {
              message: Order
              qos: at_least_once
              lifetime: affine
              persistence: ephemeral
              shield: PublicBroker
          }

        The `message` field is either a type name (e.g. `Order`) or a
        nested `Channel<T>` spelling (second-order sessions, paper §3.3).
        The raw source text of the type expression is preserved verbatim
        in node.message; the type checker (Fase 13.b) parses the spelling
        and resolves it against TypeDefinition / ChannelDefinition scope.
        """
        tok = self._consume(TokenType.CHANNEL)
        name = self._consume(TokenType.IDENTIFIER)
        node = ChannelDefinition(name=name.value, line=tok.line, column=tok.column)

        self._consume(TokenType.LBRACE)
        while not self._check(TokenType.RBRACE):
            field_tok = self._current()
            field_name = field_tok.value
            self._advance()
            self._consume(TokenType.COLON)

            match field_name:
                case "message":
                    node.message = self._parse_channel_message_type()
                case "qos":
                    q_tok = self._consume_any_identifier_or_keyword()
                    if q_tok.value not in self._VALID_CHANNEL_QOS:
                        raise AxonParseError(
                            f"Invalid qos '{q_tok.value}' in channel '{name.value}'",
                            line=q_tok.line, column=q_tok.column,
                            expected="at_most_once | at_least_once | exactly_once | broadcast | queue",
                            found=q_tok.value,
                        )
                    node.qos = q_tok.value
                case "lifetime":
                    lt_tok = self._consume_any_identifier_or_keyword()
                    if lt_tok.value not in self._VALID_LIFETIMES:
                        raise AxonParseError(
                            f"Invalid lifetime '{lt_tok.value}' in channel '{name.value}'",
                            line=lt_tok.line, column=lt_tok.column,
                            expected="linear | affine | persistent",
                            found=lt_tok.value,
                        )
                    node.lifetime = lt_tok.value
                case "persistence":
                    p_tok = self._consume_any_identifier_or_keyword()
                    if p_tok.value not in self._VALID_CHANNEL_PERSISTENCE:
                        raise AxonParseError(
                            f"Invalid persistence '{p_tok.value}' in channel '{name.value}'",
                            line=p_tok.line, column=p_tok.column,
                            expected="ephemeral | persistent_axonstore",
                            found=p_tok.value,
                        )
                    node.persistence = p_tok.value
                case "shield":
                    node.shield_ref = self._consume_any_identifier_or_keyword().value
                case _:
                    self._skip_value()

        self._consume(TokenType.RBRACE)
        return node

    def _parse_channel_message_type(self) -> str:
        """
        Parse the `message:` value of a channel declaration.

        Accepts either a plain identifier (e.g. `Order`) or a nested
        `Channel<T>` spelling that supports second-order mobility
        (paper §3.3).  Returns the source text verbatim so the type
        checker in Fase 13.b can resolve it against the symbol table.
        """
        head = self._consume(TokenType.IDENTIFIER)
        spelling = head.value
        if self._check(TokenType.LT):
            self._advance()
            inner = self._parse_channel_message_type()
            self._consume(TokenType.GT)
            spelling = f"{head.value}<{inner}>"
        return spelling

    def _parse_emit(self) -> EmitStatement:
        """
        Parse: emit ChannelName(value_ref).

        Output prefix c⟨v⟩.P in π-calculus notation.  The value can be:
          - a bare identifier — payload variable or channel name (mobility D2)
          - a dotted access path — references a prior step's result, e.g.
            `emit Hello(Build.output)` reads `step_results["Build"]["output"]`
            at runtime (Fase 13.i — closes the gap reported by adopters where
            `emit X(Step.output)` failed at parser level).

        Both shapes produce the same AST: `value_ref` is a string that may
        contain dots. The type checker (13.b) dispatches on whether the
        bare-identifier case resolves to a ChannelDefinition (mobility) or
        a payload (scalar). The dotted-access case is always treated as
        scalar — a step result is never itself a channel handle.
        """
        tok = self._consume(TokenType.EMIT)
        channel = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.LPAREN)
        value_ref = self._parse_emit_value_ref()
        self._consume(TokenType.RPAREN)
        return EmitStatement(
            channel_ref=channel.value,
            value_ref=value_ref,
            line=tok.line, column=tok.column,
        )

    def _parse_emit_value_ref(self) -> str:
        """Parse: IDENTIFIER ('.' (IDENTIFIER | keyword))*  → dot-joined string.

        Examples:
          - `payload`                → "payload"
          - `OrdersCreated`          → "OrdersCreated"      (mobility candidate)
          - `Build.output`           → "Build.output"       (step result ref —
                                       `output` is a reserved keyword in Axon
                                       but is permitted as a field-access
                                       segment because step results commonly
                                       expose `output`, `result`, etc.)
          - `Analyze.result.score`   → "Analyze.result.score" (nested field)

        Single recursive descent, conservative scope: identifiers + dots only.
        The HEAD must be a real ``IDENTIFIER`` (otherwise we would happily
        accept reserved-word noise like `daemon.x` as an emit payload).
        Subsequent segments after a `.` may be identifiers OR keywords —
        ``output``, ``result``, ``message``, ``state``, etc. are common
        field names on step outputs and we do not want adopters to fight
        the parser for accessing them.

        Function calls, indexing, arithmetic, etc. are intentionally out of
        scope here — they belong to a generic expression-parser fase if/when
        Axon needs them. Keeping `emit` value parsing minimal preserves the
        invariant that emit payloads are either named values or step-output
        addresses, never computed at emit-time.
        """
        head = self._consume(TokenType.IDENTIFIER)
        parts = [head.value]
        while self._check(TokenType.DOT):
            self._advance()  # consume '.'
            # Accept identifier or keyword for trailing segments. The
            # `_consume_any_identifier_or_keyword` helper already handles
            # this distinction in other parser paths (e.g. struct field
            # access), so reuse it for symmetry.
            part = self._consume_any_identifier_or_keyword()
            parts.append(part.value)
        return ".".join(parts)

    def _parse_publish(self) -> PublishStatement:
        """
        Parse: publish ChannelName within ShieldName.

        Capability extrusion (paper §3.4, D8).  `within <Shield>` is
        mandatory — a bare `publish ChannelName` is a compile error so
        that capability escape is always mediated by ESK.
        """
        tok = self._consume(TokenType.PUBLISH)
        channel = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.WITHIN)
        shield = self._consume(TokenType.IDENTIFIER)
        return PublishStatement(
            channel_ref=channel.value,
            shield_ref=shield.value,
            line=tok.line, column=tok.column,
        )

    def _parse_discover(self) -> DiscoverStatement:
        """
        Parse: discover ChannelName as alias.

        Dual of publish — the `as <alias>` binding is mandatory since
        every discovered handle is affine and needs a name to be
        consumed exactly once in the subsequent scope.
        """
        tok = self._consume(TokenType.DISCOVER)
        capability = self._consume(TokenType.IDENTIFIER)
        self._consume(TokenType.AS)
        alias = self._consume(TokenType.IDENTIFIER)
        return DiscoverStatement(
            capability_ref=capability.value,
            alias=alias.value,
            line=tok.line, column=tok.column,
        )

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
