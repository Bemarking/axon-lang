"""
AXON CLI — Unit Tests
=======================
Tests all seven CLI subcommands: check, compile, run, trace, version, repl, inspect.
Uses the real compiler pipeline with the bundled example file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "contract_analyzer.axon"
CLI_MODULE = [sys.executable, "-m", "axon.cli"]

# Force UTF-8 output on Windows subprocess pipes
_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _run(
    *args: str,
    check: bool = True,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute ``python -m axon.cli`` with the given arguments."""
    return subprocess.run(
        [*CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=30,
        check=check,
        env={**_ENV, **(env_overrides or {})},
    )


# ══════════════════════════════════════════════════════════════════
#  axon version
# ══════════════════════════════════════════════════════════════════


class TestVersion:
    """``axon version`` prints semver and exits 0."""

    def test_version_subcommand(self):
        r = _run("version")
        assert r.returncode == 0
        assert "axon-lang" in r.stdout
        parts = r.stdout.strip().split()
        # "axon-lang X.Y.Z" or "axon-lang X.Y.ZaN" (PEP 440)
        assert len(parts) == 2
        assert parts[0] == "axon-lang"
        # Verify it looks like a valid PEP 440 version
        from packaging.version import Version
        v = Version(parts[1])
        assert v.major >= 0 and v.minor >= 0

    def test_version_flag(self):
        r = _run("--version")
        assert r.returncode == 0
        assert "axon-lang" in r.stdout


# ══════════════════════════════════════════════════════════════════
#  axon check
# ══════════════════════════════════════════════════════════════════


class TestCheck:
    """``axon check`` validates .axon files through the front-end pipeline."""

    def test_check_valid_file(self):
        r = _run("check", str(EXAMPLE))
        assert r.returncode == 0
        assert "✓" in r.stdout or "tokens" in r.stdout

    def test_check_reports_token_count(self):
        r = _run("check", str(EXAMPLE), "--no-color")
        # Should mention tokens and declarations
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_missing_file(self):
        r = _run("check", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_check_invalid_syntax(self, tmp_path):
        bad = tmp_path / "bad.axon"
        bad.write_text("42 + garbage", encoding="utf-8")
        r = _run("check", str(bad), check=False)
        assert r.returncode == 1

    def test_check_uses_bootstrapped_native_placeholder(self):
        r = _run(
            "check",
            str(EXAMPLE),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native"},
        )
        assert r.returncode == 1
        assert "Native frontend placeholder is not implemented yet" in (r.stdout + r.stderr)

    def test_check_uses_native_dev_path_without_contract_regression(self):
        r = _run(
            "check",
            str(EXAMPLE),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "0 errors" in r.stdout
        assert r.stderr == ""

    def test_check_invalid_syntax_uses_native_dev_preparser(self, tmp_path):
        bad = tmp_path / "bad_native_dev.axon"
        bad.write_text("42 + garbage", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token at top level" in r.stderr
        assert "found 42" in r.stderr

    def test_check_invalid_lexical_syntax_uses_native_dev_prefix_lexer(self, tmp_path):
        bad = tmp_path / "bad_native_dev_lexer.axon"
        bad.write_text("// note\n~", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected character '~'" in r.stderr

    def test_check_type_range_uses_native_dev_type_subset(self, tmp_path):
        typed = tmp_path / "type_range.axon"
        typed.write_text("type RiskScore(0.0..1.0)", encoding="utf-8")

        r = _run(
            "check",
            str(typed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_structured_type_uses_native_dev_type_subset(self, tmp_path):
        typed = tmp_path / "type_struct.axon"
        typed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "type Risk {\n"
            "  score: RiskScore,\n"
            "  mitigation: Opinion?\n"
            "}\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(typed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_where_type_uses_native_dev_type_subset(self, tmp_path):
        typed = tmp_path / "type_where.axon"
        typed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(typed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_invalid_type_range_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(1.0..0.0)\n",
                "invalid_type_range_only.axon",
                {
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 1,
                },
            ),
            (
                "type RiskScore(1.0..0.0)\nrun Missing()\n",
                "invalid_type_range_run_missing.axon",
                {
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
            (
                "type RiskScore(1.0..0.0) where confidence >= 0.85\n"
                "type RiskScore(1.0..0.0) where confidence >= 0.90\n",
                "invalid_type_range_where_duplicate.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 2,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_mixed_type_flow_run_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_flow_run.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_mixed_type_where_flow_run_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_where_flow_run.axon"
        mixed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_type_with_prefixed_success_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_prefixed_success.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "anchor Safety { require: source_citation }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_type_where_with_prefixed_success_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_where_prefixed_success.axon"
        mixed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"\n',
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_type_with_structural_validation_uses_native_dev_local_error_path(self, tmp_path):
        mixed = tmp_path / "type_structural_validation.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "context Review { memory: invalid }\n"
            "run Missing() within Review\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        invalid_context_index = r.stdout.find(
            "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session"
        )
        undefined_flow_index = r.stdout.find("Undefined flow 'Missing' in run statement")
        assert invalid_context_index != -1
        assert undefined_flow_index != -1
        assert invalid_context_index < undefined_flow_index

    def test_check_type_where_with_structural_validation_uses_native_dev_local_error_path(self, tmp_path):
        mixed = tmp_path / "type_where_structural_validation.axon"
        mixed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "context Review { memory: invalid }\n"
            "run Missing() within Review\n",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(mixed),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        invalid_context_index = r.stdout.find(
            "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session"
        )
        undefined_flow_index = r.stdout.find("Undefined flow 'Missing' in run statement")
        assert invalid_context_index != -1
        assert undefined_flow_index != -1
        assert invalid_context_index < undefined_flow_index

    def test_check_type_with_isolated_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            ("type RiskScore(0.0..1.0)\nrun Missing()\n", "type_run_missing.axon"),
            (
                'type RiskScore(0.0..1.0)\nrun Missing() output_to: "report.json"\n',
                "type_run_output.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stdout.count("Undefined flow 'Missing' in run statement") == 1

    def test_check_type_where_with_isolated_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            ("type HighConfidenceClaim where confidence >= 0.85\nrun Missing()\n", "type_where_run_missing.axon"),
            (
                'type HighConfidenceClaim where confidence >= 0.85\nrun Missing() output_to: "report.json"\n',
                "type_where_run_output.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stdout.count("Undefined flow 'Missing' in run statement") == 1

    def test_check_type_with_clean_prefixed_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() as Expert\n",
                "type_persona_run_missing.axon",
            ),
            (
                "type RiskScore(0.0..1.0)\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun Missing() constrained_by [Safety]\n",
                "type_context_anchor_run_missing.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stdout.count("Undefined flow 'Missing' in run statement") == 1

    def test_check_type_where_with_clean_prefixed_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type HighConfidenceClaim where confidence >= 0.85\npersona Expert { tone: precise }\nrun Missing() as Expert\n",
                "type_where_persona_run_missing.axon",
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun Missing() constrained_by [Safety]\n",
                "type_where_context_anchor_run_missing.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stdout.count("Undefined flow 'Missing' in run statement") == 1

    def test_check_duplicate_type_declarations_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\n",
                "duplicate_type_only.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                },
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\n"
                "type HighConfidenceClaim where confidence >= 0.90\n",
                "duplicate_type_where_only.axon",
                {
                    "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)": 1,
                },
            ),
            (
                "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\nrun Missing()\n",
                "duplicate_type_run_missing.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\n"
                "type HighConfidenceClaim where confidence >= 0.90\n"
                "run Missing()\n",
                "duplicate_type_where_run_missing.axon",
                {
                    "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(mixed),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_block_signature_uses_native_dev_window(self, tmp_path):
        bad = tmp_path / "bad_persona_signature.axon"
        bad.write_text("persona { }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected IDENTIFIER, found LBRACE('{'))" in r.stderr

    def test_check_expanded_block_header_uses_native_dev_window(self, tmp_path):
        bad = tmp_path / "bad_shield_signature.axon"
        bad.write_text("shield { }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected IDENTIFIER, found LBRACE('{'))" in r.stderr

    def test_check_flow_parameter_start_uses_native_dev_fourth_token(self, tmp_path):
        bad = tmp_path / "bad_flow_param.axon"
        bad.write_text("flow Analyze({ }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected IDENTIFIER, found LBRACE('{'))" in r.stderr

    def test_check_block_field_missing_colon_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_persona_field.axon"
        bad.write_text("persona Expert { domain }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected COLON, found RBRACE('}'))" in r.stderr

    def test_check_identifier_like_block_value_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_persona_value.axon"
        bad.write_text("persona Expert { tone: ] }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Expected identifier or keyword value (found RBRACKET(']'))" in r.stderr

    def test_check_bool_block_value_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_persona_bool.axon"
        bad.write_text("persona Expert { cite_sources: ] }", encoding="utf-8")

        r = _run(
            "check",
            str(bad),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected BOOL, found RBRACKET(']'))" in r.stderr

    def test_check_simple_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "simple_import.axon"
        src.write_text("import SomeModule\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_dotted_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "dotted_import.axon"
        src.write_text("import a.b.c\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_named_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "named_import.axon"
        src.write_text("import a.b { X, Y }\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_import_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_flow_run.axon"
        src.write_text("import Utils\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_multi_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_import.axon"
        src.write_text("import A\nimport B\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_type_import_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "type_import_flow_run.axon"
        src.write_text("type Foo { x: String }\nimport bar\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_import_type_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_type_flow_run.axon"
        src.write_text("import bar\ntype Foo { x: String }\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_type_import_standalone_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "type_import_standalone.axon"
        src.write_text("type Score(0.0..1.0)\nimport bar\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_import_type_standalone_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_type_standalone.axon"
        src.write_text("import bar\ntype Score(0.0..1.0)\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_multi_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow.axon"
        src.write_text("flow A() {}\nflow B() {}\nrun A()\nrun B()\n", encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_multi_flow_run_with_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow_mod.axon"
        src.write_text('flow A() {}\nflow B() {}\nrun A() effort: high\nrun B() effort: low\n', encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_parameterized_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_flow.axon"
        src.write_text('flow Greet(name: String) {}\nrun Greet()\n', encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_parameterized_flow_run_with_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_flow_mod.axon"
        src.write_text('flow Greet(name: String) {}\nrun Greet() effort: high\n', encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_multi_flow_with_params_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow_params.axon"
        src.write_text('flow A(x: Int) {}\nflow B() {}\nrun A()\nrun B()\n', encoding="utf-8")

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_param_flow_with_referential_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_referential.axon"
        src.write_text(
            'persona Helper { tone: precise }\n'
            'flow Greet(name: String) {}\n'
            'run Greet() as Helper\n',
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(src),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_invalid_frontend_selection_returns_2(self):
        r = _run(
            "check",
            str(EXAMPLE),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "missing-frontend"},
        )
        assert r.returncode == 2
        assert "Frontend bootstrap failed" in r.stderr


# ══════════════════════════════════════════════════════════════════
#  axon compile
# ══════════════════════════════════════════════════════════════════


class TestCompile:
    """``axon compile`` produces IR JSON output."""

    def test_compile_stdout(self):
        r = _run("compile", str(EXAMPLE), "--stdout")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "node_type" in data
        assert data["node_type"] == "program"

    def test_compile_includes_meta(self):
        r = _run("compile", str(EXAMPLE), "--stdout")
        data = json.loads(r.stdout)
        assert "_meta" in data
        assert data["_meta"]["backend"] == "anthropic"
        assert "axon_version" in data["_meta"]

    def test_compile_to_file(self, tmp_path):
        src = tmp_path / "test.axon"
        src.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        out = tmp_path / "test.ir.json"
        r = _run("compile", str(src))
        assert r.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["node_type"] == "program"

    def test_compile_custom_output(self, tmp_path):
        out = tmp_path / "custom.json"
        r = _run("compile", str(EXAMPLE), "-o", str(out))
        assert r.returncode == 0
        assert out.exists()

    def test_compile_missing_file(self):
        r = _run("compile", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_compile_backend_flag(self):
        r = _run("compile", str(EXAMPLE), "--stdout", "-b", "openai")
        data = json.loads(r.stdout)
        assert data["_meta"]["backend"] == "openai"

    def test_compile_uses_native_dev_path_without_contract_regression(self):
        r = _run(
            "compile",
            str(EXAMPLE),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["node_type"] == "program"
        assert data["_meta"]["source"].endswith("examples/contract_analyzer.axon")

    def test_compile_invalid_syntax_uses_native_dev_preparser(self, tmp_path):
        bad = tmp_path / "bad_native_dev_compile.axon"
        bad.write_text("42 + garbage", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token at top level" in r.stderr
        assert "found 42" in r.stderr

    def test_compile_invalid_lexical_syntax_uses_native_dev_prefix_lexer(self, tmp_path):
        bad = tmp_path / "bad_native_dev_compile_lexer.axon"
        bad.write_text("/* unterminated", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unterminated block comment" in r.stderr

    def test_compile_structured_type_uses_native_dev_type_subset(self, tmp_path):
        typed = tmp_path / "type_struct.axon"
        typed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "type Risk {\n"
            "  score: RiskScore,\n"
            "  mitigation: Opinion?\n"
            "}\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(typed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["types"]) == 2
        assert data["types"][0]["name"] == "RiskScore"
        assert abs(data["types"][0]["range_min"] - 0.0) < 1e-9
        assert abs(data["types"][0]["range_max"] - 1.0) < 1e-9
        assert data["types"][1]["name"] == "Risk"
        assert data["types"][1]["fields"][1]["name"] == "mitigation"
        assert data["types"][1]["fields"][1]["optional"] is True

    def test_compile_where_type_uses_native_dev_type_subset(self, tmp_path):
        typed = tmp_path / "type_where.axon"
        typed.write_text(
            "type HighConfidenceClaim(0.0..1.0) where confidence >= 0.85 { claim: FactualClaim }\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(typed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["types"][0]["name"] == "HighConfidenceClaim"
        assert abs(data["types"][0]["range_min"] - 0.0) < 1e-9
        assert abs(data["types"][0]["range_max"] - 1.0) < 1e-9
        assert data["types"][0]["where_expression"] == "confidence >= 0.85"
        assert data["types"][0]["fields"][0]["name"] == "claim"

    def test_compile_invalid_type_range_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(1.0..0.0)\nflow SimpleFlow() {}\nrun SimpleFlow()\n",
                "invalid_type_range_success_compile.axon",
                {
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 1,
                },
            ),
            (
                "type RiskScore(1.0..0.0)\ncontext Review { memory: invalid }\nrun Missing() within Review\n",
                "invalid_type_range_structural_compile.axon",
                {
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
            (
                "type RiskScore(1.0..0.0) where confidence >= 0.85\n"
                "type RiskScore(1.0..0.0) where confidence >= 0.90\n",
                "invalid_type_range_where_duplicate_compile.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                    "Invalid range constraint in type 'RiskScore': min (1.0) must be less than max (0.0)": 2,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_mixed_type_flow_run_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_flow_run.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "type Risk {\n"
            "  score: RiskScore,\n"
            "  mitigation: Opinion?\n"
            "}\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [type_def["name"] for type_def in data["types"]] == ["RiskScore", "Risk"]
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert [run["flow_name"] for run in data["runs"]] == ["SimpleFlow"]
        assert data["runs"][0]["output_to"] == "report.json"

    def test_compile_mixed_type_where_flow_run_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_where_flow_run.axon"
        mixed.write_text(
            "type HighConfidenceClaim(0.0..1.0) where confidence >= 0.85\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [type_def["name"] for type_def in data["types"]] == ["HighConfidenceClaim"]
        assert abs(data["types"][0]["range_min"] - 0.0) < 1e-9
        assert abs(data["types"][0]["range_max"] - 1.0) < 1e-9
        assert data["types"][0]["where_expression"] == "confidence >= 0.85"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert [run["flow_name"] for run in data["runs"]] == ["SimpleFlow"]
        assert data["runs"][0]["output_to"] == "report.json"

    def test_compile_type_with_structural_prefixed_success_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_prefixed_success.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "type Risk {\n"
            "  score: RiskScore,\n"
            "  mitigation: Opinion?\n"
            "}\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [type_def["name"] for type_def in data["types"]] == ["RiskScore", "Risk"]
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert [run["flow_name"] for run in data["runs"]] == ["SimpleFlow"]
        assert data["runs"][0]["output_to"] == "report.json"

    def test_compile_type_where_with_structural_prefixed_success_uses_native_dev_subset(self, tmp_path):
        mixed = tmp_path / "type_where_prefixed_success.axon"
        mixed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "anchor Safety { require: source_citation }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: session }\n"
            "flow SimpleFlow() {}\n"
            'run SimpleFlow() output_to: "report.json"\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [type_def["name"] for type_def in data["types"]] == ["HighConfidenceClaim"]
        assert data["types"][0]["where_expression"] == "confidence >= 0.85"
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert [run["flow_name"] for run in data["runs"]] == ["SimpleFlow"]
        assert data["runs"][0]["output_to"] == "report.json"

    def test_compile_type_with_structural_duplicate_uses_native_dev_local_error_path(self, tmp_path):
        mixed = tmp_path / "type_structural_duplicate.axon"
        mixed.write_text(
            "type RiskScore(0.0..1.0)\n"
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: persistent }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow() within Review\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert (
            "Duplicate declaration: 'Review' already defined as context (first defined at line 3)"
            in r.stderr
        )

    def test_compile_type_where_with_structural_duplicate_uses_native_dev_local_error_path(self, tmp_path):
        mixed = tmp_path / "type_where_structural_duplicate.axon"
        mixed.write_text(
            "type HighConfidenceClaim where confidence >= 0.85\n"
            "anchor Safety { require: source_citation }\n"
            "context Review { memory: session }\n"
            "persona Expert { tone: precise }\n"
            "context Review { memory: persistent }\n"
            "flow SimpleFlow() {}\n"
            "run SimpleFlow()\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(mixed),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert (
            "Duplicate declaration: 'Review' already defined as context (first defined at line 3)"
            in r.stderr
        )

    def test_compile_type_with_isolated_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            ("type RiskScore(0.0..1.0)\nrun Missing()\n", "type_run_missing_compile.axon"),
            (
                "type RiskScore(0.0..1.0)\nrun Missing() on_failure: retry(backoff: exponential, attempts: 3)\n",
                "type_run_retry_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stderr.count("Undefined flow 'Missing' in run statement") == 1

    def test_compile_type_where_with_isolated_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            ("type HighConfidenceClaim where confidence >= 0.85\nrun Missing()\n", "type_where_run_missing_compile.axon"),
            (
                'type HighConfidenceClaim where confidence >= 0.85\nrun Missing() output_to: "report.json"\n',
                "type_where_run_output_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stderr.count("Undefined flow 'Missing' in run statement") == 1

    def test_compile_type_with_clean_prefixed_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() as Expert\n",
                "type_persona_run_missing_compile.axon",
            ),
            (
                'type RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() output_to: "report.json"\n',
                "type_persona_run_output_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stderr.count("Undefined flow 'Missing' in run statement") == 1

    def test_compile_type_where_with_clean_prefixed_run_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type HighConfidenceClaim where confidence >= 0.85\npersona Expert { tone: precise }\nrun Missing() as Expert\n",
                "type_where_persona_run_missing_compile.axon",
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun Missing() constrained_by [Safety]\n",
                "type_where_context_anchor_run_missing_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert r.stderr.count("Undefined flow 'Missing' in run statement") == 1

    def test_compile_duplicate_type_declarations_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\nflow SimpleFlow() {}\nrun SimpleFlow()\n",
                "duplicate_type_success_compile.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                },
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\n"
                "type HighConfidenceClaim where confidence >= 0.90\n"
                "flow SimpleFlow() {}\n"
                "run SimpleFlow()\n",
                "duplicate_type_where_success_compile.axon",
                {
                    "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)": 1,
                },
            ),
            (
                "type RiskScore(0.0..1.0)\ntype RiskScore(0.0..1.0)\npersona Expert { tone: precise }\nrun Missing() as Expert\n",
                "duplicate_type_prefixed_run_missing_compile.axon",
                {
                    "Duplicate declaration: 'RiskScore' already defined as type (first defined at line 1)": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
            (
                "type HighConfidenceClaim where confidence >= 0.85\n"
                "type HighConfidenceClaim where confidence >= 0.90\n"
                "persona Expert { tone: precise }\n"
                "run Missing() as Expert\n",
                "duplicate_type_where_prefixed_run_missing_compile.axon",
                {
                    "Duplicate declaration: 'HighConfidenceClaim' already defined as type (first defined at line 1)": 1,
                    "Undefined flow 'Missing' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            mixed = tmp_path / filename
            mixed.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(mixed),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_paren_signature_uses_native_dev_window(self, tmp_path):
        bad = tmp_path / "bad_run_signature.axon"
        bad.write_text("run AnalyzeContract { }", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected LPAREN, found LBRACE('{'))" in r.stderr

    def test_compile_expanded_block_header_uses_native_dev_window(self, tmp_path):
        bad = tmp_path / "bad_endpoint_signature.axon"
        bad.write_text("axonendpoint { }", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected IDENTIFIER, found LBRACE('{'))" in r.stderr

    def test_compile_flow_parameter_start_uses_native_dev_fourth_token(self, tmp_path):
        bad = tmp_path / "bad_flow_param_compile.axon"
        bad.write_text("flow Analyze(, )", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected IDENTIFIER, found COMMA(','))" in r.stderr

    def test_compile_block_field_missing_colon_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_shield_field.axon"
        bad.write_text("shield Edge { scan }", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected COLON, found RBRACE('}'))" in r.stderr

    def test_compile_identifier_like_block_value_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_context_value.axon"
        bad.write_text("context Review { memory: }", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Expected identifier or keyword value (found RBRACE('}'))" in r.stderr

    def test_compile_bool_block_value_uses_native_dev_body_guard(self, tmp_path):
        bad = tmp_path / "bad_tool_bool.axon"
        bad.write_text("tool Search { sandbox: }", encoding="utf-8")

        r = _run(
            "compile",
            str(bad),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Unexpected token (expected BOOL, found RBRACE('}'))" in r.stderr

    def test_compile_run_argument_variants_stay_on_python_path_under_native_dev(self, tmp_path):
        source = tmp_path / "run_variants.axon"
        source.write_text(
            "flow Execute() {}\n"
            'run Execute()\n'
            'run Execute("report.json")\n'
            'run Execute(5)\n'
            'run Execute(report.pdf)\n'
            'run Execute(depth: 3)\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["runs"]) == 5
        assert data["runs"][0]["arguments"] == []
        assert data["runs"][1]["arguments"] == ["report.json"]
        assert data["runs"][2]["arguments"] == ["5"]
        assert data["runs"][3]["arguments"] == ["report.pdf"]
        assert data["runs"][4]["arguments"] == ["depth", ":", "3"]

    def test_check_minimal_standalone_run_uses_native_dev_subset(self, tmp_path):
        source = tmp_path / "run_only.axon"
        source.write_text("run SimpleFlow()", encoding="utf-8")

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Undefined flow 'SimpleFlow' in run statement" in r.stdout

    def test_compile_minimal_standalone_run_uses_native_dev_subset(self, tmp_path):
        source = tmp_path / "run_only_compile.axon"
        source.write_text("run SimpleFlow()", encoding="utf-8")

        r = _run(
            "compile",
            str(source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_check_isolated_run_argument_variants_use_native_dev_subset(self, tmp_path):
        cases = [
            ('run SimpleFlow("report.json")', "run_string.axon"),
            ("run SimpleFlow(5)", "run_number.axon"),
            ("run SimpleFlow(report.pdf)", "run_dotted.axon"),
            ("run SimpleFlow(depth: 3)", "run_kv.axon"),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stdout

    def test_compile_isolated_run_argument_variants_use_native_dev_subset(self, tmp_path):
        cases = [
            ('run SimpleFlow("report.json")', "run_string_compile.axon"),
            ("run SimpleFlow(5)", "run_number_compile.axon"),
            ("run SimpleFlow(report.pdf)", "run_dotted_compile.axon"),
            ("run SimpleFlow(depth: 3)", "run_kv_compile.axon"),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_check_supported_isolated_run_modifiers_use_native_dev_subset(self, tmp_path):
        cases = [
            ('run SimpleFlow() output_to: "report.json"', "run_output.axon"),
            ("run SimpleFlow() effort: high", "run_effort.axon"),
            ("run SimpleFlow() on_failure: log", "run_on_failure_log.axon"),
            ("run SimpleFlow() on_failure: retry", "run_on_failure_retry.axon"),
            (
                "run SimpleFlow() on_failure: raise AnchorBreachError",
                "run_on_failure_raise.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stdout

    def test_compile_supported_isolated_run_modifiers_use_native_dev_subset(self, tmp_path):
        cases = [
            ('run SimpleFlow() output_to: "report.json"', "run_output_compile.axon"),
            ("run SimpleFlow() effort: high", "run_effort_compile.axon"),
            ("run SimpleFlow() on_failure: log", "run_on_failure_log_compile.axon"),
            ("run SimpleFlow() on_failure: retry", "run_on_failure_retry_compile.axon"),
            (
                "run SimpleFlow() on_failure: raise AnchorBreachError",
                "run_on_failure_raise_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential)",
                "run_on_failure_retry_param_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "run_on_failure_retry_two_params_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
                "run_on_failure_retry_three_params_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
                "run_on_failure_retry_four_params_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
                "run_on_failure_retry_five_params_compile.axon",
            ),
            (
                "run SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe, budget: low)",
                "run_on_failure_retry_six_params_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_check_shared_block_prefixed_run_uses_native_dev_subset(self, tmp_path):
        cases = [
            ("persona Expert { tone: precise }\nrun SimpleFlow()", "persona_run.axon"),
            ("persona Expert { tone: precise }\nrun SimpleFlow() as Expert", "persona_run_as.axon"),
            ('persona Expert { tone: precise }\nrun SimpleFlow() output_to: "report.json"', "persona_run_output.axon"),
            ("persona Expert { tone: precise }\nrun SimpleFlow() on_failure: log", "persona_run_on_failure_log.axon"),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "persona_run_on_failure_raise.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "persona_run_on_failure_retry_param.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "persona_run_on_failure_retry_two_params.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
                "persona_run_on_failure_retry_three_params.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
                "persona_run_on_failure_retry_four_params.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
                "persona_run_on_failure_retry_five_params.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow()",
                "persona_context_run.axon",
            ),
            (
                "context Review { memory: session }\nrun SimpleFlow() within Review",
                "context_run_within.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() as Expert",
                "persona_context_run_as.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() within Review",
                "persona_context_run_within.axon",
            ),
            (
                "anchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
                "anchor_run_constrained.axon",
            ),
            (
                "anchor Safety { require: source_citation }\nanchor Grounding { require: source_citation }\nrun SimpleFlow() constrained_by [Safety, Grounding]",
                "anchor_anchor_run_constrained.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
                "persona_context_anchor_run_constrained.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry",
                "persona_context_run_on_failure_retry.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "persona_context_run_on_failure_raise.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "persona_context_run_on_failure_retry_param.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "persona_context_run_on_failure_retry_two_params.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
                "persona_context_run_on_failure_retry_three_params.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
                "persona_context_run_on_failure_retry_four_params.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
                "persona_context_run_on_failure_retry_five_params.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe, budget: low)",
                "persona_context_run_on_failure_retry_six_params.axon",
            ),
            (
                'persona Expert { tone: precise }\nanchor Safety { require: source_citation }\nrun SimpleFlow() output_to: "report.json"',
                "persona_anchor_run_output.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stdout

    def test_compile_shared_block_prefixed_run_uses_native_dev_subset(self, tmp_path):
        cases = [
            ("persona Expert { tone: precise }\nrun SimpleFlow()", "persona_run_compile.axon"),
            ("persona Expert { tone: precise }\nrun SimpleFlow() as Expert", "persona_run_as_compile.axon"),
            ('persona Expert { tone: precise }\nrun SimpleFlow() output_to: "report.json"', "persona_run_output_compile.axon"),
            ("persona Expert { tone: precise }\nrun SimpleFlow() on_failure: log", "persona_run_on_failure_log_compile.axon"),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "persona_run_on_failure_raise_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "persona_run_on_failure_retry_param_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "persona_run_on_failure_retry_two_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
                "persona_run_on_failure_retry_three_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
                "persona_run_on_failure_retry_four_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
                "persona_run_on_failure_retry_five_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow()",
                "persona_context_run_compile.axon",
            ),
            (
                "context Review { memory: session }\nrun SimpleFlow() within Review",
                "context_run_within_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() as Expert",
                "persona_context_run_as_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() within Review",
                "persona_context_run_within_compile.axon",
            ),
            (
                "anchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
                "anchor_run_constrained_compile.axon",
            ),
            (
                "anchor Safety { require: source_citation }\nanchor Grounding { require: source_citation }\nrun SimpleFlow() constrained_by [Safety, Grounding]",
                "anchor_anchor_run_constrained_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
                "persona_context_anchor_run_constrained_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry",
                "persona_context_run_on_failure_retry_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "persona_context_run_on_failure_raise_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "persona_context_run_on_failure_retry_param_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "persona_context_run_on_failure_retry_two_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full)",
                "persona_context_run_on_failure_retry_three_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high)",
                "persona_context_run_on_failure_retry_four_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe)",
                "persona_context_run_on_failure_retry_five_params_compile.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, jitter: full, cap: high, mode: safe, budget: low)",
                "persona_context_run_on_failure_retry_six_params_compile.axon",
            ),
            (
                'persona Expert { tone: precise }\nanchor Safety { require: source_citation }\nrun SimpleFlow() output_to: "report.json"',
                "persona_anchor_run_output_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_compile_prefixed_success_case_with_repeated_constrained_by_anchors_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_constrained_repeated_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Safety]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["anchor_names"] == ["Safety", "Safety"]
        assert [anchor["name"] for anchor in data["runs"][0]["resolved_anchors"]] == ["Safety", "Safety"]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_structural_duplicate_anchor_declaration_uses_native_dev_local_error_path(self, tmp_path):
        source = tmp_path / "duplicate_anchor_structural_compile.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)" in r.stderr

    def test_compile_structural_duplicate_persona_or_context_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\npersona Expert { tone: formal }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_structural_compile.axon",
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\ncontext Review { memory: persistent }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_structural_compile.axon",
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
            ),
        ]

        for source_text, filename, expected_message in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert expected_message in r.stderr

    def test_compile_structural_multiple_clean_duplicates_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\npersona Expert { tone: formal }\ncontext Review { memory: persistent }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "multiple_duplicate_persona_context_compile.axon",
                [
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                ],
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: formal }\ncontext Review { memory: persistent }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "multiple_duplicate_all_compile.axon",
                [
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 3)",
                ],
            ),
        ]

        for source_text, filename, expected_messages in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message in expected_messages:
                assert expected_message in r.stderr

    def test_compile_structural_nonclean_duplicate_context_combinations_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "context Review { memory: invalid }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_first_invalid_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\ncontext Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_both_invalid_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 2,
                },
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\ncontext Review { memory: archive }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)": 1,
                    "Unknown memory scope 'archive' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\npersona Expert { tone: formal }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "nonclean_duplicate_persona_context_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 2,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_invalid_context_memory_without_duplicates_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "context Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_structural_compile.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_structural_prefixed_compile.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\nrun SimpleFlow() within Review",
                "invalid_context_undefined_flow_compile.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nrun SimpleFlow() within Review",
                "invalid_context_prefixed_undefined_flow_compile.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_check_structural_context_depth_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_depth_success_check.axon"
        success_source.write_text(
            "context Review { depth: deep }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        cases = [
            (
                "context Review { depth: abyss }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_depth_check.axon",
                {
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 1,
                },
            ),
            (
                "context Review { depth: abyss }\nrun SimpleFlow() within Review",
                "invalid_context_depth_undefined_flow_check.axon",
                {
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "context Review { depth: abyss }\ncontext Review { depth: deep }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_invalid_depth_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_anchor_enforce_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_enforce_success_check.axon"
        success_source.write_text(
            "anchor Safety { enforce: strict }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        cases = [
            (
                "anchor Safety { enforce: strict }\nanchor Safety { enforce: soft }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_enforce_check.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { depth: deep }\nanchor Safety { enforce: strict }\nanchor Safety { enforce: soft }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_enforce_with_context_check.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 2)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_cite_sources_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { cite_sources: true }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_cite_sources_success_check.axon",
            ),
            (
                "context Review { cite_sources: true }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "context_cite_sources_success_check.axon",
            ),
        ]

        for source_text, filename in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            assert "0 errors" in success.stdout

        cases = [
            (
                "persona Expert { cite_sources: true }\npersona Expert { cite_sources: false }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_cite_sources_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { cite_sources: true }\ncontext Review { cite_sources: false }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_cite_sources_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_compile_structural_context_depth_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_depth_success_compile.axon"
        success_source.write_text(
            "context Review { depth: deep }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["memory_scope"] == ""
        assert data["contexts"][0]["depth"] == "deep"
        assert data["runs"][0]["context_name"] == "Review"
        assert data["runs"][0]["resolved_context"]["name"] == "Review"
        assert data["runs"][0]["resolved_context"]["depth"] == "deep"

        cases = [
            (
                "context Review { depth: abyss }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_depth_compile.axon",
                {
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 1,
                },
            ),
            (
                "context Review { depth: abyss }\nrun SimpleFlow() within Review",
                "invalid_context_depth_undefined_flow_compile.axon",
                {
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "context Review { depth: abyss }\ncontext Review { depth: abyss }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_invalid_depth_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown depth 'abyss' in context 'Review'. Valid: deep, exhaustive, shallow, standard": 2,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_cite_sources_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { cite_sources: true }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_cite_sources_success_compile.axon",
                "persona",
            ),
            (
                "context Review { cite_sources: true }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "context_cite_sources_success_compile.axon",
                "context",
            ),
        ]

        for source_text, filename, kind in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            data = json.loads(success.stdout)
            if kind == "persona":
                assert [persona["name"] for persona in data["personas"]] == ["Expert"]
                assert data["personas"][0]["cite_sources"] is True
                assert data["runs"][0]["persona_name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["cite_sources"] is True
            else:
                assert [context["name"] for context in data["contexts"]] == ["Review"]
                assert data["contexts"][0]["cite_sources"] is True
                assert data["runs"][0]["context_name"] == "Review"
                assert data["runs"][0]["resolved_context"]["name"] == "Review"
                assert data["runs"][0]["resolved_context"]["cite_sources"] is True

        cases = [
            (
                "persona Expert { cite_sources: true }\npersona Expert { cite_sources: false }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_cite_sources_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { cite_sources: true }\ncontext Review { cite_sources: false }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_cite_sources_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_anchor_enforce_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_enforce_success_compile.axon"
        success_source.write_text(
            "anchor Safety { enforce: strict }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["require"] == ""
        assert data["anchors"][0]["enforce"] == "strict"
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert [anchor["name"] for anchor in data["runs"][0]["resolved_anchors"]] == ["Safety"]

        cases = [
            (
                "anchor Safety { enforce: strict }\nanchor Safety { enforce: soft }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_enforce_compile.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { depth: deep }\nanchor Safety { enforce: strict }\nanchor Safety { enforce: soft }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_enforce_with_context_compile.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 2)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_persona_context_validation_without_duplicates_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_structural_compile.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_with_context_anchor_compile.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\nrun SimpleFlow() as Expert",
                "invalid_persona_undefined_flow_compile.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_context_compile.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_persona_compile.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\nrun SimpleFlow() as Expert",
                "invalid_persona_context_undefined_flow_compile.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_duplicate_persona_with_invalid_tone_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: invalid }\npersona Expert { tone: formal }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_first_invalid_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: formal }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_second_invalid_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_both_invalid_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 2,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\npersona Expert { tone: formal }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_invalid_tone_context_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_compile_structural_prefixed_flow_run_in_supported_alternate_order_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "anchor_persona_context_flow_run_compile.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]

    def test_check_structural_language_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { language: \"es\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_language_success_check.axon",
            ),
            (
                "context Review { language: \"es\" }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "context_language_success_check.axon",
            ),
        ]

        for source_text, filename in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            assert "0 errors" in success.stdout

        cases = [
            (
                "persona Expert { language: \"es\" }\npersona Expert { language: \"en\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_language_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { language: \"es\" }\ncontext Review { language: \"en\" }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_language_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_compile_structural_prefixed_flow_run_with_nonreferential_modifiers_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"",
                "structural_output_compile.axon",
                "report.json",
                "",
                "",
                [],
            ),
            (
                "context Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() effort: high",
                "structural_effort_compile.axon",
                "",
                "high",
                "",
                [],
            ),
            (
                "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: log",
                "structural_on_failure_log_compile.axon",
                "",
                "",
                "log",
                [],
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "structural_on_failure_raise_compile.axon",
                "",
                "",
                "raise",
                [["target", "AnchorBreachError"]],
            ),
            (
                "context Review { memory: session }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "structural_on_failure_retry_compile.axon",
                "",
                "",
                "retry",
                [["backoff", "exponential"], ["attempts", "3"]],
            ),
        ]

        for source_text, filename, expected_output_to, expected_effort, expected_on_failure, expected_params in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["output_to"] == expected_output_to
            assert data["runs"][0]["effort"] == expected_effort
            assert data["runs"][0]["on_failure"] == expected_on_failure
            assert data["runs"][0]["on_failure_params"] == expected_params
            assert data["runs"][0]["persona_name"] == ""
            assert data["runs"][0]["context_name"] == ""
            assert data["runs"][0]["anchor_names"] == []
            assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_structural_language_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { language: \"es\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_language_success_compile.axon",
                "persona",
            ),
            (
                "context Review { language: \"es\" }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "context_language_success_compile.axon",
                "context",
            ),
        ]

        for source_text, filename, kind in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            data = json.loads(success.stdout)
            if kind == "persona":
                assert [persona["name"] for persona in data["personas"]] == ["Expert"]
                assert data["personas"][0]["language"] == "es"
                assert data["runs"][0]["persona_name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["language"] == "es"
            else:
                assert [context["name"] for context in data["contexts"]] == ["Review"]
                assert data["contexts"][0]["language"] == "es"
                assert data["runs"][0]["context_name"] == "Review"
                assert data["runs"][0]["resolved_context"]["name"] == "Review"
                assert data["runs"][0]["resolved_context"]["language"] == "es"

        cases = [
            (
                "persona Expert { language: \"es\" }\npersona Expert { language: \"en\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_language_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "context Review { language: \"es\" }\ncontext Review { language: \"en\" }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_language_compile.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_check_structural_description_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { description: \"Analista\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_description_success_check.axon",
            ),
            (
                "anchor Safety { description: \"No hallucinate\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "anchor_description_success_check.axon",
            ),
        ]

        for source_text, filename in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            assert "0 errors" in success.stdout

        cases = [
            (
                "persona Expert { description: \"Analista\" }\npersona Expert { description: \"Otro\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_description_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "anchor Safety { description: \"A\" }\nanchor Safety { description: \"B\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_description_check.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_compile_structural_description_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_cases = [
            (
                "persona Expert { description: \"Analista\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "persona_description_success_compile.axon",
                "persona",
            ),
            (
                "anchor Safety { description: \"No hallucinate\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "anchor_description_success_compile.axon",
                "anchor",
            ),
        ]

        for source_text, filename, kind in success_cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            success = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert success.returncode == 0
            data = json.loads(success.stdout)
            if kind == "persona":
                assert [persona["name"] for persona in data["personas"]] == ["Expert"]
                assert data["personas"][0]["description"] == "Analista"
                assert data["runs"][0]["persona_name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
                assert data["runs"][0]["resolved_persona"]["description"] == "Analista"
            else:
                assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
                assert data["anchors"][0]["description"] == "No hallucinate"
                assert data["runs"][0]["anchor_names"] == ["Safety"]
                assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
                assert data["runs"][0]["resolved_anchors"][0]["description"] == "No hallucinate"

        cases = [
            (
                "persona Expert { description: \"Analista\" }\npersona Expert { description: \"Otro\" }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_description_compile.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                },
            ),
            (
                "anchor Safety { description: \"A\" }\nanchor Safety { description: \"B\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "duplicate_anchor_description_compile.axon",
                {
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stderr.count(expected_message) == expected_count

    def test_check_structural_unknown_response_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_unknown_response_success_check.axon"
        success_source.write_text(
            "anchor Safety { unknown_response: \"No se\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        source = tmp_path / "duplicate_anchor_unknown_response_check.axon"
        source.write_text(
            "anchor Safety { unknown_response: \"A\" }\nanchor Safety { unknown_response: \"B\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert r.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1

    def test_check_structural_max_tokens_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_max_tokens_success_check.axon"
        success_source.write_text(
            "context Review { max_tokens: 256 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "context_max_tokens_invalid_check.axon"
        invalid_source.write_text(
            "context Review { max_tokens: 0 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("max_tokens must be positive, got 0 in context 'Review'") == 1

        missing_flow_source = tmp_path / "context_max_tokens_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "context Review { max_tokens: 0 }\nrun Missing() within Review",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("max_tokens must be positive, got 0 in context 'Review'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_context_max_tokens_check.axon"
        duplicate_source.write_text(
            "context Review { max_tokens: 0 }\ncontext Review { max_tokens: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Review' already defined as context (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("max_tokens must be positive, got 0 in context 'Review'") == 1

    def test_check_structural_temperature_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_temperature_success_check.axon"
        success_source.write_text(
            "context Review { temperature: 1.2 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "context_temperature_invalid_check.axon"
        invalid_source.write_text(
            "context Review { temperature: 2.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("temperature must be between 0.0 and 2.0, got 2.5") == 1

        missing_flow_source = tmp_path / "context_temperature_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "context Review { temperature: 2.5 }\nrun Missing() within Review",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("temperature must be between 0.0 and 2.0, got 2.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_context_temperature_check.axon"
        duplicate_source.write_text(
            "context Review { temperature: 2.5 }\ncontext Review { temperature: 1.2 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Review' already defined as context (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("temperature must be between 0.0 and 2.0, got 2.5") == 1

    def test_check_structural_confidence_threshold_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_confidence_threshold_success_check.axon"
        success_source.write_text(
            "persona Expert { confidence_threshold: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "persona_confidence_threshold_invalid_check.axon"
        invalid_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "persona_confidence_threshold_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\nrun Missing() as Expert",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_confidence_threshold_check.axon"
        duplicate_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\npersona Expert { confidence_threshold: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1

    def test_check_structural_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_confidence_floor_success_check.axon"
        success_source.write_text(
            "anchor Safety { confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "anchor_confidence_floor_invalid_check.axon"
        invalid_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "anchor_confidence_floor_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_confidence_floor_check.axon"
        duplicate_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nanchor Safety { confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_check_structural_on_violation_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_success_check.axon"
        success_source.write_text(
            "anchor Safety { on_violation: warn }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "anchor_on_violation_invalid_check.axon"
        invalid_source.write_text(
            "anchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

        missing_flow_source = tmp_path / "anchor_on_violation_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: explode }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_check.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: explode }\nanchor Safety { on_violation: warn }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_check_structural_on_violation_raise_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_raise_success_check.axon"
        success_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "anchor_on_violation_raise_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_raise_check.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nanchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_check_structural_on_violation_fallback_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_fallback_success_check.axon"
        success_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "anchor_on_violation_fallback_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_fallback_check.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nanchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_check_structural_reject_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_reject_success_check.axon"
        success_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "anchor_reject_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_reject_check.axon"
        duplicate_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nanchor Safety { reject: [hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1

    def test_check_structural_refuse_if_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_refuse_if_success_check.axon"
        success_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "persona_refuse_if_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\nrun Missing() as Expert",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_refuse_if_check.axon"
        duplicate_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\npersona Expert { refuse_if: [hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1

    def test_check_structural_domain_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_domain_success_check.axon"
        success_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "persona_domain_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\nrun Missing() as Expert',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_domain_check.axon"
        duplicate_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\npersona Expert { domain: ["policy"] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1

    def test_check_structural_memory_store_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_store_success_check.axon"
        success_source.write_text(
            "memory SessionMemory { store: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "memory_store_invalid_check.axon"
        invalid_source.write_text(
            "memory SessionMemory { store: remote }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1

        missing_flow_source = tmp_path / "memory_store_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { store: remote }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_store_check.axon"
        duplicate_source.write_text(
            "memory SessionMemory { store: remote }\nmemory SessionMemory { store: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1

    def test_check_structural_memory_backend_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_backend_success_check.axon"
        success_source.write_text(
            "memory SessionMemory { backend: redis }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "memory_backend_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { backend: redis }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_backend_check.axon"
        duplicate_source.write_text(
            "memory SessionMemory { backend: redis }\nmemory SessionMemory { backend: in_memory }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1

    def test_check_structural_memory_retrieval_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_retrieval_success_check.axon"
        success_source.write_text(
            "memory SessionMemory { retrieval: semantic }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "memory_retrieval_invalid_check.axon"
        invalid_source.write_text(
            "memory SessionMemory { retrieval: vector }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1

        missing_flow_source = tmp_path / "memory_retrieval_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { retrieval: vector }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_retrieval_check.axon"
        duplicate_source.write_text(
            "memory SessionMemory { retrieval: vector }\nmemory SessionMemory { retrieval: semantic }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1

    def test_check_structural_memory_decay_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_decay_duration_success_check.axon"
        success_source.write_text(
            "memory SessionMemory { decay: 5m }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "memory_decay_duration_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { decay: 5m }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_decay_check.axon"
        duplicate_source.write_text(
            "memory SessionMemory { decay: 5m }\nmemory SessionMemory { decay: daily }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_provider_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_provider_success_check.axon"
        success_source.write_text(
            "tool Search { provider: brave }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_provider_check.axon"
        duplicate_source.write_text(
            "tool Search { provider: brave }\ntool Search { provider: serpapi }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_runtime_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_runtime_success_check.axon"
        success_source.write_text(
            "tool Search { runtime: hosted }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_runtime_check.axon"
        duplicate_source.write_text(
            "tool Search { runtime: hosted }\ntool Search { runtime: local }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_sandbox_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_sandbox_success_check.axon"
        success_source.write_text(
            "tool Search { sandbox: true }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_sandbox_check.axon"
        duplicate_source.write_text(
            "tool Search { sandbox: true }\ntool Search { sandbox: false }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_timeout_success_check.axon"
        success_source.write_text(
            "tool Search { timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_timeout_check.axon"
        duplicate_source.write_text(
            "tool Search { timeout: 10s }\ntool Search { timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_max_results_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_max_results_success_check.axon"
        success_source.write_text(
            "tool Search { max_results: 3 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "tool_max_results_invalid_check.axon"
        invalid_source.write_text(
            "tool Search { max_results: 0 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("max_results must be positive, got 0 in tool 'Search'") == 1

        missing_flow_source = tmp_path / "tool_max_results_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "tool Search { max_results: 0 }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("max_results must be positive, got 0 in tool 'Search'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_tool_max_results_check.axon"
        duplicate_source.write_text(
            "tool Search { max_results: 0 }\ntool Search { max_results: 3 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("max_results must be positive, got 0 in tool 'Search'") == 1

    def test_check_structural_tool_filter_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_filter_success_check.axon"
        success_source.write_text(
            "tool Search { filter: recent }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_filter_check.axon"
        duplicate_source.write_text(
            "tool Search { filter: recent }\ntool Search { filter: broad }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_filter_call_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_filter_call_success_check.axon"
        success_source.write_text(
            "tool Search { filter: recent(days: 30) }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_tool_filter_call_check.axon"
        duplicate_source.write_text(
            "tool Search { filter: recent(days: 30) }\ntool Search { filter: recent(days: 7) }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_tool_effects_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_effects_success_check.axon"
        success_source.write_text(
            "tool Search { effects: <network, epistemic:know> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_effect_source = tmp_path / "tool_effects_invalid_effect_check.axon"
        invalid_effect_source.write_text(
            "tool Search { effects: <oops> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid_effect = _run(
            "check",
            str(invalid_effect_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_effect.returncode == 1
        assert invalid_effect.stdout.count(
            "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage"
        ) == 1

        invalid_level_source = tmp_path / "tool_effects_invalid_level_check.axon"
        invalid_level_source.write_text(
            "tool Search { effects: <network, epistemic:guess> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid_level = _run(
            "check",
            str(invalid_level_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_level.returncode == 1
        assert invalid_level.stdout.count(
            "Unknown epistemic level 'guess' in tool 'Search'. Valid levels: believe, doubt, know, speculate"
        ) == 1

        missing_flow_source = tmp_path / "tool_effects_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            "tool Search { effects: <oops> }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count(
            "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage"
        ) == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_tool_effects_check.axon"
        duplicate_source.write_text(
            "tool Search { effects: <network, epistemic:know> }\ntool Search { effects: <io> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_check_structural_intent_ask_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_ask_success_check.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_intent_ask_check.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" }\nintent Extract { ask: "B?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_check_structural_intent_given_ask_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_success_check.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        duplicate_source = tmp_path / "duplicate_intent_given_ask_check.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" }\nintent Extract { given: Contract ask: "B?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_check_structural_intent_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_confidence_floor_success_check.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "intent_confidence_floor_invalid_check.axon"
        invalid_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_confidence_floor_invalid_undefined_check.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_confidence_floor_check.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" confidence_floor: 1.5 }\nintent Extract { ask: "B?" confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_check_structural_intent_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_output_success_check.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" output: List<Party>? }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "intent_output_undefined_check.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_output_check.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" output: Party }\nintent Extract { ask: "B?" output: MissingType }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_check_structural_intent_given_ask_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_output_success_check.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: List<Party>? }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "intent_given_ask_output_undefined_check.axon"
        missing_flow_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_given_ask_output_check.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" output: Party }\nintent Extract { given: Contract ask: "B?" output: MissingType }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_check_structural_intent_given_ask_output_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_output_confidence_floor_success_check.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "intent_given_ask_output_confidence_floor_invalid_check.axon"
        invalid_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_given_ask_output_confidence_floor_invalid_undefined_check.axon"
        missing_flow_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_given_ask_output_confidence_floor_check.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" output: Party confidence_floor: 1.5 }\nintent Extract { given: Contract ask: "B?" output: MissingType confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_check_structural_intent_output_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_output_confidence_floor_success_check.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "intent_output_confidence_floor_invalid_check.axon"
        invalid_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_output_confidence_floor_invalid_undefined_check.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_output_confidence_floor_check.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" output: Party confidence_floor: 1.5 }\nintent Extract { ask: "B?" output: MissingType confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_check_structural_axonendpoint_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_method_source = tmp_path / "endpoint_invalid_method_check.axon"
        invalid_method_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid_method = _run(
            "check",
            str(invalid_method_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_method.returncode == 1
        assert invalid_method.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

        invalid_path_source = tmp_path / "endpoint_invalid_path_check.axon"
        invalid_path_source.write_text(
            'axonendpoint Api { method: post path: "x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid_path = _run(
            "check",
            str(invalid_path_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_path.returncode == 1
        assert invalid_path.stdout.count("axonendpoint 'Api' path must start with '/': got 'x'") == 1

        missing_flow_source = tmp_path / "endpoint_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_output_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Party }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_body_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_retries_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_retries_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_retries_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_retries_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_retries_timeout_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_retries_timeout_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_retries_timeout_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_output_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_output_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_output_shield_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_body_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_shield_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_body_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_timeout_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_shield_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_timeout_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_timeout_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_output_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_timeout_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_output_shield_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_timeout_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_timeout_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_output_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_retries_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_output_shield_retries_invalid_check.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_shield_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_retries_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_retries_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_retries_invalid_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_retries_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_body_shield_retries_invalid_check.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_shield_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_retries_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_retries_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_retries_invalid_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_body_output_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_output_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_body_output_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_retries_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_body_output_retries_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_output_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_retries_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_retries_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_body_retries_timeout_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_retries_timeout_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_retries_timeout_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_output_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_shield_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_body_output_shield_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_output_shield_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_output_shield_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_shield_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_output_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_retries_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_output_retries_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_retries_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_body_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_retries_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_body_retries_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_retries_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_output_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_output_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Result timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_timeout_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_shield_timeout_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_timeout_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_timeout_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_shield_timeout_invalid_method_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_check_structural_axonendpoint_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_retries_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_shield_retries_invalid_check.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_shield_retries_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_retries_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_retries_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_shield_retries_invalid_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_check_structural_axonendpoint_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_success_check.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        missing_flow_source = tmp_path / "endpoint_shield_missing_flow_check.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_undefined_check.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "check",
            str(undefined_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stdout.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_not_a_shield_check.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "check",
            str(not_a_shield_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stdout.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_shield_endpoint_check.axon"
        duplicate_source.write_text(
            'shield Safety { }\nshield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Safety' already defined as shield (first defined at line 1)"
        ) == 1

    def test_compile_structural_unknown_response_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_unknown_response_success_compile.axon"
        success_source.write_text(
            "anchor Safety { unknown_response: \"No se\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["unknown_response"] == "No se"
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["unknown_response"] == "No se"

        source = tmp_path / "duplicate_anchor_unknown_response_compile.axon"
        source.write_text(
            "anchor Safety { unknown_response: \"A\" }\nanchor Safety { unknown_response: \"B\" }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert r.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1

    def test_compile_structural_max_tokens_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_max_tokens_success_compile.axon"
        success_source.write_text(
            "context Review { max_tokens: 256 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["max_tokens"] == 256
        assert data["runs"][0]["context_name"] == "Review"
        assert data["runs"][0]["resolved_context"]["name"] == "Review"
        assert data["runs"][0]["resolved_context"]["max_tokens"] == 256

        invalid_source = tmp_path / "context_max_tokens_invalid_compile.axon"
        invalid_source.write_text(
            "context Review { max_tokens: 0 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("max_tokens must be positive, got 0 in context 'Review'") == 1

        missing_flow_source = tmp_path / "context_max_tokens_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "context Review { max_tokens: 0 }\nrun Missing() within Review",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("max_tokens must be positive, got 0 in context 'Review'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_context_max_tokens_compile.axon"
        duplicate_source.write_text(
            "context Review { max_tokens: 0 }\ncontext Review { max_tokens: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Review' already defined as context (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("max_tokens must be positive, got 0 in context 'Review'") == 1

    def test_check_structural_axonendpoint_output_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_retries_timeout_success_check.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "check",
            str(success_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        assert "0 errors" in success.stdout

        invalid_source = tmp_path / "endpoint_output_retries_timeout_invalid_check.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "check",
            str(invalid_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_retries_timeout_invalid_undefined_flow_check.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "check",
            str(missing_flow_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stdout.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_retries_timeout_invalid_check.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "check",
            str(duplicate_source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stdout.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stdout.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_temperature_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "context_temperature_success_compile.axon"
        success_source.write_text(
            "context Review { temperature: 1.2 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["temperature"] == 1.2
        assert data["runs"][0]["context_name"] == "Review"
        assert data["runs"][0]["resolved_context"]["name"] == "Review"
        assert data["runs"][0]["resolved_context"]["temperature"] == 1.2

        invalid_source = tmp_path / "context_temperature_invalid_compile.axon"
        invalid_source.write_text(
            "context Review { temperature: 2.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("temperature must be between 0.0 and 2.0, got 2.5") == 1

        missing_flow_source = tmp_path / "context_temperature_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "context Review { temperature: 2.5 }\nrun Missing() within Review",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("temperature must be between 0.0 and 2.0, got 2.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_context_temperature_compile.axon"
        duplicate_source.write_text(
            "context Review { temperature: 2.5 }\ncontext Review { temperature: 1.2 }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Review' already defined as context (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("temperature must be between 0.0 and 2.0, got 2.5") == 1

    def test_compile_structural_confidence_threshold_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_confidence_threshold_success_compile.axon"
        success_source.write_text(
            "persona Expert { confidence_threshold: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["confidence_threshold"] == 0.8
        assert data["runs"][0]["persona_name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["confidence_threshold"] == 0.8

        invalid_source = tmp_path / "persona_confidence_threshold_invalid_compile.axon"
        invalid_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "persona_confidence_threshold_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\nrun Missing() as Expert",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_confidence_threshold_compile.axon"
        duplicate_source.write_text(
            "persona Expert { confidence_threshold: 1.5 }\npersona Expert { confidence_threshold: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("confidence_threshold must be between 0.0 and 1.0, got 1.5") == 1

    def test_compile_structural_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_confidence_floor_success_compile.axon"
        success_source.write_text(
            "anchor Safety { confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["confidence_floor"] == 0.8
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["confidence_floor"] == 0.8

        invalid_source = tmp_path / "anchor_confidence_floor_invalid_compile.axon"
        invalid_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "anchor_confidence_floor_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_confidence_floor_compile.axon"
        duplicate_source.write_text(
            "anchor Safety { confidence_floor: 1.5 }\nanchor Safety { confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_compile_structural_on_violation_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_success_compile.axon"
        success_source.write_text(
            "anchor Safety { on_violation: warn }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["on_violation"] == "warn"
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["on_violation"] == "warn"

        invalid_source = tmp_path / "anchor_on_violation_invalid_compile.axon"
        invalid_source.write_text(
            "anchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

        missing_flow_source = tmp_path / "anchor_on_violation_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: explode }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_compile.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: explode }\nanchor Safety { on_violation: warn }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_compile_structural_on_violation_raise_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_raise_success_compile.axon"
        success_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["on_violation"] == "raise"
        assert data["anchors"][0]["on_violation_target"] == "AnchorBreachError"
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["on_violation"] == "raise"
        assert data["runs"][0]["resolved_anchors"][0]["on_violation_target"] == "AnchorBreachError"

        missing_flow_source = tmp_path / "anchor_on_violation_raise_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_raise_compile.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: raise AnchorBreachError }\nanchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_compile_structural_on_violation_fallback_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_on_violation_fallback_success_compile.axon"
        success_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["on_violation"] == "fallback"
        assert data["anchors"][0]["on_violation_target"] == "No se"
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["on_violation"] == "fallback"
        assert data["runs"][0]["resolved_anchors"][0]["on_violation_target"] == "No se"

        missing_flow_source = tmp_path / "anchor_on_violation_fallback_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_on_violation_fallback_compile.axon"
        duplicate_source.write_text(
            "anchor Safety { on_violation: fallback(\"No se\") }\nanchor Safety { on_violation: explode }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown on_violation action 'explode' in anchor 'Safety'. Valid: escalate, fallback, log, raise, warn"
        ) == 1

    def test_compile_structural_reject_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "anchor_reject_success_compile.axon"
        success_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["reject"] == ["speculation", "hallucination"]
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_anchors"][0]["reject"] == ["speculation", "hallucination"]

        missing_flow_source = tmp_path / "anchor_reject_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nrun Missing() constrained_by [Safety]",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_anchor_reject_compile.axon"
        duplicate_source.write_text(
            "anchor Safety { reject: [speculation, hallucination] }\nanchor Safety { reject: [hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)"
        ) == 1

    def test_compile_structural_refuse_if_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_refuse_if_success_compile.axon"
        success_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["refuse_if"] == ["speculation", "hallucination"]
        assert data["runs"][0]["persona_name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["refuse_if"] == ["speculation", "hallucination"]

        missing_flow_source = tmp_path / "persona_refuse_if_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\nrun Missing() as Expert",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_refuse_if_compile.axon"
        duplicate_source.write_text(
            "persona Expert { refuse_if: [speculation, hallucination] }\npersona Expert { refuse_if: [hallucination] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1

    def test_compile_structural_domain_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "persona_domain_success_compile.axon"
        success_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["domain"] == ["science", "safety"]
        assert data["runs"][0]["persona_name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["domain"] == ["science", "safety"]

        missing_flow_source = tmp_path / "persona_domain_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\nrun Missing() as Expert',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_persona_domain_compile.axon"
        duplicate_source.write_text(
            'persona Expert { domain: ["science", "safety"] }\npersona Expert { domain: ["policy"] }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)"
        ) == 1

    def test_compile_structural_memory_store_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_store_success_compile.axon"
        success_source.write_text(
            "memory SessionMemory { store: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [memory["name"] for memory in data["memories"]] == ["SessionMemory"]
        assert data["memories"][0]["store"] == "session"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "memory_store_invalid_compile.axon"
        invalid_source.write_text(
            "memory SessionMemory { store: remote }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1

        missing_flow_source = tmp_path / "memory_store_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { store: remote }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_store_compile.axon"
        duplicate_source.write_text(
            "memory SessionMemory { store: remote }\nmemory SessionMemory { store: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown store type 'remote' in memory 'SessionMemory'. Valid: ephemeral, none, persistent, session"
        ) == 1

    def test_compile_structural_memory_backend_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_backend_success_compile.axon"
        success_source.write_text(
            "memory SessionMemory { backend: redis }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [memory["name"] for memory in data["memories"]] == ["SessionMemory"]
        assert data["memories"][0]["backend"] == "redis"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "memory_backend_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { backend: redis }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_backend_compile.axon"
        duplicate_source.write_text(
            "memory SessionMemory { backend: redis }\nmemory SessionMemory { backend: in_memory }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1

    def test_compile_structural_memory_retrieval_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_retrieval_success_compile.axon"
        success_source.write_text(
            "memory SessionMemory { retrieval: semantic }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [memory["name"] for memory in data["memories"]] == ["SessionMemory"]
        assert data["memories"][0]["retrieval"] == "semantic"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "memory_retrieval_invalid_compile.axon"
        invalid_source.write_text(
            "memory SessionMemory { retrieval: vector }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1

        missing_flow_source = tmp_path / "memory_retrieval_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { retrieval: vector }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_retrieval_compile.axon"
        duplicate_source.write_text(
            "memory SessionMemory { retrieval: vector }\nmemory SessionMemory { retrieval: semantic }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown retrieval strategy 'vector' in memory 'SessionMemory'. Valid: exact, hybrid, semantic"
        ) == 1

    def test_compile_structural_memory_decay_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "memory_decay_duration_success_compile.axon"
        success_source.write_text(
            "memory SessionMemory { decay: 5m }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [memory["name"] for memory in data["memories"]] == ["SessionMemory"]
        assert data["memories"][0]["decay"] == "5m"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "memory_decay_duration_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "memory SessionMemory { decay: 5m }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_memory_decay_compile.axon"
        duplicate_source.write_text(
            "memory SessionMemory { decay: 5m }\nmemory SessionMemory { decay: daily }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'SessionMemory' already defined as memory (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_provider_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_provider_success_compile.axon"
        success_source.write_text(
            "tool Search { provider: brave }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["provider"] == "brave"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_provider_compile.axon"
        duplicate_source.write_text(
            "tool Search { provider: brave }\ntool Search { provider: serpapi }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_runtime_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_runtime_success_compile.axon"
        success_source.write_text(
            "tool Search { runtime: hosted }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["runtime"] == "hosted"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_runtime_compile.axon"
        duplicate_source.write_text(
            "tool Search { runtime: hosted }\ntool Search { runtime: local }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_sandbox_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_sandbox_success_compile.axon"
        success_source.write_text(
            "tool Search { sandbox: true }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["sandbox"] is True
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_sandbox_compile.axon"
        duplicate_source.write_text(
            "tool Search { sandbox: true }\ntool Search { sandbox: false }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_timeout_success_compile.axon"
        success_source.write_text(
            "tool Search { timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_timeout_compile.axon"
        duplicate_source.write_text(
            "tool Search { timeout: 10s }\ntool Search { timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_max_results_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_max_results_success_compile.axon"
        success_source.write_text(
            "tool Search { max_results: 3 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["max_results"] == 3
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "tool_max_results_invalid_compile.axon"
        invalid_source.write_text(
            "tool Search { max_results: 0 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("max_results must be positive, got 0 in tool 'Search'") == 1

        missing_flow_source = tmp_path / "tool_max_results_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "tool Search { max_results: 0 }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("max_results must be positive, got 0 in tool 'Search'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_tool_max_results_compile.axon"
        duplicate_source.write_text(
            "tool Search { max_results: 0 }\ntool Search { max_results: 3 }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("max_results must be positive, got 0 in tool 'Search'") == 1

    def test_compile_structural_tool_filter_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_filter_success_compile.axon"
        success_source.write_text(
            "tool Search { filter: recent }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["filter_expr"] == "recent"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_filter_compile.axon"
        duplicate_source.write_text(
            "tool Search { filter: recent }\ntool Search { filter: broad }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_filter_call_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_filter_call_success_compile.axon"
        success_source.write_text(
            "tool Search { filter: recent(days: 30) }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert data["tools"][0]["filter_expr"] == "recent(days:30)"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_tool_filter_call_compile.axon"
        duplicate_source.write_text(
            "tool Search { filter: recent(days: 30) }\ntool Search { filter: recent(days: 7) }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_tool_effects_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "tool_effects_success_compile.axon"
        success_source.write_text(
            "tool Search { effects: <network, epistemic:know> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [tool["name"] for tool in data["tools"]] == ["Search"]
        assert tuple(data["tools"][0]["effect_row"]) == ("network", "epistemic:know")
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_effect_source = tmp_path / "tool_effects_invalid_effect_compile.axon"
        invalid_effect_source.write_text(
            "tool Search { effects: <oops> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid_effect = _run(
            "compile",
            str(invalid_effect_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_effect.returncode == 1
        assert invalid_effect.stderr.count(
            "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage"
        ) == 1

        invalid_level_source = tmp_path / "tool_effects_invalid_level_compile.axon"
        invalid_level_source.write_text(
            "tool Search { effects: <network, epistemic:guess> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        invalid_level = _run(
            "compile",
            str(invalid_level_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_level.returncode == 1
        assert invalid_level.stderr.count(
            "Unknown epistemic level 'guess' in tool 'Search'. Valid levels: believe, doubt, know, speculate"
        ) == 1

        missing_flow_source = tmp_path / "tool_effects_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            "tool Search { effects: <oops> }\nrun Missing()",
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count(
            "Unknown effect 'oops' in tool 'Search'. Valid effects: io, network, pure, random, storage"
        ) == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_tool_effects_compile.axon"
        duplicate_source.write_text(
            "tool Search { effects: <network, epistemic:know> }\ntool Search { effects: <io> }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Search' already defined as tool (first defined at line 1)"
        ) == 1

    def test_compile_structural_intent_ask_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_ask_success_compile.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_intent_ask_compile.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" }\nintent Extract { ask: "B?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_compile_structural_intent_given_ask_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_success_compile.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        duplicate_source = tmp_path / "duplicate_intent_given_ask_compile.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" }\nintent Extract { given: Contract ask: "B?" }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_compile_structural_intent_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_confidence_floor_success_compile.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "intent_confidence_floor_invalid_compile.axon"
        invalid_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_confidence_floor_invalid_undefined_compile.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_confidence_floor_compile.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" confidence_floor: 1.5 }\nintent Extract { ask: "B?" confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_compile_structural_intent_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_output_success_compile.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" output: List<Party>? }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "intent_output_undefined_compile.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_output_compile.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" output: Party }\nintent Extract { ask: "B?" output: MissingType }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_compile_structural_intent_given_ask_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_output_success_compile.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: List<Party>? }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "intent_given_ask_output_undefined_compile.axon"
        missing_flow_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_given_ask_output_compile.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" output: Party }\nintent Extract { given: Contract ask: "B?" output: MissingType }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1

    def test_compile_structural_intent_given_ask_output_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_given_ask_output_confidence_floor_success_compile.axon"
        success_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "intent_given_ask_output_confidence_floor_invalid_compile.axon"
        invalid_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_given_ask_output_confidence_floor_invalid_undefined_compile.axon"
        missing_flow_source.write_text(
            'intent Extract { given: Document ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_given_ask_output_confidence_floor_compile.axon"
        duplicate_source.write_text(
            'intent Extract { given: Document ask: "A?" output: Party confidence_floor: 1.5 }\nintent Extract { given: Contract ask: "B?" output: MissingType confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_compile_structural_intent_output_confidence_floor_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "intent_output_confidence_floor_success_compile.axon"
        success_source.write_text(
            'intent Extract { ask: "Who signed?" output: List<Party>? confidence_floor: 0.9 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert data["tools"] == []
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "intent_output_confidence_floor_invalid_compile.axon"
        invalid_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

        missing_flow_source = tmp_path / "intent_output_confidence_floor_invalid_undefined_compile.axon"
        missing_flow_source.write_text(
            'intent Extract { ask: "Who signed?" output: MissingType confidence_floor: 1.5 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_intent_output_confidence_floor_compile.axon"
        duplicate_source.write_text(
            'intent Extract { ask: "A?" output: Party confidence_floor: 1.5 }\nintent Extract { ask: "B?" output: MissingType confidence_floor: 0.8 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Extract' already defined as intent (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("confidence_floor must be between 0.0 and 1.0, got 1.5") == 1

    def test_compile_structural_axonendpoint_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_method_source = tmp_path / "endpoint_invalid_method_compile.axon"
        invalid_method_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid_method = _run(
            "compile",
            str(invalid_method_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_method.returncode == 1
        assert invalid_method.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

        invalid_path_source = tmp_path / "endpoint_invalid_path_compile.axon"
        invalid_path_source.write_text(
            'axonendpoint Api { method: post path: "x" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid_path = _run(
            "compile",
            str(invalid_path_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid_path.returncode == 1
        assert invalid_path.stderr.count("axonendpoint 'Api' path must start with '/': got 'x'") == 1

        missing_flow_source = tmp_path / "endpoint_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["output_type"] == "Party"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_output_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Party }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_body_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_retries_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["retries"] == 1
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_retries_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_retries_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["retries"] == 1
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_retries_timeout_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_retries_timeout_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_retries_timeout_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_body_output_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_output_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_output_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["output_type"] == "Party"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_output_shield_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_body_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_shield_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_body_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_timeout_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_shield_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_timeout_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_timeout_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_output_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_timeout_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["output_type"] == "Party"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_output_shield_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_timeout_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_timeout_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Party shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_output_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_shield_retries_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["output_type"] == "Party"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["retries"] == 1
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_output_shield_retries_invalid_compile.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_shield_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing output: Party shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_output_shield_retries_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_output_shield_retries_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_shield_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Party shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_body_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_shield_retries_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["retries"] == 1
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_body_shield_retries_invalid_compile.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_shield_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_shield_retries_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_shield_retries_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_shield_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_body_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_body_output_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_output_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_body_output_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_retries_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["retries"] == 1
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_body_output_retries_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_output_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

    def test_compile_structural_axonendpoint_body_output_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_output_shield_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_body_output_shield_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing body: Payload output: Result shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_body_output_shield_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_body_output_shield_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_shield_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow body: Payload output: Result shield: Safety }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_output_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload output: Result retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_output_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_retries_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["retries"] == 1
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_output_retries_timeout_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_retries_timeout_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_retries_timeout_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_body_retries_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_retries_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["retries"] == 1
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_body_retries_timeout_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_retries_timeout_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_retries_timeout_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload retries: 1 timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_output_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_retries_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["retries"] == 1
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_output_retries_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_output_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_body_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_body_retries_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["body_type"] == "Payload"
        assert data["endpoints"][0]["retries"] == 1
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_body_retries_invalid_compile.axon"
        invalid_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_body_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing body: Payload retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_body_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow body: Payload retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow body: Payload retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_output_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_output_timeout_success_compile.axon"
        success_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow output: Result timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["method"] == "POST"
        assert data["endpoints"][0]["path"] == "/x"
        assert data["endpoints"][0]["execute_flow"] == "SimpleFlow"
        assert data["endpoints"][0]["output_type"] == "Result"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_output_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: Missing output: Result timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_output_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'axonendpoint Api { method: bogus path: "/x" execute: SimpleFlow output: Result timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow output: Result timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 1)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_shield_timeout_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_timeout_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["timeout"] == "10s"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_shield_timeout_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety timeout: 10s }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_timeout_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_timeout_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_shield_timeout_invalid_method_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: bogus path: "/x" execute: SimpleFlow shield: Safety timeout: 10s }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety timeout: 5s }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count(
            "Unknown HTTP method 'BOGUS' in axonendpoint 'Api'. Valid: DELETE, GET, PATCH, POST, PUT"
        ) == 1

    def test_compile_structural_axonendpoint_shield_retries_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_retries_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["endpoints"][0]["retries"] == 1
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        invalid_source = tmp_path / "endpoint_shield_retries_invalid_compile.axon"
        invalid_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        invalid = _run(
            "compile",
            str(invalid_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert invalid.returncode == 1
        assert invalid.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

        missing_flow_source = tmp_path / "endpoint_shield_retries_invalid_undefined_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety retries: -1 }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_retries_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_retries_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_endpoint_shield_retries_invalid_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety retries: -1 }\naxonendpoint Api { method: post path: "/y" execute: SimpleFlow shield: Safety retries: 1 }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Api' already defined as axonendpoint (first defined at line 2)"
        ) == 1
        assert duplicate.stderr.count("axonendpoint 'Api' retries must be >= 0, got -1") == 1

    def test_compile_structural_axonendpoint_shield_paths_use_native_dev_local_or_success_path(self, tmp_path):
        success_source = tmp_path / "endpoint_shield_success_compile.axon"
        success_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        success = _run(
            "compile",
            str(success_source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert success.returncode == 0
        data = json.loads(success.stdout)
        assert [shield["name"] for shield in data["shields"]] == ["Safety"]
        assert [endpoint["name"] for endpoint in data["endpoints"]] == ["Api"]
        assert data["endpoints"][0]["shield_ref"] == "Safety"
        assert data["flows"][0]["name"] == "SimpleFlow"
        assert data["runs"][0]["flow_name"] == "SimpleFlow"

        missing_flow_source = tmp_path / "endpoint_shield_missing_flow_compile.axon"
        missing_flow_source.write_text(
            'shield Safety { }\naxonendpoint Api { method: post path: "/x" execute: Missing shield: Safety }\nrun Missing()',
            encoding="utf-8",
        )

        missing_flow = _run(
            "compile",
            str(missing_flow_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert missing_flow.returncode == 1
        assert missing_flow.stderr.count("axonendpoint 'Api' references undefined flow 'Missing'") == 1
        assert missing_flow.stderr.count("Undefined flow 'Missing' in run statement") == 1

        undefined_shield_source = tmp_path / "endpoint_shield_undefined_compile.axon"
        undefined_shield_source.write_text(
            'axonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Missing }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        undefined_shield = _run(
            "compile",
            str(undefined_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert undefined_shield.returncode == 1
        assert undefined_shield.stderr.count("axonendpoint 'Api' references undefined shield 'Missing'") == 1

        not_a_shield_source = tmp_path / "endpoint_shield_not_a_shield_compile.axon"
        not_a_shield_source.write_text(
            'anchor Safety { require: source_citation }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        not_a_shield = _run(
            "compile",
            str(not_a_shield_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert not_a_shield.returncode == 1
        assert not_a_shield.stderr.count("'Safety' is a anchor, not a shield") == 1

        duplicate_source = tmp_path / "duplicate_shield_endpoint_compile.axon"
        duplicate_source.write_text(
            'shield Safety { }\nshield Safety { }\naxonendpoint Api { method: post path: "/x" execute: SimpleFlow shield: Safety }\nflow SimpleFlow() {}\nrun SimpleFlow()',
            encoding="utf-8",
        )

        duplicate = _run(
            "compile",
            str(duplicate_source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert duplicate.returncode == 1
        assert duplicate.stderr.count(
            "Duplicate declaration: 'Safety' already defined as shield (first defined at line 1)"
        ) == 1

    def test_compile_structural_prefixed_flow_run_with_singular_referential_modifiers_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "structural_as_compile.axon",
                "Expert",
                "",
                [],
                "Expert",
                None,
                [],
            ),
            (
                "context Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "structural_within_compile.axon",
                "",
                "Review",
                [],
                None,
                "Review",
                [],
            ),
            (
                "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "structural_constrained_compile.axon",
                "",
                "",
                ["Safety"],
                None,
                None,
                ["Safety"],
            ),
        ]

        for (
            source_text,
            filename,
            expected_persona_name,
            expected_context_name,
            expected_anchor_names,
            expected_resolved_persona,
            expected_resolved_context,
            expected_resolved_anchors,
        ) in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["persona_name"] == expected_persona_name
            assert data["runs"][0]["context_name"] == expected_context_name
            assert data["runs"][0]["anchor_names"] == expected_anchor_names
            resolved_persona = data["runs"][0]["resolved_persona"]
            resolved_context = data["runs"][0]["resolved_context"]
            resolved_anchors = data["runs"][0]["resolved_anchors"]
            assert (resolved_persona["name"] if resolved_persona else None) == expected_resolved_persona
            assert (resolved_context["name"] if resolved_context else None) == expected_resolved_context
            assert [anchor["name"] for anchor in resolved_anchors] == expected_resolved_anchors
            assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_structural_prefixed_flow_run_with_multi_anchor_constrained_by_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "structural_multi_anchor_compile.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Grounding { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Grounding]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety", "Grounding"]
        assert data["runs"][0]["anchor_names"] == ["Safety", "Grounding"]
        assert [anchor["name"] for anchor in data["runs"][0]["resolved_anchors"]] == ["Safety", "Grounding"]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_structural_prefixed_flow_run_with_repeated_constrained_by_anchors_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "structural_repeated_anchor_compile.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Grounding { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Safety, Grounding]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety", "Grounding"]
        assert data["runs"][0]["anchor_names"] == ["Safety", "Safety", "Grounding"]
        assert [anchor["name"] for anchor in data["runs"][0]["resolved_anchors"]] == ["Safety", "Safety", "Grounding"]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_constrained_by_single_anchor_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_constrained_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["anchor_names"] == ["Safety"]
        assert len(data["runs"][0]["resolved_anchors"]) == 1
        assert data["runs"][0]["resolved_anchors"][0]["name"] == "Safety"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_within_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_within_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["context_name"] == "Review"
        assert data["runs"][0]["resolved_context"]["name"] == "Review"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_as_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_as_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["persona_name"] == "Expert"
        assert data["runs"][0]["resolved_persona"]["name"] == "Expert"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_with_twenty_retry_parameters_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_retry_twenty_params_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, mode: cautious, priority: high, budget: strict, window: narrow, channel: audit, lane: safe, trace: verbose, guard: strict, batch: full, scope: narrow, review: staged, cadence: nightly, quorum: strict, ledger: complete, route: deterministic, mirror: enabled, limit: hard, gate: closed)",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["on_failure"] == "retry"
        assert data["runs"][0]["on_failure_params"] == [["backoff", "exponential"], ["attempts", "3"], ["mode", "cautious"], ["priority", "high"], ["budget", "strict"], ["window", "narrow"], ["channel", "audit"], ["lane", "safe"], ["trace", "verbose"], ["guard", "strict"], ["batch", "full"], ["scope", "narrow"], ["review", "staged"], ["cadence", "nightly"], ["quorum", "strict"], ["ledger", "complete"], ["route", "deterministic"], ["mirror", "enabled"], ["limit", "hard"], ["gate", "closed"]]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_with_raise_on_failure_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_raise_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["on_failure"] == "raise"
        assert data["runs"][0]["on_failure_params"] == [["target", "AnchorBreachError"]]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_with_simple_on_failure_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: log",
                "persona_context_anchor_flow_run_on_failure_log_compile.axon",
                "log",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry",
                "persona_context_anchor_flow_run_on_failure_retry_compile.axon",
                "retry",
            ),
        ]

        for source_text, filename, expected_on_failure in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["on_failure"] == expected_on_failure
            assert data["runs"][0]["on_failure_params"] == []
            assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_with_output_to_or_effort_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"",
                "persona_context_anchor_flow_run_output_compile.axon",
                "report.json",
                "",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() effort: high",
                "persona_context_anchor_flow_run_effort_compile.axon",
                "",
                "high",
            ),
        ]

        for source_text, filename, expected_output_to, expected_effort in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["output_to"] == expected_output_to
            assert data["runs"][0]["effort"] == expected_effort
            assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["tone"] == "precise"
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["memory_scope"] == "session"
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["require"] == "source_citation"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_context_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "context_anchor_flow_run_compile.axon"
        source.write_text(
            "context Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["memory_scope"] == "session"
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["require"] == "source_citation"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_anchor_flow_run_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["tone"] == "precise"
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["require"] == "source_citation"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_context_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_flow_run_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["tone"] == "precise"
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["memory_scope"] == "session"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "anchor_flow_run_compile.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [anchor["name"] for anchor in data["anchors"]] == ["Safety"]
        assert data["anchors"][0]["require"] == "source_citation"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_context_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "context_flow_run_compile.axon"
        source.write_text(
            "context Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [context["name"] for context in data["contexts"]] == ["Review"]
        assert data["contexts"][0]["memory_scope"] == "session"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_persona_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_flow_run_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [persona["name"] for persona in data["personas"]] == ["Expert"]
        assert data["personas"][0]["tone"] == "precise"
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_minimal_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "minimal_flow_run_compile.axon"
        source.write_text(
            "flow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert [flow["name"] for flow in data["flows"]] == ["SimpleFlow"]
        assert [run["flow_name"] for run in data["runs"]] == ["SimpleFlow"]
        assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_compile_minimal_flow_run_with_output_to_or_effort_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"",
                "minimal_flow_run_output_compile.axon",
                "report.json",
                "",
            ),
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() effort: high",
                "minimal_flow_run_effort_compile.axon",
                "",
                "high",
            ),
        ]

        for source_text, filename, expected_output_to, expected_effort in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["output_to"] == expected_output_to
            assert data["runs"][0]["effort"] == expected_effort
            assert data["runs"][0]["resolved_flow"]["name"] == "SimpleFlow"

    def test_check_minimal_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "minimal_flow_run_check.axon"
        source.write_text(
            "flow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_minimal_flow_run_with_output_to_or_effort_uses_native_dev_success_path(self, tmp_path):
        cases = [
            ("flow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"", "minimal_flow_run_output_check.axon"),
            ("flow SimpleFlow() {}\nrun SimpleFlow() effort: high", "minimal_flow_run_effort_check.axon"),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_check_prefixed_success_case_with_repeated_constrained_by_anchors_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_constrained_repeated_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Safety]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_structural_duplicate_anchor_declaration_uses_native_dev_local_error_path(self, tmp_path):
        source = tmp_path / "duplicate_anchor_structural_check.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 1)" in r.stdout

    def test_check_structural_duplicate_persona_or_context_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\npersona Expert { tone: formal }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_structural_check.axon",
                "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\ncontext Review { memory: persistent }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "duplicate_context_structural_check.axon",
                "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
            ),
        ]

        for source_text, filename, expected_message in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert expected_message in r.stdout

    def test_check_structural_multiple_clean_duplicates_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\npersona Expert { tone: formal }\ncontext Review { memory: persistent }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "multiple_duplicate_persona_context_check.axon",
                [
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                ],
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: formal }\ncontext Review { memory: persistent }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "multiple_duplicate_all_check.axon",
                [
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)",
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)",
                    "Duplicate declaration: 'Safety' already defined as anchor (first defined at line 3)",
                ],
            ),
        ]

        for source_text, filename, expected_messages in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message in expected_messages:
                assert expected_message in r.stdout

    def test_check_structural_nonclean_duplicate_context_combinations_use_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "context Review { memory: invalid }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_first_invalid_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\ncontext Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_both_invalid_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 1)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 2,
                },
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\ncontext Review { memory: archive }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "nonclean_duplicate_context_check.axon",
                {
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)": 1,
                    "Unknown memory scope 'archive' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\npersona Expert { tone: formal }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
                "nonclean_duplicate_persona_context_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Duplicate declaration: 'Review' already defined as context (first defined at line 2)": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 2,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_invalid_context_memory_without_duplicates_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "context Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_structural_check.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_structural_prefixed_check.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\nrun SimpleFlow() within Review",
                "invalid_context_undefined_flow_check.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: invalid }\nanchor Safety { require: source_citation }\nrun SimpleFlow() within Review",
                "invalid_context_prefixed_undefined_flow_check.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_persona_context_validation_without_duplicates_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_structural_check.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_with_context_anchor_check.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\nrun SimpleFlow() as Expert",
                "invalid_persona_undefined_flow_check.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "invalid_persona_context_check.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
            (
                "context Review { memory: invalid }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "invalid_context_persona_check.axon",
                {
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\nrun SimpleFlow() as Expert",
                "invalid_persona_context_undefined_flow_check.axon",
                {
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                    "Undefined flow 'SimpleFlow' in run statement": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_duplicate_persona_with_invalid_tone_uses_native_dev_local_error_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: invalid }\npersona Expert { tone: formal }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_first_invalid_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: formal }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_second_invalid_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                },
            ),
            (
                "persona Expert { tone: invalid }\npersona Expert { tone: invalid }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_both_invalid_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 2,
                },
            ),
            (
                "persona Expert { tone: invalid }\ncontext Review { memory: invalid }\npersona Expert { tone: formal }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "duplicate_persona_invalid_tone_context_check.axon",
                {
                    "Duplicate declaration: 'Expert' already defined as persona (first defined at line 1)": 1,
                    "Unknown tone 'invalid' for persona 'Expert'. Valid tones: analytical, assertive, casual, diplomatic, empathetic, formal, friendly, precise": 1,
                    "Unknown memory scope 'invalid' in context 'Review'. Valid: ephemeral, none, persistent, session": 1,
                },
            ),
        ]

        for source_text, filename, expected_message_counts in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            for expected_message, expected_count in expected_message_counts.items():
                assert r.stdout.count(expected_message) == expected_count

    def test_check_structural_prefixed_flow_run_in_supported_alternate_order_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "anchor_persona_context_flow_run_check.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_structural_prefixed_flow_run_with_nonreferential_modifiers_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"",
                "structural_output_check.axon",
            ),
            (
                "context Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() effort: high",
                "structural_effort_check.axon",
            ),
            (
                "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: log",
                "structural_on_failure_log_check.axon",
            ),
            (
                "anchor Safety { require: source_citation }\ncontext Review { memory: session }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
                "structural_on_failure_raise_check.axon",
            ),
            (
                "context Review { memory: session }\npersona Expert { tone: precise }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "structural_on_failure_retry_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_check_structural_prefixed_flow_run_with_singular_referential_modifiers_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
                "structural_as_check.axon",
            ),
            (
                "context Review { memory: session }\nanchor Safety { require: source_citation }\npersona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
                "structural_within_check.axon",
            ),
            (
                "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
                "structural_constrained_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_check_structural_prefixed_flow_run_with_repeated_constrained_by_anchors_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "structural_repeated_anchor_check.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Grounding { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Safety, Grounding]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_structural_prefixed_flow_run_with_multi_anchor_constrained_by_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "structural_multi_anchor_check.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\npersona Expert { tone: precise }\nanchor Grounding { require: source_citation }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety, Grounding]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_constrained_by_single_anchor_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_constrained_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() constrained_by [Safety]",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_within_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_within_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() within Review",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_as_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_as_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() as Expert",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_with_twenty_retry_parameters_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_retry_twenty_params_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3, mode: cautious, priority: high, budget: strict, window: narrow, channel: audit, lane: safe, trace: verbose, guard: strict, batch: full, scope: narrow, review: staged, cadence: nightly, quorum: strict, ledger: complete, route: deterministic, mirror: enabled, limit: hard, gate: closed)",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_with_raise_on_failure_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_raise_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_with_simple_on_failure_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: log",
                "persona_context_anchor_flow_run_on_failure_log_check.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry",
                "persona_context_anchor_flow_run_on_failure_retry_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_with_output_to_or_effort_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() output_to: \"report.json\"",
                "persona_context_anchor_flow_run_output_check.axon",
            ),
            (
                "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow() effort: high",
                "persona_context_anchor_flow_run_effort_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_check_persona_context_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_anchor_flow_run_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_context_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "context_anchor_flow_run_check.axon"
        source.write_text(
            "context Review { memory: session }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_anchor_flow_run_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\nanchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_context_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_context_flow_run_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\ncontext Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_anchor_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "anchor_flow_run_check.axon"
        source.write_text(
            "anchor Safety { require: source_citation }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_context_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "context_flow_run_check.axon"
        source.write_text(
            "context Review { memory: session }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_persona_prefixed_flow_run_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "persona_flow_run_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\nflow SimpleFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_check_minimal_flow_run_with_simple_on_failure_uses_native_dev_success_path(self, tmp_path):
        cases = [
            ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: log", "minimal_flow_run_on_failure_log_check.axon"),
            ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry", "minimal_flow_run_on_failure_retry_check.axon"),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_compile_minimal_flow_run_with_simple_on_failure_uses_native_dev_success_path(self, tmp_path):
        cases = [
            ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: log", "minimal_flow_run_on_failure_log_compile.axon", "log"),
            ("flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry", "minimal_flow_run_on_failure_retry_compile.axon", "retry"),
        ]

        for source_text, filename, expected_on_failure in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["on_failure"] == expected_on_failure
            assert data["runs"][0]["on_failure_params"] == []

    def test_check_minimal_flow_run_with_raise_on_failure_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "minimal_flow_run_raise_on_failure_check.axon"
        source.write_text(
            "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        assert "0 errors" in r.stdout

    def test_compile_minimal_flow_run_with_raise_on_failure_uses_native_dev_success_path(self, tmp_path):
        source = tmp_path / "minimal_flow_run_raise_on_failure_compile.axon"
        source.write_text(
            "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: raise AnchorBreachError",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["runs"][0]["on_failure"] == "raise"
        assert data["runs"][0]["on_failure_params"] == [["target", "AnchorBreachError"]]

    def test_check_minimal_flow_run_with_parameterized_retry_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "minimal_flow_run_retry_one_param_check.axon",
            ),
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "minimal_flow_run_retry_two_params_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_compile_minimal_flow_run_with_parameterized_retry_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential)",
                "minimal_flow_run_retry_one_param_compile.axon",
                [["backoff", "exponential"]],
            ),
            (
                "flow SimpleFlow() {}\nrun SimpleFlow() on_failure: retry(backoff: exponential, attempts: 3)",
                "minimal_flow_run_retry_two_params_compile.axon",
                [["backoff", "exponential"], ["attempts", "3"]],
            ),
        ]

        for source_text, filename, expected_params in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                "--stdout",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data["runs"][0]["on_failure"] == "retry"
            assert data["runs"][0]["on_failure_params"] == expected_params

    def test_compile_mismatched_flow_adjacent_run_stays_on_python_path_under_native_dev(self, tmp_path):
        source = tmp_path / "persona_flow_run_mismatched_compile.axon"
        source.write_text(
            "persona Expert { tone: precise }\nflow OtherFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(source),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_check_mismatched_flow_adjacent_run_stays_on_python_path_under_native_dev(self, tmp_path):
        source = tmp_path / "persona_flow_run_mismatched_check.axon"
        source.write_text(
            "persona Expert { tone: precise }\nflow OtherFlow() {}\nrun SimpleFlow()",
            encoding="utf-8",
        )

        r = _run(
            "check",
            str(source),
            "--no-color",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 1
        assert "Undefined flow 'SimpleFlow' in run statement" in r.stdout

    def test_compile_isolated_or_mismatched_as_and_other_remaining_modifiers_stay_on_python_path_under_native_dev(self, tmp_path):
        cases = [
            ("run SimpleFlow() as Expert", "run_as_isolated_compile.axon"),
            (
                "persona Guide { tone: precise }\nrun SimpleFlow() as Expert",
                "run_as_mismatched_compile.axon",
            ),
            ("run SimpleFlow() within Review", "run_within_isolated_compile.axon"),
            (
                "context SessionCtx { memory: session }\nrun SimpleFlow() within Review",
                "run_within_mismatched_compile.axon",
            ),
            ("run SimpleFlow() constrained_by [Safety]", "run_constrained_isolated_compile.axon"),
            (
                "anchor Known { require: source_citation }\nrun SimpleFlow() constrained_by [Safety]",
                "run_constrained_mismatched_compile.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "compile",
                str(source),
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 1
            assert "Undefined flow 'SimpleFlow' in run statement" in r.stderr

    def test_compile_simple_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "simple_import.axon"
        src.write_text("import SomeModule\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["SomeModule"]
        assert data["imports"][0]["resolved"] is False

    def test_compile_dotted_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "dotted_import.axon"
        src.write_text("import a.b.c\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["a", "b", "c"]
        assert data["imports"][0]["resolved"] is False

    def test_compile_named_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "named_import.axon"
        src.write_text("import a.b { X, Y }\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["a", "b"]
        assert data["imports"][0]["names"] == ["X", "Y"]
        assert data["imports"][0]["resolved"] is False

    def test_compile_import_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_flow_run.axon"
        src.write_text("import Utils\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["Utils"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][0]["resolved"] is False
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Main"
        assert len(data["runs"]) == 1

    def test_compile_multi_import_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_import.axon"
        src.write_text("import A\nimport b.c { X }\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 2
        assert data["imports"][0]["module_path"] == ["A"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][1]["module_path"] == ["b", "c"]
        assert data["imports"][1]["names"] == ["X"]

    def test_compile_type_import_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "type_import_flow_run.axon"
        src.write_text("type Foo { x: String }\nimport bar\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["types"]) == 1
        assert data["types"][0]["name"] == "Foo"
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["bar"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][0]["resolved"] is False
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Main"
        assert len(data["runs"]) == 1

    def test_compile_import_type_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_type_flow_run.axon"
        src.write_text("import bar\ntype Foo { x: String }\nflow Main() {}\nrun Main()\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["bar"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][0]["resolved"] is False
        assert len(data["types"]) == 1
        assert data["types"][0]["name"] == "Foo"
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Main"
        assert len(data["runs"]) == 1

    def test_compile_type_import_standalone_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "type_import_standalone.axon"
        src.write_text("type Score(0.0..1.0)\nimport bar\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["types"]) == 1
        assert data["types"][0]["name"] == "Score"
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["bar"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][0]["resolved"] is False
        assert data["flows"] == []
        assert data["runs"] == []

    def test_compile_import_type_standalone_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "import_type_standalone.axon"
        src.write_text("import bar\ntype Score(0.0..1.0)\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["module_path"] == ["bar"]
        assert data["imports"][0]["names"] == []
        assert data["imports"][0]["resolved"] is False
        assert len(data["types"]) == 1
        assert data["types"][0]["name"] == "Score"
        assert data["flows"] == []
        assert data["runs"] == []

    def test_compile_multi_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow.axon"
        src.write_text("flow A() {}\nflow B() {}\nrun A()\nrun B()\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 2
        assert data["flows"][0]["name"] == "A"
        assert data["flows"][1]["name"] == "B"
        assert len(data["runs"]) == 2
        assert data["runs"][0]["flow_name"] == "A"
        assert data["runs"][1]["flow_name"] == "B"
        assert data["runs"][0]["resolved_flow"]["name"] == "A"
        assert data["runs"][1]["resolved_flow"]["name"] == "B"

    def test_compile_multi_flow_run_with_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow_mod.axon"
        src.write_text('flow A() {}\nflow B() {}\nrun A() effort: high\nrun B() effort: low\n', encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 2
        assert len(data["runs"]) == 2
        assert data["runs"][0]["effort"] == "high"
        assert data["runs"][1]["effort"] == "low"
        assert data["runs"][0]["resolved_flow"]["name"] == "A"
        assert data["runs"][1]["resolved_flow"]["name"] == "B"

    def test_compile_parameterized_flow_run_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_flow.axon"
        src.write_text('flow Greet(name: String) {}\nrun Greet()\n', encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Greet"
        assert len(data["flows"][0]["parameters"]) == 1
        assert data["flows"][0]["parameters"][0]["name"] == "name"
        assert data["flows"][0]["parameters"][0]["type_name"] == "String"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["flow_name"] == "Greet"
        assert data["runs"][0]["resolved_flow"]["name"] == "Greet"

    def test_compile_parameterized_flow_run_with_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_flow_mod.axon"
        src.write_text('flow Greet(name: String) {}\nrun Greet() effort: high\n', encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Greet"
        assert len(data["flows"][0]["parameters"]) == 1
        assert data["flows"][0]["parameters"][0]["name"] == "name"
        assert data["flows"][0]["parameters"][0]["type_name"] == "String"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["flow_name"] == "Greet"
        assert data["runs"][0]["effort"] == "high"
        assert data["runs"][0]["resolved_flow"]["name"] == "Greet"

    def test_compile_multi_flow_with_params_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "multi_flow_params.axon"
        src.write_text('flow A(x: Int) {}\nflow B() {}\nrun A()\nrun B()\n', encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 2
        assert data["flows"][0]["name"] == "A"
        assert len(data["flows"][0]["parameters"]) == 1
        assert data["flows"][0]["parameters"][0]["name"] == "x"
        assert data["flows"][0]["parameters"][0]["type_name"] == "Int"
        assert data["flows"][1]["name"] == "B"
        assert len(data["flows"][1]["parameters"]) == 0
        assert len(data["runs"]) == 2
        assert data["runs"][0]["flow_name"] == "A"
        assert data["runs"][0]["resolved_flow"]["name"] == "A"
        assert data["runs"][1]["flow_name"] == "B"
        assert data["runs"][1]["resolved_flow"]["name"] == "B"

    def test_compile_param_flow_with_referential_modifiers_uses_native_dev_local_success_path(self, tmp_path):
        src = tmp_path / "param_referential.axon"
        src.write_text(
            'persona Helper { tone: precise }\n'
            'flow Greet(name: String) {}\n'
            'run Greet() as Helper\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Greet"
        assert len(data["flows"][0]["parameters"]) == 1
        assert data["flows"][0]["parameters"][0]["name"] == "name"
        assert data["flows"][0]["parameters"][0]["type_name"] == "String"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["flow_name"] == "Greet"
        assert data["runs"][0]["persona_name"] == "Helper"
        assert data["runs"][0]["resolved_persona"]["name"] == "Helper"
        assert data["runs"][0]["resolved_flow"]["name"] == "Greet"

    def test_check_structural_prefixed_multi_flow_with_referential_modifiers_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "persona Helper { tone: precise }\nflow A() {}\nflow B() {}\nrun A() as Helper\nrun B()\n",
                "multi_as_check.axon",
            ),
            (
                "context Sales { domain: retail }\nflow A() {}\nflow B() {}\nrun A() within Sales\nrun B()\n",
                "multi_within_check.axon",
            ),
            (
                "anchor Safety { require: honesty }\nflow A() {}\nflow B() {}\nrun A() constrained_by [Safety]\nrun B()\n",
                "multi_constrained_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_compile_structural_prefixed_multi_flow_with_referential_modifiers_uses_native_dev_success_path(self, tmp_path):
        src = tmp_path / "multi_referential.axon"
        src.write_text(
            'persona Helper { tone: precise }\n'
            'flow A() {}\n'
            'flow B() {}\n'
            'run A() as Helper\n'
            'run B()\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 2
        assert {f["name"] for f in data["flows"]} == {"A", "B"}
        assert len(data["runs"]) == 2
        assert data["runs"][0]["flow_name"] == "A"
        assert data["runs"][0]["persona_name"] == "Helper"
        assert data["runs"][0]["resolved_persona"]["name"] == "Helper"
        assert data["runs"][1]["flow_name"] == "B"
        assert data["runs"][1]["persona_name"] == ""

    def test_check_flow_body_with_steps_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "flow Greet() {\n  step Extract {}\n}\nrun Greet()\n",
                "body_step_check.axon",
            ),
            (
                "flow Greet() {\n  step A {}\n  step B {}\n}\nrun Greet()\n",
                "body_multi_step_check.axon",
            ),
            (
                "persona Expert { tone: precise }\nflow Analyze() {\n  step Extract {}\n}\nrun Analyze() as Expert\n",
                "prefix_body_step_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_compile_flow_body_with_steps_uses_native_dev_success_path(self, tmp_path):
        src = tmp_path / "body_step.axon"
        src.write_text(
            'flow Greet() {\n  step Extract {}\n}\nrun Greet()\n',
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["flows"]) == 1
        assert data["flows"][0]["name"] == "Greet"
        assert len(data["flows"][0]["steps"]) == 1
        assert data["flows"][0]["steps"][0]["name"] == "Extract"
        assert data["flows"][0]["execution_levels"] == [["Extract"]]
        assert len(data["runs"]) == 1
        assert data["runs"][0]["flow_name"] == "Greet"

    def test_check_shield_compute_fields_uses_native_dev_success_path(self, tmp_path):
        cases = [
            (
                "shield Guard {\n  severity: high\n}\nflow A() {}\nrun A()\n",
                "shield_fields_check.axon",
            ),
            (
                "compute Task {\n  output: Number\n}\nflow A() {}\nrun A()\n",
                "compute_fields_check.axon",
            ),
            (
                "shield Guard {\n  strategy: pattern\n  on_breach: halt\n"
                "  severity: high\n}\nflow A() {}\nrun A()\n",
                "shield_multi_fields_check.axon",
            ),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0
            assert "0 errors" in r.stdout

    def test_compile_shield_fields_uses_native_dev_success_path(self, tmp_path):
        src = tmp_path / "shield_fields.axon"
        src.write_text(
            "shield Guard {\n  severity: high\n}\nflow A() {}\nrun A()\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["shields"]) == 1
        assert data["shields"][0]["name"] == "Guard"
        assert data["shields"][0]["severity"] == "high"
        assert len(data["flows"]) == 1
        assert len(data["runs"]) == 1

    def test_compile_compute_fields_uses_native_dev_success_path(self, tmp_path):
        src = tmp_path / "compute_fields.axon"
        src.write_text(
            "compute Task {\n  output: Number\n}\nflow A() {}\nrun A()\n",
            encoding="utf-8",
        )

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["compute_specs"]) == 1
        assert data["compute_specs"][0]["name"] == "Task"
        assert data["compute_specs"][0]["output_type"] == "Number"
        assert len(data["flows"]) == 1
        assert len(data["runs"]) == 1

    def test_check_standalone_prefix_declarations_uses_native_dev_success_path(self, tmp_path):
        cases = [
            ("persona P { tone: precise }\n", "persona_only.axon"),
            ("context C { depth: standard }\n", "context_only.axon"),
            ("shield Guard {}\n", "shield_empty_only.axon"),
            ("compute Calc {}\n", "compute_empty_only.axon"),
            ("tool T { provider: openai }\n", "tool_only.axon"),
            ("shield G {}\ncompute C {}\n", "shield_compute_only.axon"),
        ]

        for source_text, filename in cases:
            source = tmp_path / filename
            source.write_text(source_text, encoding="utf-8")

            r = _run(
                "check",
                str(source),
                "--no-color",
                check=False,
                env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
            )
            assert r.returncode == 0, f"{filename}: check failed"
            assert "0 errors" in r.stdout, f"{filename}: errors found"

    def test_compile_standalone_persona_uses_native_dev_success_path(self, tmp_path):
        src = tmp_path / "persona_only.axon"
        src.write_text("persona P { tone: precise }\n", encoding="utf-8")

        r = _run(
            "compile",
            str(src),
            "--stdout",
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "native-dev"},
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["personas"]) == 1
        assert data["personas"][0]["name"] == "P"
        assert data["personas"][0]["tone"] == "precise"
        assert len(data["flows"]) == 0
        assert len(data["runs"]) == 0


# ══════════════════════════════════════════════════════════════════
#  axon trace
# ══════════════════════════════════════════════════════════════════


class TestTrace:
    """``axon trace`` pretty-prints a trace JSON file."""

    @pytest.fixture()
    def trace_file(self, tmp_path) -> Path:
        """Create a minimal trace JSON file."""
        trace = {
            "_meta": {"source": "test.axon", "backend": "anthropic"},
            "events": [
                {"type": "step_start", "data": {"step_name": "Extract"}},
                {"type": "model_call", "data": {"message": "Extracting..."}},
                {"type": "anchor_pass", "data": {"name": "NoHallucination"}},
                {"type": "step_end", "data": {"step_name": "Extract"}},
            ],
        }
        path = tmp_path / "test.trace.json"
        path.write_text(json.dumps(trace), encoding="utf-8")
        return path

    def test_trace_renders(self, trace_file):
        r = _run("trace", str(trace_file))
        assert r.returncode == 0
        assert "AXON Execution Trace" in r.stdout

    def test_trace_shows_events(self, trace_file):
        r = _run("trace", str(trace_file), "--no-color")
        assert "step_start" in r.stdout
        assert "anchor_pass" in r.stdout

    def test_trace_missing_file(self):
        r = _run("trace", "nonexistent.trace.json", check=False)
        assert r.returncode == 2

    def test_trace_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        r = _run("trace", str(bad), check=False)
        assert r.returncode == 2

    def test_trace_ignores_invalid_frontend_selection(self, trace_file):
        r = _run(
            "trace",
            str(trace_file),
            check=False,
            env_overrides={"AXON_FRONTEND_IMPLEMENTATION": "missing-frontend"},
        )
        assert r.returncode == 0
        assert "AXON Execution Trace" in r.stdout


# ══════════════════════════════════════════════════════════════════
#  axon (no args) + help
# ══════════════════════════════════════════════════════════════════


class TestHelp:
    """CLI shows help when invoked without subcommand or with --help."""

    def test_no_args_shows_help(self):
        r = _run(check=False)
        assert r.returncode == 0
        assert "AXON" in r.stdout
        assert "check" in r.stdout
        assert "compile" in r.stdout
        assert "run" in r.stdout

    def test_help_flag(self):
        r = _run("--help")
        assert r.returncode == 0
        assert "check" in r.stdout


# ══════════════════════════════════════════════════════════════════
#  axon run (smoke test — no API key required for check only)
# ══════════════════════════════════════════════════════════════════


class TestRunSmoke:
    """``axon run`` at minimum compiles the file before failing on backend."""

    def test_run_missing_file(self):
        r = _run("run", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_run_invalid_syntax(self, tmp_path):
        bad = tmp_path / "bad.axon"
        bad.write_text("42 + garbage", encoding="utf-8")
        r = _run("run", str(bad), check=False)
        assert r.returncode == 1


# ══════════════════════════════════════════════════════════════════
#  axon inspect
# ══════════════════════════════════════════════════════════════════


class TestInspect:
    """``axon inspect`` introspects the stdlib."""

    def test_inspect_anchors(self):
        r = _run("inspect", "anchors")
        assert r.returncode == 0
        assert "ANCHORS" in r.stdout
        assert "NoHallucination" in r.stdout

    def test_inspect_personas(self):
        r = _run("inspect", "personas")
        assert r.returncode == 0
        assert "PERSONAS" in r.stdout

    def test_inspect_tools(self):
        r = _run("inspect", "tools")
        assert r.returncode == 0
        assert "TOOLS" in r.stdout

    def test_inspect_flows(self):
        r = _run("inspect", "flows")
        assert r.returncode == 0
        assert "FLOWS" in r.stdout

    def test_inspect_all(self):
        r = _run("inspect", "--all")
        assert r.returncode == 0
        assert "ANCHORS" in r.stdout
        assert "PERSONAS" in r.stdout

    def test_inspect_specific_anchor(self):
        r = _run("inspect", "NoHallucination")
        assert r.returncode == 0
        assert "NoHallucination" in r.stdout
        assert "anchors" in r.stdout.lower()

    def test_inspect_not_found(self):
        r = _run("inspect", "NonexistentThing", check=False)
        assert r.returncode == 1
        assert "not found" in r.stdout
