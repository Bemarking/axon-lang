"""Tests for the AXON frontend facade introduced in Phase B4."""

from __future__ import annotations

from pathlib import Path

from axon.compiler import (
    FRONTEND_IMPLEMENTATION_ENV_VAR,
    FrontendCheckResult,
    FrontendCompileResult,
    FrontendDiagnostic,
    NativeDevelopmentFrontendImplementation,
    NativeFrontendPlaceholder,
    PythonFrontendImplementation,
    bootstrap_frontend,
    create_frontend_implementation,
    current_frontend_selection,
    frontend,
    get_frontend_implementation,
    list_frontend_implementations,
    register_frontend_implementation,
    reset_frontend_implementation,
    serialize_ir_program,
    set_frontend_implementation,
)


ROOT = Path(__file__).resolve().parent.parent
VALID_SOURCE = ROOT / "examples" / "contract_analyzer.axon"


def test_check_source_success_returns_counts() -> None:
    source = VALID_SOURCE.read_text(encoding="utf-8")

    result = frontend.check_source(source, str(VALID_SOURCE))

    assert result.ok
    assert result.token_count == 168
    assert result.declaration_count == 9
    assert result.diagnostics == ()


def test_check_source_parser_error_reports_stage() -> None:
    result = frontend.check_source("42 + garbage", "bad.axon")

    assert not result.ok
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.stage == "parser"
    assert diagnostic.line == 1
    assert diagnostic.column == 1
    assert "Unexpected token at top level" in diagnostic.message


def test_check_source_type_error_reports_stage() -> None:
    source = "persona Bad {\n  confidence_threshold: 1.5\n}\n"

    result = frontend.check_source(source, "bad_type.axon")

    assert not result.ok
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.stage == "type_checker"
    assert "confidence_threshold" in diagnostic.message


def test_compile_source_success_returns_ir_program() -> None:
    source = VALID_SOURCE.read_text(encoding="utf-8")

    result = frontend.compile_source(source, str(VALID_SOURCE))

    assert result.ok
    assert result.ir_program is not None
    ir_dict = serialize_ir_program(result.ir_program)
    assert ir_dict["node_type"] == "program"
    assert "flows" in ir_dict
    assert "runs" in ir_dict


def test_default_frontend_implementation_is_python() -> None:
    implementation = get_frontend_implementation()

    assert isinstance(implementation, PythonFrontendImplementation)


def test_frontend_facade_can_swap_implementation() -> None:
    class StubFrontendImplementation:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            return FrontendCheckResult(
                token_count=7,
                declaration_count=3,
                diagnostics=(
                    FrontendDiagnostic(
                        stage="type_checker",
                        message=f"stub-check:{filename}",
                        line=5,
                        column=2,
                    ),
                ),
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            return FrontendCompileResult(
                token_count=11,
                declaration_count=4,
                diagnostics=(
                    FrontendDiagnostic(
                        stage="ir_generator",
                        message=f"stub-compile:{filename}",
                    ),
                ),
                ir_program=None,
            )

    original = get_frontend_implementation()
    stub = StubFrontendImplementation()

    try:
        set_frontend_implementation(stub)

        check_result = frontend.check_source("persona X {}", "stub.axon")
        assert check_result.token_count == 7
        assert check_result.declaration_count == 3
        assert check_result.diagnostics[0].message == "stub-check:stub.axon"

        compile_result = frontend.compile_source("persona X {}", "stub.axon")
        assert compile_result.ir_program is None
        assert compile_result.diagnostics[0].stage == "ir_generator"
        assert compile_result.diagnostics[0].message == "stub-compile:stub.axon"
    finally:
        set_frontend_implementation(original)


def test_frontend_facade_reset_restores_python_implementation() -> None:
    class StubFrontendImplementation:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            return FrontendCheckResult(token_count=1, declaration_count=1)

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            return FrontendCompileResult(token_count=1, declaration_count=1)

    set_frontend_implementation(StubFrontendImplementation())

    try:
        assert not isinstance(get_frontend_implementation(), PythonFrontendImplementation)
        reset_frontend_implementation()
        assert isinstance(get_frontend_implementation(), PythonFrontendImplementation)
    finally:
        reset_frontend_implementation()


def test_list_frontend_implementations_includes_python_and_native() -> None:
    implementations = list_frontend_implementations()

    assert "python" in implementations
    assert "native-dev" in implementations
    assert "native" in implementations


def test_create_frontend_implementation_builds_registered_backend() -> None:
    python_impl = create_frontend_implementation("python")
    native_dev_impl = create_frontend_implementation("native-dev")
    native_impl = create_frontend_implementation("native")

    assert isinstance(python_impl, PythonFrontendImplementation)
    assert isinstance(native_dev_impl, NativeDevelopmentFrontendImplementation)
    assert isinstance(native_impl, NativeFrontendPlaceholder)


def test_bootstrap_frontend_selects_python_by_name() -> None:
    reset_frontend_implementation()

    implementation = bootstrap_frontend("python")

    assert isinstance(implementation, PythonFrontendImplementation)
    assert isinstance(get_frontend_implementation(), PythonFrontendImplementation)
    assert current_frontend_selection() == "python"


def test_bootstrap_frontend_uses_environment_selection(monkeypatch) -> None:
    monkeypatch.setenv(FRONTEND_IMPLEMENTATION_ENV_VAR, "native")

    implementation = bootstrap_frontend()

    try:
        assert isinstance(implementation, NativeFrontendPlaceholder)
        assert isinstance(get_frontend_implementation(), NativeFrontendPlaceholder)
        assert current_frontend_selection() == "native"
    finally:
        reset_frontend_implementation()


def test_native_placeholder_returns_safe_diagnostics() -> None:
    implementation = NativeFrontendPlaceholder()

    check_result = implementation.check_source("persona X {}", "native.axon")
    compile_result = implementation.compile_source("persona X {}", "native.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert "not implemented yet" in check_result.diagnostics[0].message

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "ir_generator"
    assert "not implemented yet" in compile_result.diagnostics[0].message


def test_native_dev_implementation_preserves_frontend_contract() -> None:
    source = VALID_SOURCE.read_text(encoding="utf-8")
    implementation = NativeDevelopmentFrontendImplementation()

    check_result = implementation.check_source(source, str(VALID_SOURCE))
    compile_result = implementation.compile_source(source, str(VALID_SOURCE))

    assert check_result.ok
    assert check_result.token_count == 168
    assert check_result.declaration_count == 9

    assert compile_result.ok
    assert compile_result.ir_program is not None
    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["node_type"] == "program"


def test_native_dev_handles_invalid_top_level_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for invalid top-level source")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for invalid top-level source")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("42 + garbage", "bad.axon")
    compile_result = implementation.compile_source("42 + garbage", "bad.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].line == 1
    assert check_result.diagnostics[0].column == 1
    assert "Unexpected token at top level" in check_result.diagnostics[0].message
    assert "found 42" in check_result.diagnostics[0].message

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].line == 1
    assert compile_result.diagnostics[0].column == 1
    assert "found 42" in compile_result.diagnostics[0].message


def test_native_dev_skips_leading_comments_before_top_level_parse_gate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used when native-dev catches top-level error")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used when native-dev catches top-level error")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source("// note\n42 + garbage", "bad.axon")

    assert not result.ok
    assert result.diagnostics[0].stage == "parser"
    assert result.diagnostics[0].line == 2
    assert result.diagnostics[0].column == 1
    assert "found 42" in result.diagnostics[0].message


def test_native_dev_reports_lexer_error_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev lexer errors")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev lexer errors")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("// note\n~", "bad.axon")
    compile_result = implementation.compile_source("/* unterminated", "bad.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "lexer"
    assert check_result.diagnostics[0].line == 2
    assert check_result.diagnostics[0].column == 1
    assert "Unexpected character '~'" == check_result.diagnostics[0].message

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "lexer"
    assert compile_result.diagnostics[0].line == 1
    assert compile_result.diagnostics[0].column == 1
    assert compile_result.diagnostics[0].message == "Unterminated block comment"


def test_native_dev_handles_range_type_check_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev range type check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev range type compile")

    source = "type RiskScore(0.0..1.0)"
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source(source, "type_range.axon")

    assert result.ok
    assert result.token_count > 0
    assert result.declaration_count == 1


def test_native_dev_handles_structured_type_check_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev structured type check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev structured type compile")

    source = (
        "type RiskScore(0.0..1.0)\n"
        "type Risk {\n"
        "  score: RiskScore,\n"
        "  mitigation: Opinion?\n"
        "}"
    )
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source(source, "type_struct.axon")

    assert result.ok
    assert result.token_count > 0
    assert result.declaration_count == 2


def test_native_dev_handles_where_type_check_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev where type check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev where type compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("type HighConfidenceClaim where confidence >= 0.85", 7),
        ("type HighConfidenceClaim(0.0..1.0) where confidence >= 0.85", 12),
        (
            "type HighConfidenceClaim where confidence >= 0.85 { claim: FactualClaim }",
            12,
        ),
    ]

    for source, expected_token_count in cases:
        result = implementation.check_source(source, "type_where.axon")

        assert result.ok
        assert result.token_count == expected_token_count
        assert result.declaration_count == 1


def test_native_dev_handles_invalid_type_range_constraints_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev invalid type range check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev invalid type range compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "type RiskScore(1.0..0.0)",
            8,
            1,
            ["Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)"],
        ),
        (
            "type RiskScore(1.0..0.0)\nflow SimpleFlow() {}\nrun SimpleFlow()",
            18,
            3,
            ["Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)"],
        ),
        (
            "type RiskScore(1.0..0.0)\nrun Missing()",
            12,
            2,
            [
                "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
        (
            "type RiskScore(1.0..0.0)\ncontext Review { memory: invalid }\nrun Missing() within Review",
            21,
            3,
            [
                "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
        (
            "type RiskScore(1.0..0.0) where confidence >= 0.85\ntype RiskScore(1.0..0.0) where confidence >= 0.90",
            23,
            2,
            [
                "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)",
                "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)",
                "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "invalid_type_range.axon")
        compile_result = implementation.compile_source(source, "invalid_type_range.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_rejects_block_signature_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed block signature")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed block signature")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("persona { }", "bad_persona.axon")
    compile_result = implementation.compile_source("anchor { }", "bad_anchor.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].line == 1
    assert check_result.diagnostics[0].column == 9
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found LBRACE('{'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found LBRACE('{'))"
    )


def test_native_dev_rejects_paren_signature_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed paren signature")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed paren signature")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("flow AnalyzeContract { }", "bad_flow.axon")
    compile_result = implementation.compile_source("run AnalyzeContract { }", "bad_run.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected LPAREN, found LBRACE('{'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected LPAREN, found LBRACE('{'))"
    )


def test_native_dev_rejects_expanded_block_headers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for expanded shared block headers")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for expanded shared block headers")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("shield { }", "bad_shield.axon")
    compile_result = implementation.compile_source("axonendpoint { }", "bad_endpoint.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found LBRACE('{'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found LBRACE('{'))"
    )


def test_native_dev_rejects_invalid_flow_parameter_start_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed flow parameter start")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed flow parameter start")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("flow Analyze({ }", "bad_flow_param.axon")
    compile_result = implementation.compile_source("flow Analyze(, )", "bad_flow_param_compile.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found LBRACE('{'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected IDENTIFIER, found COMMA(','))"
    )


def test_native_dev_allows_empty_flow_parameter_list_to_delegate() -> None:
    class RecordingPythonDelegate:
        def __init__(self) -> None:
            self.check_calls: list[tuple[str, str]] = []

        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            self.check_calls.append((source, filename))
            return PythonFrontendImplementation().check_source(source, filename)

    source = "flow SystemStatus() {}"
    delegate = RecordingPythonDelegate()
    implementation = NativeDevelopmentFrontendImplementation(delegate=delegate)

    result = implementation.check_source(source, "empty_flow.axon")

    assert result.ok
    assert len(delegate.check_calls) == 1


def test_native_dev_rejects_block_field_without_colon_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed first block field")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed first block field")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("persona Expert { domain }", "bad_persona_field.axon")
    compile_result = implementation.compile_source("shield Edge { scan }", "bad_shield_field.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected COLON, found RBRACE('}'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected COLON, found RBRACE('}'))"
    )


def test_native_dev_handles_block_field_with_colon_locally() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for locally handled persona block")

    source = 'persona Expert {\n  domain: ["contracts"]\n}'
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source(source, "persona_field.axon")

    assert result.ok


def test_native_dev_rejects_invalid_identifier_like_block_value_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed identifier-like value")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed identifier-like value")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("persona Expert { tone: ] }", "bad_persona_value.axon")
    compile_result = implementation.compile_source("context Review { memory: }", "bad_context_value.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Expected identifier or keyword value (found RBRACKET(']'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Expected identifier or keyword value (found RBRACE('}'))"
    )


def test_native_dev_handles_identifier_like_block_value_locally() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for locally handled persona block")

    source = "persona Expert { tone: precise }"
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source(source, "persona_tone.axon")

    assert result.ok


def test_native_dev_rejects_invalid_bool_block_value_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for malformed bool value")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for malformed bool value")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("persona Expert { cite_sources: ] }", "bad_persona_bool.axon")
    compile_result = implementation.compile_source("tool Search { sandbox: }", "bad_tool_bool.axon")

    assert not check_result.ok
    assert check_result.diagnostics[0].stage == "parser"
    assert check_result.diagnostics[0].message == (
        "Unexpected token (expected BOOL, found RBRACKET(']'))"
    )

    assert not compile_result.ok
    assert compile_result.diagnostics[0].stage == "parser"
    assert compile_result.diagnostics[0].message == (
        "Unexpected token (expected BOOL, found RBRACE('}'))"
    )


def test_native_dev_handles_bool_block_value_locally() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for locally handled persona block")

    source = "persona Expert { cite_sources: true }"
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.check_source(source, "persona_bool.axon")

    assert result.ok


def test_native_dev_delegates_run_argument_variants_to_python_delegate() -> None:
    class RecordingPythonDelegate:
        def __init__(self) -> None:
            self.compile_calls: list[tuple[str, str]] = []

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            self.compile_calls.append((source, filename))
            return PythonFrontendImplementation().compile_source(source, filename)

    source = (
        "flow Execute() {}\n"
        'run Execute()\n'
        'run Execute("report.json")\n'
        'run Execute(5)\n'
        'run Execute(report.pdf)\n'
        'run Execute(depth: 3)\n'
    )
    delegate = RecordingPythonDelegate()
    implementation = NativeDevelopmentFrontendImplementation(delegate=delegate)

    result = implementation.compile_source(source, "run_variants.axon")

    assert result.ok
    assert result.ir_program is not None
    assert len(delegate.compile_calls) == 1
    ir_dict = serialize_ir_program(result.ir_program)
    assert len(ir_dict["runs"]) == 5
    assert list(ir_dict["runs"][0]["arguments"]) == []
    assert list(ir_dict["runs"][1]["arguments"]) == ["report.json"]
    assert list(ir_dict["runs"][2]["arguments"]) == ["5"]
    assert list(ir_dict["runs"][3]["arguments"]) == ["report.pdf"]
    assert list(ir_dict["runs"][4]["arguments"]) == ["depth", ":", "3"]


def test_native_dev_handles_minimal_standalone_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal standalone run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal standalone run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    check_result = implementation.check_source("run SimpleFlow()", "run.axon")
    compile_result = implementation.compile_source("run SimpleFlow()", "run.axon")

    assert not check_result.ok
    assert check_result.token_count == 5
    assert check_result.declaration_count == 1
    assert check_result.diagnostics[0].stage == "type_checker"
    assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

    assert not compile_result.ok
    assert compile_result.token_count == 5
    assert compile_result.declaration_count == 1
    assert compile_result.diagnostics[0].stage == "type_checker"
    assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_isolated_run_argument_variants_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for isolated native-dev run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for isolated native-dev run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("run SimpleFlow(\"report.json\")", 6),
        ("run SimpleFlow(5)", 6),
        ("run SimpleFlow(report.pdf)", 8),
        ("run SimpleFlow(depth: 3)", 8),
    ]

    for source, expected_token_count in cases:
        check_result = implementation.check_source(source, "run.axon")
        compile_result = implementation.compile_source(source, "run.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 1
        assert check_result.diagnostics[0].stage == "type_checker"
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 1
        assert compile_result.diagnostics[0].stage == "type_checker"
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_supported_isolated_run_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for supported isolated run modifiers")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for supported isolated run modifiers")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ('run SimpleFlow() output_to: "report.json"', 8),
        ("run SimpleFlow() effort: high", 8),
        ("run SimpleFlow() on_failure: log", 8),
        ("run SimpleFlow() on_failure: retry", 8),
    ]

    for source, expected_token_count in cases:
        check_result = implementation.check_source(source, "run.axon")
        compile_result = implementation.compile_source(source, "run.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 1
        assert check_result.diagnostics[0].stage == "type_checker"
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 1
        assert compile_result.diagnostics[0].stage == "type_checker"
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_simple_on_failure_in_shared_block_prefixed_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for simple prefixed on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for simple prefixed on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("persona Expert { tone: precise }\nrun SimpleFlow() on_failure: log", 15, 2),
        ("persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry", 22, 3),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "prefixed_on_failure.axon")
        compile_result = implementation.compile_source(source, "prefixed_on_failure.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_retry_on_failure_with_single_parameter_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for retry(...) on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for retry(...) on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("run SimpleFlow() on_failure: retry(backoff: exponential)", 13, 1),
        (
            "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
            20,
            2,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
            27,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "retry_on_failure.axon")
        compile_result = implementation.compile_source(source, "retry_on_failure.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_retry_on_failure_with_two_parameters_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for retry(..., ...) on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for retry(..., ...) on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)", 17, 1),
        (
            "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
            24,
            2,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
            31,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "retry_on_failure_two_pairs.axon")
        compile_result = implementation.compile_source(source, "retry_on_failure_two_pairs.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_retry_on_failure_with_three_parameters_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for retry(..., ..., ...) on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for retry(..., ..., ...) on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
            21,
            1,
        ),
        (
            "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
            28,
            2,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
            35,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "retry_on_failure_three_pairs.axon")
        compile_result = implementation.compile_source(source, "retry_on_failure_three_pairs.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_retry_on_failure_with_four_parameters_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for retry(... x4) on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for retry(... x4) on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
            25,
            1,
        ),
        (
            "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
            32,
            2,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
            39,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "retry_on_failure_four_pairs.axon")
        compile_result = implementation.compile_source(source, "retry_on_failure_four_pairs.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_retry_on_failure_with_five_or_more_parameters_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for retry(... x5+) on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for retry(... x5+) on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
            29,
            1,
        ),
        (
            "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe, budget: low)",
            33,
            1,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
            43,
            3,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe, budget: low)",
            47,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "retry_on_failure_five_plus_pairs.axon")
        compile_result = implementation.compile_source(source, "retry_on_failure_five_plus_pairs.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_as_modifier_with_matching_persona_prefix_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for supported prefixed as modifier check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for supported prefixed as modifier compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("persona Expert { tone: precise }\nrun SimpleFlow() as Expert", 14, 2),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() as Expert",
            21,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "run_as_prefixed.axon")
        compile_result = implementation.compile_source(source, "run_as_prefixed.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_keeps_isolated_or_mismatched_as_and_other_remaining_modifiers_on_python_delegate() -> None:
    class RecordingPythonDelegate:
        def __init__(self) -> None:
            self.check_calls: list[tuple[str, str]] = []
            self.compile_calls: list[tuple[str, str]] = []

        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            self.check_calls.append((source, filename))
            return PythonFrontendImplementation().check_source(source, filename)

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            self.compile_calls.append((source, filename))
            return PythonFrontendImplementation().compile_source(source, filename)

    cases = [
        "run SimpleFlow() as Expert",
        "persona Guide { tone: precise }\nrun SimpleFlow() as Expert",
        "run SimpleFlow() within Review",
        "context SessionCtx { memory: session }\nrun SimpleFlow() within Review",
        "run SimpleFlow() constrained_by [Safety]",
        "anchor Known { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
    ]

    for index, source in enumerate(cases, start=1):
        delegate = RecordingPythonDelegate()
        implementation = NativeDevelopmentFrontendImplementation(delegate=delegate)

        check_result = implementation.check_source(source, f"run_remaining_modifier_{index}.axon")
        compile_result = implementation.compile_source(source, f"run_remaining_modifier_{index}.axon")

        assert not check_result.ok
        assert "Undefined flow 'SimpleFlow' in run statement" in [d.message for d in check_result.diagnostics]
        assert len(delegate.check_calls) == 1

        assert not compile_result.ok
        assert "Undefined flow 'SimpleFlow' in run statement" in [d.message for d in compile_result.diagnostics]
        assert len(delegate.compile_calls) == 1


def test_native_dev_handles_within_modifier_with_matching_context_prefix_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for supported prefixed within modifier check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for supported prefixed within modifier compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("context Review { memory: session }\nrun SimpleFlow() within Review", 14, 2),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() within Review",
            21,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "run_within_prefixed.axon")
        compile_result = implementation.compile_source(source, "run_within_prefixed.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_constrained_by_with_matching_anchor_prefix_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for supported prefixed constrained_by check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for supported prefixed constrained_by compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("anchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]", 16, 2),
        (
            "anchor Safety { require: source_citation }\nanchor Grounding { require: source_citation }\nrun SimpleFlow() constrained_by [Safety, Grounding]",
            25,
            3,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
            30,
            4,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "run_constrained_prefixed.axon")
        compile_result = implementation.compile_source(source, "run_constrained_prefixed.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_raise_on_failure_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for raise on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for raise on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("run SimpleFlow() on_failure: raise AnchorBreachError", 9, 1),
        (
            "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            16,
            2,
        ),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            23,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "raise_on_failure.axon")
        compile_result = implementation.compile_source(source, "raise_on_failure.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_shared_block_prefixed_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for prefixed block + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for prefixed block + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("persona Expert { tone: precise }\nrun SimpleFlow()", 12, 2),
        ('persona Expert { tone: precise }\nrun SimpleFlow() output_to: "report.json"', 15, 2),
        (
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow()",
            19,
            3,
        ),
        (
            'persona Expert { tone: precise }\nanchor Safety { require: source_citation }\nrun SimpleFlow() output_to: "report.json"',
            22,
            3,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "prefixed_run.axon")
        compile_result = implementation.compile_source(source, "prefixed_run.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics[0].stage == "type_checker"
        assert check_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics[0].stage == "type_checker"
        assert compile_result.diagnostics[0].message == "Undefined flow 'SimpleFlow' in run statement"


def test_native_dev_handles_minimal_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "flow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "minimal_success.axon")
    compile_result = implementation.compile_source(source, "minimal_success.axon")

    assert check_result.ok
    assert check_result.token_count == 11
    assert check_result.declaration_count == 2
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 11
    assert compile_result.declaration_count == 2
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [flow["name"] for flow in ir_dict["flows"]] == ["SimpleFlow"]
    assert [run["flow_name"] for run in ir_dict["runs"]] == ["SimpleFlow"]
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_minimal_flow_run_success_with_output_to_or_effort_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal successful flow + run modifier check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal successful flow + run modifier compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("flow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"", 14, "report.json", ""),
        ("flow SimpleFlow() {}\nrun SimpleFlow() effort: high", 14, "", "high"),
    ]

    for source, expected_token_count, expected_output_to, expected_effort in cases:
        check_result = implementation.check_source(source, "minimal_success_modifier.axon")
        compile_result = implementation.compile_source(source, "minimal_success_modifier.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 2
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 2
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["output_to"] == expected_output_to
        assert ir_dict["runs"][0]["effort"] == expected_effort
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_minimal_flow_run_success_with_simple_on_failure_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal successful flow + simple on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal successful flow + simple on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: log", 14, "log"),
        ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry", 14, "retry"),
    ]

    for source, expected_token_count, expected_on_failure in cases:
        check_result = implementation.check_source(source, "minimal_success_on_failure.axon")
        compile_result = implementation.compile_source(source, "minimal_success_on_failure.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 2
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 2
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["on_failure"] == expected_on_failure
        assert ir_dict["runs"][0]["on_failure_params"] == ()
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_minimal_flow_run_success_with_raise_on_failure_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal successful flow + raise on_failure check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal successful flow + raise on_failure compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError"

    check_result = implementation.check_source(source, "minimal_success_raise.axon")
    compile_result = implementation.compile_source(source, "minimal_success_raise.axon")

    assert check_result.ok
    assert check_result.token_count == 15
    assert check_result.declaration_count == 2
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 15
    assert compile_result.declaration_count == 2
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["on_failure"] == "raise"
    assert ir_dict["runs"][0]["on_failure_params"] == (("target", "AnchorBreachError"),)
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_minimal_flow_run_success_with_parameterized_retry_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for minimal successful flow + retry(...) check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for minimal successful flow + retry(...) compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
            19,
            (("backoff", "exponential"),),
        ),
        (
            "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
            23,
            (("backoff", "exponential"), ("attempts", "3")),
        ),
    ]

    for source, expected_token_count, expected_params in cases:
        check_result = implementation.check_source(source, "minimal_success_retry_param.axon")
        compile_result = implementation.compile_source(source, "minimal_success_retry_param.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 2
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 2
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["on_failure"] == "retry"
        assert ir_dict["runs"][0]["on_failure_params"] == expected_params
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact persona-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact persona-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "persona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "persona_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "persona_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert ir_dict["personas"][0]["tone"] == "precise"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_context_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact context-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact context-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "context Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "context_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "context_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert ir_dict["contexts"][0]["memory_scope"] == "session"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_anchor_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact anchor-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact anchor-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "anchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "anchor_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "anchor_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert ir_dict["anchors"][0]["require"] == "source_citation"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact persona+context-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact persona+context-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "persona_context_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert ir_dict["personas"][0]["tone"] == "precise"
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert ir_dict["contexts"][0]["memory_scope"] == "session"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_anchor_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact persona+anchor-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact persona+anchor-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "persona_anchor_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "persona_anchor_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert ir_dict["personas"][0]["tone"] == "precise"
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert ir_dict["anchors"][0]["require"] == "source_citation"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_context_anchor_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact context+anchor-prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact context+anchor-prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "context_anchor_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "context_anchor_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert ir_dict["contexts"][0]["memory_scope"] == "session"
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert ir_dict["anchors"][0]["require"] == "source_citation"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + run check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + run compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 32
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 32
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert ir_dict["personas"][0]["tone"] == "precise"
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert ir_dict["contexts"][0]["memory_scope"] == "session"
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert ir_dict["anchors"][0]["require"] == "source_citation"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_flow_run_success_in_supported_alternate_orders_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for structural prefixed successful flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for structural prefixed successful flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            25,
            4,
            ["Expert"],
            [],
            ["Safety"],
        ),
        (
            "context Review { memory: session }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            32,
            5,
            ["Expert"],
            ["Review"],
            ["Safety"],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_personas, expected_contexts, expected_anchors in cases:
        check_result = implementation.check_source(source, "structural_prefixed_success.axon")
        compile_result = implementation.compile_source(source, "structural_prefixed_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [persona["name"] for persona in ir_dict["personas"]] == expected_personas
        assert [context["name"] for context in ir_dict["contexts"]] == expected_contexts
        assert [anchor["name"] for anchor in ir_dict["anchors"]] == expected_anchors
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_flow_run_with_nonreferential_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + non-referential modifier check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + non-referential modifier compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"',
            35,
            "report.json",
            "",
            "",
            (),
        ),
        (
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() effort: high",
            35,
            "",
            "high",
            "",
            (),
        ),
        (
            "persona Expert { tone: precise }\n"
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() on_failure: log",
            35,
            "",
            "",
            "log",
            (),
        ),
        (
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() on_failure: raise AnchorBreachError",
            36,
            "",
            "",
            "raise",
            (("target", "AnchorBreachError"),),
        ),
        (
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
            44,
            "",
            "",
            "retry",
            (("backoff", "exponential"), ("attempts", "3")),
        ),
    ]

    for source, expected_token_count, expected_output_to, expected_effort, expected_on_failure, expected_params in cases:
        check_result = implementation.check_source(source, "structural_prefixed_modifier_success.axon")
        compile_result = implementation.compile_source(source, "structural_prefixed_modifier_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 5
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 5
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["output_to"] == expected_output_to
        assert ir_dict["runs"][0]["effort"] == expected_effort
        assert ir_dict["runs"][0]["on_failure"] == expected_on_failure
        assert ir_dict["runs"][0]["on_failure_params"] == expected_params
        assert ir_dict["runs"][0]["persona_name"] == ""
        assert ir_dict["runs"][0]["context_name"] == ""
        assert ir_dict["runs"][0]["anchor_names"] == ()
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_flow_run_with_singular_referential_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + singular referential modifier check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + singular referential modifier compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            34,
            "Expert",
            "",
            (),
            "Expert",
            None,
            (),
        ),
        (
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            34,
            "",
            "Review",
            (),
            None,
            "Review",
            (),
        ),
        (
            "persona Expert { tone: precise }\n"
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            36,
            "",
            "",
            ("Safety",),
            None,
            None,
            ("Safety",),
        ),
    ]

    for (
        source,
        expected_token_count,
        expected_persona_name,
        expected_context_name,
        expected_anchor_names,
        expected_resolved_persona,
        expected_resolved_context,
        expected_resolved_anchors,
    ) in cases:
        check_result = implementation.check_source(source, "structural_prefixed_referential_success.axon")
        compile_result = implementation.compile_source(source, "structural_prefixed_referential_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 5
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 5
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["persona_name"] == expected_persona_name
        assert ir_dict["runs"][0]["context_name"] == expected_context_name
        assert ir_dict["runs"][0]["anchor_names"] == expected_anchor_names
        resolved_persona = ir_dict["runs"][0]["resolved_persona"]
        resolved_context = ir_dict["runs"][0]["resolved_context"]
        resolved_anchors = ir_dict["runs"][0]["resolved_anchors"]
        assert (resolved_persona["name"] if resolved_persona else None) == expected_resolved_persona
        assert (resolved_context["name"] if resolved_context else None) == expected_resolved_context
        assert tuple(anchor["name"] for anchor in resolved_anchors) == expected_resolved_anchors
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_flow_run_with_multi_anchor_constrained_by_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + multi-anchor constrained_by check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + multi-anchor constrained_by compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { require: source_citation }\n"
        "persona Expert { tone: precise }\n"
        "anchor Grounding { require: source_citation }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety, Grounding]"
    )

    check_result = implementation.check_source(source, "structural_prefixed_multi_anchor_success.axon")
    compile_result = implementation.compile_source(source, "structural_prefixed_multi_anchor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 45
    assert check_result.declaration_count == 6
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 45
    assert compile_result.declaration_count == 6
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety", "Grounding"]
    assert ir_dict["runs"][0]["anchor_names"] == ("Safety", "Grounding")
    assert tuple(anchor["name"] for anchor in ir_dict["runs"][0]["resolved_anchors"]) == ("Safety", "Grounding")
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_flow_run_with_repeated_constrained_by_anchors_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + repeated constrained_by anchors check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed successful flow + repeated constrained_by anchors compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { require: source_citation }\n"
        "persona Expert { tone: precise }\n"
        "anchor Grounding { require: source_citation }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety, Safety, Grounding]"
    )

    check_result = implementation.check_source(source, "structural_prefixed_repeated_anchor_success.axon")
    compile_result = implementation.compile_source(source, "structural_prefixed_repeated_anchor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 47
    assert check_result.declaration_count == 6
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 47
    assert compile_result.declaration_count == 6
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety", "Grounding"]
    assert ir_dict["runs"][0]["anchor_names"] == ("Safety", "Safety", "Grounding")
    assert tuple(anchor["name"] for anchor in ir_dict["runs"][0]["resolved_anchors"]) == (
        "Safety",
        "Safety",
        "Grounding",
    )
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_success_with_output_to_or_effort_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + run modifier check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + run modifier compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"',
            35,
            "report.json",
            "",
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() effort: high",
            35,
            "",
            "high",
        ),
    ]

    for source, expected_token_count, expected_output_to, expected_effort in cases:
        check_result = implementation.check_source(source, "persona_context_anchor_prefixed_modifier_success.axon")
        compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_modifier_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 5
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 5
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["output_to"] == expected_output_to
        assert ir_dict["runs"][0]["effort"] == expected_effort
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_success_with_simple_on_failure_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + simple on_failure check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + simple on_failure compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() on_failure: log",
            35,
            "log",
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() on_failure: retry",
            35,
            "retry",
        ),
    ]

    for source, expected_token_count, expected_on_failure in cases:
        check_result = implementation.check_source(source, "persona_context_anchor_prefixed_on_failure_success.axon")
        compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_on_failure_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 5
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 5
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert ir_dict["runs"][0]["on_failure"] == expected_on_failure
        assert ir_dict["runs"][0]["on_failure_params"] == ()
        assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_success_with_raise_on_failure_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + raise on_failure check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + raise on_failure compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() on_failure: raise AnchorBreachError"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_raise_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_raise_success.axon")

    assert check_result.ok
    assert check_result.token_count == 36
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 36
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["on_failure"] == "raise"
    assert ir_dict["runs"][0]["on_failure_params"] == (("target", "AnchorBreachError"),)
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_success_with_twenty_retry_parameters_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + twenty retry params check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for exact persona+context+anchor-prefixed successful flow + twenty retry params compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, mode: cautious, priority: high, budget: strict, window: narrow, channel: audit, lane: safe, trace: verbose, guard: strict, batch: full, scope: narrow, review: staged, cadence: nightly, quorum: strict, ledger: complete, route: deterministic, mirror: enabled, limit: hard, gate: closed)"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_retry_twenty_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_retry_twenty_success.axon")

    assert check_result.ok
    assert check_result.token_count == 116
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 116
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["on_failure"] == "retry"
    assert ir_dict["runs"][0]["on_failure_params"] == (("backoff", "exponential"), ("attempts", "3"), ("mode", "cautious"), ("priority", "high"), ("budget", "strict"), ("window", "narrow"), ("channel", "audit"), ("lane", "safe"), ("trace", "verbose"), ("guard", "strict"), ("batch", "full"), ("scope", "narrow"), ("review", "staged"), ("cadence", "nightly"), ("quorum", "strict"), ("ledger", "complete"), ("route", "deterministic"), ("mirror", "enabled"), ("limit", "hard"), ("gate", "closed"))
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_as_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact prefixed as success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact prefixed as success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() as Expert"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_as_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_as_success.axon")

    assert check_result.ok
    assert check_result.token_count == 34
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 34
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["persona_name"] == "Expert"
    assert ir_dict["runs"][0]["resolved_persona"]["name"] == "Expert"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_within_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact prefixed within success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact prefixed within success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_within_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_within_success.axon")

    assert check_result.ok
    assert check_result.token_count == 34
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 34
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["context_name"] == "Review"
    assert ir_dict["runs"][0]["resolved_context"]["name"] == "Review"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_persona_context_anchor_prefixed_flow_run_constrained_by_single_anchor_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for exact prefixed constrained_by success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for exact prefixed constrained_by success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "persona_context_anchor_prefixed_constrained_success.axon")
    compile_result = implementation.compile_source(source, "persona_context_anchor_prefixed_constrained_success.axon")

    assert check_result.ok
    assert check_result.token_count == 36
    assert check_result.declaration_count == 5
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 36
    assert compile_result.declaration_count == 5
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert ir_dict["runs"][0]["anchor_names"] == ("Safety",)
    assert len(ir_dict["runs"][0]["resolved_anchors"]) == 1
    assert ir_dict["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_keeps_prefixed_success_cases_outside_exact_subset_on_python_delegate() -> None:
    class RecordingPythonDelegate:
        def __init__(self) -> None:
            self.check_calls: list[tuple[str, str]] = []
            self.compile_calls: list[tuple[str, str]] = []

        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            self.check_calls.append((source, filename))
            return PythonFrontendImplementation().check_source(source, filename)

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            self.compile_calls.append((source, filename))
            return PythonFrontendImplementation().compile_source(source, filename)

    cases = [
        (
            "persona Expert { tone: precise }\npersona Guide { tone: formal }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            1,
        ),
        (
            "memory SessionStore { backend: local }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { provider: brave }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { runtime: hosted }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { filter: recent }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { max_results: 3 }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { effects: <network, epistemic:know> }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { ask: \"Who signed?\" }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { ask: \"Who signed?\" given: Document }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { ask: \"Who signed?\" confidence_floor: 0.9 }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "axonendpoint Api { method: post path: \"/x\" execute: SimpleFlow }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "tool Search { filter: recent(days: 30) }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { ask: \"Who signed?\" output: Party }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { ask: \"Who signed?\" output: Party confidence_floor: 0.9 }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { given: Document ask: \"Who signed?\" output: Party }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { given: Document ask: \"Who signed?\" output: Party confidence_floor: 0.9 }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "axonendpoint Api { method: post path: \"/x\" execute: SimpleFlow output: Party }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "shield Safety { }\naxonendpoint Api { method: post path: \"/x\" execute: SimpleFlow shield: Safety }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Grounding { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            True,
            (),
            0,
        ),
        (
            "intent Extract { given: Document }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            False,
            ("Intent 'Extract' is missing required 'ask' field — every intent must express a question",),
            1,
        ),
        (
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Grounding]",
            False,
            (
                "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
                "Undefined anchor 'Grounding'",
            ),
            1,
        ),
        (
            "flow OtherFlow() {}\nrun SimpleFlow()",
            False,
            ("Undefined flow 'SimpleFlow' in run statement",),
            1,
        ),
        (
            "anchor Safety { require: source_citation }\nflow OtherFlow() {}\nrun SimpleFlow()",
            False,
            ("Undefined flow 'SimpleFlow' in run statement",),
            1,
        ),
    ]

    for index, (source, expected_ok, expected_messages, expected_delegate_calls) in enumerate(cases, start=1):
        delegate = RecordingPythonDelegate()
        implementation = NativeDevelopmentFrontendImplementation(delegate=delegate)

        check_result = implementation.check_source(source, f"flow_prefixed_run_{index}.axon")
        compile_result = implementation.compile_source(source, f"flow_prefixed_run_{index}.axon")

        assert check_result.ok is expected_ok
        assert len(delegate.check_calls) == expected_delegate_calls
        assert compile_result.ok is expected_ok
        assert len(delegate.compile_calls) == expected_delegate_calls
        if expected_ok:
            assert compile_result.ir_program is not None
        else:
            check_messages = [d.message for d in check_result.diagnostics]
            compile_messages = [d.message for d in compile_result.diagnostics]
            for expected_message in expected_messages:
                assert expected_message in check_messages
                assert expected_message in compile_messages


def test_native_dev_handles_structured_type_compile_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev structured type check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev structured type compile")

    source = (
        "type RiskScore(0.0..1.0)\n"
        "type Risk {\n"
        "  score: RiskScore,\n"
        "  mitigation: Opinion?\n"
        "}"
    )
    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    result = implementation.compile_source(source, "type_struct.axon")

    assert result.ok
    assert result.ir_program is not None
    ir_dict = serialize_ir_program(result.ir_program)
    assert len(ir_dict["types"]) == 2
    assert ir_dict["types"][0]["name"] == "RiskScore"
    assert abs(ir_dict["types"][0]["range_min"] - 0.0) < 1e-9
    assert abs(ir_dict["types"][0]["range_max"] - 1.0) < 1e-9
    assert ir_dict["types"][1]["name"] == "Risk"
    assert ir_dict["types"][1]["fields"][1]["name"] == "mitigation"
    assert ir_dict["types"][1]["fields"][1]["optional"] is True


def test_native_dev_handles_where_type_compile_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev where type check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev where type compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "type HighConfidenceClaim where confidence >= 0.85",
            None,
            None,
            "confidence >= 0.85",
            0,
        ),
        (
            "type HighConfidenceClaim(0.0..1.0) where confidence >= 0.85",
            0.0,
            1.0,
            "confidence >= 0.85",
            0,
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85 { claim: FactualClaim }",
            None,
            None,
            "confidence >= 0.85",
            1,
        ),
    ]

    for source, expected_min, expected_max, expected_where, expected_field_count in cases:
        result = implementation.compile_source(source, "type_where.axon")

        assert result.ok
        assert result.ir_program is not None
        ir_dict = serialize_ir_program(result.ir_program)
        type_def = ir_dict["types"][0]
        assert type_def["where_expression"] == expected_where
        assert type_def["range_min"] == expected_min
        assert type_def["range_max"] == expected_max
        assert len(type_def["fields"]) == expected_field_count


def test_native_dev_handles_mixed_type_flow_run_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for mixed type + flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for mixed type + flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "type_flow_run.axon")
    compile_result = implementation.compile_source(source, "type_flow_run.axon")

    assert check_result.ok
    assert check_result.token_count > 0
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count > 0
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["RiskScore"]
    assert abs(ir_dict["types"][0]["range_min"] - 0.0) < 1e-9
    assert abs(ir_dict["types"][0]["range_max"] - 1.0) < 1e-9
    assert [flow["name"] for flow in ir_dict["flows"]] == ["SimpleFlow"]
    assert [run["flow_name"] for run in ir_dict["runs"]] == ["SimpleFlow"]


def test_native_dev_handles_mixed_type_flow_run_with_output_to_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for mixed type + flow + run modifier check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for mixed type + flow + run modifier compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "type Risk {\n"
        "  score: RiskScore,\n"
        "  mitigation: Opinion?\n"
        "}\n"
        "flow SimpleFlow() {}\n"
        'run SimpleFlow() output_to: "report.json"'
    )

    check_result = implementation.check_source(source, "type_flow_run_output.axon")
    compile_result = implementation.compile_source(source, "type_flow_run_output.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["RiskScore", "Risk"]
    assert ir_dict["runs"][0]["output_to"] == "report.json"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_mixed_type_where_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for mixed type + where + flow + run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for mixed type + where + flow + run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type HighConfidenceClaim(0.0..1.0) where confidence >= 0.85\n"
        "flow SimpleFlow() {}\n"
        'run SimpleFlow() output_to: "report.json"'
    )

    check_result = implementation.check_source(source, "type_where_flow_run.axon")
    compile_result = implementation.compile_source(source, "type_where_flow_run.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["HighConfidenceClaim"]
    assert abs(ir_dict["types"][0]["range_min"] - 0.0) < 1e-9
    assert abs(ir_dict["types"][0]["range_max"] - 1.0) < 1e-9
    assert ir_dict["types"][0]["where_expression"] == "confidence >= 0.85"
    assert [flow["name"] for flow in ir_dict["flows"]] == ["SimpleFlow"]
    assert [run["flow_name"] for run in ir_dict["runs"]] == ["SimpleFlow"]
    assert ir_dict["runs"][0]["output_to"] == "report.json"


def test_native_dev_handles_type_with_persona_context_anchor_prefixed_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for type + prefixed success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for type + prefixed success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "anchor Safety { require: source_citation }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "type_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "type_prefixed_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 6
    assert compile_result.ok
    assert compile_result.declaration_count == 6
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["RiskScore"]
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert [flow["name"] for flow in ir_dict["flows"]] == ["SimpleFlow"]
    assert [run["flow_name"] for run in ir_dict["runs"]] == ["SimpleFlow"]


def test_native_dev_handles_type_with_structural_prefixed_success_and_output_to_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for structural type + prefixed success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for structural type + prefixed success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "type Risk {\n"
        "  score: RiskScore,\n"
        "  mitigation: Opinion?\n"
        "}\n"
        "anchor Safety { require: source_citation }\n"
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        'run SimpleFlow() output_to: "report.json"'
    )

    check_result = implementation.check_source(source, "type_structural_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "type_structural_prefixed_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 7
    assert compile_result.ok
    assert compile_result.declaration_count == 7
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["RiskScore", "Risk"]
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert ir_dict["runs"][0]["output_to"] == "report.json"
    assert ir_dict["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"


def test_native_dev_handles_type_where_with_structural_prefixed_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for structural type + where + prefixed success check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for structural type + where + prefixed success compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type HighConfidenceClaim where confidence >= 0.85\n"
        "anchor Safety { require: source_citation }\n"
        "persona Expert { tone: precise }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        'run SimpleFlow() output_to: "report.json"'
    )

    check_result = implementation.check_source(source, "type_where_prefixed_success.axon")
    compile_result = implementation.compile_source(source, "type_where_prefixed_success.axon")

    assert check_result.ok
    assert check_result.token_count == 41
    assert check_result.declaration_count == 6
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 41
    assert compile_result.declaration_count == 6
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert [type_def["name"] for type_def in ir_dict["types"]] == ["HighConfidenceClaim"]
    assert ir_dict["types"][0]["where_expression"] == "confidence >= 0.85"
    assert [persona["name"] for persona in ir_dict["personas"]] == ["Expert"]
    assert [context["name"] for context in ir_dict["contexts"]] == ["Review"]
    assert [anchor["name"] for anchor in ir_dict["anchors"]] == ["Safety"]
    assert [flow["name"] for flow in ir_dict["flows"]] == ["SimpleFlow"]
    assert [run["flow_name"] for run in ir_dict["runs"]] == ["SimpleFlow"]
    assert ir_dict["runs"][0]["output_to"] == "report.json"


def test_native_dev_handles_type_with_structural_prefixed_validation_and_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for type + structural prefixed validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for type + structural prefixed validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "context Review { memory: invalid }\n"
        "run Missing() within Review"
    )

    check_result = implementation.check_source(source, "type_structural_validation.axon")
    compile_result = implementation.compile_source(source, "type_structural_validation.axon")
    expected_messages = [
        "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_type_where_with_structural_prefixed_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for type + where + structural prefixed validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for type + where + structural prefixed validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type HighConfidenceClaim where confidence >= 0.85\n"
        "context Review { memory: invalid }\n"
        "run Missing() within Review"
    )

    check_result = implementation.check_source(source, "type_where_structural_validation.axon")
    compile_result = implementation.compile_source(source, "type_where_structural_validation.axon")
    expected_messages = [
        "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_type_with_structural_prefixed_duplicate_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for type + structural prefixed duplicate check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for type + structural prefixed duplicate compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type RiskScore(0.0..1.0)\n"
        "anchor Safety { require: source_citation }\n"
        "context Review { memory: session }\n"
        "persona Expert { tone: precise }\n"
        "context Review { memory: persistent }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "type_structural_duplicate.axon")
    compile_result = implementation.compile_source(source, "type_structural_duplicate.axon")
    expected_messages = [
        "Duplicate declaration: 'Review' already defined as context (first defined at line 3)"
    ]

    assert not check_result.ok
    assert check_result.token_count == 48
    assert check_result.declaration_count == 7
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 48
    assert compile_result.declaration_count == 7
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_type_where_with_structural_prefixed_duplicate_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for type + where + structural prefixed duplicate check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for type + where + structural prefixed duplicate compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "type HighConfidenceClaim where confidence >= 0.85\n"
        "anchor Safety { require: source_citation }\n"
        "context Review { memory: session }\n"
        "persona Expert { tone: precise }\n"
        "context Review { memory: persistent }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "type_where_structural_duplicate.axon")
    compile_result = implementation.compile_source(source, "type_where_structural_duplicate.axon")
    expected_messages = [
        "Duplicate declaration: 'Review' already defined as context (first defined at line 3)"
    ]

    assert not check_result.ok
    assert check_result.token_count == 45
    assert check_result.declaration_count == 7
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 45
    assert compile_result.declaration_count == 7
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_type_with_isolated_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for type + isolated run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for type + isolated run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("type RiskScore(0.0..1.0)\nrun Missing()", 12),
        ('type RiskScore(0.0..1.0)\nrun Missing() output_to: "report.json"', 15),
        (
            "type RiskScore(0.0..1.0)\nrun Missing() on_failure: retry(backoff: exponential, attempts: 3)",
            24,
        ),
    ]

    for source, expected_token_count in cases:
        check_result = implementation.check_source(source, "type_run_missing.axon")
        compile_result = implementation.compile_source(source, "type_run_missing.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 2
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 2
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]
        assert compile_result.ir_program is None


def test_native_dev_handles_type_where_with_isolated_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for type + where + isolated run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for type + where + isolated run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        ("type HighConfidenceClaim where confidence >= 0.85\nrun Missing()", 11),
        (
            'type HighConfidenceClaim where confidence >= 0.85\nrun Missing() output_to: "report.json"',
            14,
        ),
    ]

    for source, expected_token_count in cases:
        check_result = implementation.check_source(source, "type_where_run_missing.axon")
        compile_result = implementation.compile_source(source, "type_where_run_missing.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 2
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 2
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]
        assert compile_result.ir_program is None


def test_native_dev_handles_type_with_clean_prefixed_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for type + clean prefixed run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for type + clean prefixed run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "type RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() as Expert",
            21,
            3,
        ),
        (
            "type RiskScore(0.0..1.0)\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun Missing() constrained_by [Safety]",
            30,
            4,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "type_prefixed_run_missing.axon")
        compile_result = implementation.compile_source(source, "type_prefixed_run_missing.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]
        assert compile_result.ir_program is None


def test_native_dev_handles_type_where_with_clean_prefixed_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for type + where + clean prefixed run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for type + where + clean prefixed run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "type HighConfidenceClaim where confidence >= 0.85\npersona Expert { tone: precise }\nrun Missing() as Expert",
            20,
            3,
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun Missing() constrained_by [Safety]",
            29,
            4,
        ),
    ]

    for source, expected_token_count, expected_declaration_count in cases:
        check_result = implementation.check_source(source, "type_where_prefixed_run_missing.axon")
        compile_result = implementation.compile_source(source, "type_where_prefixed_run_missing.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
            "Undefined flow 'Missing' in run statement"
        ]
        assert compile_result.ir_program is None


def test_native_dev_handles_duplicate_type_declarations_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for duplicate type declarations check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for duplicate type declarations compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)",
            15,
            2,
            ["Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)"],
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "type HighConfidenceClaim where confidence >= 0.90",
            13,
            2,
            [
                "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)"
            ],
        ),
        (
            "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\nflow SimpleFlow() {}\nrun SimpleFlow()",
            25,
            4,
            ["Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)"],
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "type HighConfidenceClaim where confidence >= 0.90\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()",
            23,
            4,
            [
                "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)"
            ],
        ),
        (
            "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\nrun Missing()",
            19,
            3,
            [
                "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "type HighConfidenceClaim where confidence >= 0.90\n"
            "run Missing()",
            17,
            3,
            [
                "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
        (
            "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() as Expert",
            28,
            4,
            [
                "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
        (
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "type HighConfidenceClaim where confidence >= 0.90\n"
            "persona Expert { tone: precise }\n"
            "run Missing() as Expert",
            26,
            4,
            [
                "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_type.axon")
        compile_result = implementation.compile_source(source, "duplicate_type.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_declaration_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate anchor declaration check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate anchor declaration compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { require: source_citation }\n"
        "persona Expert { tone: precise }\n"
        "anchor Safety { require: source_citation }\n"
        "context Review { memory: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "duplicate_anchor_structural_full.axon")
    compile_result = implementation.compile_source(source, "duplicate_anchor_structural_full.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 6
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
    ]

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 6
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
    ]
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_or_context_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate persona/context check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate persona/context compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: formal }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            41,
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
        ),
        (
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: persistent }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            41,
            "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
        ),
    ]

    for source, expected_token_count, expected_message in cases:
        check_result = implementation.check_source(source, "duplicate_singleton_structural.axon")
        compile_result = implementation.compile_source(source, "duplicate_singleton_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == 6
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == [expected_message]

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == 6
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [expected_message]
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_multiple_clean_duplicates_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed multiple duplicate declarations check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed multiple duplicate declarations compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: formal }\n"
            "context Review { memory: persistent }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()",
            46,
            7,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
            ],
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: formal }\n"
            "context Review { memory: persistent }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()",
            53,
            8,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 3)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "multiple_duplicate_structural.axon")
        compile_result = implementation.compile_source(source, "multiple_duplicate_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_nonclean_duplicate_context_combinations_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed non-clean duplicate combinations check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed non-clean duplicate combinations compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { memory: invalid }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
        (
            "context Review { memory: invalid }\n"
            "context Review { memory: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
        (
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: archive }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            41,
            6,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                "Unknown memory scope 'archive' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: invalid }\n"
            "persona Expert { tone: formal }\n"
            "context Review { memory: invalid }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()",
            46,
            7,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "nonclean_duplicate_structural.axon")
        compile_result = implementation.compile_source(source, "nonclean_duplicate_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_context_memory_without_duplicates_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context memory check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context memory compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { memory: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            [
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: invalid }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            34,
            5,
            [
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "invalid_context_structural.axon")
        compile_result = implementation.compile_source(source, "invalid_context_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_context_memory_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context memory + undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context memory + undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { memory: invalid }\n"
            "run SimpleFlow() within Review",
            14,
            2,
            [
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Undefined flow 'SimpleFlow' in run statement",
            ],
        ),
        (
            "persona Expert { tone: precise }\n"
            "context Review { memory: invalid }\n"
            "anchor Safety { require: source_citation }\n"
            "run SimpleFlow() within Review",
            28,
            4,
            [
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Undefined flow 'SimpleFlow' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "invalid_context_prefixed_run.axon")
        compile_result = implementation.compile_source(source, "invalid_context_prefixed_run.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_context_depth_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed context depth success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed context depth success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { depth: deep }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "context_depth_success.axon")
    compile_result = implementation.compile_source(source, "context_depth_success.axon")

    assert check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert len(compile_result.ir_program.contexts) == 1
    context = compile_result.ir_program.contexts[0]
    run = compile_result.ir_program.runs[0]
    assert context.name == "Review"
    assert context.memory_scope == ""
    assert context.depth == "deep"
    assert run.context_name == "Review"
    assert run.resolved_context == context


def test_native_dev_handles_structural_prefixed_anchor_enforce_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed anchor enforce success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed anchor enforce success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { enforce: strict }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "anchor_enforce_success.axon")
    compile_result = implementation.compile_source(source, "anchor_enforce_success.axon")

    assert check_result.ok
    assert check_result.token_count == 22
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 22
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert len(compile_result.ir_program.anchors) == 1
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.require == ""
    assert anchor.enforce == "strict"
    assert run.anchor_names == ("Safety",)
    assert tuple(resolved.name for resolved in run.resolved_anchors) == ("Safety",)


def test_native_dev_handles_structural_prefixed_persona_context_cite_sources_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed cite_sources success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed cite_sources success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { cite_sources: true }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            20,
            3,
            "persona",
        ),
        (
            "context Review { cite_sources: true }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            "context",
        ),
    ]

    for source, expected_token_count, expected_declaration_count, kind in cases:
        check_result = implementation.check_source(source, "cite_sources_success.axon")
        compile_result = implementation.compile_source(source, "cite_sources_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        if kind == "persona":
            persona = compile_result.ir_program.personas[0]
            run = compile_result.ir_program.runs[0]
            assert persona.name == "Expert"
            assert persona.cite_sources is True
            assert run.persona_name == "Expert"
            assert run.resolved_persona == persona
        else:
            context = compile_result.ir_program.contexts[0]
            run = compile_result.ir_program.runs[0]
            assert context.name == "Review"
            assert context.cite_sources is True
            assert run.context_name == "Review"
            assert run.resolved_context == context


def test_native_dev_handles_structural_prefixed_persona_context_language_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed language success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed language success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { language: \"es\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            20,
            3,
            "persona",
        ),
        (
            "context Review { language: \"es\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            "context",
        ),
    ]

    for source, expected_token_count, expected_declaration_count, kind in cases:
        check_result = implementation.check_source(source, "language_success.axon")
        compile_result = implementation.compile_source(source, "language_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        if kind == "persona":
            persona = compile_result.ir_program.personas[0]
            run = compile_result.ir_program.runs[0]
            assert persona.name == "Expert"
            assert persona.language == "es"
            assert run.persona_name == "Expert"
            assert run.resolved_persona == persona
        else:
            context = compile_result.ir_program.contexts[0]
            run = compile_result.ir_program.runs[0]
            assert context.name == "Review"
            assert context.language == "es"
            assert run.context_name == "Review"
            assert run.resolved_context == context


def test_native_dev_handles_structural_prefixed_duplicate_persona_context_with_language_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate language check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate language compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { language: \"es\" }\n"
            "persona Expert { language: \"en\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
            ],
        ),
        (
            "context Review { language: \"es\" }\n"
            "context Review { language: \"en\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_language.axon")
        compile_result = implementation.compile_source(source, "duplicate_language.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_persona_anchor_description_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed description success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed description success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { description: \"Analista\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            20,
            3,
            "persona",
        ),
        (
            "anchor Safety { description: \"No hallucinate\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            22,
            3,
            "anchor",
        ),
    ]

    for source, expected_token_count, expected_declaration_count, kind in cases:
        check_result = implementation.check_source(source, "description_success.axon")
        compile_result = implementation.compile_source(source, "description_success.axon")

        assert check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        if kind == "persona":
            persona = compile_result.ir_program.personas[0]
            run = compile_result.ir_program.runs[0]
            assert persona.name == "Expert"
            assert persona.description == "Analista"
            assert run.persona_name == "Expert"
            assert run.resolved_persona == persona
        else:
            anchor = compile_result.ir_program.anchors[0]
            run = compile_result.ir_program.runs[0]
            assert anchor.name == "Safety"
            assert anchor.description == "No hallucinate"
            assert run.anchor_names == ("Safety",)
            assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_duplicate_persona_anchor_with_description_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate description check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate description compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { description: \"Analista\" }\n"
            "persona Expert { description: \"Otro\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
            ],
        ),
        (
            "anchor Safety { description: \"A\" }\n"
            "anchor Safety { description: \"B\" }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            29,
            4,
            [
                "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_description.axon")
        compile_result = implementation.compile_source(source, "duplicate_description.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_unknown_response_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed unknown_response success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed unknown_response success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { unknown_response: \"No se\" }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "unknown_response_success.axon")
    compile_result = implementation.compile_source(source, "unknown_response_success.axon")

    assert check_result.ok
    assert check_result.token_count == 22
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 22
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.unknown_response == "No se"
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_context_max_tokens_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed max_tokens success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed max_tokens success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { max_tokens: 256 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "max_tokens_success.axon")
    compile_result = implementation.compile_source(source, "max_tokens_success.axon")

    assert check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    context = compile_result.ir_program.contexts[0]
    run = compile_result.ir_program.runs[0]
    assert context.name == "Review"
    assert context.max_tokens == 256
    assert run.context_name == "Review"
    assert run.resolved_context == context


def test_native_dev_handles_structural_prefixed_context_max_tokens_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed max_tokens validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed max_tokens validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { max_tokens: 0 }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            ["max_tokens must be positive, got 0 in context 'Review'"],
        ),
        (
            "context Review { max_tokens: 0 }\n"
            "run Missing() within Review",
            14,
            2,
            [
                "max_tokens must be positive, got 0 in context 'Review'",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "max_tokens_validation.axon")
        compile_result = implementation.compile_source(source, "max_tokens_validation.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_context_temperature_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed temperature success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed temperature success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { temperature: 1.2 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "temperature_success.axon")
    compile_result = implementation.compile_source(source, "temperature_success.axon")

    assert check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    context = compile_result.ir_program.contexts[0]
    run = compile_result.ir_program.runs[0]
    assert context.name == "Review"
    assert context.temperature == 1.2
    assert run.context_name == "Review"
    assert run.resolved_context == context


def test_native_dev_handles_structural_prefixed_context_temperature_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed temperature validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed temperature validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { temperature: 2.5 }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            ["temperature must be between 0.0 and 2.0, got 2.5"],
        ),
        (
            "context Review { temperature: 2.5 }\n"
            "run Missing() within Review",
            14,
            2,
            [
                "temperature must be between 0.0 and 2.0, got 2.5",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "temperature_validation.axon")
        compile_result = implementation.compile_source(source, "temperature_validation.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_context_with_temperature_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate temperature check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate temperature compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { temperature: 2.5 }\n"
        "context Review { temperature: 1.2 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "duplicate_temperature.axon")
    compile_result = implementation.compile_source(source, "duplicate_temperature.axon")
    expected_messages = [
        "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
        "temperature must be between 0.0 and 2.0, got 2.5",
    ]

    assert not check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_persona_confidence_threshold_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_threshold success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_threshold success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { confidence_threshold: 0.8 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() as Expert"
    )

    check_result = implementation.check_source(source, "confidence_threshold_success.axon")
    compile_result = implementation.compile_source(source, "confidence_threshold_success.axon")

    assert check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    persona = compile_result.ir_program.personas[0]
    run = compile_result.ir_program.runs[0]
    assert persona.name == "Expert"
    assert persona.confidence_threshold == 0.8
    assert run.persona_name == "Expert"
    assert run.resolved_persona == persona


def test_native_dev_handles_structural_prefixed_persona_confidence_threshold_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_threshold validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_threshold validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { confidence_threshold: 1.5 }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            20,
            3,
            ["confidence_threshold must be between 0.0 and 1.0, got 1.5"],
        ),
        (
            "persona Expert { confidence_threshold: 1.5 }\n"
            "run Missing() as Expert",
            14,
            2,
            [
                "confidence_threshold must be between 0.0 and 1.0, got 1.5",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "confidence_threshold_validation.axon")
        compile_result = implementation.compile_source(source, "confidence_threshold_validation.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_with_confidence_threshold_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate confidence_threshold check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate confidence_threshold compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { confidence_threshold: 1.5 }\n"
        "persona Expert { confidence_threshold: 0.8 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() as Expert"
    )

    check_result = implementation.check_source(source, "duplicate_confidence_threshold.axon")
    compile_result = implementation.compile_source(source, "duplicate_confidence_threshold.axon")
    expected_messages = [
        "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
        "confidence_threshold must be between 0.0 and 1.0, got 1.5",
    ]

    assert not check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_confidence_floor_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_floor success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_floor success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { confidence_floor: 0.8 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "confidence_floor_success.axon")
    compile_result = implementation.compile_source(source, "confidence_floor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 22
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 22
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.confidence_floor == 0.8
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_anchor_confidence_floor_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_floor validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed confidence_floor validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { confidence_floor: 1.5 }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            22,
            3,
            ["confidence_floor must be between 0.0 and 1.0, got 1.5"],
        ),
        (
            "anchor Safety { confidence_floor: 1.5 }\n"
            "run Missing() constrained_by [Safety]",
            16,
            2,
            [
                "confidence_floor must be between 0.0 and 1.0, got 1.5",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "confidence_floor_validation.axon")
        compile_result = implementation.compile_source(source, "confidence_floor_validation.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_confidence_floor_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate confidence_floor check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate confidence_floor compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { confidence_floor: 1.5 }\n"
        "anchor Safety { confidence_floor: 0.8 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "duplicate_confidence_floor.axon")
    compile_result = implementation.compile_source(source, "duplicate_confidence_floor.axon")
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
    ]

    assert not check_result.ok
    assert check_result.token_count == 29
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 29
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_on_violation_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: warn }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "on_violation_success.axon")
    compile_result = implementation.compile_source(source, "on_violation_success.axon")

    assert check_result.ok
    assert check_result.token_count == 22
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 22
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.on_violation == "warn"
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_anchor_on_violation_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { on_violation: explode }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            22,
            3,
            [
                "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
            ],
        ),
        (
            "anchor Safety { on_violation: explode }\n"
            "run Missing() constrained_by [Safety]",
            16,
            2,
            [
                "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn",
                "Undefined flow 'Missing' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "on_violation_validation.axon")
        compile_result = implementation.compile_source(source, "on_violation_validation.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_on_violation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: explode }\n"
        "anchor Safety { on_violation: warn }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "duplicate_on_violation.axon")
    compile_result = implementation.compile_source(source, "duplicate_on_violation.axon")
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
        "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn",
    ]

    assert not check_result.ok
    assert check_result.token_count == 29
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 29
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_on_violation_raise_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation raise success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation raise success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: raise AnchorBreachError }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "on_violation_raise_success.axon")
    compile_result = implementation.compile_source(source, "on_violation_raise_success.axon")

    assert check_result.ok
    assert check_result.token_count == 23
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 23
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.on_violation == "raise"
    assert anchor.on_violation_target == "AnchorBreachError"
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_anchor_on_violation_raise_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation raise undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation raise undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: raise AnchorBreachError }\n"
        "run Missing() constrained_by [Safety]"
    )
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "on_violation_raise_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "on_violation_raise_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 17
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 17
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_on_violation_raise_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation raise check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation raise compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: raise AnchorBreachError }\n"
        "anchor Safety { on_violation: explode }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
        "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn",
    ]

    check_result = implementation.check_source(source, "duplicate_on_violation_raise.axon")
    compile_result = implementation.compile_source(source, "duplicate_on_violation_raise.axon")

    assert not check_result.ok
    assert check_result.token_count == 30
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 30
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_on_violation_fallback_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation fallback success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation fallback success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: fallback(\"No se\") }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "on_violation_fallback_success.axon")
    compile_result = implementation.compile_source(source, "on_violation_fallback_success.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.on_violation == "fallback"
    assert anchor.on_violation_target == "No se"
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_anchor_on_violation_fallback_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation fallback undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed on_violation fallback undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: fallback(\"No se\") }\n"
        "run Missing() constrained_by [Safety]"
    )
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "on_violation_fallback_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "on_violation_fallback_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 19
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 19
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_on_violation_fallback_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation fallback check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate on_violation fallback compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { on_violation: fallback(\"No se\") }\n"
        "anchor Safety { on_violation: explode }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
        "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn",
    ]

    check_result = implementation.check_source(source, "duplicate_on_violation_fallback.axon")
    compile_result = implementation.compile_source(source, "duplicate_on_violation_fallback.axon")

    assert not check_result.ok
    assert check_result.token_count == 32
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 32
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_anchor_reject_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed reject success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed reject success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { reject: [speculation, hallucination] }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "anchor_reject_success.axon")
    compile_result = implementation.compile_source(source, "anchor_reject_success.axon")

    assert check_result.ok
    assert check_result.token_count == 26
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 26
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    anchor = compile_result.ir_program.anchors[0]
    run = compile_result.ir_program.runs[0]
    assert anchor.name == "Safety"
    assert anchor.reject == ("speculation", "hallucination")
    assert run.anchor_names == ("Safety",)
    assert run.resolved_anchors == (anchor,)


def test_native_dev_handles_structural_prefixed_anchor_reject_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed reject undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed reject undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { reject: [speculation, hallucination] }\n"
        "run Missing() constrained_by [Safety]"
    )
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "anchor_reject_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "anchor_reject_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_reject_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate reject check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate reject compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { reject: [speculation, hallucination] }\n"
        "anchor Safety { reject: [hallucination] }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_anchor_reject.axon")
    compile_result = implementation.compile_source(source, "duplicate_anchor_reject.axon")

    assert not check_result.ok
    assert check_result.token_count == 35
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 35
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_persona_refuse_if_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed refuse_if success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed refuse_if success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { refuse_if: [speculation, hallucination] }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() as Expert"
    )

    check_result = implementation.check_source(source, "persona_refuse_if_success.axon")
    compile_result = implementation.compile_source(source, "persona_refuse_if_success.axon")

    assert check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    persona = compile_result.ir_program.personas[0]
    run = compile_result.ir_program.runs[0]
    assert persona.name == "Expert"
    assert persona.refuse_if == ("speculation", "hallucination")
    assert run.persona_name == "Expert"
    assert run.resolved_persona == persona


def test_native_dev_handles_structural_prefixed_persona_refuse_if_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed refuse_if undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed refuse_if undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { refuse_if: [speculation, hallucination] }\n"
        "run Missing() as Expert"
    )
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "persona_refuse_if_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "persona_refuse_if_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_with_refuse_if_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate refuse_if check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate refuse_if compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "persona Expert { refuse_if: [speculation, hallucination] }\n"
        "persona Expert { refuse_if: [hallucination] }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() as Expert"
    )
    expected_messages = [
        "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_persona_refuse_if.axon")
    compile_result = implementation.compile_source(source, "duplicate_persona_refuse_if.axon")

    assert not check_result.ok
    assert check_result.token_count == 33
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 33
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_persona_domain_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed domain success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed domain success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'persona Expert { domain: ["science", "safety"] }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow() as Expert'
    )

    check_result = implementation.check_source(source, "persona_domain_success.axon")
    compile_result = implementation.compile_source(source, "persona_domain_success.axon")

    assert check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    persona = compile_result.ir_program.personas[0]
    run = compile_result.ir_program.runs[0]
    assert persona.name == "Expert"
    assert persona.domain == ("science", "safety")
    assert run.persona_name == "Expert"
    assert run.resolved_persona == persona


def test_native_dev_handles_structural_prefixed_persona_domain_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed domain undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed domain undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'persona Expert { domain: ["science", "safety"] }\nrun Missing() as Expert'
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "persona_domain_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "persona_domain_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_with_domain_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate domain check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate domain compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'persona Expert { domain: ["science", "safety"] }\n'
        'persona Expert { domain: ["policy"] }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow() as Expert'
    )
    expected_messages = [
        "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_persona_domain.axon")
    compile_result = implementation.compile_source(source, "duplicate_persona_domain.axon")

    assert not check_result.ok
    assert check_result.token_count == 33
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 33
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_memory_store_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.store success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.store success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { store: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "memory_store_success.axon")
    compile_result = implementation.compile_source(source, "memory_store_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    memory = compile_result.ir_program.memories[0]
    assert memory.name == "SessionMemory"
    assert memory.store == "session"


def test_native_dev_handles_structural_prefixed_invalid_memory_store_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.store check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.store compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { store: remote }\nflow SimpleFlow() {}\nrun SimpleFlow()"
    expected_messages = [
        "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session",
    ]

    check_result = implementation.check_source(source, "memory_store_invalid.axon")
    compile_result = implementation.compile_source(source, "memory_store_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_memory_store_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.store + undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.store + undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { store: remote }\nrun Missing()"
    expected_messages = [
        "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "memory_store_invalid_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "memory_store_invalid_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 12
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 12
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_memory_with_invalid_store_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.store check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.store compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { store: remote }\n"
        "memory SessionMemory { store: session }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)",
        "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session",
    ]

    check_result = implementation.check_source(source, "duplicate_memory_store.axon")
    compile_result = implementation.compile_source(source, "duplicate_memory_store.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_memory_backend_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.backend success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.backend success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { backend: redis }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "memory_backend_success.axon")
    compile_result = implementation.compile_source(source, "memory_backend_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    memory = compile_result.ir_program.memories[0]
    assert memory.name == "SessionMemory"
    assert memory.backend == "redis"


def test_native_dev_handles_structural_prefixed_memory_backend_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.backend undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.backend undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { backend: redis }\nrun Missing()"
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "memory_backend_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "memory_backend_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 12
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 12
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_memory_with_backend_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.backend check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.backend compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { backend: redis }\n"
        "memory SessionMemory { backend: in_memory }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_memory_backend.axon")
    compile_result = implementation.compile_source(source, "duplicate_memory_backend.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_memory_retrieval_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.retrieval success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.retrieval success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { retrieval: semantic }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "memory_retrieval_success.axon")
    compile_result = implementation.compile_source(source, "memory_retrieval_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    memory = compile_result.ir_program.memories[0]
    assert memory.name == "SessionMemory"
    assert memory.retrieval == "semantic"


def test_native_dev_handles_structural_prefixed_invalid_memory_retrieval_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.retrieval check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.retrieval compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { retrieval: vector }\nflow SimpleFlow() {}\nrun SimpleFlow()"
    expected_messages = [
        "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic",
    ]

    check_result = implementation.check_source(source, "memory_retrieval_invalid.axon")
    compile_result = implementation.compile_source(source, "memory_retrieval_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_memory_retrieval_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.retrieval + undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid memory.retrieval + undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { retrieval: vector }\nrun Missing()"
    expected_messages = [
        "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "memory_retrieval_invalid_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "memory_retrieval_invalid_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 12
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 12
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_memory_with_invalid_retrieval_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.retrieval check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.retrieval compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { retrieval: vector }\n"
        "memory SessionMemory { retrieval: semantic }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)",
        "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic",
    ]

    check_result = implementation.check_source(source, "duplicate_memory_retrieval.axon")
    compile_result = implementation.compile_source(source, "duplicate_memory_retrieval.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_memory_decay_duration_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.decay duration success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.decay duration success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { decay: 5m }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )

    check_result = implementation.check_source(source, "memory_decay_duration_success.axon")
    compile_result = implementation.compile_source(source, "memory_decay_duration_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    memory = compile_result.ir_program.memories[0]
    assert memory.name == "SessionMemory"
    assert memory.decay == "5m"


def test_native_dev_handles_structural_prefixed_memory_decay_duration_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.decay duration undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed memory.decay duration undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "memory SessionMemory { decay: 5m }\nrun Missing()"
    expected_messages = ["Undefined flow 'Missing' in run statement"]

    check_result = implementation.check_source(source, "memory_decay_duration_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "memory_decay_duration_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 12
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 12
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_memory_with_decay_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.decay check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate memory.decay compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "memory SessionMemory { decay: 5m }\n"
        "memory SessionMemory { decay: daily }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_memory_decay.axon")
    compile_result = implementation.compile_source(source, "duplicate_memory_decay.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_provider_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.provider success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.provider success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { provider: brave }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_provider_success.axon")
    compile_result = implementation.compile_source(source, "tool_provider_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.provider == "brave"


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_provider_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.provider check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.provider compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { provider: brave }\n"
        "tool Search { provider: serpapi }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_provider.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_provider.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_runtime_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.runtime success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.runtime success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { runtime: hosted }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_runtime_success.axon")
    compile_result = implementation.compile_source(source, "tool_runtime_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.runtime == "hosted"


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_runtime_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.runtime check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.runtime compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { runtime: hosted }\n"
        "tool Search { runtime: local }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_runtime.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_runtime.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_sandbox_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.sandbox success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.sandbox success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { sandbox: true }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_sandbox_success.axon")
    compile_result = implementation.compile_source(source, "tool_sandbox_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.sandbox is True


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_sandbox_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.sandbox check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.sandbox compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { sandbox: true }\n"
        "tool Search { sandbox: false }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_sandbox.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_sandbox.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_timeout_success.axon")
    compile_result = implementation.compile_source(source, "tool_timeout_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.timeout == "10s"


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_timeout_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.timeout check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.timeout compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { timeout: 10s }\n"
        "tool Search { timeout: 5s }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_timeout.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_timeout.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_filter_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.filter success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.filter success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { filter: recent }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_filter_success.axon")
    compile_result = implementation.compile_source(source, "tool_filter_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.filter_expr == "recent"


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_filter_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.filter check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.filter compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { filter: recent }\n"
        "tool Search { filter: broad }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_filter.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_filter.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_filter_call_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.filter(...) success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.filter(...) success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { filter: recent(days: 30) }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_filter_call_success.axon")
    compile_result = implementation.compile_source(source, "tool_filter_call_success.axon")

    assert check_result.ok
    assert check_result.token_count == 23
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 23
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.filter_expr == "recent(days:30)"


def test_native_dev_handles_structural_prefixed_tool_effects_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { effects: <network, epistemic:know> }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_effects_success.axon")
    compile_result = implementation.compile_source(source, "tool_effects_success.axon")

    assert check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    tool = compile_result.ir_program.tools[0]
    assert tool.name == "Search"
    assert tool.effect_row == ("network", "epistemic:know")


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_effects_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.effects check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.effects compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { effects: <network, epistemic:know> }\n"
        "tool Search { effects: <io> }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_effects.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_effects.axon")

    assert not check_result.ok
    assert check_result.token_count == 33
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 33
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_effects_invalid_effect_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid-effect check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid-effect compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { effects: <oops> }\nflow SimpleFlow() {}\nrun SimpleFlow()"
    expected_messages = [
        "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage",
    ]

    check_result = implementation.check_source(source, "tool_effects_invalid_effect.axon")
    compile_result = implementation.compile_source(source, "tool_effects_invalid_effect.axon")

    assert not check_result.ok
    assert check_result.token_count == 20
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 20
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_effects_invalid_level_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid-level check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid-level compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { effects: <network, epistemic:guess> }\nflow SimpleFlow() {}\nrun SimpleFlow()"
    expected_messages = [
        "Unknown epistemic level 'guess' in tool 'Search'. Valid levels: believe, doubt, know, speculate",
    ]

    check_result = implementation.check_source(source, "tool_effects_invalid_level.axon")
    compile_result = implementation.compile_source(source, "tool_effects_invalid_level.axon")

    assert not check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_effects_invalid_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.effects invalid undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { effects: <oops> }\nrun Missing()"
    expected_messages = [
        "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "tool_effects_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "tool_effects_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 14
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 14
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_ask_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()'

    check_result = implementation.check_source(source, "intent_ask_success.axon")
    compile_result = implementation.compile_source(source, "intent_ask_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.tools == ()
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_ask_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.ask check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.ask compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { ask: "A?" }\n'
        'intent Extract { ask: "B?" }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_ask.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_ask.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_given_ask_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { given: Document ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()'

    check_result = implementation.check_source(source, "intent_given_ask_success.axon")
    compile_result = implementation.compile_source(source, "intent_given_ask_success.axon")

    assert check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.tools == ()
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_given_ask_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { given: Document ask: "A?" }\n'
        'intent Extract { given: Contract ask: "B?" }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_given_ask.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_given_ask.axon")

    assert not check_result.ok
    assert check_result.token_count == 31
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 31
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_confidence_floor_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()'

    check_result = implementation.check_source(source, "intent_confidence_floor_success.axon")
    compile_result = implementation.compile_source(source, "intent_confidence_floor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.tools == ()
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_intent_output_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.output success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.output success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" output: List<Party>? }\nflow SimpleFlow() {}\nrun SimpleFlow()'

    check_result = implementation.check_source(source, "intent_output_success.axon")
    compile_result = implementation.compile_source(source, "intent_output_success.axon")

    assert check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_intent_output_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.output undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.output undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" output: MissingType }\nrun Missing()'
    expected_messages = [
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "intent_output_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "intent_output_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 15
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 15
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_output_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.output check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.output compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { ask: "A?" output: Party }\n'
        'intent Extract { ask: "B?" output: MissingType }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_output.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_output.axon")

    assert not check_result.ok
    assert check_result.token_count == 31
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 31
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_given_ask_output_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { given: Document ask: "Who signed?" output: List<Party>? }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "intent_given_ask_output_success.axon")
    compile_result = implementation.compile_source(source, "intent_given_ask_output_success.axon")

    assert check_result.ok
    assert check_result.token_count == 28
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 28
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_intent_given_ask_output_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { given: Document ask: "Who signed?" output: MissingType }\nrun Missing()'
    expected_messages = [
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "intent_given_ask_output_undefined_flow.axon")
    compile_result = implementation.compile_source(source, "intent_given_ask_output_undefined_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_given_ask_output_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask+output check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask+output compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { given: Document ask: "A?" output: Party }\n'
        'intent Extract { given: Contract ask: "B?" output: MissingType }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_given_ask_output.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_given_ask_output.axon")

    assert not check_result.ok
    assert check_result.token_count == 37
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 37
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_given_ask_output_confidence_floor_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output+confidence_floor success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output+confidence_floor success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { given: Document ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "intent_given_ask_output_confidence_floor_success.axon")
    compile_result = implementation.compile_source(source, "intent_given_ask_output_confidence_floor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 31
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 31
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_intent_given_ask_output_confidence_floor_validation_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output+confidence_floor validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.given+ask+output+confidence_floor validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { given: Document ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()'
    expected_messages = [
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "intent_given_ask_output_confidence_floor_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "intent_given_ask_output_confidence_floor_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_given_ask_output_confidence_floor_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask+output+confidence_floor check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.given+ask+output+confidence_floor compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { given: Document ask: "A?" output: Party confidence_floor: 1.5 }\n'
        'intent Extract { given: Contract ask: "B?" output: MissingType confidence_floor: 0.8 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_given_ask_output_confidence_floor.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_given_ask_output_confidence_floor.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_output_confidence_floor_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask+output+confidence_floor success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask+output+confidence_floor success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "intent_output_confidence_floor_success.axon")
    compile_result = implementation.compile_source(source, "intent_output_confidence_floor_success.axon")

    assert check_result.ok
    assert check_result.token_count == 28
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 28
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_intent_output_confidence_floor_validation_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask+output+confidence_floor validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.ask+output+confidence_floor validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()'
    expected_messages = [
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "intent_output_confidence_floor_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "intent_output_confidence_floor_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_output_confidence_floor_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.ask+output+confidence_floor check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.ask+output+confidence_floor compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { ask: "A?" output: Party confidence_floor: 1.5 }\n'
        'intent Extract { ask: "B?" output: MissingType confidence_floor: 0.8 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_output_confidence_floor.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_output_confidence_floor.axon")

    assert not check_result.ok
    assert check_result.token_count == 37
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 37
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_confidence_floor_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()'
    expected_messages = [
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
    ]

    check_result = implementation.check_source(source, "intent_confidence_floor_invalid.axon")
    compile_result = implementation.compile_source(source, "intent_confidence_floor_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_intent_confidence_floor_validation_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed intent.confidence_floor undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nrun Missing()'
    expected_messages = [
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "intent_confidence_floor_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "intent_confidence_floor_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 15
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 15
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_intent_with_confidence_floor_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.confidence_floor check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate intent.confidence_floor compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'intent Extract { ask: "A?" confidence_floor: 1.5 }\n'
        'intent Extract { ask: "B?" confidence_floor: 0.8 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)",
        "confidence_floor must be between 0.0 and 1.0, got 1.5",
    ]

    check_result = implementation.check_source(source, "duplicate_intent_confidence_floor.axon")
    compile_result = implementation.compile_source(source, "duplicate_intent_confidence_floor.axon")

    assert not check_result.ok
    assert check_result.token_count == 31
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 31
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_filter_call_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.filter(...) check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.filter(...) compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { filter: recent(days: 30) }\n"
        "tool Search { filter: recent(days: 7) }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_filter_call.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_filter_call.axon")

    assert not check_result.ok
    assert check_result.token_count == 35
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 35
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_max_results_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { max_results: 3 }\nflow SimpleFlow() {}\nrun SimpleFlow()"

    check_result = implementation.check_source(source, "tool_max_results_success.axon")
    compile_result = implementation.compile_source(source, "tool_max_results_success.axon")

    assert check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None


def test_native_dev_handles_structural_prefixed_axonendpoint_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()'

    check_result = implementation.check_source(source, "endpoint_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_success.axon")

    assert check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.flows[0].name == "SimpleFlow"
    assert compile_result.ir_program.runs[0].flow_name == "SimpleFlow"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_success.axon")

    assert check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].output_type == "Party"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_success.axon")

    assert check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_timeout_success.axon")

        assert check_result.ok
        assert check_result.token_count == 27
        assert check_result.declaration_count == 3
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == 27
        assert compile_result.declaration_count == 3
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_retries_success.axon")

    assert check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_retries_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_retries_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_retries_timeout_success.axon")

        assert check_result.ok
        assert check_result.token_count == 30
        assert check_result.declaration_count == 3
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == 30
        assert compile_result.declaration_count == 3
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].retries == 1
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_success.axon")

    assert check_result.ok
    assert check_result.token_count == 30
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 30
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].output_type == "Result"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_body_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_body_timeout_success.axon")

        assert check_result.ok
        assert check_result.token_count == 30
        assert check_result.declaration_count == 3
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == 30
        assert compile_result.declaration_count == 3
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].body_type == "Payload"
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_body_output_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_body_output_timeout_success.axon")

        assert check_result.ok
        assert check_result.declaration_count == 3
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.declaration_count == 3
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].body_type == "Payload"
        assert compile_result.ir_program.endpoints[0].output_type == "Result"
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_retries_success.axon")

    assert check_result.ok
    assert check_result.token_count == 30
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 30
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].output_type == "Result"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_retries_success.axon")

    assert check_result.ok
    assert check_result.token_count == 30
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 30
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_output_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_output_timeout_success.axon")

        assert check_result.ok
        assert check_result.token_count == 30
        assert check_result.declaration_count == 3
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.token_count == 30
        assert compile_result.declaration_count == 3
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].output_type == "Result"
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            'shield Safety { }\n'
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "10s",
        ),
        (
            'shield Safety { }\n'
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: slow }\n'
            'flow SimpleFlow() {}\n'
            'run SimpleFlow()',
            "slow",
        ),
    ]

    for source, expected_timeout in cases:
        check_result = implementation.check_source(source, "endpoint_shield_timeout_success.axon")
        compile_result = implementation.compile_source(source, "endpoint_shield_timeout_success.axon")

        assert check_result.ok
        assert check_result.declaration_count == 4
        assert check_result.diagnostics == ()

        assert compile_result.ok
        assert compile_result.declaration_count == 4
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None
        assert compile_result.ir_program.shields[0].name == "Safety"
        assert compile_result.ir_program.endpoints[0].name == "Api"
        assert compile_result.ir_program.endpoints[0].method == "POST"
        assert compile_result.ir_program.endpoints[0].path == "/x"
        assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
        assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
        assert compile_result.ir_program.endpoints[0].timeout == expected_timeout


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].output_type == "Party"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result }\nrun Missing()'

    check_result = implementation.check_source(source, "endpoint_body_output_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_body_shield_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload timeout: 10s }\nrun Missing()'

    check_result = implementation.check_source(source, "endpoint_body_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_retries_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_retries_timeout_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_retries_timeout_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].retries == 1
    assert compile_result.ir_program.endpoints[0].timeout == "10s"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_retries_and_timeout_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_retries_timeout_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_retries_timeout_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_retries_and_timeout_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries+timeout invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 timeout: 10s }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(
        source,
        "endpoint_body_retries_timeout_invalid_missing_flow.axon",
    )
    compile_result = implementation.compile_source(
        source,
        "endpoint_body_retries_timeout_invalid_missing_flow.axon",
    )

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result timeout: 10s }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_retries_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].output_type == "Result"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_retries_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_retries_timeout_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_retries_timeout_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 3
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 3
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].output_type == "Result"
    assert compile_result.ir_program.endpoints[0].retries == 1
    assert compile_result.ir_program.endpoints[0].timeout == "10s"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_retries_and_timeout_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_retries_timeout_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_retries_timeout_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_retries_and_timeout_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries+timeout invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 timeout: 10s }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(
        source,
        "endpoint_output_retries_timeout_invalid_missing_flow.axon",
    )
    compile_result = implementation.compile_source(
        source,
        "endpoint_output_retries_timeout_invalid_missing_flow.axon",
    )

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_shield_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_shield_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_shield_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].output_type == "Result"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_shield_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result shield: Safety }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_shield_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_shield_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Missing }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_shield_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_shield_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+shield not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_shield_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_shield_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_timeout_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_timeout_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
    assert compile_result.ir_program.endpoints[0].timeout == "10s"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety timeout: 10s }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_undefined_shield_and_timeout_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_timeout_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_timeout_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_timeout_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+timeout not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_timeout_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_timeout_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_timeout_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_timeout_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_timeout_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].output_type == "Party"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
    assert compile_result.ir_program.endpoints[0].timeout == "10s"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety timeout: 10s }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_undefined_shield_and_timeout_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_timeout_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_timeout_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_timeout_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+timeout not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_timeout_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_timeout_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_retries_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].output_type == "Party"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety retries: -1 }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_undefined_shield_and_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_retries_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_retries_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_and_retries_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield+retries not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_shield_retries_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_retries_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_retries_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].method == "POST"
    assert compile_result.ir_program.endpoints[0].path == "/x"
    assert compile_result.ir_program.endpoints[0].execute_flow == "SimpleFlow"
    assert compile_result.ir_program.endpoints[0].body_type == "Payload"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
    assert compile_result.ir_program.endpoints[0].retries == 1


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety retries: -1 }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_undefined_shield_and_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_retries_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_retries_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_shield_and_retries_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield+retries not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_retries_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_retries_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_output_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 }\nrun Missing()'

    check_result = implementation.check_source(source, "endpoint_output_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 }\nrun Missing()'

    check_result = implementation.check_source(source, "endpoint_body_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_output_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+output+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result retries: -1 }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_body_output_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_output_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_invalid_retries_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries invalid retries undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries invalid retries undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing shield: Safety retries: -1 }\n'
        'run Missing()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_retries_invalid_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_retries_invalid_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing output: Result timeout: 10s }\nrun Missing()'

    check_result = implementation.check_source(source, "endpoint_output_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout undefined flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout undefined flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing shield: Safety timeout: 10s }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_shield_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_timeout_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_timeout_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_timeout_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_timeout_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+timeout not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_timeout_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_timeout_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_retries_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 2 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_retries_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_retries_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].name == "Api"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"
    assert compile_result.ir_program.endpoints[0].retries == 2


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_and_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body+shield not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_body_shield_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_shield_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_retries_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_retries_undefined_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_retries_undefined_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_and_retries_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries not-a-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield+retries not-a-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_retries_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_retries_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "'Safety' is a anchor, not a shield",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_output_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_output_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_output_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_shield_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_shield_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_shield_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_shield_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_shield_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_shield_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_output_and_shield_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+shield+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+shield+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_output_shield_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_output_shield_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_shield_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+shield+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_shield_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_shield_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_output_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_output_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_output_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_output_and_shield_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+shield invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+shield invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_output_shield_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_output_shield_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_output_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+output+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_output_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_output_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_output_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_output_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_output_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_body_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_shield_and_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.shield+retries invalid retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.shield+retries invalid retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_shield_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_shield_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_output_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Result timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_output_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_output_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_shield_and_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.shield+timeout invalid method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.shield+timeout invalid method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "duplicate_endpoint_shield_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_shield_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_success_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield success check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield success compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )

    check_result = implementation.check_source(source, "endpoint_shield_success.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_success.axon")

    assert check_result.ok
    assert check_result.declaration_count == 4
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.declaration_count == 4
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None
    assert compile_result.ir_program.shields[0].name == "Safety"
    assert compile_result.ir_program.endpoints[0].shield_ref == "Safety"


def test_native_dev_handles_structural_prefixed_axonendpoint_with_shield_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing shield: Safety }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_shield_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    check_result = implementation.check_source(source, "endpoint_shield_undefined.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_undefined.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield kind-mismatch check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.shield kind-mismatch compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "'Safety' is a anchor, not a shield",
    ]

    check_result = implementation.check_source(source, "endpoint_shield_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_shield_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint invalid-method check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint invalid-method compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()'
    expected_messages = [
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "endpoint_invalid_method.axon")
    compile_result = implementation.compile_source(source, "endpoint_invalid_method.axon")

    assert not check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_invalid_path_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint invalid-path check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint invalid-path compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()'
    expected_messages = [
        "axonendpoint 'Api' path must start with '/': got 'x'",
    ]

    check_result = implementation.check_source(source, "endpoint_invalid_path.axon")
    compile_result = implementation.compile_source(source, "endpoint_invalid_path.axon")

    assert not check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = 'axonendpoint Api { method: post path: "/x" execute: Missing }\nrun Missing()'
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_missing_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing output: Party }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_output_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_missing_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_body_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.body undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_body_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_body_missing_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.timeout undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.timeout undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing timeout: 10s }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_timeout_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_timeout_missing_flow.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    check_result = implementation.check_source(source, "endpoint_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "endpoint_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_invalid_retries_and_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_retries_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "endpoint_retries_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 21
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 21
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_invalid_retries_and_timeout_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries+timeout undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.retries+timeout undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 timeout: 10s }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "axonendpoint 'Api' retries must be >= 0, got -1",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_retries_timeout_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "endpoint_retries_timeout_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 24
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 24
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_shield_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety }\n'
        'run Missing()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined flow 'Missing'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "endpoint_output_shield_missing_flow.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_missing_flow.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_undefined_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield undefined-shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield undefined-shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "axonendpoint 'Api' references undefined shield 'Missing'",
    ]

    check_result = implementation.check_source(source, "endpoint_output_shield_undefined.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_undefined.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_axonendpoint_with_output_and_not_a_shield_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield kind-mismatch check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed axonendpoint.output+shield kind-mismatch compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'anchor Safety { require: source_citation }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "'Safety' is a anchor, not a shield",
    ]

    check_result = implementation.check_source(source, "endpoint_output_shield_not_a_shield.axon")
    compile_result = implementation.compile_source(source, "endpoint_output_shield_not_a_shield.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_invalid_method.axon")

    assert not check_result.ok
    assert check_result.token_count == 37
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 37
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_body_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.body compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Result }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_body_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_body_invalid_method.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_timeout_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.timeout check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.timeout compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_timeout_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_timeout_invalid_method.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_invalid_retries_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.retries check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.retries compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_retries_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_retries_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_invalid_retries_and_timeout_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.retries+timeout check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.retries+timeout compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 timeout: 10s }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 timeout: 5s }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "axonendpoint 'Api' retries must be >= 0, got -1",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_retries_timeout_invalid.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_retries_timeout_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 49
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 49
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_output_and_shield_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output+shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_output_shield_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_output_shield_invalid_method.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_axonendpoint_with_output_invalid_method_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate axonendpoint.output compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party }\n'
        'axonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)",
        "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT",
    ]

    check_result = implementation.check_source(source, "duplicate_endpoint_output_invalid_method.axon")
    compile_result = implementation.compile_source(source, "duplicate_endpoint_output_invalid_method.axon")

    assert not check_result.ok
    assert check_result.token_count == 43
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 43
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_shield_declaration_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate shield check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate shield compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        'shield Safety { }\n'
        'shield Safety { }\n'
        'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\n'
        'flow SimpleFlow() {}\n'
        'run SimpleFlow()'
    )
    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as shield (first defined at line 1)",
    ]

    check_result = implementation.check_source(source, "duplicate_shield_endpoint.axon")
    compile_result = implementation.compile_source(source, "duplicate_shield_endpoint.axon")

    assert not check_result.ok
    assert check_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.declaration_count == 5
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_max_results_validation_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results validation check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results validation compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { max_results: 0 }\nflow SimpleFlow() {}\nrun SimpleFlow()"
    expected_messages = [
        "max_results must be positive, got 0 in tool 'Search'",
    ]

    check_result = implementation.check_source(source, "tool_max_results_invalid.axon")
    compile_result = implementation.compile_source(source, "tool_max_results_invalid.axon")

    assert not check_result.ok
    assert check_result.token_count == 18
    assert check_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 18
    assert compile_result.declaration_count == 3
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_tool_max_results_validation_with_undefined_flow_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results undefined-flow check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed tool.max_results undefined-flow compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = "tool Search { max_results: 0 }\nrun Missing()"
    expected_messages = [
        "max_results must be positive, got 0 in tool 'Search'",
        "Undefined flow 'Missing' in run statement",
    ]

    check_result = implementation.check_source(source, "tool_max_results_invalid_undefined.axon")
    compile_result = implementation.compile_source(source, "tool_max_results_invalid_undefined.axon")

    assert not check_result.ok
    assert check_result.token_count == 12
    assert check_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 12
    assert compile_result.declaration_count == 2
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_tool_with_max_results_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.max_results check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate tool.max_results compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "tool Search { max_results: 0 }\n"
        "tool Search { max_results: 3 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow()"
    )
    expected_messages = [
        "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)",
        "max_results must be positive, got 0 in tool 'Search'",
    ]

    check_result = implementation.check_source(source, "duplicate_tool_max_results.axon")
    compile_result = implementation.compile_source(source, "duplicate_tool_max_results.axon")

    assert not check_result.ok
    assert check_result.token_count == 25
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 25
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_context_with_max_tokens_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate max_tokens check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate max_tokens compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "context Review { max_tokens: 0 }\n"
        "context Review { max_tokens: 1 }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() within Review"
    )

    check_result = implementation.check_source(source, "duplicate_max_tokens.axon")
    compile_result = implementation.compile_source(source, "duplicate_max_tokens.axon")
    expected_messages = [
        "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
        "max_tokens must be positive, got 0 in context 'Review'",
    ]

    assert not check_result.ok
    assert check_result.token_count == 27
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 27
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_unknown_response_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate unknown_response check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate unknown_response compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    source = (
        "anchor Safety { unknown_response: \"A\" }\n"
        "anchor Safety { unknown_response: \"B\" }\n"
        "flow SimpleFlow() {}\n"
        "run SimpleFlow() constrained_by [Safety]"
    )

    check_result = implementation.check_source(source, "duplicate_unknown_response.axon")
    compile_result = implementation.compile_source(source, "duplicate_unknown_response.axon")

    expected_messages = [
        "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
    ]

    assert not check_result.ok
    assert check_result.token_count == 29
    assert check_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

    assert not compile_result.ok
    assert compile_result.token_count == 29
    assert compile_result.declaration_count == 4
    assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
    assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_context_with_cite_sources_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate cite_sources check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate cite_sources compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { cite_sources: true }\n"
            "persona Expert { cite_sources: false }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
            ],
        ),
        (
            "context Review { cite_sources: true }\n"
            "context Review { cite_sources: false }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_cite_sources.axon")
        compile_result = implementation.compile_source(source, "duplicate_cite_sources.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_anchor_with_enforce_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate anchor enforce check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate anchor enforce compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "anchor Safety { enforce: strict }\n"
            "anchor Safety { enforce: soft }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            29,
            4,
            [
                "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)",
            ],
        ),
        (
            "context Review { depth: deep }\n"
            "anchor Safety { enforce: strict }\n"
            "anchor Safety { enforce: soft }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() constrained_by [Safety]",
            36,
            5,
            [
                "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 2)",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_anchor_enforce.axon")
        compile_result = implementation.compile_source(source, "duplicate_anchor_enforce.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_context_depth_without_duplicates_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context depth check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid context depth compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { depth: abyss }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            20,
            3,
            [
                "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard",
            ],
        ),
        (
            "context Review { depth: abyss }\n"
            "run SimpleFlow() within Review",
            14,
            2,
            [
                "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard",
                "Undefined flow 'SimpleFlow' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "invalid_context_depth_structural.axon")
        compile_result = implementation.compile_source(source, "invalid_context_depth_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_context_with_invalid_depth_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate context + invalid depth check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate context + invalid depth compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "context Review { depth: abyss }\n"
            "context Review { depth: deep }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
                "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard",
            ],
        ),
        (
            "context Review { depth: abyss }\n"
            "context Review { depth: abyss }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Duplicate declaration: 'Review' already defined as context (first defined at line 1)",
                "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard",
                "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_context_invalid_depth.axon")
        compile_result = implementation.compile_source(source, "duplicate_context_invalid_depth.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_invalid_persona_tone_without_duplicates_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid persona tone check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed invalid persona tone compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            20,
            3,
            [
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
        (
            "persona Expert { tone: invalid }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            34,
            5,
            [
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "invalid_persona_structural.axon")
        compile_result = implementation.compile_source(source, "invalid_persona_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_persona_context_validation_combinations_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed persona/context validation combinations check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed persona/context validation combinations compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: invalid }\n"
            "run SimpleFlow() as Expert",
            14,
            2,
            [
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
                "Undefined flow 'SimpleFlow' in run statement",
            ],
        ),
        (
            "persona Expert { tone: invalid }\n"
            "context Review { memory: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
        (
            "context Review { memory: invalid }\n"
            "persona Expert { tone: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review",
            27,
            4,
            [
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
        (
            "persona Expert { tone: invalid }\n"
            "context Review { memory: invalid }\n"
            "run SimpleFlow() as Expert",
            21,
            3,
            [
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
                "Undefined flow 'SimpleFlow' in run statement",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "persona_context_validation_structural.axon")
        compile_result = implementation.compile_source(source, "persona_context_validation_structural.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_native_dev_handles_structural_prefixed_duplicate_persona_with_invalid_tone_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate persona + invalid tone check"
            )

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError(
                "delegate should not be used for structural prefixed duplicate persona + invalid tone compile"
            )

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())
    cases = [
        (
            "persona Expert { tone: invalid }\n"
            "persona Expert { tone: formal }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
        (
            "persona Expert { tone: formal }\n"
            "persona Expert { tone: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
        (
            "persona Expert { tone: invalid }\n"
            "persona Expert { tone: invalid }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            27,
            4,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
            ],
        ),
        (
            "persona Expert { tone: invalid }\n"
            "context Review { memory: invalid }\n"
            "persona Expert { tone: formal }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() as Expert",
            34,
            5,
            [
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise",
                "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session",
            ],
        ),
    ]

    for source, expected_token_count, expected_declaration_count, expected_messages in cases:
        check_result = implementation.check_source(source, "duplicate_persona_invalid_tone.axon")
        compile_result = implementation.compile_source(source, "duplicate_persona_invalid_tone.axon")

        assert not check_result.ok
        assert check_result.token_count == expected_token_count
        assert check_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in check_result.diagnostics] == expected_messages

        assert not compile_result.ok
        assert compile_result.token_count == expected_token_count
        assert compile_result.declaration_count == expected_declaration_count
        assert [diagnostic.message for diagnostic in compile_result.diagnostics] == expected_messages
        assert compile_result.ir_program is None


def test_register_frontend_implementation_makes_backend_bootstrappable() -> None:
    class CustomFrontendImplementation:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            return FrontendCheckResult(token_count=21, declaration_count=8)

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            return FrontendCompileResult(token_count=21, declaration_count=8)

    register_frontend_implementation("custom-test", CustomFrontendImplementation)

    implementation = bootstrap_frontend("custom-test")

    try:
        assert implementation.__class__.__name__ == "CustomFrontendImplementation"
        result = frontend.check_source("persona X {}", "custom.axon")
        assert result.token_count == 21
        assert result.declaration_count == 8
        assert current_frontend_selection() == "custom-test"
    finally:
        reset_frontend_implementation()


def test_bootstrap_frontend_selects_native_dev_by_name() -> None:
    reset_frontend_implementation()

    implementation = bootstrap_frontend("native-dev")

    try:
        assert isinstance(implementation, NativeDevelopmentFrontendImplementation)
        assert isinstance(get_frontend_implementation(), NativeDevelopmentFrontendImplementation)
        assert current_frontend_selection() == "native-dev"
        result = frontend.check_source(VALID_SOURCE.read_text(encoding="utf-8"), str(VALID_SOURCE))
        assert result.ok
        assert result.token_count == 168
    finally:
        reset_frontend_implementation()


def test_native_dev_handles_simple_import_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev simple import check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev simple import compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    source = "import SomeModule"

    check_result = implementation.check_source(source, "import.axon")
    compile_result = implementation.compile_source(source, "import.axon")

    assert check_result.ok
    assert check_result.token_count == 3
    assert check_result.declaration_count == 1
    assert check_result.diagnostics == ()

    assert compile_result.ok
    assert compile_result.token_count == 3
    assert compile_result.declaration_count == 1
    assert compile_result.diagnostics == ()
    assert compile_result.ir_program is not None

    ir_dict = serialize_ir_program(compile_result.ir_program)
    assert len(ir_dict["imports"]) == 1
    assert ir_dict["imports"][0]["module_path"] == ("SomeModule",)
    assert ir_dict["imports"][0]["names"] == ()
    assert ir_dict["imports"][0]["resolved"] is False


def test_native_dev_handles_dotted_import_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev dotted import check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev dotted import compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        ("import a.b", 5, ("a", "b")),
        ("import a.b.c", 7, ("a", "b", "c")),
        ("import a.b.c.d", 9, ("a", "b", "c", "d")),
    ]

    for source, expected_tc, expected_path in cases:
        check_result = implementation.check_source(source, "import.axon")
        compile_result = implementation.compile_source(source, "import.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}"
        assert check_result.declaration_count == 1
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == 1
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["imports"]) == 1
        assert ir_dict["imports"][0]["module_path"] == expected_path, f"path mismatch for {source}"
        assert ir_dict["imports"][0]["names"] == ()
        assert ir_dict["imports"][0]["resolved"] is False


def test_native_dev_handles_named_import_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev named import check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev named import compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        ("import a { X }", 6, ("a",), ("X",)),
        ("import a { X, Y }", 8, ("a",), ("X", "Y")),
        ("import a.b { X }", 8, ("a", "b"), ("X",)),
        ("import a.b { X, Y }", 10, ("a", "b"), ("X", "Y")),
        ("import a.b.c { X, Y, Z }", 14, ("a", "b", "c"), ("X", "Y", "Z")),
    ]

    for source, expected_tc, expected_path, expected_names in cases:
        check_result = implementation.check_source(source, "import.axon")
        compile_result = implementation.compile_source(source, "import.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}"
        assert check_result.declaration_count == 1
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == 1
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["imports"]) == 1
        assert ir_dict["imports"][0]["module_path"] == expected_path, f"path mismatch for {source}"
        assert ir_dict["imports"][0]["names"] == expected_names, f"names mismatch for {source}"
        assert ir_dict["imports"][0]["resolved"] is False


def test_native_dev_handles_import_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev import+flow/run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev import+flow/run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        ("import Utils\nflow Main() {}\nrun Main()", 13, 3, ("Utils",), ()),
        ("import a.b\nflow Main() {}\nrun Main()", 15, 3, ("a", "b"), ()),
        ("import a { X }\nflow Main() {}\nrun Main()", 16, 3, ("a",), ("X",)),
        ("import Utils\npersona Bot { tone: friendly }\nflow Main() {}\nrun Main()", 20, 4, ("Utils",), ()),
    ]

    for source, expected_tc, expected_dc, expected_import_path, expected_import_names in cases:
        check_result = implementation.check_source(source, "import_flow_run.axon")
        compile_result = implementation.compile_source(source, "import_flow_run.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["imports"]) == 1
        assert ir_dict["imports"][0]["module_path"] == expected_import_path, f"path mismatch for {source}"
        assert ir_dict["imports"][0]["names"] == expected_import_names, f"names mismatch for {source}"
        assert ir_dict["imports"][0]["resolved"] is False
        assert len(ir_dict["flows"]) == 1
        assert ir_dict["flows"][0]["name"] == "Main"
        assert len(ir_dict["runs"]) == 1


def test_native_dev_handles_multi_import_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev multi-import check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev multi-import compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        ("import A\nimport B", 5, 2, [("A",), ("B",)], [(), ()]),
        ("import A\nimport B\nimport C", 7, 3, [("A",), ("B",), ("C",)], [(), (), ()]),
        ("import a.b\nimport c.d.e", 11, 2, [("a", "b"), ("c", "d", "e")], [(), ()]),
        ("import a { X }\nimport b.c { Y, Z }", 15, 2, [("a",), ("b", "c")], [("X",), ("Y", "Z")]),
    ]

    for source, expected_tc, expected_dc, expected_paths, expected_names_list in cases:
        check_result = implementation.check_source(source, "multi_import.axon")
        compile_result = implementation.compile_source(source, "multi_import.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["imports"]) == expected_dc, f"import count mismatch for {source}"
        for i, (exp_path, exp_names) in enumerate(zip(expected_paths, expected_names_list)):
            assert ir_dict["imports"][i]["module_path"] == exp_path, f"path[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["names"] == exp_names, f"names[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["resolved"] is False


def test_native_dev_handles_type_import_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev type+import+flow/run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev type+import+flow/run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "type Foo { x: String }\nimport bar\nflow Main() {}\nrun Main()",
            20, 4,
            ["Foo"], [("bar",)], [()],
        ),
        (
            "type Foo { x: String }\nimport a.b\nflow Main() {}\nrun Main()",
            22, 4,
            ["Foo"], [("a", "b")], [()],
        ),
        (
            "type Foo { x: String }\nimport bar\nimport baz\nflow Main() {}\nrun Main()",
            22, 5,
            ["Foo"], [("bar",), ("baz",)], [(), ()],
        ),
        (
            "type Foo { x: String }\ntype Bar { y: Number }\nimport baz\nflow Main() {}\nrun Main()",
            27, 5,
            ["Foo", "Bar"], [("baz",)], [()],
        ),
    ]

    for source, expected_tc, expected_dc, expected_types, expected_import_paths, expected_import_names in cases:
        check_result = implementation.check_source(source, "type_import_flow_run.axon")
        compile_result = implementation.compile_source(source, "type_import_flow_run.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [t["name"] for t in ir_dict["types"]] == expected_types, f"types mismatch for {source}"
        assert len(ir_dict["imports"]) == len(expected_import_paths), f"import count mismatch for {source}"
        for i, (exp_path, exp_names) in enumerate(zip(expected_import_paths, expected_import_names)):
            assert ir_dict["imports"][i]["module_path"] == exp_path, f"import path[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["names"] == exp_names, f"import names[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["resolved"] is False
        assert len(ir_dict["flows"]) == 1
        assert ir_dict["flows"][0]["name"] == "Main"
        assert len(ir_dict["runs"]) == 1
        assert ir_dict["runs"][0]["flow_name"] == "Main"


def test_native_dev_handles_import_type_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev import+type+flow/run check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev import+type+flow/run compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "import bar\ntype Foo { x: String }\nflow Main() {}\nrun Main()",
            20, 4,
            [("bar",)], [()],
            ["Foo"],
        ),
        (
            "import a.b\ntype Foo { x: String }\nflow Main() {}\nrun Main()",
            22, 4,
            [("a", "b")], [()],
            ["Foo"],
        ),
        (
            "import bar\nimport baz\ntype Foo { x: String }\nflow Main() {}\nrun Main()",
            22, 5,
            [("bar",), ("baz",)], [(), ()],
            ["Foo"],
        ),
        (
            "import bar\ntype Foo { x: String }\ntype Bar { y: Number }\nflow Main() {}\nrun Main()",
            27, 5,
            [("bar",)], [()],
            ["Foo", "Bar"],
        ),
    ]

    for source, expected_tc, expected_dc, expected_import_paths, expected_import_names, expected_types in cases:
        check_result = implementation.check_source(source, "import_type_flow_run.axon")
        compile_result = implementation.compile_source(source, "import_type_flow_run.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [t["name"] for t in ir_dict["types"]] == expected_types, f"types mismatch for {source}"
        assert len(ir_dict["imports"]) == len(expected_import_paths), f"import count mismatch for {source}"
        for i, (exp_path, exp_names) in enumerate(zip(expected_import_paths, expected_import_names)):
            assert ir_dict["imports"][i]["module_path"] == exp_path, f"import path[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["names"] == exp_names, f"import names[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["resolved"] is False
        assert len(ir_dict["flows"]) == 1
        assert ir_dict["flows"][0]["name"] == "Main"
        assert len(ir_dict["runs"]) == 1
        assert ir_dict["runs"][0]["flow_name"] == "Main"


def test_native_dev_handles_type_import_standalone_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev type+import standalone check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev type+import standalone compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "type Score(0.0..1.0)\nimport bar",
            10, 2,
            [("bar",)], [()],
            ["Score"],
        ),
        (
            "type Score(0.0..1.0)\nimport bar.baz",
            12, 2,
            [("bar", "baz")], [()],
            ["Score"],
        ),
        (
            "type Score(0.0..1.0)\nimport bar { X }",
            13, 2,
            [("bar",)], [("X",)],
            ["Score"],
        ),
        (
            "type Score(0.0..1.0)\ntype Risk { level: Score }\nimport bar",
            17, 3,
            [("bar",)], [()],
            ["Score", "Risk"],
        ),
        (
            "type Score(0.0..1.0)\nimport bar\nimport baz",
            12, 3,
            [("bar",), ("baz",)], [(), ()],
            ["Score"],
        ),
    ]

    for source, expected_tc, expected_dc, expected_import_paths, expected_import_names, expected_types in cases:
        check_result = implementation.check_source(source, "type_import_standalone.axon")
        compile_result = implementation.compile_source(source, "type_import_standalone.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [t["name"] for t in ir_dict["types"]] == expected_types, f"types mismatch for {source}"
        assert len(ir_dict["imports"]) == len(expected_import_paths), f"import count mismatch for {source}"
        for i, (exp_path, exp_names) in enumerate(zip(expected_import_paths, expected_import_names)):
            assert ir_dict["imports"][i]["module_path"] == exp_path, f"import path[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["names"] == exp_names, f"import names[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["resolved"] is False
        assert ir_dict["flows"] == ()
        assert ir_dict["runs"] == ()


def test_native_dev_handles_import_type_standalone_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev import+type standalone check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev import+type standalone compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "import bar\ntype Score(0.0..1.0)",
            10, 2,
            [("bar",)], [()],
            ["Score"],
        ),
        (
            "import bar.baz\ntype Score(0.0..1.0)",
            12, 2,
            [("bar", "baz")], [()],
            ["Score"],
        ),
        (
            "import bar { X }\ntype Score(0.0..1.0)",
            13, 2,
            [("bar",)], [("X",)],
            ["Score"],
        ),
        (
            "import bar\nimport baz\ntype Score(0.0..1.0)",
            12, 3,
            [("bar",), ("baz",)], [(), ()],
            ["Score"],
        ),
        (
            "import bar\ntype Score(0.0..1.0)\ntype Risk { level: Score }",
            17, 3,
            [("bar",)], [()],
            ["Score", "Risk"],
        ),
    ]

    for source, expected_tc, expected_dc, expected_import_paths, expected_import_names, expected_types in cases:
        check_result = implementation.check_source(source, "import_type_standalone.axon")
        compile_result = implementation.compile_source(source, "import_type_standalone.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [t["name"] for t in ir_dict["types"]] == expected_types, f"types mismatch for {source}"
        assert len(ir_dict["imports"]) == len(expected_import_paths), f"import count mismatch for {source}"
        for i, (exp_path, exp_names) in enumerate(zip(expected_import_paths, expected_import_names)):
            assert ir_dict["imports"][i]["module_path"] == exp_path, f"import path[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["names"] == exp_names, f"import names[{i}] mismatch for {source}"
            assert ir_dict["imports"][i]["resolved"] is False
        assert ir_dict["flows"] == ()
        assert ir_dict["runs"] == ()


def test_native_dev_handles_multi_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "flow A() {}\nflow B() {}\nrun A()\nrun B()",
            21, 4, ["A", "B"], ["A", "B"],
        ),
        (
            "flow A() {}\nflow B() {}\nrun A()",
            17, 3, ["A", "B"], ["A"],
        ),
        (
            "flow A() {}\nflow B() {}\nflow C() {}\nrun A()\nrun B()\nrun C()",
            31, 6, ["A", "B", "C"], ["A", "B", "C"],
        ),
        (
            "flow X() {}\nflow Y() {}\nrun Y()\nrun X()",
            21, 4, ["X", "Y"], ["Y", "X"],
        ),
    ]

    for source, expected_tc, expected_dc, expected_flow_names, expected_run_names in cases:
        check_result = implementation.check_source(source, "multi_flow.axon")
        compile_result = implementation.compile_source(source, "multi_flow.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [f["name"] for f in ir_dict["flows"]] == expected_flow_names, f"flows mismatch for {source}"
        assert [r["flow_name"] for r in ir_dict["runs"]] == expected_run_names, f"runs mismatch for {source}"
        for run_entry in ir_dict["runs"]:
            assert run_entry["resolved_flow"] is not None, f"unresolved run in {source}"
            assert run_entry["resolved_flow"]["name"] == run_entry["flow_name"]
        assert ir_dict["types"] == ()
        assert ir_dict["imports"] == ()


def test_native_dev_handles_multi_flow_run_with_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow+modifiers check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow+modifiers compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            'flow A() {}\nflow B() {}\nrun A() output_to: "result"\nrun B()',
            24, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "result", "effort": "", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A() {}\nflow B() {}\nrun A() effort: high\nrun B()',
            24, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "", "effort": "high", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A() {}\nflow B() {}\nrun A() on_failure: log\nrun B()',
            24, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "log", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A() {}\nflow B() {}\nrun A() on_failure: raise Boom\nrun B()',
            25, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "raise", "on_failure_params": (("target", "Boom"),)},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A() {}\nflow B() {}\nrun A() on_failure: retry(max_retries: 3)\nrun B()',
            29, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "retry", "on_failure_params": (("max_retries", "3"),)},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A() {}\nflow B() {}\nrun A() effort: high\nrun B() effort: low',
            27, 4, ["A", "B"],
            [{"flow_name": "A", "output_to": "", "effort": "high", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "low", "on_failure": "", "on_failure_params": ()}],
        ),
    ]

    for source, expected_tc, expected_dc, expected_flow_names, expected_runs in cases:
        check_result = implementation.check_source(source, "multi_flow_mod.axon")
        compile_result = implementation.compile_source(source, "multi_flow_mod.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [f["name"] for f in ir_dict["flows"]] == expected_flow_names, f"flows mismatch for {source}"
        assert len(ir_dict["runs"]) == len(expected_runs), f"run count mismatch for {source}"
        for i, exp in enumerate(expected_runs):
            actual_run = ir_dict["runs"][i]
            assert actual_run["flow_name"] == exp["flow_name"], f"run[{i}] flow_name mismatch for {source}"
            assert actual_run["output_to"] == exp["output_to"], f"run[{i}] output_to mismatch for {source}"
            assert actual_run["effort"] == exp["effort"], f"run[{i}] effort mismatch for {source}"
            assert actual_run["on_failure"] == exp["on_failure"], f"run[{i}] on_failure mismatch for {source}"
            assert actual_run["on_failure_params"] == exp["on_failure_params"], f"run[{i}] on_failure_params mismatch for {source}"
            assert actual_run["resolved_flow"] is not None, f"run[{i}] unresolved in {source}"


def test_native_dev_handles_parameterized_flow_run_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev parameterized flow check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev parameterized flow compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "flow Greet(name: String) {}\nrun Greet()",
            14, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
        ),
        (
            "flow Check(x: String?) {}\nrun Check()",
            15, 2, "Check",
            [{"name": "x", "type_name": "String", "generic_param": "", "optional": True}],
        ),
        (
            "flow Filter(items: List<String>) {}\nrun Filter()",
            17, 2, "Filter",
            [{"name": "items", "type_name": "List", "generic_param": "String", "optional": False}],
        ),
        (
            "flow Process(x: Int, y: String) {}\nrun Process()",
            18, 2, "Process",
            [
                {"name": "x", "type_name": "Int", "generic_param": "", "optional": False},
                {"name": "y", "type_name": "String", "generic_param": "", "optional": False},
            ],
        ),
    ]

    for source, expected_tc, expected_dc, expected_flow_name, expected_params in cases:
        check_result = implementation.check_source(source, "param_flow.axon")
        compile_result = implementation.compile_source(source, "param_flow.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["flows"]) == 1, f"flow count mismatch for {source}"
        flow = ir_dict["flows"][0]
        assert flow["name"] == expected_flow_name, f"flow name mismatch for {source}"
        assert len(flow["parameters"]) == len(expected_params), f"param count mismatch for {source}"
        for i, exp in enumerate(expected_params):
            actual_param = flow["parameters"][i]
            assert actual_param["name"] == exp["name"], f"param[{i}] name mismatch for {source}"
            assert actual_param["type_name"] == exp["type_name"], f"param[{i}] type_name mismatch for {source}"
            assert actual_param["generic_param"] == exp["generic_param"], f"param[{i}] generic_param mismatch for {source}"
            assert actual_param["optional"] == exp["optional"], f"param[{i}] optional mismatch for {source}"

        assert len(ir_dict["runs"]) == 1, f"run count mismatch for {source}"
        run = ir_dict["runs"][0]
        assert run["flow_name"] == expected_flow_name, f"run flow_name mismatch for {source}"
        assert run["resolved_flow"] is not None, f"run unresolved in {source}"
        assert ir_dict["types"] == ()
        assert ir_dict["imports"] == ()


def test_native_dev_handles_parameterized_flow_run_with_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev parameterized flow+modifier check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev parameterized flow+modifier compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            'flow Greet(name: String) {}\nrun Greet() output_to: "result"',
            17, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
            {"flow_name": "Greet", "output_to": "result", "effort": "", "on_failure": "", "on_failure_params": ()},
        ),
        (
            "flow Greet(name: String) {}\nrun Greet() effort: high",
            17, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
            {"flow_name": "Greet", "output_to": "", "effort": "high", "on_failure": "", "on_failure_params": ()},
        ),
        (
            "flow Greet(name: String) {}\nrun Greet() on_failure: log",
            17, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
            {"flow_name": "Greet", "output_to": "", "effort": "", "on_failure": "log", "on_failure_params": ()},
        ),
        (
            "flow Greet(name: String) {}\nrun Greet() on_failure: raise Boom",
            18, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
            {"flow_name": "Greet", "output_to": "", "effort": "", "on_failure": "raise", "on_failure_params": (("target", "Boom"),)},
        ),
        (
            "flow Greet(name: String) {}\nrun Greet() on_failure: retry(max_retries: 3)",
            22, 2, "Greet",
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
            {"flow_name": "Greet", "output_to": "", "effort": "", "on_failure": "retry", "on_failure_params": (("max_retries", "3"),)},
        ),
    ]

    for source, expected_tc, expected_dc, expected_flow_name, expected_params, expected_run in cases:
        check_result = implementation.check_source(source, "param_flow_mod.axon")
        compile_result = implementation.compile_source(source, "param_flow_mod.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["flows"]) == 1, f"flow count mismatch for {source}"
        flow = ir_dict["flows"][0]
        assert flow["name"] == expected_flow_name, f"flow name mismatch for {source}"
        assert len(flow["parameters"]) == len(expected_params), f"param count mismatch for {source}"
        for i, exp in enumerate(expected_params):
            actual_param = flow["parameters"][i]
            assert actual_param["name"] == exp["name"], f"param[{i}] name mismatch for {source}"
            assert actual_param["type_name"] == exp["type_name"], f"param[{i}] type_name mismatch for {source}"
            assert actual_param["generic_param"] == exp["generic_param"], f"param[{i}] generic_param mismatch for {source}"
            assert actual_param["optional"] == exp["optional"], f"param[{i}] optional mismatch for {source}"

        assert len(ir_dict["runs"]) == 1, f"run count mismatch for {source}"
        run = ir_dict["runs"][0]
        assert run["flow_name"] == expected_run["flow_name"], f"run flow_name mismatch for {source}"
        assert run["output_to"] == expected_run["output_to"], f"run output_to mismatch for {source}"
        assert run["effort"] == expected_run["effort"], f"run effort mismatch for {source}"
        assert run["on_failure"] == expected_run["on_failure"], f"run on_failure mismatch for {source}"
        assert run["on_failure_params"] == expected_run["on_failure_params"], f"run on_failure_params mismatch for {source}"
        assert run["resolved_flow"] is not None, f"run unresolved in {source}"
        assert ir_dict["types"] == ()
        assert ir_dict["imports"] == ()


def test_native_dev_handles_multi_flow_run_with_params_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow+params check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev multi_flow+params compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        (
            "flow A(x: Int) {}\nflow B() {}\nrun A()\nrun B()",
            24, 4, ["A", "B"],
            {"A": [{"name": "x", "type_name": "Int", "generic_param": "", "optional": False}], "B": []},
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            "flow A() {}\nflow B(y: String) {}\nrun A()\nrun B()",
            24, 4, ["A", "B"],
            {"A": [], "B": [{"name": "y", "type_name": "String", "generic_param": "", "optional": False}]},
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            "flow A(x: Int) {}\nflow B(y: String) {}\nrun A()\nrun B()",
            27, 4, ["A", "B"],
            {"A": [{"name": "x", "type_name": "Int", "generic_param": "", "optional": False}],
             "B": [{"name": "y", "type_name": "String", "generic_param": "", "optional": False}]},
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            "flow A(x: List<String>) {}\nflow B(y: Map<Int>) {}\nrun A()\nrun B()",
            33, 4, ["A", "B"],
            {"A": [{"name": "x", "type_name": "List", "generic_param": "String", "optional": False}],
             "B": [{"name": "y", "type_name": "Map", "generic_param": "Int", "optional": False}]},
            [{"flow_name": "A", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
        (
            'flow A(x: Int) {}\nflow B() {}\nrun A() effort: high\nrun B()',
            27, 4, ["A", "B"],
            {"A": [{"name": "x", "type_name": "Int", "generic_param": "", "optional": False}], "B": []},
            [{"flow_name": "A", "output_to": "", "effort": "high", "on_failure": "", "on_failure_params": ()},
             {"flow_name": "B", "output_to": "", "effort": "", "on_failure": "", "on_failure_params": ()}],
        ),
    ]

    for source, expected_tc, expected_dc, expected_flow_names, expected_params_map, expected_runs in cases:
        check_result = implementation.check_source(source, "multi_flow_params.axon")
        compile_result = implementation.compile_source(source, "multi_flow_params.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert [f["name"] for f in ir_dict["flows"]] == expected_flow_names, f"flows mismatch for {source}"

        for flow in ir_dict["flows"]:
            exp_params = expected_params_map[flow["name"]]
            assert len(flow["parameters"]) == len(exp_params), f"param count mismatch for flow {flow['name']} in {source}"
            for i, exp in enumerate(exp_params):
                actual_param = flow["parameters"][i]
                assert actual_param["name"] == exp["name"], f"param[{i}] name mismatch for flow {flow['name']} in {source}"
                assert actual_param["type_name"] == exp["type_name"], f"param[{i}] type_name mismatch for flow {flow['name']} in {source}"
                assert actual_param["generic_param"] == exp["generic_param"], f"param[{i}] generic_param mismatch for flow {flow['name']} in {source}"
                assert actual_param["optional"] == exp["optional"], f"param[{i}] optional mismatch for flow {flow['name']} in {source}"

        assert len(ir_dict["runs"]) == len(expected_runs), f"run count mismatch for {source}"
        for i, exp in enumerate(expected_runs):
            actual_run = ir_dict["runs"][i]
            assert actual_run["flow_name"] == exp["flow_name"], f"run[{i}] flow_name mismatch for {source}"
            assert actual_run["output_to"] == exp["output_to"], f"run[{i}] output_to mismatch for {source}"
            assert actual_run["effort"] == exp["effort"], f"run[{i}] effort mismatch for {source}"
            assert actual_run["on_failure"] == exp["on_failure"], f"run[{i}] on_failure mismatch for {source}"
            assert actual_run["on_failure_params"] == exp["on_failure_params"], f"run[{i}] on_failure_params mismatch for {source}"
            assert actual_run["resolved_flow"] is not None, f"run[{i}] unresolved in {source}"


def test_native_dev_handles_parameterized_flow_run_with_referential_modifiers_without_delegate() -> None:
    class ExplodingDelegate:
        def check_source(self, source: str, filename: str) -> FrontendCheckResult:
            raise AssertionError("delegate should not be used for native-dev param+referential check")

        def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
            raise AssertionError("delegate should not be used for native-dev param+referential compile")

    implementation = NativeDevelopmentFrontendImplementation(delegate=ExplodingDelegate())

    cases = [
        # (source, expected_tc, expected_dc, expected_persona, expected_context, expected_anchors,
        #  expected_resolved_persona, expected_resolved_context, expected_resolved_anchors,
        #  expected_params)
        (
            "persona Helper { tone: formal }\n"
            "flow Greet(name: String) {}\n"
            "run Greet() as Helper",
            23, 3, "Helper", "", (),
            "Helper", None, (),
            [{"name": "name", "type_name": "String", "generic_param": "", "optional": False}],
        ),
        (
            "context Sales { memory: session }\n"
            "flow Pitch(product: String) {}\n"
            "run Pitch() within Sales",
            23, 3, "", "Sales", (),
            None, "Sales", (),
            [{"name": "product", "type_name": "String", "generic_param": "", "optional": False}],
        ),
        (
            "anchor Safety { require: honesty }\n"
            "flow Check(item: String) {}\n"
            "run Check() constrained_by [Safety]",
            25, 3, "", "", ("Safety",),
            None, None, ("Safety",),
            [{"name": "item", "type_name": "String", "generic_param": "", "optional": False}],
        ),
    ]

    for (
        source,
        expected_tc,
        expected_dc,
        expected_persona,
        expected_context,
        expected_anchors,
        expected_resolved_persona,
        expected_resolved_context,
        expected_resolved_anchors,
        expected_params,
    ) in cases:
        check_result = implementation.check_source(source, "param_referential.axon")
        compile_result = implementation.compile_source(source, "param_referential.axon")

        assert check_result.ok, f"check failed for {source}"
        assert check_result.token_count == expected_tc, f"tc mismatch for {source}: got {check_result.token_count}"
        assert check_result.declaration_count == expected_dc, f"dc mismatch for {source}: got {check_result.declaration_count}"
        assert check_result.diagnostics == ()

        assert compile_result.ok, f"compile failed for {source}"
        assert compile_result.token_count == expected_tc
        assert compile_result.declaration_count == expected_dc
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        ir_dict = serialize_ir_program(compile_result.ir_program)
        assert len(ir_dict["flows"]) == 1
        flow = ir_dict["flows"][0]
        assert len(flow["parameters"]) == len(expected_params), f"param count mismatch for {source}"
        for i, exp in enumerate(expected_params):
            actual_param = flow["parameters"][i]
            assert actual_param["name"] == exp["name"]
            assert actual_param["type_name"] == exp["type_name"]
            assert actual_param["generic_param"] == exp["generic_param"]
            assert actual_param["optional"] == exp["optional"]

        run = ir_dict["runs"][0]
        assert run["persona_name"] == expected_persona, f"persona_name mismatch for {source}"
        assert run["context_name"] == expected_context, f"context_name mismatch for {source}"
        assert run["anchor_names"] == expected_anchors, f"anchor_names mismatch for {source}"
        resolved_persona = run["resolved_persona"]
        resolved_context = run["resolved_context"]
        resolved_anchors = run["resolved_anchors"]
        assert (resolved_persona["name"] if resolved_persona else None) == expected_resolved_persona
        assert (resolved_context["name"] if resolved_context else None) == expected_resolved_context
        assert tuple(a["name"] for a in resolved_anchors) == expected_resolved_anchors
        assert run["resolved_flow"] is not None


def test_native_dev_handles_multi_flow_run_with_referential_modifiers_without_delegate():
    """B180: multi_flow + referential modifiers handled locally, no delegation."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        serialize_ir_program,
    )

    class DelegationTracker(NativeDevelopmentFrontendImplementation):
        def check_source(self, source, filename):
            self.delegated = False
            result = super().check_source(source, filename)
            return result, self.delegated

        def compile_source(self, source, filename):
            self.delegated = False
            result = super().compile_source(source, filename)
            return result, self.delegated

    tracker = DelegationTracker()
    py = PythonFrontendImplementation()

    cases = [
        (
            "persona Helper { tone: precise }\n"
            "flow A() {}\n"
            "flow B() {}\n"
            "run A() as Helper\n"
            "run B()\n",
            "multi+as",
        ),
        (
            "context Sales { domain: retail }\n"
            "flow A() {}\n"
            "flow B() {}\n"
            "run A() within Sales\n"
            "run B()\n",
            "multi+within",
        ),
        (
            "anchor Safety { require: honesty }\n"
            "flow A() {}\n"
            "flow B() {}\n"
            "run A() constrained_by [Safety]\n"
            "run B()\n",
            "multi+constrained_by",
        ),
        (
            "persona Helper { tone: precise }\n"
            "flow A(x: String) {}\n"
            "flow B(y: Int) {}\n"
            "run A() as Helper\n"
            "run B()\n",
            "multi+param+as",
        ),
        (
            "context Sales { domain: retail }\n"
            "flow A(x: String) {}\n"
            "flow B(y: Int) {}\n"
            "run A() within Sales\n"
            "run B()\n",
            "multi+param+within",
        ),
    ]

    for source, label in cases:
        check_result, delegated = tracker.check_source(source, "test.axon")
        assert not delegated, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        compile_result, delegated = tracker.compile_source(source, "test.axon")
        assert not delegated, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch"


def test_native_dev_handles_flow_body_with_steps_without_delegate():
    """B181: flow_body with step blocks handled locally, no delegation."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        FrontendCheckResult,
        FrontendCompileResult,
        serialize_ir_program,
    )

    class DelegateDetector(PythonFrontendImplementation):
        def __init__(self):
            super().__init__()
            self.was_called = False
        def check_source(self, source, filename):
            self.was_called = True
            return super().check_source(source, filename)
        def compile_source(self, source, filename):
            self.was_called = True
            return super().compile_source(source, filename)

    py = PythonFrontendImplementation()

    cases = [
        (
            "flow Greet() {\n  step Extract {}\n}\nrun Greet()\n",
            "flow_body_step",
        ),
        (
            "flow Greet() {\n  step A {}\n  step B {}\n}\nrun Greet()\n",
            "flow_body_multi_step",
        ),
        (
            "persona Expert { tone: precise }\n"
            "flow Analyze() {\n  step Extract {}\n}\n"
            "run Analyze() as Expert\n",
            "prefix+flow_body_step",
        ),
        (
            "flow A() {\n  step X {}\n}\n"
            "flow B() {}\n"
            "run A()\nrun B()\n",
            "multi_flow_body",
        ),
    ]

    for source, label in cases:
        detector = DelegateDetector()
        nd = NativeDevelopmentFrontendImplementation(delegate=detector)

        detector.was_called = False
        check_result = nd.check_source(source, "test.axon")
        assert not detector.was_called, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        detector.was_called = False
        compile_result = nd.compile_source(source, "test.axon")
        assert not detector.was_called, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch"


def test_native_dev_handles_shield_compute_fields_without_delegate():
    """B182: shield fields and compute prefix blocks handled locally."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        serialize_ir_program,
    )

    class DelegateDetector(PythonFrontendImplementation):
        def __init__(self):
            super().__init__()
            self.was_called = False
        def check_source(self, source, filename):
            self.was_called = True
            return super().check_source(source, filename)
        def compile_source(self, source, filename):
            self.was_called = True
            return super().compile_source(source, filename)

    py = PythonFrontendImplementation()

    cases = [
        (
            "shield Guard {\n  severity: high\n}\nflow A() {}\nrun A()\n",
            "shield_fields+flow+run",
        ),
        (
            "persona P { tone: precise }\n"
            "shield Guard {\n  severity: high\n}\n"
            "flow A() {}\nrun A() as P\n",
            "prefix+shield_fields+flow+run",
        ),
        (
            "shield Guard {\n  strategy: pattern\n  on_breach: halt\n"
            "  severity: high\n  max_retries: 3\n  sandbox: true\n}\n"
            "flow A() {}\nrun A()\n",
            "shield_multi_fields+flow+run",
        ),
        (
            "compute Task {}\nflow A() {}\nrun A()\n",
            "compute_empty+flow+run",
        ),
        (
            "compute Task {\n  output: Number\n}\nflow A() {}\nrun A()\n",
            "compute_fields+flow+run",
        ),
        (
            "compute Task {\n  output: Number\n  shield: Guard\n}\n"
            "flow A() {}\nrun A()\n",
            "compute_multi_fields+flow+run",
        ),
    ]

    for source, label in cases:
        detector = DelegateDetector()
        nd = NativeDevelopmentFrontendImplementation(delegate=detector)

        detector.was_called = False
        check_result = nd.check_source(source, "test.axon")
        assert not detector.was_called, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        detector.was_called = False
        compile_result = nd.compile_source(source, "test.axon")
        assert not detector.was_called, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch"


def test_native_dev_handles_standalone_prefix_declarations_without_delegate():
    """B183: standalone prefix-only declarations (no flow+run) handled locally."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        serialize_ir_program,
    )

    class DelegateDetector(PythonFrontendImplementation):
        def __init__(self):
            super().__init__()
            self.was_called = False
        def check_source(self, source, filename):
            self.was_called = True
            return super().check_source(source, filename)
        def compile_source(self, source, filename):
            self.was_called = True
            return super().compile_source(source, filename)

    py = PythonFrontendImplementation()

    cases = [
        ("persona P { tone: precise }\n", "persona_only"),
        ("context C { depth: standard }\n", "context_only"),
        ('anchor A { description: "test" }\n', "anchor_only"),
        ('intent I { ask: "test" }\n', "intent_only"),
        ("memory M { backend: vector }\n", "memory_only"),
        ("tool T { provider: openai }\n", "tool_only"),
        ("shield Guard {}\n", "shield_empty_only"),
        ("compute Calc {}\n", "compute_empty_only"),
        ("shield G {}\ncompute C {}\n", "shield+compute_only"),
    ]

    for source, label in cases:
        detector = DelegateDetector()
        nd = NativeDevelopmentFrontendImplementation(delegate=detector)

        detector.was_called = False
        check_result = nd.check_source(source, "test.axon")
        assert not detector.was_called, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        detector.was_called = False
        compile_result = nd.compile_source(source, "test.axon")
        assert not detector.was_called, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch"


def test_native_dev_handles_dataspace_and_axonstore_locally():
    """B184: dataspace and axonstore declarations handled locally."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        serialize_ir_program,
    )

    class DelegateDetector(PythonFrontendImplementation):
        def __init__(self):
            super().__init__()
            self.was_called = False
        def check_source(self, source, filename):
            self.was_called = True
            return super().check_source(source, filename)
        def compile_source(self, source, filename):
            self.was_called = True
            return super().compile_source(source, filename)

    py = PythonFrontendImplementation()

    cases = [
        ("dataspace DS {}\n", "dataspace_only"),
        ("axonstore S {}\n", "axonstore_only"),
        ("dataspace DS {}\naxonstore S {}\n", "dataspace+axonstore"),
    ]

    for source, label in cases:
        detector = DelegateDetector()
        nd = NativeDevelopmentFrontendImplementation(delegate=detector)

        detector.was_called = False
        check_result = nd.check_source(source, "test.axon")
        assert not detector.was_called, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        detector.was_called = False
        compile_result = nd.compile_source(source, "test.axon")
        assert not detector.was_called, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch"


def test_native_dev_no_crash_on_dataspace_axonstore_with_invalid_flow():
    """B185: dataspace/axonstore in duplicate/validation scanners don't crash."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
    )

    py = PythonFrontendImplementation()

    # These patterns hit the duplicate declaration scanner path where
    # dataspace/axonstore previously crashed on anchor fallback.
    cases = [
        ("axonstore S {}\npersona P { tone: precise }\ncontext C { depth: standard }\n"
         'anchor R { description: "test" }\nflow A(x: String) {}\nrun A with P, C, R\n',
         "axonstore+prefix+flow+run"),
        ("dataspace DS {}\npersona P { tone: precise }\ncontext C { depth: standard }\n"
         'anchor R { description: "test" }\nflow A(x: String) {}\nrun A with P, C, R\n',
         "dataspace+prefix+flow+run"),
    ]

    for source, label in cases:
        # Must not crash — both frontends should produce identical diagnostics
        nd = NativeDevelopmentFrontendImplementation(delegate=py)
        nd_result = nd.check_source(source, "test.axon")
        py_result = py.check_source(source, "test.axon")
        nd_msgs = tuple(d.message for d in nd_result.diagnostics)
        py_msgs = tuple(d.message for d in py_result.diagnostics)
        assert nd_result.ok == py_result.ok, f"{label}: ok mismatch ND={nd_result.ok} PY={py_result.ok}"
        assert nd_msgs == py_msgs, f"{label}: diag mismatch ND={nd_msgs} PY={py_msgs}"


def test_native_dev_axonstore_field_parsing_locally():
    """B186: axonstore with scalar fields parsed natively without delegation."""
    from axon.compiler.frontend import (
        NativeDevelopmentFrontendImplementation,
        PythonFrontendImplementation,
        serialize_ir_program,
    )

    class DelegateDetector(PythonFrontendImplementation):
        def __init__(self):
            super().__init__()
            self.was_called = False
        def check_source(self, source, filename):
            self.was_called = True
            return super().check_source(source, filename)
        def compile_source(self, source, filename):
            self.was_called = True
            return super().compile_source(source, filename)

    py = PythonFrontendImplementation()

    cases = [
        # Single-field cases (7-token simple path)
        ("axonstore S { backend: postgresql }\n", "single_backend"),
        ("axonstore S { isolation: serializable }\n", "single_isolation"),
        ("axonstore S { on_breach: rollback }\n", "single_on_breach"),
        ('axonstore S { connection: "postgres://localhost/db" }\n', "single_connection"),
        ("axonstore S { confidence_floor: 0.85 }\n", "single_confidence_floor"),
        # Multi-field cases (extended parser path)
        ("axonstore S { backend: postgresql\nisolation: serializable }\n", "two_fields"),
        ("axonstore S { backend: sqlite\non_breach: rollback\nconfidence_floor: 0.9 }\n", "three_fields"),
        ("axonstore S { backend: postgresql\nconnection: \"postgres://localhost/db\"\nisolation: read_committed\non_breach: raise\nconfidence_floor: 0.95 }\n", "all_five_fields"),
    ]

    for source, label in cases:
        detector = DelegateDetector()
        nd = NativeDevelopmentFrontendImplementation(delegate=detector)

        detector.was_called = False
        check_result = nd.check_source(source, "test.axon")
        assert not detector.was_called, f"{label}: check delegated"
        assert check_result.ok, f"{label}: check not ok"
        assert check_result.diagnostics == ()

        detector.was_called = False
        compile_result = nd.compile_source(source, "test.axon")
        assert not detector.was_called, f"{label}: compile delegated"
        assert compile_result.ok, f"{label}: compile not ok"
        assert compile_result.diagnostics == ()
        assert compile_result.ir_program is not None

        py_result = py.compile_source(source, "test.axon")
        nd_ir = serialize_ir_program(compile_result.ir_program)
        py_ir = serialize_ir_program(py_result.ir_program)
        assert nd_ir == py_ir, f"{label}: IR mismatch\nND: {nd_ir}\nPY: {py_ir}"
