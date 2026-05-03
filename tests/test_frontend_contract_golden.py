"""Golden compatibility tests for the frozen AXON frontend contract.

These tests anchor Phase B Session B3. They validate the minimum stable
contract defined in docs/phase_b_frontend_contract.md for `axon check`
and `axon compile` without overfitting to transient implementation details.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VALID_SOURCE = ROOT / "examples" / "contract_analyzer.axon"
CLI_MODULE = [sys.executable, "-m", "axon.cli"]
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
TOP_LEVEL_COLLECTIONS = (
    "personas",
    "contexts",
    "anchors",
    "tools",
    "memories",
    "types",
    "flows",
    "runs",
    "imports",
    "agents",
    "shields",
    "daemons",
    "ots_specs",
    "pix_specs",
    "corpus_specs",
    "psyche_specs",
    "mandate_specs",
    "lambda_data_specs",
    "compute_specs",
    "axonstore_specs",
    "endpoints",
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=30,
        env=ENV,
        check=False,
    )


def _normalize_cli_path(text: str) -> str:
    return text.replace("\\", "/")


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def _assert_single_line(text: str) -> None:
    stripped = text.strip()
    assert stripped
    assert len(stripped.splitlines()) == 1


def _assert_location_diagnostic(text: str, file_name: str) -> None:
    assert re.search(rf"{re.escape(file_name)}:\d+:\d+", text)


def _assert_type_error_line_present(text: str) -> None:
    assert re.search(r"line\s+\d+", text)


def _assert_ir_node_shape(node: dict, *required_fields: str) -> None:
    assert "node_type" in node
    assert "source_line" in node
    assert "source_column" in node
    for field in required_fields:
        assert field in node


def test_check_success_golden_contract() -> None:
    result = _run("check", str(VALID_SOURCE), "--no-color")

    assert result.returncode == 0
    assert result.stderr == ""
    _assert_single_line(result.stdout)
    assert "contract_analyzer.axon" in result.stdout
    assert "tokens" in result.stdout
    assert "declarations" in result.stdout
    assert "0 errors" in result.stdout


def test_check_missing_file_golden_contract() -> None:
    result = _run("check", "examples/__missing__.axon", "--no-color")

    assert result.returncode == 2
    assert result.stdout == ""
    _assert_single_line(result.stderr)
    normalized = _normalize_cli_path(result.stderr.strip())
    assert normalized.startswith("✗ File not found:")
    assert normalized.endswith("examples/__missing__.axon")


def test_check_parser_error_golden_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad_parser.axon"
    bad.write_text("42 + garbage", encoding="utf-8")

    result = _run("check", str(bad), "--no-color")

    assert result.returncode == 1
    assert result.stdout == ""
    _assert_single_line(result.stderr)
    _assert_location_diagnostic(result.stderr, bad.name)
    assert "Unexpected token at top level" in result.stderr


def test_check_type_error_golden_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad_type.axon"
    bad.write_text(
        "persona Bad {\n"
        "  confidence_threshold: 1.5\n"
        "}\n",
        encoding="utf-8",
    )

    result = _run("check", str(bad), "--no-color")

    assert result.returncode == 1
    output = _combined_output(result)
    assert bad.name in output
    assert "confidence_threshold" in output
    _assert_type_error_line_present(output)


def test_compile_stdout_golden_contract() -> None:
    result = _run("compile", str(VALID_SOURCE), "--stdout")

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    assert payload["node_type"] == "program"
    assert "source_line" in payload
    assert "source_column" in payload
    assert "_meta" in payload

    for name in TOP_LEVEL_COLLECTIONS:
        assert name in payload
        assert isinstance(payload[name], list)

    meta = payload["_meta"]
    assert meta["source"].endswith("examples/contract_analyzer.axon")
    assert "/" in meta["source"]
    assert meta["backend"] == "anthropic"
    # Lives in lockstep with `axon.__version__`, `pyproject.toml`, and
    # `axon-rs/Cargo.toml`. Bumps coordinated via bump-my-version (see
    # `[tool.bumpversion]` block in pyproject.toml + the
    # `coordinated-release.yml` workflow). 1.5.1 (2026-04-27) inaugurates
    # the lockstep cross-stack policy: every release ships axon-lang
    # Python and axon-lang Rust at the same version.
    assert meta["axon_version"] == "1.9.0"

    _assert_ir_node_shape(payload["personas"][0], "name")
    _assert_ir_node_shape(payload["contexts"][0], "name", "memory_scope", "language", "depth")
    _assert_ir_node_shape(
        payload["anchors"][0],
        "name",
        "require",
        "confidence_floor",
        "on_violation",
        "on_violation_target",
    )
    _assert_ir_node_shape(payload["types"][0], "name", "fields", "range_min", "range_max", "where_expression")
    _assert_ir_node_shape(payload["flows"][0], "name", "parameters", "return_type_name", "steps", "edges", "execution_levels")
    _assert_ir_node_shape(payload["flows"][0]["parameters"][0], "name", "type_name", "optional")
    _assert_ir_node_shape(payload["flows"][0]["steps"][0], "name", "given", "ask", "output_type")
    _assert_ir_node_shape(payload["flows"][0]["edges"][0], "source_step", "target_step", "type_name")
    _assert_ir_node_shape(
        payload["runs"][0],
        "flow_name",
        "arguments",
        "persona_name",
        "context_name",
        "anchor_names",
        "on_failure",
        "on_failure_params",
        "output_to",
        "effort",
    )


def test_compile_output_file_golden_contract(tmp_path: Path) -> None:
    out_path = tmp_path / "golden.ir.json"

    result = _run("compile", str(VALID_SOURCE), "--output", str(out_path))

    assert result.returncode == 0
    assert result.stderr == ""
    _assert_single_line(result.stdout)
    normalized = _normalize_cli_path(result.stdout.strip())
    assert normalized.startswith("✓ Compiled")
    assert normalized.endswith(_normalize_cli_path(str(out_path)))
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["node_type"] == "program"
    assert payload["_meta"]["backend"] == "anthropic"


def test_compile_missing_file_golden_contract() -> None:
    result = _run("compile", "examples/__missing__.axon")

    assert result.returncode == 2
    assert result.stdout == ""
    _assert_single_line(result.stderr)
    normalized = _normalize_cli_path(result.stderr.strip())
    assert normalized.startswith("✗ File not found:")
    assert normalized.endswith("examples/__missing__.axon")


def test_compile_parser_error_golden_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad_compile_parser.axon"
    bad.write_text("42 + garbage", encoding="utf-8")

    result = _run("compile", str(bad))

    assert result.returncode == 1
    assert result.stdout == ""
    _assert_single_line(result.stderr)
    _assert_location_diagnostic(result.stderr, bad.name)
    assert "Unexpected token at top level" in result.stderr


def test_compile_type_error_golden_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad_compile_type.axon"
    bad.write_text(
        "persona Bad {\n"
        "  confidence_threshold: 1.5\n"
        "}\n",
        encoding="utf-8",
    )

    result = _run("compile", str(bad))

    assert result.returncode == 1
    output = _combined_output(result)
    assert bad.name in output
    assert "type error(s)" in output
    assert "confidence_threshold" in output
    _assert_type_error_line_present(output)